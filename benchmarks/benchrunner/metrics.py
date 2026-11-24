"""Portable run accounting derived from immutable scheduler state."""

from __future__ import annotations

from collections import defaultdict
from itertools import chain
from math import isfinite
from typing import Any, Iterable, Iterator

from benchmarks.react_report_building.runtime.provider_cost import (
    add_provider_cost,
    empty_provider_cost_summary,
    normalize_provider_cost,
)

from .retry import failed_response_accounting_from_error
from .storage import RunStore, is_pre_response_disconnect
from benchmarks.react_report_building.runtime.accounting import episode_turns


USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "cached_input_tokens",
)


def record_outcomes(
    episodes: list[dict[str, Any]], score: dict[str, Any] | None,
) -> dict[str, Any]:
    """Keep protocol, terminal, validity, generation and scientific axes separate.

    Missing diagnostics stay unmeasured. In particular, normalized turns cannot
    establish raw conformance, and an inherited keep is never counted as newly
    generated Markdown. Scientific components remain visible on invalid output.
    """

    def counts() -> dict[str, int]:
        return {"valid": 0, "invalid": 0, "unmeasured": 0, "total": 0}

    def add(target: dict[str, int], value: bool | None) -> None:
        target["total"] += 1
        target["valid" if value is True else "invalid" if value is False else "unmeasured"] += 1

    strict = counts()
    raw_native = counts()
    normalized_native = counts()
    actions = {action: {"accepted": 0, "output_validity": counts()} for action in (
        "create", "replace", "keep", "unknown"
    )}
    observations = {
        "completed_retrieval_calls": 0,
        "available_retrieval_results": 0,
        "completed_calculation_calls": 0,
        "available_calculation_results": 0,
    }
    accepted = 0
    first_attempt_accepted = 0
    normalizations = 0
    for episode in episodes:
        first = (episode.get("prior_attempts") or [episode])[0]
        first_attempt_accepted += (first.get("terminal") or {}).get("status") == "accepted"
        terminal = episode.get("terminal") or {}
        validity = (terminal.get("output_validation") or {}).get("valid")
        add(strict, validity if isinstance(validity, bool) else None)
        if terminal.get("status") == "accepted":
            accepted += 1
            mode = terminal.get("mode")
            tool = terminal.get("tool")
            action = (
                "keep" if mode in {"keep", "retain"} or tool == "keep_section"
                else "replace" if mode in {"replace", "rewrite"} or tool == "replace_section"
                else "create" if mode == "create" or tool in {"create_report", "create_section"}
                else "unknown"
            )
            actions[action]["accepted"] += 1
            add(actions[action]["output_validity"], validity if isinstance(validity, bool) else None)
        for turn in episode_turns(episode):
            normalization_count = len(turn.get("normalizations") or [])
            normalizations += normalization_count
            if (turn.get("action_protocol") or turn.get("protocol")) == "native_tools":
                conformant = (
                    False if turn.get("status") == "protocol_error" or any(
                        item.get("status") in {"protocol_error", "invalid_arguments"}
                        for item in turn.get("observations") or []
                    ) else True if turn.get("status") == "completed" else None
                )
                add(normalized_native, conformant)
                add(raw_native, None if normalization_count else conformant)
            for observation in turn.get("observations") or []:
                prefix = (
                    "retrieval" if observation.get("tool") == "get_data"
                    else "calculation" if observation.get("tool") == "calculate"
                    else None
                )
                if prefix is not None and observation.get("status") == "completed":
                    observations[f"completed_{prefix}_calls"] += 1
                    observations[f"available_{prefix}_results"] += sum(
                        result.get("status") == "available"
                        for result in observation.get("results") or []
                    )
    update = (score or {}).get("update") or {}
    return {
        "schema_version": "benchrunner.record_outcomes/v1",
        "episodes": len(episodes),
        "terminal_accepted": accepted,
        "terminal_unaccepted": len(episodes) - accepted,
        "episode_terminal_reached_rate": accepted / len(episodes) if episodes else None,
        "report_reached_terminal": bool(episodes) and accepted == len(episodes),
        "first_attempt_terminal_accepted": first_attempt_accepted,
        "first_attempt_report_reached_terminal": bool(episodes) and first_attempt_accepted == len(episodes),
        "episode_terminal_rate_definition": "accepted terminal submissions / episodes; not content completeness or correctness",
        "episodes_retried": sum(bool(e.get("prior_attempts")) for e in episodes),
        "strict_output_validity": strict,
        "terminal_actions": actions,
        "generated_outputs": actions["create"]["accepted"] + actions["replace"]["accepted"],
        "inherited_keeps": actions["keep"]["accepted"],
        "raw_native_conformance": raw_native,
        "normalized_native_conformance": normalized_native,
        "native_conformance_basis": "controller_action_validation; normalized_raw_turns_unmeasured",
        "normalization_count": normalizations,
        "tool_observations": observations,
        "scientific_primary_score": (score or {}).get("primary_score"),
        "scientific_score_scope": (score or {}).get("score_scope"),
        "semantic_prose_quality_measured": (score or {}).get("semantic_prose_quality_measured"),
        "scientific_component_scores": (
            {name: component.get("score") for name, component in score["components"].items()}
            if isinstance((score or {}).get("components"), dict) else None
        ),
        "affected_update_correctness": update.get("affected_section_correctness"),
        "unaffected_preservation": update.get("unaffected_section_preservation"),
        "update_routing": update.get("routing"),
    }


def provider_turn_records(store: RunStore) -> Iterator[dict[str, Any]]:
    """Return one sanitized row per successful provider response.

    Provider-turn checkpoints are the authoritative run-level cost ledger.
    Failed requests that produced no response have no checkpoint and therefore
    contribute no tokens. Replaying a checkpoint during resume also contributes
    no additional row or usage.
    """

    states = {state.work.work_id: state for state in store.states()}
    expected_count = store.provider_turn_checkpoint_count()
    observed_count = 0
    ledgers: dict[str, dict[str, int]] = {}
    for checkpoint in store.iter_provider_turn_metric_records():
        observed_count += 1
        name = checkpoint["name"]
        state = states.get(checkpoint["work_id"])
        if state is None:
            raise ValueError(
                f"provider-turn checkpoint has unknown work: "
                f"{checkpoint['work_id']}/{name}"
            )
        usage = _normalized_usage(checkpoint, checkpoint=name)
        provider_cost = _normalized_provider_cost(
            checkpoint.get("provider_cost"),
            checkpoint=name,
        )
        latency = _nonnegative_float(
            checkpoint.get("latency_seconds"),
            field="latency_seconds",
            checkpoint=name,
        )
        normalization_count = _nonnegative_int(
            checkpoint.get("normalization_count"),
            field="normalization_count",
            checkpoint=name,
        )
        normalization_rule_counts = _normalized_rule_counts(
            checkpoint.get("normalization_rule_counts"),
            checkpoint=name,
        )
        if sum(normalization_rule_counts.values()) != normalization_count:
            raise ValueError(
                "provider-turn checkpoint normalization counts disagree: "
                f"{name}"
            )
        identity = dict(state.work.identity)
        model_identity = work_model_identity(state.work)
        turn_index = _turn_index(name)
        ledger = ledgers.setdefault(
            state.work.work_id,
            {
                "previous_input_tokens": -1,
                "cumulative_input_tokens": 0,
                "cumulative_output_tokens": 0,
            },
        )
        input_tokens = usage["input_tokens"]
        output_tokens = usage["output_tokens"]
        cached_input_tokens = min(
            input_tokens,
            usage["cached_input_tokens"],
        )
        previous_input_tokens = ledger["previous_input_tokens"]
        ledger["cumulative_input_tokens"] += input_tokens
        ledger["cumulative_output_tokens"] += output_tokens
        token_attribution: dict[str, Any] = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "reasoning_tokens": usage["reasoning_tokens"],
            "cached_input_tokens": cached_input_tokens,
            "uncached_input_tokens": input_tokens - cached_input_tokens,
            "input_token_change_from_previous_turn": (
                None
                if previous_input_tokens < 0
                else input_tokens - previous_input_tokens
            ),
            "cumulative_input_tokens": ledger["cumulative_input_tokens"],
            "cumulative_output_tokens": ledger["cumulative_output_tokens"],
            "cumulative_total_tokens": (
                ledger["cumulative_input_tokens"]
                + ledger["cumulative_output_tokens"]
            ),
        }
        request_context = checkpoint.get("request_context")
        if isinstance(request_context, dict) and request_context:
            token_attribution["request_context"] = request_context
        ledger["previous_input_tokens"] = input_tokens
        yield {
            "schema_version": "benchrunner.provider_turn_export/v3",
            "work_id": state.work.work_id,
            "work_status": state.status,
            "checkpoint_name": name,
            "checkpoint_sha256": checkpoint["payload_sha256"],
            "checkpoint_created_at": float(checkpoint["checkpoint_created_at"]),
            "producer_implementation_sha256": checkpoint.get(
                "producer_implementation_sha256"
            ),
            "turn_index": turn_index,
            "provider": model_identity["provider_profile"],
            "model": model_identity["model_id"],
            **model_identity,
            "project_id": identity.get("project_id"),
            "task": identity.get("task"),
            "scope": identity.get("scope"),
            "section_id": identity.get("section_id"),
            "action_protocol": identity.get("action_protocol"),
            "action_output_contract": identity.get("action_output_contract"),
            "usage": usage,
            "provider_cost": provider_cost,
            "token_attribution": token_attribution,
            "normalization_count": normalization_count,
            "normalization_rule_counts": normalization_rule_counts,
            "successful_response_latency_seconds": latency,
        }
    if observed_count != expected_count:
        raise ValueError(
            "one or more provider-turn checkpoints lack valid compact metrics"
        )


def scheduler_attempt_records(store: RunStore) -> Iterator[dict[str, Any]]:
    """Return sanitized attempt history with global and cycle-relative IDs."""

    states = {state.work.work_id: state for state in store.states()}
    cycles: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in store.retry_cycle_records():
        cycles[str(row["work_id"])].append(row)

    for attempt in store.iter_attempt_records():
        work_id = str(attempt["work_id"])
        state = states.get(work_id)
        if state is None:
            raise ValueError(f"scheduler attempt has unknown work: {work_id}")
        global_attempt = int(attempt["attempt"])
        cycle, base = _cycle_for_attempt(cycles[work_id], global_attempt)
        started = float(attempt["started_at"])
        finished_raw = attempt.get("finished_at")
        finished = float(finished_raw) if finished_raw is not None else None
        identity = dict(state.work.identity)
        model_identity = work_model_identity(state.work)
        error_value = attempt.get("error_json")
        failed_response = failed_response_accounting_from_error(error_value)
        record = {
            "schema_version": "benchrunner.scheduler_attempt_export/v3",
            "work_id": work_id,
            "kind": state.work.kind,
            "provider": state.work.provider,
            "model": state.work.model,
            **model_identity,
            "project_id": identity.get("project_id"),
            "task": identity.get("task"),
            "scope": identity.get("scope"),
            "section_id": identity.get("section_id"),
            "attempt": global_attempt,
            "retry_cycle": cycle,
            "cycle_attempt": global_attempt - base,
            "owner": attempt["owner"],
            "producer_implementation_sha256": attempt.get(
                "producer_implementation_sha256"
            ),
            "status": attempt["status"],
            "started_at": started,
            "finished_at": finished,
            "wall_seconds": (
                max(0.0, finished - started) if finished is not None else None
            ),
            "scheduled_retry_delay_seconds": float(
                attempt.get("retry_delay_seconds") or 0.0
            ),
            "timing": attempt.get("timing_json") or {},
            "error": error_value,
        }
        if failed_response is not None:
            record["failed_response_accounting"] = failed_response
        yield record


def retry_cycle_export_records(store: RunStore) -> Iterator[dict[str, Any]]:
    """Return explicit resume-cycle boundaries and their audit reasons."""

    states = {state.work.work_id: state for state in store.states()}
    for row in store.retry_cycle_records():
        work_id = str(row["work_id"])
        state = states.get(work_id)
        if state is None:
            raise ValueError(f"retry cycle has unknown work: {work_id}")
        identity = dict(state.work.identity)
        reason = row.get("reason_json")
        reason = reason if isinstance(reason, dict) else None
        yield {
            "schema_version": "benchrunner.retry_cycle_export/v1",
            "work_id": work_id,
            "kind": state.work.kind,
            **work_model_identity(state.work),
            "project_id": identity.get("project_id"),
            "task": identity.get("task"),
            "scope": identity.get("scope"),
            "section_id": identity.get("section_id"),
            "retry_cycle": int(row["cycle"]),
            "attempt_base": int(row["attempt_base"]),
            "created_at": float(row["created_at"]),
            "resume_implementation_sha256": (
                (
                    reason.get("resume_implementation_sha256")
                    or reason.get("runner_implementation_sha256")
                )
                if reason
                else None
            ),
            "reason": reason,
        }


def work_model_identity(work: Any) -> dict[str, Any]:
    """Resolve the immutable actual model identity from a work specification."""

    identity = dict(work.identity)
    return {
        "provider_profile": str(
            identity.get("provider_profile") or work.provider
        ),
        "model_alias": str(identity.get("model_alias") or work.model),
        "model_id": str(identity.get("model_id") or work.model),
        "reasoning_effort": identity.get("reasoning_effort"),
        "action_output_contract": identity.get("action_output_contract"),
    }


def observed_provider_accounting(
    records: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    overall = _empty_usage_totals()
    grouped: dict[tuple[str, str, str | None, str | None], dict[str, Any]] = {}
    aliases: dict[
        tuple[str, str, str | None, str | None], set[str]
    ] = defaultdict(set)
    for row in records:
        _add_usage(overall, row)
        reasoning_raw = row.get("reasoning_effort")
        reasoning = None if reasoning_raw is None else str(reasoning_raw)
        contract_raw = row.get("action_output_contract")
        action_output_contract = (
            None if contract_raw is None else str(contract_raw)
        )
        key = (
            str(row.get("provider_profile") or row["provider"]),
            str(row.get("model_id") or row["model"]),
            reasoning,
            action_output_contract,
        )
        aliases[key].add(str(row.get("model_alias") or row["model"]))
        _add_usage(grouped.setdefault(key, _empty_usage_totals()), row)
    by_model = []
    for (
        provider_profile,
        model_id,
        reasoning_effort,
        action_output_contract,
    ), totals in sorted(
        grouped.items(),
        key=lambda item: (
            item[0][0],
            item[0][1],
            item[0][2] or "",
            item[0][3] or "",
        ),
    ):
        model_aliases = sorted(
            aliases[
                (
                    provider_profile,
                    model_id,
                    reasoning_effort,
                    action_output_contract,
                )
            ]
        )
        by_model.append(
            {
                "provider": provider_profile,
                "model": model_id,
                "provider_profile": provider_profile,
                "model_id": model_id,
                "model_alias": (
                    model_aliases[0] if len(model_aliases) == 1 else None
                ),
                "model_aliases": model_aliases,
                "reasoning_effort": reasoning_effort,
                "action_output_contract": action_output_contract,
                **totals,
            }
        )
    return {
        "basis": "immutable_successful_provider_turn_checkpoints",
        "no_response_attempts_included": False,
        **overall,
        "by_model": by_model,
    }


def failed_provider_response_accounting(
    records: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate sanitized responses that failed and were retried."""

    reports: dict[
        tuple[str, str, str | None, str | None] | None,
        dict[str, int],
    ] = defaultdict(
        lambda: {
            "usage_reported_response_turns": 0,
            "usage_unreported_response_turns": 0,
        }
    )

    def tracked_rows() -> Iterator[dict[str, Any]]:
        for row in _failed_response_rows(records):
            counter = (
                "usage_reported_response_turns"
                if row["failed_usage_reported"]
                else "usage_unreported_response_turns"
            )
            for key in (None, _accounting_model_key(row)):
                reports[key][counter] += 1
            yield row

    summary = observed_provider_accounting(tracked_rows())
    return {
        "basis": "immutable_scheduler_attempt_failed_response_receipts",
        "no_response_attempts_included": False,
        **_failed_accounting_view(summary, reports[None]),
        "by_model": [
            _failed_accounting_view(
                item,
                reports[_accounting_model_key(item)],
            )
            for item in summary["by_model"]
        ],
    }


def operational_provider_accounting(
    successful_records: Iterable[dict[str, Any]],
    attempt_records: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Combine successful turns and failed-response receipts for operations."""

    split: dict[
        tuple[str, str, str | None, str | None] | None,
        dict[str, float | int],
    ] = defaultdict(
        lambda: {
            "successful_response_turns": 0,
            "failed_response_turns": 0,
            "failed_usage_reported_response_turns": 0,
            "failed_usage_unreported_response_turns": 0,
            "successful_response_latency_seconds": 0.0,
            "failed_response_latency_seconds": 0.0,
        }
    )
    preflights = defaultdict(_ContextPreflightTotals)

    def track_preflight(row: dict[str, Any]) -> None:
        for key in (None, _accounting_model_key(row)):
            preflights[key].add(row)

    def tagged_successful() -> Iterator[dict[str, Any]]:
        for row in successful_records:
            track_preflight(row)
            latency = float(
                row.get("successful_response_latency_seconds") or 0.0
            )
            for key in (None, _accounting_model_key(row)):
                split[key]["successful_response_turns"] += 1
                split[key]["successful_response_latency_seconds"] += latency
            yield row

    def tagged_failed() -> Iterator[dict[str, Any]]:
        def tracked_attempts() -> Iterator[dict[str, Any]]:
            for attempt in attempt_records:
                # Only the failing request's receipt lives in attempt metadata;
                # prior completed/replayed turns are already in checkpoints.
                if _context_budget_receipt(attempt) is not None:
                    track_preflight(attempt)
                yield attempt

        for row in _failed_response_rows(tracked_attempts()):
            latency = float(row["successful_response_latency_seconds"])
            for key in (None, _accounting_model_key(row)):
                split[key]["failed_response_turns"] += 1
                split[key]["failed_response_latency_seconds"] += latency
                report_key = (
                    "failed_usage_reported_response_turns"
                    if row["failed_usage_reported"]
                    else "failed_usage_unreported_response_turns"
                )
                split[key][report_key] += 1
            yield row

    summary = observed_provider_accounting(
        chain(tagged_successful(), tagged_failed())
    )
    _annotate_operational_accounting(summary, split[None])
    summary["context_preflight_accounting"] = preflights[None].result()
    summary["context_preflight_accounting"]["by_model"] = [
        {
            "provider_profile": key[0], "model_id": key[1],
            "reasoning_effort": key[2], "action_output_contract": key[3],
            **totals.result(),
        }
        for key, totals in sorted(
            ((key, value) for key, value in preflights.items() if key is not None),
            key=lambda item: tuple(value or "" for value in item[0]),
        )
    ]
    for item in summary["by_model"]:
        _annotate_operational_accounting(
            item,
            split[_accounting_model_key(item)],
        )
        item["context_preflight_accounting"] = preflights[_accounting_model_key(item)].result()
    summary["basis"] = (
        "successful_provider_turn_checkpoints_plus_"
        "scheduler_failed_response_receipts"
    )
    return summary


def context_preflight_accounting(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Summarize counting overhead separately from task-generation usage.

    Supply each immutable checkpoint/failure receipt once. Equal request hashes
    are not deduplicated: a retry can perform the same preflight again. A local
    conservative estimate makes zero provider requests; an injected counter
    without a receipt has unknown overhead.
    """
    totals = _ContextPreflightTotals()
    for row in records:
        totals.add(row)
    return totals.result()


def _context_budget_receipt(row: dict[str, Any]) -> dict[str, Any] | None:
    context = row.get("request_context")
    if context is None:
        context = (row.get("token_attribution") or {}).get("request_context")
    if context is None:
        context = ((row.get("error") or {}).get("metadata") or {}).get("request_context")
    budget = context.get("context_budget") if isinstance(context, dict) else None
    return budget if isinstance(budget, dict) else None


class _ContextPreflightTotals:
    def __init__(self) -> None:
        self.budget_checks = 0
        self.without_receipt = 0
        self.methods: dict[str, int] = defaultdict(int)
        self.count_kinds: dict[str, int] = defaultdict(int)
        self.probes_triggered = 0
        self.known_requests = 0
        self.unknown_requests = 0
        self.generation_requests = 0
        self.unknown_generation = 0
        self.latency = 0.0
        self.unknown_latency = 0
        self.usage = {field: 0 for field in USAGE_FIELDS}
        self.coverage = {field: {"reported_requests": 0, "unreported_requests": 0, "inconsistent_requests": 0} for field in USAGE_FIELDS}
        self.usage_warning_counts: dict[str, int] = defaultdict(int)
        self.provider_cost = empty_provider_cost_summary()

    def add(self, row: dict[str, Any]) -> None:
        budget = _context_budget_receipt(row)
        if budget is None:
            self.without_receipt += 1
            return
        mode = budget.get("input_token_count_mode")
        conditional_probe = mode == "openrouter_probe_on_clamp"
        if (
            budget.get("schema_version") not in (
                {"react_report.context_budget/v2", "react_report.context_budget/v3", "react_report.context_budget/v4"} if conditional_probe else {"react_report.context_budget/v1"}
            )
            or not isinstance(mode, str)
            or mode not in {"openai_responses", "responses_probe", "vllm_responses", "conservative_bytes", "injected", "openrouter_probe_on_clamp"}
        ):
            raise ValueError("context preflight receipt has an invalid counting method")
        self.budget_checks += 1
        self.methods[mode] += 1
        kind = budget.get("count_kind")
        if not isinstance(kind, str) or kind not in {"estimate", "exact"}:
            raise ValueError("context preflight receipt has an invalid count kind")
        self.count_kinds[kind] += 1
        if conditional_probe:
            triggered = budget.get("probe_triggered")
            if not isinstance(triggered, bool):
                raise ValueError("conditional context preflight must report probe_triggered")
            self.probes_triggered += int(triggered)
        receipt = budget.get("preflight")
        if receipt is None and (mode == "conservative_bytes" or (conditional_probe and not triggered)):
            return
        if receipt is None:
            receipt = {}
        if not isinstance(receipt, dict):
            raise ValueError("context preflight receipt must be an object")
        for attempt in receipt.get("attempts", [receipt]):
            self._add_preflight(attempt)

    def _add_preflight(self, receipt: dict[str, Any]) -> None:
        count = receipt.get("request_count")
        if count is not None:
            if not isinstance(count, int) or isinstance(count, bool):
                raise ValueError("context preflight request_count must be an integer")
            count = _nonnegative_int(count, field="request_count", checkpoint="context_preflight")
            self.known_requests += count
        else:
            self.unknown_requests += 1
        if count == 0:
            # A budget denial before sending a probe incurs no provider work.
            # Do not turn absent latency/usage/cost into unknown paid overhead.
            return
        generated = receipt.get("generation_requested")
        if generated is True and count is not None:
            self.generation_requests += count
        elif generated is not False:
            self.unknown_generation += 1
        latency = receipt.get("latency_seconds")
        if latency is None:
            self.unknown_latency += 1
        else:
            if isinstance(latency, bool) or not isinstance(latency, (int, float)) or not isfinite(latency):
                raise ValueError("context preflight latency must be a finite number")
            self.latency += _nonnegative_float(latency, field="latency_seconds", checkpoint="context_preflight")
        usage = receipt.get("usage")
        if usage is not None and not isinstance(usage, dict):
            raise ValueError("context preflight usage must be an object or null")
        warnings = receipt.get("usage_warnings", [])
        for warning in warnings:
            self.usage_warning_counts[warning] += count if count is not None else 1
        for field in USAGE_FIELDS:
            value = (usage or {}).get(field)
            if field == "reasoning_tokens" and "reasoning_tokens_exceed_output_tokens" in warnings:
                # Keep the reported detail in the receipt, but do not present
                # an inconsistent component as a trustworthy aggregate.
                self.coverage[field]["inconsistent_requests"] += count if count is not None else 1
            elif value is None:
                self.coverage[field]["unreported_requests"] += count if count is not None else 1
            else:
                if not isinstance(value, int) or isinstance(value, bool):
                    raise ValueError("context preflight token usage must be an integer")
                self.usage[field] += _nonnegative_int(value, field=field, checkpoint="context_preflight")
                self.coverage[field]["reported_requests"] += count if count is not None else 1
        if count == 1:
            add_provider_cost(self.provider_cost, receipt.get("provider_cost"))

    def result(self) -> dict[str, Any]:
        usage = {
            field: None if (self.coverage[field]["unreported_requests"]
                            or self.coverage[field]["inconsistent_requests"]) else self.usage[field]
            for field in USAGE_FIELDS
        }
        provider_cost = dict(self.provider_cost)
        if self.known_requests == 0 and self.unknown_requests == 0:
            provider_cost["total"] = "0"
        return {
            "schema_version": "benchrunner.context_preflight_accounting/v1",
            "basis": "observed_context_budget_receipts; task_generation_usage_excluded",
            "budget_checks": self.budget_checks,
            "records_without_budget_receipt": self.without_receipt,
            "method_counts": dict(sorted(self.methods.items())),
            "count_kind_counts": dict(sorted(self.count_kinds.items())),
            "conditional_probes_triggered": self.probes_triggered,
            "request_count": None if self.unknown_requests else self.known_requests,
            "known_request_count": self.known_requests,
            "checks_with_unknown_request_count": self.unknown_requests,
            "generation_request_count": None if self.unknown_generation else self.generation_requests,
            "known_generation_request_count": self.generation_requests,
            "provider_latency_seconds": None if self.unknown_latency else self.latency,
            "known_provider_latency_seconds": self.latency,
            "checks_with_unknown_latency": self.unknown_latency,
            "usage": usage,
            "known_usage": dict(self.usage),
            "usage_coverage": self.coverage,
            "usage_warning_counts": dict(sorted(self.usage_warning_counts.items())),
            "provider_cost": provider_cost,
            "total_tokens": (
                usage["input_tokens"] + usage["output_tokens"]
                if usage["input_tokens"] is not None and usage["output_tokens"] is not None else None
            ),
        }


def retry_diagnostics(
    records: Iterable[dict[str, Any]],
    *,
    retry_cycle_count: int,
) -> dict[str, Any]:
    statuses: dict[str, int] = {}
    provider_no_response_failures = 0
    provider_http_failures = 0
    provider_failed_responses = 0
    attempt_wall_seconds = 0.0
    executor_seconds = 0.0
    queue_seconds = 0.0
    scheduled_retry_delay_seconds = 0.0
    attempt_count = 0
    for row in records:
        attempt_count += 1
        status = str(row.get("status") or "unknown")
        statuses[status] = statuses.get(status, 0) + 1
        error = row.get("error")
        metadata = error.get("metadata") if isinstance(error, dict) else None
        metadata = metadata if isinstance(metadata, dict) else {}
        if is_pre_response_disconnect(error):
            provider_no_response_failures += 1
        elif metadata.get("response_received") is True:
            provider_failed_responses += 1
        elif (
            isinstance(error, dict)
            and error.get("code") == "provider.request_failed"
            and "http_status" in metadata
        ):
            provider_http_failures += 1
        if row.get("wall_seconds") is not None:
            attempt_wall_seconds += float(row["wall_seconds"])
        timing = row.get("timing")
        timing = timing if isinstance(timing, dict) else {}
        durations = timing.get("durations_seconds")
        durations = durations if isinstance(durations, dict) else {}
        executor_seconds += float(durations.get("executor_seconds") or 0.0)
        queue_seconds += float(durations.get("queue_seconds") or 0.0)
        scheduled_retry_delay_seconds += float(
            row.get("scheduled_retry_delay_seconds") or 0.0
        )
    return {
        "attempt_count": attempt_count,
        "attempt_statuses": dict(sorted(statuses.items())),
        "provider_no_response_failures": provider_no_response_failures,
        "provider_http_failures": provider_http_failures,
        "provider_failed_responses": provider_failed_responses,
        "retry_cycles": int(retry_cycle_count),
        "attempt_wall_seconds": attempt_wall_seconds,
        "executor_seconds": executor_seconds,
        "queue_seconds": queue_seconds,
        "scheduled_retry_delay_seconds": scheduled_retry_delay_seconds,
        "token_accounting_policy": (
            "no_response_attempts_add_zero_tokens; failed responses are "
            "accounted from sanitized scheduler receipts"
        ),
    }


def run_metrics(store: RunStore) -> dict[str, Any]:
    cycles = store.retry_cycle_records()
    states = store.states()
    episode_states = [state for state in states if state.work.kind == "react_episode"]
    record_states = [state for state in states if state.work.kind == "react_record"]
    completed_records = [
        state
        for state in record_states
        if state.status == "completed" and isinstance(state.result, dict)
    ]
    successful_accounting = observed_provider_accounting(
        provider_turn_records(store)
    )
    failed_accounting = failed_provider_response_accounting(
        scheduler_attempt_records(store)
    )
    operational_accounting = operational_provider_accounting(
        provider_turn_records(store),
        scheduler_attempt_records(store),
    )
    return {
        "scheduler": store.summary(),
        "episodes": {
            "materialized": sum(state.status == "completed" for state in episode_states),
            "total": len(episode_states),
        },
        "records": {
            "evaluated": len(completed_records),
            "finalized": len(completed_records),
            "with_scientific_scores": sum(
                isinstance((state.result.get("record") or {}).get("score"), dict)
                for state in completed_records
            ),
            "analysis_eligible": sum(
                (state.result.get("record") or {}).get("analysis_eligible") is True
                for state in completed_records
            ),
            "total": len(record_states),
        },
        "observed_provider_accounting": successful_accounting,
        "failed_provider_response_accounting": failed_accounting,
        "operational_provider_accounting": operational_accounting,
        "retry_diagnostics": retry_diagnostics(
            scheduler_attempt_records(store),
            retry_cycle_count=len(cycles),
        ),
    }


def _accounting_model_key(
    row: dict[str, Any],
) -> tuple[str, str, str | None, str | None]:
    reasoning_raw = row.get("reasoning_effort")
    reasoning = None if reasoning_raw is None else str(reasoning_raw)
    contract_raw = row.get("action_output_contract")
    action_output_contract = (
        None if contract_raw is None else str(contract_raw)
    )
    return (
        str(row.get("provider_profile") or row["provider"]),
        str(row.get("model_id") or row["model"]),
        reasoning,
        action_output_contract,
    )


def _failed_response_from_attempt(
    row: dict[str, Any],
) -> dict[str, Any] | None:
    value = row.get("failed_response_accounting")
    if value is None:
        return failed_response_accounting_from_error(row.get("error"))
    # Revalidate even the promoted export field before using it in totals.
    return failed_response_accounting_from_error(
        {
            "metadata": {
                "failed_response_accounting": value,
            }
        }
    )


def _failed_response_rows(
    records: Iterable[dict[str, Any]],
) -> Iterator[dict[str, Any]]:
    for row in records:
        accounting = _failed_response_from_attempt(row)
        if accounting is None:
            continue
        yield {
            key: row.get(key)
            for key in (
                "provider",
                "model",
                "provider_profile",
                "model_id",
                "model_alias",
                "reasoning_effort",
                "action_output_contract",
            )
        } | {
            "usage": accounting["usage"]
            or {field_name: 0 for field_name in USAGE_FIELDS},
            "failed_usage_reported": accounting["usage_reported"],
            "provider_cost": accounting["provider_cost"],
            "normalization_count": 0,
            "normalization_rule_counts": {},
            "successful_response_latency_seconds": accounting[
                "latency_seconds"
            ],
        }


def _failed_accounting_view(
    summary: dict[str, Any],
    reports: dict[str, int],
) -> dict[str, Any]:
    omitted = {
        "basis",
        "by_model",
        "no_response_attempts_included",
        "normalization_count",
        "normalization_rule_counts",
        "response_turns",
        "successful_response_latency_seconds",
    }
    return {
        key: value for key, value in summary.items() if key not in omitted
    } | {
        "failed_response_turns": int(summary["response_turns"]),
        **reports,
        "failed_response_latency_seconds": float(
            summary["successful_response_latency_seconds"]
        ),
    }


def _annotate_operational_accounting(
    summary: dict[str, Any],
    split: dict[str, float | int],
) -> None:
    total_latency = float(summary["successful_response_latency_seconds"])
    summary.update(split)
    summary["provider_response_latency_seconds"] = total_latency


def _empty_usage_totals() -> dict[str, Any]:
    return {
        **{field: 0 for field in USAGE_FIELDS},
        "total_tokens": 0,
        "response_turns": 0,
        "normalization_count": 0,
        "normalization_rule_counts": {},
        "successful_response_latency_seconds": 0.0,
        "provider_cost": empty_provider_cost_summary(),
    }


def _add_usage(totals: dict[str, Any], row: dict[str, Any]) -> None:
    for field in USAGE_FIELDS:
        totals[field] += int(row["usage"].get(field) or 0)
    totals["total_tokens"] = totals["input_tokens"] + totals["output_tokens"]
    totals["response_turns"] += 1
    totals["normalization_count"] += int(row.get("normalization_count") or 0)
    rule_counts = row.get("normalization_rule_counts")
    rule_counts = rule_counts if isinstance(rule_counts, dict) else {}
    for rule, count in rule_counts.items():
        totals["normalization_rule_counts"][str(rule)] = (
            totals["normalization_rule_counts"].get(str(rule), 0) + int(count)
        )
    totals["normalization_rule_counts"] = dict(
        sorted(totals["normalization_rule_counts"].items())
    )
    totals["successful_response_latency_seconds"] += float(
        row.get("successful_response_latency_seconds") or 0.0
    )
    add_provider_cost(totals["provider_cost"], row.get("provider_cost"))


def _normalized_usage(value: Any, *, checkpoint: str) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError(f"provider-turn checkpoint has invalid usage: {checkpoint}")
    output: dict[str, int] = {}
    for field in USAGE_FIELDS:
        raw = value.get(field, 0)
        if isinstance(raw, bool):
            raise ValueError(
                f"provider-turn checkpoint has invalid {field}: {checkpoint}"
            )
        try:
            count = int(raw or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"provider-turn checkpoint has invalid {field}: {checkpoint}"
            ) from exc
        if count < 0:
            raise ValueError(
                f"provider-turn checkpoint has negative {field}: {checkpoint}"
            )
        output[field] = count
    output["total_tokens"] = output["input_tokens"] + output["output_tokens"]
    return output


def _normalized_provider_cost(value: Any, *, checkpoint: str) -> dict[str, Any]:
    try:
        return normalize_provider_cost(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"provider-turn checkpoint has invalid provider cost: {checkpoint}"
        ) from exc


def _nonnegative_int(value: Any, *, field: str, checkpoint: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"provider-turn checkpoint has invalid {field}: {checkpoint}")
    try:
        count = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"provider-turn checkpoint has invalid {field}: {checkpoint}"
        ) from exc
    if count < 0:
        raise ValueError(
            f"provider-turn checkpoint has negative {field}: {checkpoint}"
        )
    return count


def _normalized_rule_counts(value: Any, *, checkpoint: str) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError(
            "provider-turn checkpoint has invalid normalization rule counts: "
            f"{checkpoint}"
        )
    output: dict[str, int] = {}
    for raw_rule, raw_count in value.items():
        rule = str(raw_rule or "").strip()
        if not rule:
            raise ValueError(
                "provider-turn checkpoint has empty normalization rule: "
                f"{checkpoint}"
            )
        output[rule] = _nonnegative_int(
            raw_count,
            field=f"normalization_rule_counts.{rule}",
            checkpoint=checkpoint,
        )
    return dict(sorted(output.items()))


def _nonnegative_float(value: Any, *, field: str, checkpoint: str) -> float:
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"provider-turn checkpoint has invalid {field}: {checkpoint}"
        ) from exc
    if number < 0:
        raise ValueError(
            f"provider-turn checkpoint has negative {field}: {checkpoint}"
        )
    return number


def _turn_index(name: str) -> int:
    try:
        return int(name.removeprefix("provider-turn-"))
    except ValueError as exc:
        raise ValueError(f"invalid provider-turn checkpoint name: {name}") from exc


def _cycle_for_attempt(
    cycles: list[dict[str, Any]],
    attempt: int,
) -> tuple[int, int]:
    selected = (0, 0)
    for row in cycles:
        base = int(row["attempt_base"])
        if attempt > base:
            selected = (int(row["cycle"]), base)
    return selected
