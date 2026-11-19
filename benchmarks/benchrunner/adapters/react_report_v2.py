"""Adapter from generic work items to the v2 ReAct report benchmark."""

from __future__ import annotations

from pathlib import Path
from copy import deepcopy
from dataclasses import replace
from threading import RLock
from typing import Any

from benchmarks.react_report_building.paths import NORMALIZED_ROOT
from benchmarks.react_report_building.runtime.accounting import (
    aggregate_report_episodes,
    aggregate_usage,
    episode_turns,
)
from benchmarks.react_report_building.runtime.calculator import Calculator
from benchmarks.react_report_building.runtime.evidence_store import EvidenceStore
from benchmarks.react_report_building.runtime.providers import create_provider
from benchmarks.react_report_building.runtime.providers.base import (
    ProviderRequestError as RuntimeProviderRequestError,
    ProviderResponseError as RuntimeProviderResponseError,
)
from benchmarks.react_report_building.runtime.rendering import calculate_all
from benchmarks.react_report_building.util import (
    read_json,
    sha256_json,
    sha256_text,
)
from benchmarks.react_report_building.v2.document import (
    compose_report,
    section_contracts,
)
from benchmarks.react_report_building.v2.evaluation import evaluate_v2_report
from benchmarks.react_report_building.v2.oracle import build_executable_gold
from benchmarks.react_report_building.v2.perturbations import (
    POPULATION_CONDITIONS_PATH,
)
from benchmarks.react_report_building.v2.registry import calculation_registry
from benchmarks.react_report_building.v2.source_aliases import validate_mask_alias_closure
from benchmarks.react_report_building.v2.runner import (
    resolve_runtime_context,
    run_report,
    run_section,
)
from benchmarks.react_report_building.v2.update_runner import (
    UpdateReadinessError,
    prepare_canonical_t0,
    prepare_update_case,
    reduce_section_update_results,
    run_report_update,
    run_section_update,
)

from ..artifacts import write_episode_artifact, write_record_artifacts
from ..checkpointing import CheckpointMismatchError, CheckpointingProvider
from ..config import ModelSpec, StudyConfig, sanitized_config
from ..metrics import context_preflight_accounting, record_outcomes
from ..probe_budget import ProbeBudgetError, ProbeBudgetLedger
from ..retry import (
    PermanentWorkError,
    WorkExecutionError,
    failed_response_accounting_metadata,
)
from ..scheduler import ExecutionContext
from ..storage import RunStore
from ..work import WorkSpec


RECORD_SCHEMA_VERSION = "react_report.run_record/v2"


class ReactReportV2Executor:
    """Execute and reduce immutable v2 work items.

    Provider episodes are independent scheduler work. Section-scope records are
    a local DAG reduction, allowing all 15 model queries to run concurrently.
    """

    def __init__(
        self,
        config: StudyConfig,
        store: RunStore,
        run_dir: Path,
    ) -> None:
        if config.adapter != "react_report_v2":
            raise ValueError(f"unsupported adapter {config.adapter!r}")
        self.config = config
        self.store = store
        self.run_dir = Path(run_dir).resolve()
        self.models = {item.alias: item for item in config.models}
        self.conditions = _condition_index()
        self._twins: dict[str, dict[str, Any]] = {}
        self._canonical_t0: dict[str, dict[str, Any]] = {}
        self._cache_lock = RLock()

    def __call__(self, work: WorkSpec, context: ExecutionContext) -> Any:
        try:
            if work.kind == "react_episode":
                return self._episode(work, context)
            if work.kind == "react_record":
                return self._record(work)
            raise PermanentWorkError(
                "adapter.unknown_work_kind",
                f"react_report_v2 cannot execute {work.kind!r}",
            )
        except RuntimeProviderRequestError as exc:
            response_metadata: dict[str, Any] = {}
            if getattr(exc, "request_context", None) is not None:
                response_metadata["request_context"] = exc.request_context
            if getattr(exc, "code", None) is not None:
                response_metadata["provider_error_code"] = exc.code
            if getattr(exc, "failure_evidence", None) is not None:
                response_metadata["failure_evidence"] = exc.failure_evidence
            failed_response_received = False
            if isinstance(exc, RuntimeProviderResponseError):
                response_metadata["provider_error_code"] = exc.code
                if exc.latency_seconds is not None:
                    failed_response_received = True
                    response_metadata["response_received"] = True
                    response_metadata["failed_response_accounting"] = (
                        failed_response_accounting_metadata(
                            usage=exc.usage,
                            provider_cost=exc.provider_cost,
                            latency_seconds=exc.latency_seconds,
                        )
                    )
            is_context_failure = getattr(exc, "code", None) in {
                "input_token_count_failed", "insufficient_output_budget",
            }
            raise WorkExecutionError(
                f"context.{exc.code}" if is_context_failure else "provider.request_failed",
                str(exc),
                retryable=bool(exc.retryable),
                retry_after_seconds=getattr(exc, "retry_after_seconds", None),
                metadata={
                    "transport": exc.transport,
                    **(
                        {"http_status": int(exc.status_code)}
                        if hasattr(exc, "status_code")
                        else {}
                    ),
                    **(
                        {"provider_request_id": exc.provider_request_id}
                        if exc.provider_request_id
                        and not failed_response_received
                        else {}
                    ),
                    **response_metadata,
                },
            ) from exc
        except CheckpointMismatchError as exc:
            raise PermanentWorkError(
                "checkpoint.request_mismatch", str(exc)
            ) from exc
        except ProbeBudgetError as exc:
            raise PermanentWorkError(f"context.{exc.code}", str(exc)) from exc
        except UpdateReadinessError as exc:
            raise PermanentWorkError(
                f"benchmark.{exc.code}",
                str(exc),
            ) from exc

    def _episode(
        self,
        work: WorkSpec,
        execution: ExecutionContext,
    ) -> dict[str, Any]:
        limit = self.config.generation.episode_retry_limit
        if not limit:
            return self._episode_attempt(work, execution)
        attempts = []
        for attempt in range(limit + 1):
            name = f"episode-attempt-{attempt:03d}"
            result = execution.checkpoints.load(name)
            if result is None:
                result = self._episode_attempt(work, execution, attempt=attempt)
                execution.checkpoints.save(name, result)
            if not isinstance(result, dict) or result.get("record_key") != work.identity["record_key"]:
                raise CheckpointMismatchError("saved episode attempt does not match the work identity")
            attempts.append(result)
            # Only failures to reach a terminal get one fresh episode attempt.
            # Accepted but poor-quality or diagnostically invalid reports do not.
            if result.get("status") not in {"protocol_failure", "turn_limit_exhausted"}:
                break
        final = deepcopy(attempts[-1])
        final["prior_attempts"] = deepcopy(attempts[:-1])
        final["episode_retry"] = {
            "schema_version": "react_report.episode_retry/v1",
            "retry_limit": limit,
            "attempt_count": len(attempts),
            "first_attempt_status": attempts[0]["status"],
            "first_attempt_reached_terminal": attempts[0].get("status") == "completed",
            "recovered": len(attempts) > 1 and final.get("status") == "completed",
            "basis": "fresh_failed_episode_only; no_quality_selection; base_seed_plus_attempt",
            "attempt_artifacts": [r["runner_artifact"] for r in attempts],
        }
        final["accounting"] = aggregate_usage(episode_turns(final))
        final["runner_artifact"] = f"episodes/{work.work_id}.json"
        final["checkpoint_names"] = list(execution.checkpoints.names())
        write_episode_artifact(self.run_dir, work.work_id, final)
        return final

    def _episode_attempt(
        self,
        work: WorkSpec,
        execution: ExecutionContext,
        *,
        attempt: int = 0,
    ) -> dict[str, Any]:
        identity = dict(work.identity)
        model = self._model(work.model)
        if attempt:
            identity["episode_attempt"] = attempt
            if model.generation_seed is not None:
                model = replace(model, generation_seed=model.generation_seed + attempt)
        twin = self._twin(str(identity["project_id"]))
        condition = self._condition(identity)
        task = str(identity["task"])
        if task == "missingness":
            if condition is None:
                raise PermanentWorkError(
                    "benchmark.missing_condition", "missingness episode has no frozen condition"
                )
            try:
                validate_mask_alias_closure(resolve_runtime_context(twin).twin, condition)
            except ValueError as exc:
                raise PermanentWorkError("benchmark.invalid_alias_intervention", str(exc)) from exc
        provider = CheckpointingProvider(
            self._provider(model),
            execution.checkpoints,
            work_identity=identity,
            turn_index_offset=attempt * int(identity["max_turns"]),
        )
        scope = str(identity["scope"])
        section_id = identity.get("section_id")
        max_turns = int(identity["max_turns"])
        turn_policy = str(identity.get("turn_policy") or "unrestricted")
        masked_ids = set((condition or {}).get("masked_ids") or ())

        if task == "update":
            if condition is None:
                raise ValueError("update episode has no frozen condition")
            canonical = self._t0(twin)
            result = (
                run_report_update(
                    twin,
                    condition,
                    provider,
                    canonical_t0=canonical,
                    expected_t0_sha256=identity.get("canonical_t0_sha256"),
                    max_turns=max_turns,
                    turn_policy=turn_policy,
                    terminal_protocol_version=self.config.generation.terminal_protocol_version,
                )
                if scope == "report"
                else run_section_update(
                    twin,
                    condition,
                    provider,
                    section_id=str(section_id),
                    canonical_t0=canonical,
                    expected_t0_sha256=identity.get("canonical_t0_sha256"),
                    max_turns=max_turns,
                    turn_policy=turn_policy,
                    terminal_protocol_version=self.config.generation.terminal_protocol_version,
                )
            )
        elif scope == "report":
            result = run_report(
                twin,
                provider,
                max_turns=max_turns,
                turn_policy=turn_policy,
                terminal_protocol_version=self.config.generation.terminal_protocol_version,
                masked_ids=masked_ids,
            )
        else:
            result = run_section(
                twin,
                provider,
                section_id=str(section_id),
                max_turns=max_turns,
                turn_policy=turn_policy,
                terminal_protocol_version=self.config.generation.terminal_protocol_version,
                masked_ids=masked_ids,
            )

        result.update(
            runner_work_id=work.work_id,
            record_key=identity["record_key"],
            model_alias=model.alias,
            model_id=model.model,
            provider_profile=model.provider,
            action_protocol=self.config.generation.action_protocol,
            turn_policy=turn_policy,
            checkpoint_names=list(execution.checkpoints.names()),
        )
        if model.generation_seed is not None:
            result["generation_seed"] = model.generation_seed
        suffix = f".attempt-{attempt:03d}" if self.config.generation.episode_retry_limit else ""
        artifact_id = work.work_id + suffix
        artifact = f"episodes/{artifact_id}.json"
        result["runner_artifact"] = artifact
        write_episode_artifact(self.run_dir, artifact_id, result)
        return result

    def _record(self, work: WorkSpec) -> dict[str, Any]:
        identity = dict(work.identity)
        episodes = [
            self.store.get_state(work_id).result
            for work_id in work.dependencies
        ]
        if any(not isinstance(item, dict) for item in episodes):
            raise PermanentWorkError(
                "reducer.missing_episode_result",
                "a completed dependency has no JSON episode result",
            )
        episode_results: list[dict[str, Any]] = list(episodes)
        twin = self._twin(str(identity["project_id"]))
        condition = self._condition(identity)
        partial = bool(identity.get("partial_smoke"))
        task = str(identity["task"])
        scope = str(identity["scope"])

        generation = self._reduce_generation(
            identity,
            twin,
            condition,
            episode_results,
            partial=partial,
        )
        markdown = generation.get("markdown")
        status = str(generation.get("status") or "failed")
        score = generation.get("score")
        record = {
            **identity,
            "schema_version": RECORD_SCHEMA_VERSION,
            "status": status,
            "analysis_eligible": bool(
                self.config.inferential and not partial and status == "completed"
            ),
            "diagnostic_only": bool(partial or not self.config.inferential),
            "episode_work_ids": list(work.dependencies),
            "episode_artifacts": [
                item.get("runner_artifact") for item in episode_results
            ],
            "episode_statuses": {
                str(item.get("section_id") or "report"): str(
                    item.get("status") or "unknown"
                )
                for item in episode_results
            },
            "accounting": generation.get("accounting"),
            "context_preflight_accounting": context_preflight_accounting(
                turn for episode in episode_results for turn in episode_turns(episode)
            ),
            "candidate_markdown_sha256": (
                sha256_text(markdown) if isinstance(markdown, str) else None
            ),
            "expected_markdown_sha256": generation.get(
                "expected_markdown_sha256"
            ),
            "expected_gold_sha256": generation.get("expected_gold_sha256"),
            "score": score,
            "outcomes": record_outcomes(episode_results, score),
            **(
                {"partial_diagnostic": generation["partial_diagnostic"]}
                if generation.get("partial_diagnostic") is not None
                else {}
            ),
        }
        candidate_path = (
            f"candidates/{work.work_id}.md"
            if isinstance(markdown, str)
            else None
        )
        record["record_artifact"] = f"records/{work.work_id}.json"
        record["candidate_artifact"] = candidate_path
        record_path, candidate_path = write_record_artifacts(
            self.run_dir,
            work.work_id,
            record,
            markdown if isinstance(markdown, str) else None,
        )
        return {
            "record": record,
            "record_artifact": record_path,
            "candidate_artifact": candidate_path,
        }

    def _reduce_generation(
        self,
        identity: dict[str, Any],
        twin: dict[str, Any],
        condition: dict[str, Any] | None,
        episodes: list[dict[str, Any]],
        *,
        partial: bool,
    ) -> dict[str, Any]:
        task = str(identity["task"])
        scope = str(identity["scope"])
        if scope == "report":
            result = episodes[0]
            terminal = result.get("terminal") or {}
            markdown = terminal.get("markdown")
            score = result.get("score") if task == "update" else None
            expected_sha256 = result.get("expected_t1_sha256")
            if (
                task != "update"
                and result.get("status") == "completed"
                and isinstance(markdown, str)
            ):
                context = resolve_runtime_context(twin)
                executable_gold, expected_store = _expected_gold(
                    context,
                    condition if task == "missingness" else None,
                )
                score = evaluate_v2_report(
                    markdown,
                    store=expected_store,
                    record_id=str(identity["record_key"]),
                    contract=context.contract,
                    executable_gold=executable_gold,
                )
            return {
                "status": result.get("status"),
                "markdown": markdown,
                "accounting": result.get("accounting"),
                "score": score,
                "expected_markdown_sha256": (
                    expected_sha256 if task == "update" else None
                ),
                "expected_gold_sha256": (
                    executable_gold["gold_sha256"]
                    if task != "update"
                    and result.get("status") == "completed"
                    and isinstance(markdown, str)
                    else (score or {}).get("gold_sha256")
                ),
            }

        if partial:
            return self._partial_section_diagnostic(
                twin,
                condition,
                task,
                episodes,
            )

        if task == "update":
            if condition is None:
                raise ValueError("update reduction has no frozen condition")
            result = reduce_section_update_results(
                twin,
                condition,
                episodes,
                canonical_t0=self._t0(twin),
                expected_t0_sha256=identity.get("canonical_t0_sha256"),
            )
            result["expected_markdown_sha256"] = result.get(
                "expected_t1_sha256"
            )
            result["expected_gold_sha256"] = (
                (result.get("score") or {}).get("gold_sha256")
            )
            return result

        context = resolve_runtime_context(twin)
        expected_ids = [
            section["id"] for section in section_contracts(context.contract)
        ]
        by_section = {item.get("section_id"): item for item in episodes}
        rendered: dict[str, str] = {}
        for section_id in expected_ids:
            item = by_section.get(section_id) or {}
            terminal = item.get("terminal") or {}
            if item.get("status") == "completed" and isinstance(
                terminal.get("markdown"), str
            ):
                rendered[section_id] = terminal["markdown"]
        complete = list(rendered) == expected_ids
        title = str(context.twin["nodes"]["dt.project.title"].get("value") or "")
        markdown = (
            compose_report(rendered, title=title, contract=context.contract)
            if complete
            else None
        )
        score = None
        if markdown is not None:
            executable_gold, expected_store = _expected_gold(
                context,
                condition if task == "missingness" else None,
            )
            score = evaluate_v2_report(
                markdown,
                store=expected_store,
                record_id=str(identity["record_key"]),
                contract=context.contract,
                executable_gold=executable_gold,
            )
        return {
            "status": "completed" if complete else "failed",
            "markdown": markdown,
            "accounting": aggregate_report_episodes(episodes),
            "score": score,
            "expected_markdown_sha256": None,
            "expected_gold_sha256": (
                executable_gold["gold_sha256"]
                if markdown is not None
                else None
            ),
        }

    def _partial_section_diagnostic(
        self,
        twin: dict[str, Any],
        condition: dict[str, Any] | None,
        task: str,
        episodes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        completed = all(item.get("status") == "completed" for item in episodes)
        terminal_submissions_recorded = all(
            item.get("status") == "completed"
            and (item.get("terminal") or {}).get("status") == "accepted"
            for item in episodes
        )
        output_validation_states = [
            (item.get("terminal") or {}).get("output_validation") or {}
            for item in episodes
        ]
        valid_output_count = sum(
            validation.get("valid") is True
            for validation in output_validation_states
        )
        invalid_output_count = sum(
            validation.get("valid") is False
            for validation in output_validation_states
        )
        missing_output_validation_count = (
            len(output_validation_states)
            - valid_output_count
            - invalid_output_count
        )
        all_output_contract_diagnostics_valid = (
            terminal_submissions_recorded
            and bool(episodes)
            and valid_output_count == len(episodes)
        )
        sections = {
            str(item.get("section_id")): (item.get("terminal") or {}).get(
                "markdown"
            )
            for item in episodes
            if item.get("status") == "completed"
        }
        diagnostic: dict[str, Any] = {
            "selected_section_count": len(episodes),
            "selected_section_ids": sorted(sections),
            "all_terminal_submissions_recorded": terminal_submissions_recorded,
            # Retain the established field with its corrected content-validity
            # meaning for downstream readers.
            "all_terminal_outputs_valid": all_output_contract_diagnostics_valid,
            "all_output_contract_diagnostics_valid": (
                all_output_contract_diagnostics_valid
            ),
            "output_contract_diagnostics": {
                "valid_count": valid_output_count,
                "invalid_count": invalid_output_count,
                "missing_count": missing_output_validation_count,
            },
        }
        if task == "update" and condition is not None:
            case = prepare_update_case(
                twin,
                condition,
                canonical_t0=self._t0(twin),
            )
            actions = {}
            for item in episodes:
                section_id = str(item.get("section_id"))
                mode = (item.get("terminal") or {}).get("mode")
                actual = (
                    "retain" if mode in {"keep", "retain"}
                    else "rewrite" if mode in {"replace", "rewrite"}
                    else "invalid"
                )
                expected = (
                    "rewrite"
                    if section_id in case.affected_section_ids
                    else "retain"
                )
                actions[section_id] = {
                    "actual": actual,
                    "expected": expected,
                    "correct": actual == expected,
                }
            diagnostic["routing"] = actions
            diagnostic["routing_exact"] = all(
                item["correct"] for item in actions.values()
            )
        markdown = next(iter(sections.values()), None) if len(sections) == 1 else None
        return {
            "status": "completed" if completed else "failed",
            "markdown": markdown,
            "accounting": aggregate_report_episodes(episodes),
            "score": None,
            "expected_markdown_sha256": None,
            "expected_gold_sha256": None,
            "partial_diagnostic": diagnostic,
        }

    def _provider(self, model: ModelSpec):
        from ..retry import policy_from_spec
        if model.provider == "fixture":
            return create_provider("fixture")
        probe_budget = None
        if model.input_token_count_mode == "openrouter_probe_on_clamp":
            probe_budget = ProbeBudgetLedger(
                self.run_dir,
                model_alias=model.alias,
                treatment_sha256=sha256_json(sanitized_config(self.config)),
                max_requests=model.context_probe_max_requests,
                max_cost_usd=model.context_probe_max_cost_usd,
            )
        return create_provider(
            "openai_responses",
            model=model.model,
            profile_id=model.provider,
            action_protocol=self.config.generation.action_protocol,
            action_output_contract=model.action_output_contract,
            timeout_seconds=self.config.generation.timeout_seconds,
            max_output_tokens=self.config.generation.max_output_tokens,
            reasoning_effort=model.reasoning_effort,
            generation_seed=model.generation_seed,
            openrouter_policy=model.openrouter,
            final_turn_tool_choice_policy=model.final_turn_tool_choice_policy,
            native_tool_policy=model.native_tool_policy,
            context_window_tokens=model.context_window_tokens,
            context_safety_margin_tokens=model.context_safety_margin_tokens,
            input_token_count_mode=model.input_token_count_mode,
            context_probe_max_requests=model.context_probe_max_requests,
            context_probe_max_cost_usd=model.context_probe_max_cost_usd,
            context_probe_budget=probe_budget,
            context_probe_retry_policy=policy_from_spec(self.config.retry),
        )

    def _model(self, alias: str) -> ModelSpec:
        try:
            return self.models[alias]
        except KeyError as exc:
            raise ValueError(f"unknown model alias {alias!r}") from exc

    def _condition(self, identity: dict[str, Any]) -> dict[str, Any] | None:
        condition_id = identity.get("condition_id")
        if not condition_id:
            return None
        try:
            condition = self.conditions[str(condition_id)]
        except KeyError as exc:
            raise ValueError(f"unknown frozen condition {condition_id!r}") from exc
        if sha256_json(condition) != identity.get("condition_sha256"):
            raise ValueError(f"frozen condition changed: {condition_id}")
        return condition

    def _twin(self, project_id: str) -> dict[str, Any]:
        project = project_id.upper()
        with self._cache_lock:
            if project not in self._twins:
                self._twins[project] = read_json(
                    NORMALIZED_ROOT / f"{project.lower()}.json"
                )
            return self._twins[project]

    def _t0(self, twin: dict[str, Any]) -> dict[str, Any]:
        project = str(twin["project_id"]).upper()
        with self._cache_lock:
            if project not in self._canonical_t0:
                self._canonical_t0[project] = prepare_canonical_t0(twin)
            return self._canonical_t0[project]


def _condition_index() -> dict[str, dict[str, Any]]:
    manifest = read_json(POPULATION_CONDITIONS_PATH)
    output: dict[str, dict[str, Any]] = {}
    for project in manifest.get("projects", []):
        for group in ("masks", "mutations"):
            for condition in project.get(group, []):
                condition_id = str(condition.get("condition_id") or "")
                if not condition_id or condition_id in output:
                    raise ValueError("v2 condition manifest has invalid IDs")
                output[condition_id] = condition
    return output


def _expected_gold(
    context: Any,
    condition: dict[str, Any] | None,
) -> tuple[dict[str, Any], EvidenceStore]:
    masked_ids = set((condition or {}).get("masked_ids") or ())
    store = EvidenceStore(
        context.twin,
        context.reference,
        masked_ids=masked_ids,
    )
    calculate_all(
        Calculator(store, registry=calculation_registry(context.contract))
    )
    gold = build_executable_gold(
        store,
        contract=context.contract,
        data_catalogue=context.catalogue,
        condition_id=(
            str(condition.get("condition_id")) if condition is not None else None
        ),
    )
    return gold, store
