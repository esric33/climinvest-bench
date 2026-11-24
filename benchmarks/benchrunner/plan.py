"""Expand a validated study config into stable scientific records and a DAG."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from benchmarks.benchrunner.providers.profiles import resolve_provider_profile
from benchmarks.react_report_building.paths import NORMALIZED_ROOT, PROMPT_ROOT
from benchmarks.react_report_building.util import (
    read_json,
    sha256_json,
    sha256_text,
)
from benchmarks.react_report_building.v2.document import section_contracts
from benchmarks.react_report_building.v2.perturbations import (
    POPULATION_CONDITIONS_PATH,
    TOPOLOGY_CATEGORIES,
)
from benchmarks.react_report_building.v2.registry import project_catalogue
from benchmarks.react_report_building.v2.runner import resolve_runtime_context
from benchmarks.react_report_building.v2.study_design import load_population

from .config import (
    LEGACY_TERMINAL_PROTOCOL,
    CaseSpec,
    StudyConfig,
    sanitized_config,
)
from .work import WorkGraph, WorkSpec


PLAN_SCHEMA_VERSION = "benchrunner.study_plan/v1"
RECORD_SCHEMA_VERSION = "benchrunner.record_spec/v1"
EPISODE_SCHEMA_VERSION = "benchrunner.react_episode_spec/v1"


class StudyPlanError(ValueError):
    """Raised when a valid-looking config cannot bind to the frozen benchmark."""


@dataclass(frozen=True, slots=True)
class StudyPlan:
    config: StudyConfig
    graph: WorkGraph
    records: tuple[dict[str, Any], ...]
    execution_shard: dict[str, Any] | None = None
    canonical_plan: StudyPlan | None = field(default=None, repr=False, compare=False)

    @property
    def plan_id(self) -> str:
        return f"plan-{sha256_json(self.to_dict(include_graph=False))}"

    @property
    def episode_count(self) -> int:
        return sum(item.kind == "react_episode" for item in self.graph)

    @property
    def record_count(self) -> int:
        return len(self.records)

    def to_dict(self, *, include_graph: bool = True) -> dict[str, Any]:
        value = {
            "schema_version": PLAN_SCHEMA_VERSION,
            "config": sanitized_config(self.config),
            "graph_id": self.graph.graph_id,
            "record_count": self.record_count,
            "episode_count": self.episode_count,
            "records": list(self.records),
        }
        if include_graph:
            value["graph"] = self.graph.to_dict()
        if self.execution_shard is not None:
            value["execution_shard"] = self.execution_shard
        return value


def build_study_plan(
    config: StudyConfig,
    *,
    enforce_condition_readiness: bool = True,
) -> StudyPlan:
    """Bind every selected scientific cell before any provider call."""

    population = load_population()
    population_ids = tuple(item["project_id"] for item in population["projects"])
    if config.mode == "full" and set(config.selection.projects) != set(population_ids):
        raise StudyPlanError(
            "full mode project selection must equal the frozen 20-project population"
        )
    cases = expand_cases(config, population_ids=population_ids)
    canonical_case_ids = [
        (
            case.project_id,
            case.task,
            case.scope,
            case.category,
            frozenset(case.section_ids),
        )
        for case in cases
    ]
    if len(set(canonical_case_ids)) != len(canonical_case_ids):
        raise StudyPlanError(
            "study selection duplicates a treatment and section set"
        )
    conditions = _condition_index()
    contexts: dict[str, Any] = {}
    twins: dict[str, dict[str, Any]] = {}
    t0_by_project: dict[str, dict[str, Any]] = {}
    update_preflights: set[str] = set()
    missingness_preflights: set[str] = set()
    catalogues: dict[str, dict[str, Any]] = {}
    catalogue_hashes: dict[str, str] = {}
    prompt_hashes: dict[tuple[str, str], str] = {}
    action_interface_hash = _action_interface_hash()
    normalization_policy = _action_normalization_policy(
        config.generation.action_protocol
    )
    adapter_implementation_hash = _adapter_implementation_hash()
    provider_profile_hashes = {
        model.provider: _provider_profile_hash(model.provider)
        for model in config.models
    }
    work: list[WorkSpec] = []
    records: list[dict[str, Any]] = []

    for case in cases:
        if case.project_id not in contexts:
            twin = _load_twin(case.project_id)
            twins[case.project_id] = twin
            contexts[case.project_id] = resolve_runtime_context(twin)
        context = contexts[case.project_id]
        twin = twins[case.project_id]
        contract_hash = sha256_json(context.contract)
        prepared_evidence_hash = sha256_json(
            {"twin": context.twin, "reference": context.reference}
        )
        available_sections = tuple(
            item["id"] for item in section_contracts(context.contract)
        )
        section_ids = _selected_sections(case, available_sections)
        condition = _condition_for_case(case, conditions)
        if condition is not None:
            declared_contract = condition.get("contract_sha256")
            if declared_contract != contract_hash:
                raise StudyPlanError(
                    f"{condition['condition_id']}: contract hash is stale"
                )
            if condition.get("prepared_evidence_sha256") != sha256_json(
                context.twin
            ):
                raise StudyPlanError(
                    f"{condition['condition_id']}: prepared evidence hash is stale"
                )
            condition_id = str(condition.get("condition_id"))
            if (
                enforce_condition_readiness
                and case.task == "missingness"
                and condition_id not in missingness_preflights
            ):
                from benchmarks.react_report_building.v2.missingness_runner import (
                    preflight_missingness_case,
                )

                mask_preflight = preflight_missingness_case(twin, condition)
                if mask_preflight.get("ready_for_provider_smoke") is not True:
                    codes = ", ".join(
                        str(item.get("code"))
                        for item in mask_preflight.get("errors", [])
                    )
                    raise StudyPlanError(
                        f"{condition_id}: missingness readiness failed: {codes}"
                    )
                missingness_preflights.add(condition_id)

        t0: dict[str, Any] | None = None
        if case.task == "update":
            if case.project_id not in t0_by_project:
                from benchmarks.react_report_building.v2.update_runner import (
                    prepare_canonical_t0,
                )

                t0_by_project[case.project_id] = prepare_canonical_t0(
                    twin
                )
            t0 = t0_by_project[case.project_id]
            condition_id = str(condition.get("condition_id"))
            if enforce_condition_readiness and condition_id not in update_preflights:
                from benchmarks.react_report_building.v2.update_runner import (
                    preflight_update_case,
                )

                update_preflight = preflight_update_case(
                    twin,
                    condition,
                    canonical_t0=t0,
                    expected_t0_sha256=t0["report_sha256"],
                )
                if update_preflight.get("ready_for_provider_smoke") is not True:
                    codes = ", ".join(
                        str(item.get("code"))
                        for item in update_preflight.get("errors", [])
                    )
                    raise StudyPlanError(
                        f"{condition_id}: update readiness failed: {codes}"
                    )
                update_preflights.add(condition_id)

        if case.project_id not in catalogues:
            catalogues[case.project_id] = project_catalogue(
                contract=context.contract,
                project_id=case.project_id,
            )
            catalogue_hashes[case.project_id] = sha256_json(
                catalogues[case.project_id]
            )
        catalogue = catalogues[case.project_id]
        prompt_key = (case.task, case.scope)
        if prompt_key not in prompt_hashes:
            prompt_hashes[prompt_key] = _prompt_bundle_hash(*prompt_key)

        for model in config.models:
            openrouter_identity = (
                model.openrouter.as_config()
                if model.openrouter is not None
                else None
            )
            for replicate in range(config.replicates):
                record_key = _record_key(
                    model_alias=model.alias,
                    case=case,
                    replicate=replicate,
                    selected_section_ids=section_ids,
                )
                episode_work: list[WorkSpec] = []
                planned_sections: tuple[str | None, ...] = (
                    (None,) if case.scope == "report" else section_ids
                )
                for section_id in planned_sections:
                    identity = {
                        "schema_version": EPISODE_SCHEMA_VERSION,
                        "study_id": config.study_id,
                        "study_mode": config.mode,
                        "inferential": config.inferential,
                        "adapter": config.adapter,
                        "record_key": record_key,
                        "replicate": replicate,
                        "project_id": case.project_id,
                        "template_id": context.template_id,
                        "contract_sha256": contract_hash,
                        "prepared_evidence_sha256": prepared_evidence_hash,
                        "prepared_twin_sha256": sha256_json(context.twin),
                        "prepared_reference_sha256": sha256_json(
                            context.reference
                        ),
                        "task": case.task,
                        "scope": case.scope,
                        "section_id": section_id,
                        "condition_id": (
                            condition.get("condition_id") if condition else None
                        ),
                        "condition_sha256": (
                            sha256_json(condition) if condition else None
                        ),
                        "category": case.category,
                        "canonical_t0_sha256": (
                            t0.get("report_sha256") if t0 else None
                        ),
                        "prompt_bundle_sha256": prompt_hashes[prompt_key],
                        "public_catalogue_sha256": catalogue_hashes[
                            case.project_id
                        ],
                        "action_interface_sha256": action_interface_hash,
                        "action_normalization_policy_id": normalization_policy[
                            "policy_id"
                        ],
                        "action_normalization_policy_sha256": normalization_policy[
                            "sha256"
                        ],
                        "adapter_implementation_sha256": (
                            adapter_implementation_hash
                        ),
                        "provider_profile": model.provider,
                        "provider_profile_sha256": provider_profile_hashes[
                            model.provider
                        ],
                        "model_alias": model.alias,
                        "model_id": model.model,
                        "reasoning_effort": model.reasoning_effort,
                        "action_output_contract": model.action_output_contract,
                        "action_protocol": config.generation.action_protocol,
                        "max_turns": config.generation.max_turns,
                        "turn_policy": config.generation.turn_policy,
                        "max_output_tokens": config.generation.max_output_tokens,
                        "timeout_seconds": config.generation.timeout_seconds,
                    }
                    if openrouter_identity is not None:
                        identity["openrouter"] = openrouter_identity
                    if config.generation.terminal_protocol_version != LEGACY_TERMINAL_PROTOCOL:
                        identity["terminal_protocol_version"] = (
                            config.generation.terminal_protocol_version
                        )
                    if model.generation_seed is not None:
                        identity["generation_seed"] = model.generation_seed
                    if config.generation.episode_retry_limit:
                        identity["episode_retry_limit"] = config.generation.episode_retry_limit
                    if model.native_tool_policy is not None:
                        identity["native_tool_policy"] = model.native_tool_policy
                    if model.final_turn_tool_choice_policy is not None:
                        identity["final_turn_tool_choice_policy"] = model.final_turn_tool_choice_policy
                    if model.context_window_tokens is not None:
                        identity.update(
                            context_window_tokens=model.context_window_tokens,
                            context_safety_margin_tokens=model.context_safety_margin_tokens,
                            input_token_count_mode=model.input_token_count_mode,
                        )
                    if model.context_probe_max_requests is not None:
                        identity.update(
                            context_probe_max_requests=model.context_probe_max_requests,
                            context_probe_max_cost_usd=model.context_probe_max_cost_usd,
                        )
                    labels = {
                        "record_key": record_key,
                        "replicate": replicate,
                        "project_id": case.project_id,
                        "template_id": context.template_id,
                        "task": case.task,
                        "scope": case.scope,
                        "section_id": section_id,
                        "category": case.category,
                        "condition_id": (
                            condition.get("condition_id") if condition else None
                        ),
                        "model_alias": model.alias,
                        "provider_profile": model.provider,
                        "partial_smoke": bool(case.section_ids),
                    }
                    episode = WorkSpec(
                        kind="react_episode",
                        provider=model.provider,
                        model=model.alias,
                        identity=identity,
                        priority=10,
                        labels=labels,
                    )
                    episode_work.append(episode)
                    work.append(episode)

                record_identity = {
                    "schema_version": RECORD_SCHEMA_VERSION,
                    "study_id": config.study_id,
                    "study_mode": config.mode,
                    "inferential": config.inferential,
                    "record_key": record_key,
                    "replicate": replicate,
                    "project_id": case.project_id,
                    "template_id": context.template_id,
                    "contract_sha256": contract_hash,
                    "prepared_evidence_sha256": prepared_evidence_hash,
                    "task": case.task,
                    "scope": case.scope,
                    "category": case.category,
                    "condition_id": (
                        condition.get("condition_id") if condition else None
                    ),
                    "condition_sha256": (
                        sha256_json(condition) if condition else None
                    ),
                    "canonical_t0_sha256": (
                        t0.get("report_sha256") if t0 else None
                    ),
                    "provider_profile": model.provider,
                    "provider_profile_sha256": provider_profile_hashes[
                        model.provider
                    ],
                    "adapter_implementation_sha256": (
                        adapter_implementation_hash
                    ),
                    "action_normalization_policy_id": normalization_policy[
                        "policy_id"
                    ],
                    "action_normalization_policy_sha256": normalization_policy[
                        "sha256"
                    ],
                    "model_alias": model.alias,
                    "model_id": model.model,
                    "reasoning_effort": model.reasoning_effort,
                    "action_output_contract": model.action_output_contract,
                    "action_protocol": config.generation.action_protocol,
                    "max_turns": config.generation.max_turns,
                    "turn_policy": config.generation.turn_policy,
                    "max_output_tokens": config.generation.max_output_tokens,
                    "timeout_seconds": config.generation.timeout_seconds,
                    "partial_smoke": bool(case.section_ids),
                    "section_ids": [item for item in planned_sections if item],
                }
                if openrouter_identity is not None:
                    record_identity["openrouter"] = openrouter_identity
                if config.generation.terminal_protocol_version != LEGACY_TERMINAL_PROTOCOL:
                    record_identity["terminal_protocol_version"] = (
                        config.generation.terminal_protocol_version
                    )
                if model.generation_seed is not None:
                    record_identity["generation_seed"] = model.generation_seed
                if config.generation.episode_retry_limit:
                    record_identity["episode_retry_limit"] = config.generation.episode_retry_limit
                if model.native_tool_policy is not None:
                    record_identity["native_tool_policy"] = model.native_tool_policy
                if model.final_turn_tool_choice_policy is not None:
                    record_identity["final_turn_tool_choice_policy"] = model.final_turn_tool_choice_policy
                if model.context_window_tokens is not None:
                    record_identity.update(
                        context_window_tokens=model.context_window_tokens,
                        context_safety_margin_tokens=model.context_safety_margin_tokens,
                        input_token_count_mode=model.input_token_count_mode,
                    )
                if model.context_probe_max_requests is not None:
                    record_identity.update(
                        context_probe_max_requests=model.context_probe_max_requests,
                        context_probe_max_cost_usd=model.context_probe_max_cost_usd,
                    )
                reduction = WorkSpec(
                    kind="react_record",
                    provider="local",
                    model="reducer",
                    identity=record_identity,
                    dependencies=tuple(item.work_id for item in episode_work),
                    priority=20,
                    labels=record_identity,
                )
                work.append(reduction)
                records.append(
                    {
                        **record_identity,
                        "work_id": reduction.work_id,
                        "episode_work_ids": [
                            item.work_id for item in episode_work
                        ],
                    }
                )

    graph = WorkGraph(work)
    records.sort(key=lambda item: item["record_key"])
    return StudyPlan(config=config, graph=graph, records=tuple(records))


def expand_cases(
    config: StudyConfig,
    *,
    population_ids: tuple[str, ...] | None = None,
) -> tuple[CaseSpec, ...]:
    authoritative = set(
        population_ids
        or tuple(item["project_id"] for item in load_population()["projects"])
    )
    if config.selection.is_explicit:
        cases = config.selection.cases
    else:
        categories = (
            TOPOLOGY_CATEGORIES
            if config.selection.categories == "all"
            else tuple(config.selection.categories)
        )
        unknown_categories = sorted(set(categories) - set(TOPOLOGY_CATEGORIES))
        if unknown_categories:
            raise StudyPlanError(
                "unknown topology categories: " + ", ".join(unknown_categories)
            )
        expanded: list[CaseSpec] = []
        for project_id in config.selection.projects:
            for task in config.selection.tasks:
                task_categories: tuple[str | None, ...] = (
                    (None,) if task == "complete" else tuple(categories)
                )
                for category in task_categories:
                    for scope in config.selection.scopes:
                        expanded.append(
                            CaseSpec(project_id, task, scope, category)
                        )
        cases = tuple(expanded)

    unknown_projects = sorted(
        {case.project_id for case in cases} - authoritative
    )
    if unknown_projects:
        raise StudyPlanError(
            "projects are outside the frozen population: "
            + ", ".join(unknown_projects)
        )
    unknown_categories = sorted(
        {
            str(case.category)
            for case in cases
            if case.category is not None
        }
        - set(TOPOLOGY_CATEGORIES)
    )
    if unknown_categories:
        raise StudyPlanError(
            "unknown topology categories: " + ", ".join(unknown_categories)
        )
    return tuple(cases)


def _condition_index() -> dict[tuple[str, str, str], dict[str, Any]]:
    manifest = read_json(POPULATION_CONDITIONS_PATH)
    output: dict[tuple[str, str, str], dict[str, Any]] = {}
    for project in manifest.get("projects", []):
        project_id = str(project.get("project_id") or "").upper()
        for task, group in (("missingness", "masks"), ("update", "mutations")):
            for condition in project.get(group, []):
                key = (project_id, task, str(condition.get("category") or ""))
                if key in output:
                    raise StudyPlanError(f"duplicate condition for {key}")
                output[key] = condition
    return output


def _condition_for_case(
    case: CaseSpec,
    conditions: dict[tuple[str, str, str], dict[str, Any]],
) -> dict[str, Any] | None:
    if case.task == "complete":
        return None
    key = (case.project_id, case.task, str(case.category or ""))
    try:
        return conditions[key]
    except KeyError as exc:
        raise StudyPlanError(
            f"no frozen {case.task} condition for "
            f"{case.project_id}/{case.category}"
        ) from exc


def _selected_sections(
    case: CaseSpec,
    available: tuple[str, ...],
) -> tuple[str, ...]:
    selected = case.section_ids or available
    unknown = sorted(set(selected) - set(available))
    if unknown:
        raise StudyPlanError(
            f"{case.project_id}: unknown section IDs: {', '.join(unknown)}"
        )
    selected_set = set(selected)
    return tuple(section_id for section_id in available if section_id in selected_set)


def _load_twin(project_id: str) -> dict[str, Any]:
    path = NORMALIZED_ROOT / f"{project_id.lower()}.json"
    if not path.is_file():
        raise StudyPlanError(f"normalized twin is missing: {project_id}")
    return read_json(path)


def _record_key(
    *,
    model_alias: str,
    case: CaseSpec,
    replicate: int,
    selected_section_ids: tuple[str, ...],
) -> str:
    category = case.category.replace(".", "-") if case.category else "complete"
    parts = [
            model_alias,
            case.project_id.lower(),
            case.task,
            category,
            case.scope,
            f"r{replicate}",
    ]
    if case.section_ids:
        parts.append(
            f"sections-{sha256_json(list(selected_section_ids))[:10]}"
        )
    return ".".join(parts)


def _prompt_bundle_hash(task: str, scope: str) -> str:
    task_name = (
        "v2_report_generation.md"
        if task != "update" and scope == "report"
        else "v2_section_generation.md"
        if task != "update"
        else "v2_report_update.md"
        if scope == "report"
        else "v2_section_update.md"
    )
    paths = (PROMPT_ROOT / "v2_react_system.md", PROMPT_ROOT / task_name)
    try:
        contents = {
            path.name: path.read_text(encoding="utf-8") for path in paths
        }
    except OSError as exc:
        raise StudyPlanError(f"required prompt is missing: {exc.filename}") from exc
    return sha256_json(
        {name: sha256_text(text) for name, text in sorted(contents.items())}
    )


def _provider_profile_hash(profile_id: str) -> str:
    if profile_id == "fixture":
        value = {
            "profile_id": "fixture",
            "protocol": "in_process_fixture",
            "model_source": "deterministic-fixture-v1",
        }
    else:
        profile = resolve_provider_profile(profile_id)
        value = {
            "profile_id": profile.profile_id,
            "protocol": profile.protocol,
            "base_url": profile.base_url,
            "responses_endpoint": profile.responses_endpoint,
            "api_key_env": profile.api_key_env,
            "allow_insecure_http": profile.allow_insecure_http,
            "structured_output_dialect": profile.structured_output_dialect,
            "request_headers": [list(item) for item in profile.request_headers],
            "supports_openrouter_policy": profile.supports_openrouter_policy,
        }
    return sha256_json(value)


def _action_interface_hash() -> str:
    from benchmarks.react_report_building.runtime import (
        native_tool_policy,
        protocol,
        structured_output,
        tool_schemas,
    )
    from benchmarks.react_report_building.runtime.providers import openai_responses

    paths = (
        Path(native_tool_policy.__file__),
        Path(protocol.__file__),
        Path(structured_output.__file__),
        Path(tool_schemas.__file__),
        Path(openai_responses.__file__),
    )
    return sha256_json(
        {
            path.name: sha256_text(path.read_text(encoding="utf-8"))
            for path in paths
        }
    )


def _action_normalization_policy(action_protocol: str) -> dict[str, str]:
    from benchmarks.react_report_building.runtime.providers.openai_responses import (
        NATIVE_ACTION_NORMALIZATION_POLICY,
        TEXTUAL_ACTION_NORMALIZATION_POLICY,
    )

    policy = (
        NATIVE_ACTION_NORMALIZATION_POLICY
        if action_protocol == "native_tools"
        else TEXTUAL_ACTION_NORMALIZATION_POLICY
    )
    return {
        "policy_id": str(policy["policy_id"]),
        "sha256": sha256_json(policy),
    }


def _adapter_implementation_hash() -> str:
    repository = Path(__file__).resolve().parents[2]
    fixed = [
        repository / "benchmarks/benchrunner/adapters/react_report_v2.py",
        repository / "benchmarks/benchrunner/checkpointing.py",
        repository / "benchmarks/benchrunner/metrics.py",
        repository / "benchmarks/benchrunner/storage.py",
        repository / "benchmarks/benchrunner/probe_budget.py",
        repository / "benchmarks/benchrunner/providers/profiles.py",
        repository / "benchmarks/react_report_building/runtime/episode_factory.py",
        repository / "benchmarks/react_report_building/runtime/accounting.py",
        repository / "benchmarks/react_report_building/runtime/provider_cost.py",
        repository / "benchmarks/react_report_building/runtime/calculator.py",
        repository / "benchmarks/react_report_building/runtime/controller.py",
        repository / "benchmarks/react_report_building/runtime/episode.py",
        repository / "benchmarks/react_report_building/runtime/final_turn_policy.py",
        repository / "benchmarks/react_report_building/runtime/native_tool_policy.py",
        repository / "benchmarks/react_report_building/runtime/context_budget.py",
        repository / "benchmarks/react_report_building/runtime/evidence_store.py",
        repository / "benchmarks/react_report_building/runtime/protocol.py",
        repository / "benchmarks/react_report_building/runtime/structured_output.py",
        repository / "benchmarks/react_report_building/runtime/tool_schemas.py",
        repository / "benchmarks/react_report_building/runtime/providers/__init__.py",
        repository / "benchmarks/react_report_building/runtime/providers/base.py",
        repository / "benchmarks/react_report_building/runtime/providers/factory.py",
        repository / "benchmarks/react_report_building/runtime/providers/fixtures.py",
        repository / "benchmarks/react_report_building/runtime/providers/openai_responses.py",
        repository / "benchmarks/react_report_building/v2/document.py",
        repository / "benchmarks/react_report_building/v2/citation_context.py",
        repository / "benchmarks/react_report_building/evaluation/alignment.py",
        repository / "benchmarks/react_report_building/evaluation/oracle.py",
        repository / "benchmarks/react_report_building/v2/evaluation.py",
        repository / "benchmarks/react_report_building/v2/evidence.py",
        repository / "benchmarks/react_report_building/v2/missingness_runner.py",
        repository / "benchmarks/react_report_building/v2/output_validation.py",
        repository / "benchmarks/react_report_building/v2/perturbations.py",
        repository / "benchmarks/react_report_building/v2/source_aliases.py",
        repository / "benchmarks/react_report_building/v2/registry.py",
        repository / "benchmarks/react_report_building/v2/rendering.py",
        repository / "benchmarks/react_report_building/v2/runner.py",
        repository / "benchmarks/react_report_building/v2/update_runner.py",
    ]
    paths = sorted(
        set(fixed)
        | set(
            (
                repository
                / "benchmarks/react_report_building/runtime/tools"
            ).glob("*.py")
        )
    )
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise StudyPlanError(
            "adapter implementation file is missing: "
            + ", ".join(path.name for path in missing)
        )
    return sha256_json(
        {
            path.relative_to(repository).as_posix(): sha256_text(
                path.read_text(encoding="utf-8")
            )
            for path in paths
        }
    )
