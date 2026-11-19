"""Bounded native-serving qualification using the production episode runtime.

These synthetic transport cases measure protocol behavior, never scientific
report quality. No dataset or gold artifact is loaded. Production-settings mode uses the study retry policy.
The real tool-continuation case takes at most three requests; each of four
terminal-schema cases takes one fresh request, with no fabricated prior history.
An explicit opt-in adds one long-form synthetic terminal request with its own
output allowance; the five original qualification cases remain unchanged.
Conditional OpenRouter counting has one separately identified counting-only
case and one shared probe allowance across this qualification, never an action.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from jsonschema import Draft202012Validator

from benchmarks.react_report_building.paths import PROMPT_ROOT
from benchmarks.react_report_building.runtime import tool_schemas
from benchmarks.react_report_building.runtime.accounting import aggregate_usage
from benchmarks.react_report_building.runtime.context_budget import OPENROUTER_PROBE_MAX_OBSERVED_OUTPUT_TOKENS, OPENROUTER_PROBE_MAX_OUTPUT_TOKENS
from benchmarks.react_report_building.runtime.controller import run_episode
from benchmarks.react_report_building.runtime.episode import Episode, RESERVE_FINAL_TURN, SPLIT_TERMINAL_PROTOCOL, TERMINAL_TOOLS
from benchmarks.react_report_building.runtime.episode_factory import make_episode
from benchmarks.react_report_building.runtime.final_turn_policy import final_turn_policy_provenance
from benchmarks.react_report_building.runtime.providers.base import ProviderHTTPError, ProviderRequestError, ProviderResponseError, ProviderTurn
from benchmarks.react_report_building.runtime.providers.factory import create_provider
from benchmarks.react_report_building.runtime.providers.openai_responses import ProviderContextBudgetError
from benchmarks.react_report_building.runtime.tool_schemas import semantic_tool_definitions
from benchmarks.react_report_building.util import sha256_json, sha256_text

from ..config import StudyConfig, sanitized_config
from ..retry import RetryPolicy, policy_from_spec, retry_call
from . import profiles


SCHEMA_VERSION = "benchrunner.native_serving_smoke/v4"
LONG_FORM_SCHEMA_VERSION = "benchrunner.native_serving_smoke/v5"
MAX_REQUESTS_PER_MODEL = 7
LONG_FORM_MAX_OUTPUT_TOKENS = 8192
LONG_FORM_MIN_MARKDOWN_BYTES = 8192
LONG_FORM_CASE_SPEC = ("terminal_long_form_report", "report_create", 1, True, False)
OPENROUTER_CONDITIONAL_COUNT_MODE = "openrouter_probe_on_clamp"
MAX_CONDITIONAL_COUNT_PROBES_PER_MODEL = 1
MAX_AUDIT_BYTES_PER_RESPONSE = 2_000_000
SECTION_ID = "smoke_section"
TEXT = 'Quoted "£ value" with C:\\climate\\Δ'
CHANGED_TEXT = 'Updated "£ value" with C:\\climate\\Δ'
EVIDENCE_IDS = ["dt.smoke.text", "dt.smoke.number"]
CALCULATION_IDS = ["calc.smoke_sum", "calc.smoke_difference"]
CASE_SPECS = (
    ("tool_continuation", "section_create", 3, False, False),
    ("terminal_create_section", "section_create", 1, True, False),
    ("terminal_create_report", "report_create", 1, True, False),
    ("terminal_keep_section", "section_update", 1, True, False),
    ("terminal_replace_section", "section_update", 1, True, True),
)


class _RequestLimitReached(RuntimeError):
    pass


class _CountConsistencyError(RuntimeError):
    pass


def run_native_smoke(
    config: StudyConfig,
    output_dir: Path,
    *,
    provider_factory: Callable[..., Any] = create_provider,
    probe_max_output_tokens: int = 2048,
    include_long_form: bool = False,
    long_form_max_output_tokens: int = LONG_FORM_MAX_OUTPUT_TOKENS,
    production_settings: bool = False,
) -> dict[str, Any]:
    """Execute up to seven action requests and declared counting work per model.

The caller authorizes model requests by invoking this function. Merely importing
it or parsing a study performs no provider work. ``provider_factory`` allows
offline contract tests to inject the real Responses adapter with fake HTTP.
"""

    _validate_config(config)
    if production_settings:
        probe_max_output_tokens = long_form_max_output_tokens = config.generation.max_output_tokens
    retry_policy = policy_from_spec(config.retry) if production_settings else RetryPolicy(max_attempts=1)
    if isinstance(probe_max_output_tokens, bool) or not isinstance(probe_max_output_tokens, int) or probe_max_output_tokens < 256:
        raise ValueError("probe_max_output_tokens must be an integer >=256")
    if not isinstance(include_long_form, bool):
        raise ValueError("include_long_form must be a boolean")
    if isinstance(long_form_max_output_tokens, bool) or not isinstance(long_form_max_output_tokens, int) or long_form_max_output_tokens < 256:
        raise ValueError("long_form_max_output_tokens must be an integer >=256")
    effective_probe_cap = min(config.generation.max_output_tokens, probe_max_output_tokens)
    effective_long_form_cap = min(config.generation.max_output_tokens, long_form_max_output_tokens)
    request_budget = MAX_REQUESTS_PER_MODEL + int(include_long_form)
    schema_version = LONG_FORM_SCHEMA_VERSION if include_long_form else SCHEMA_VERSION
    qualification_constraints = {"schema_version": schema_version, "probe_requested_max_output_tokens": probe_max_output_tokens, "probe_effective_max_output_tokens": effective_probe_cap, "request_budget_per_model": request_budget, "conditional_count_probe_request_ceiling_per_model": MAX_CONDITIONAL_COUNT_PROBES_PER_MODEL, "conditional_count_max_observed_output_tokens": OPENROUTER_PROBE_MAX_OBSERVED_OUTPUT_TOKENS}
    if include_long_form:
        choices = {model.final_turn_tool_choice_policy for model in config.models}
        common_choice = next(iter(choices)) if len(choices) == 1 else "per_model"
        qualification_constraints["long_form"] = _long_form_constraints(long_form_max_output_tokens, effective_long_form_cap, tool_choice=common_choice)
        if common_choice == "per_model":
            qualification_constraints["long_form"]["tool_choice_by_model"] = {
                model.alias: model.final_turn_tool_choice_policy for model in config.models
            }
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    study = sanitized_config(config)
    receipt: dict[str, Any] = {
        "schema_version": schema_version,
        "status": "running",
        "stage": "A_native_serving_conformance",
        "study": study,
        "study_sha256": sha256_json(study),
        "runtime_source_sha256": _runtime_source_hash(),
        "provider_profile_implementation_sha256": sha256_text(Path(profiles.__file__).read_text(encoding="utf-8")),
        "smoke_implementation_sha256": sha256_text(Path(__file__).read_text(encoding="utf-8")),
        "probe_budget_implementation_sha256": sha256_text((Path(__file__).resolve().parents[1] / "probe_budget.py").read_text(encoding="utf-8")),
        "vllm_count_implementation_sha256": sha256_text(Path(__file__).with_name("vllm_input_tokens.py").read_text(encoding="utf-8")),
        "scientific_score": None,
        "scientific_score_status": "not_measured_synthetic_protocol_inputs",
        "request_budget_per_model": request_budget,
        "request_budget_basis": ("up to eight action requests including one optional long-form request; up to eight inference-free direct/renderer counts, or one shared conditional OpenRouter counting-only request" if include_long_form else "up to seven action requests; up to seven inference-free direct/renderer counts, or one shared conditional OpenRouter counting-only request"),
        "parallelism_required": False,
        "retry_attempts": 0,
        "request_count_basis": "generation HTTP attempts plus separately recorded context-count HTTP attempts",
        "production_max_output_tokens": config.generation.max_output_tokens,
        "probe_requested_max_output_tokens": probe_max_output_tokens,
        "probe_effective_max_output_tokens": effective_probe_cap,
        "output_token_ceiling_per_model": MAX_REQUESTS_PER_MODEL * effective_probe_cap + (effective_long_form_cap if include_long_form else 0),
        "context_probe_output_token_ceiling_per_model": max((_context_probe_request_ceiling(model.input_token_count_mode) for model in config.models), default=0),
        "counting_only_case_request_ceiling_per_model": MAX_CONDITIONAL_COUNT_PROBES_PER_MODEL if any(model.input_token_count_mode == OPENROUTER_CONDITIONAL_COUNT_MODE for model in config.models) else 0,
        "output_token_limit_basis": "explicit_stage_A_qualification_cap; stage_B_uses_production_cap; context_budget_may_reduce_further",
        "qualification_constraints_sha256": sha256_json(qualification_constraints),
        "history_policy": "fresh terminal requests; continuation replays only actual provider-returned calls and observations",
        "qualification_scope": "serving_and_native_schema_mechanics; no scientific decision or output-fidelity grading",
        "models": [],
    }
    if include_long_form:
        receipt["long_form"] = deepcopy(qualification_constraints["long_form"])
    receipt["production_settings"] = production_settings
    if production_settings:
        receipt.update(schema_version="benchrunner.native_serving_smoke/v6",
                       retry_policy=sanitized_config(config)["retry"],
                       context_limit_test="not_run; advertised_window_accepted",
                       request_budget_per_model=request_budget * retry_policy.max_attempts,
                       request_budget_basis="generation HTTP attempts; counting attempts separately bounded by the production ledger and per-request retry policy",
                       counting_only_case_request_ceiling_per_model=retry_policy.max_attempts,
                       output_token_ceiling_per_model=receipt["output_token_ceiling_per_model"] * retry_policy.max_attempts,
                       context_probe_output_token_ceiling_per_model=min(max((m.context_probe_max_requests or 0 for m in config.models), default=0), (request_budget * retry_policy.max_attempts + 1) * retry_policy.max_attempts) * OPENROUTER_PROBE_MAX_OUTPUT_TOKENS,
                       retry_implementation_sha256=sha256_text((Path(__file__).parents[1] / "retry.py").read_text()),
                       output_token_limit_basis="production_config; normal_runtime_context_accounting")
    if production_settings and include_long_form:
        receipt["long_form"].pop("retry_attempts", None)
        receipt["long_form"]["retry_policy"] = sanitized_config(config)["retry"]
    for index, model in enumerate(config.models):
        model_result: dict[str, Any] = {
            "model": study["models"][index],
            "treatment_sha256": sha256_json({"model": study["models"][index], "generation": study["generation"]}),
            "final_turn_policy": final_turn_policy_provenance(model.final_turn_tool_choice_policy),
            "reasoning_requested": model.reasoning_effort,
            "reasoning_setting_status": "explicit" if model.reasoning_effort is not None else "provider_default_explicitly_unset",
            "cases": [],
            "counting_cases": [],
        }
        receipt["models"].append(model_result)
        try:
            context_probe_budget = _qualification_probe_budget(model, model_result["treatment_sha256"], output_dir,
                                                               production_settings=production_settings)
            model_result["context_probe_limits"] = {
                "production_max_requests": model.context_probe_max_requests,
                "production_max_cost_usd": model.context_probe_max_cost_usd,
                "qualification_max_requests": context_probe_budget.snapshot()["max_requests"] if context_probe_budget is not None else None,
                "qualification_max_cost_usd": model.context_probe_max_cost_usd if context_probe_budget is not None else None,
                "scope": "native_smoke_output_directory_per_model",
            }
            provider_kwargs = dict(
                model=model.model, profile_id=model.provider,
                action_protocol=config.generation.action_protocol,
                action_output_contract=model.action_output_contract,
                timeout_seconds=config.generation.timeout_seconds,
                max_output_tokens=effective_probe_cap,
                reasoning_effort=model.reasoning_effort,
                generation_seed=model.generation_seed,
                diagnostic_content_scope="synthetic",
                openrouter_policy=model.openrouter,
                final_turn_tool_choice_policy=model.final_turn_tool_choice_policy,
                native_tool_policy=model.native_tool_policy,
                context_window_tokens=model.context_window_tokens,
                context_safety_margin_tokens=model.context_safety_margin_tokens,
                input_token_count_mode=model.input_token_count_mode,
                context_probe_retry_policy=retry_policy,
                **({"context_probe_budget": context_probe_budget,
                    "context_probe_max_requests": model.context_probe_max_requests,
                    "context_probe_max_cost_usd": model.context_probe_max_cost_usd} if context_probe_budget is not None else {}),
            )
            provider = provider_factory("openai_responses", **provider_kwargs)
            if hasattr(provider, "api_key") and not provider.api_key:
                raise ValueError("provider credentials are unavailable")
        except Exception as exc:
            model_result.update(status="configuration_failed", failure=_failure(exc), request_count=0)
            _write_receipt(output_dir, receipt)
            continue
        endpoint = str(getattr(provider, "endpoint", ""))
        parsed = urlsplit(endpoint)
        model_result["resolved_endpoint"] = urlunsplit((parsed.scheme, parsed.netloc.rsplit("@", 1)[-1], parsed.path, "", ""))
        model_result["resolved_endpoint_sha256"] = sha256_text(endpoint)
        model_result["routing"] = deepcopy(getattr(provider, "provider_routing_provenance", None))
        usage_turns: list[dict[str, Any]] = []
        model_result["request_count"] = 0
        case_specs = (*CASE_SPECS, LONG_FORM_CASE_SPEC) if include_long_form else CASE_SPECS
        for case_index, spec in enumerate(case_specs):
            is_long_form = spec == LONG_FORM_CASE_SPEC
            episode, expected_tool, expected_markdown = (_long_form_episode(config.generation.max_turns) if is_long_form else _episode(spec, config.generation.max_turns))
            initial_history_count = len(episode.turns)
            wrapper = _BoundedProvider(provider, limit=spec[2], retry_policy=retry_policy)
            case_provider = provider
            failure = None
            trace = None
            try:
                if is_long_form:
                    case_provider = provider_factory("openai_responses", **{
                        **provider_kwargs, "max_output_tokens": effective_long_form_cap,
                    })
                    wrapper.provider = case_provider
                trace = run_episode(episode, wrapper)
            except Exception as exc:
                failure = _failure(exc)
            actual_turns = episode.turns[initial_history_count:]
            normalized_ok = _normalized_conformance(wrapper.responses, wrapper.schemas, actual_turns)
            raw_checks = [_raw_conformance(turn.raw_response, schemas) for turn, schemas in zip(wrapper.responses, wrapper.schemas)]
            terminal_schema_ok = bool(
                trace and trace.get("terminal")
                and trace["terminal"].get("tool") == expected_tool
            )
            continuation_ok = _continuation_conformance(actual_turns) if not spec[3] else None
            parallel_ok = bool(continuation_ok and len(actual_turns[0].get("calls", [])) == 2) if not spec[3] else None
            normalized_ok = bool(normalized_ok and trace and trace.get("status") == "completed" and failure is None)
            raw_ok = bool(normalized_ok and raw_checks and all(item["valid"] for item in raw_checks))
            integration_blocked = bool(failure and failure.get("classification") == "integration_probe_blocked")
            case_result = {
                "case_id": spec[0], "status": "inconclusive" if integration_blocked else "passed" if normalized_ok and raw_ok and terminal_schema_ok and continuation_ok is not False else "failed",
                "provider_invocation_count": wrapper.requests,
                "generation_request_count": wrapper.generation_requests,
                "context_count_request_count": wrapper.preflight_requests,
                "request_count": wrapper.generation_requests + wrapper.preflight_requests,
                "replayed_provider_history_turns_at_start": initial_history_count,
                "history_policy": "fresh_request" if spec[3] else "provider_authentic_continuation",
                "prompt_sha256": sha256_json(episode.messages),
                "offered_production_schemas": [{"sha256": sha256_json(schemas), "definitions": schemas} for schemas in wrapper.schemas],
                "protocol": config.generation.action_protocol,
                "terminal_protocol_version": config.generation.terminal_protocol_version,
                "turn_policy": config.generation.turn_policy,
                "final_turn_policy": model_result["final_turn_policy"],
                "native_conformance_raw": raw_ok,
                "native_conformance_normalized": normalized_ok,
                "raw_response_checks": raw_checks,
                "served_model_ids": sorted({str(turn.raw_response["model"]) for turn in wrapper.responses if isinstance(turn.raw_response, dict) and turn.raw_response.get("model")}),
                "normalization_count": sum(len(turn.normalizations) for turn in wrapper.responses),
                "normalizations": [event for turn in wrapper.responses for event in turn.normalizations],
                "terminal_accepted": bool(trace and trace.get("terminal")),
                "terminal_tool": trace["terminal"].get("tool") if trace and trace.get("terminal") else None,
                "terminal_schema_valid": terminal_schema_ok,
                "output_fidelity": "not_graded_stage_A",
                "input_count_consistency": wrapper.count_consistency,
                "parallel_arrays_and_continuation": parallel_ok,
                "continuation_valid": continuation_ok,
                "parallelism_required": False,
                "scientific_score": None,
                "failure": failure,
                "request_contexts": wrapper.request_contexts,
                "retry_events": wrapper.retry_events,
                "retry_wait_seconds": sum(event["delay_seconds"] for event in wrapper.retry_events),
                "audit_artifacts": [],
            }
            if is_long_form:
                long_form_checks = _long_form_conformance(trace)
                case_result["long_form"] = {
                    **_long_form_constraints(long_form_max_output_tokens, effective_long_form_cap,
                                             tool_choice=model.final_turn_tool_choice_policy),
                    "checks": long_form_checks,
                    "scope": "synthetic_payload_volume_and_escaping; no scientific_or_prose_quality_grading",
                }
                if not long_form_checks["valid"] and case_result["status"] == "passed":
                    case_result["status"] = "failed"
            for turn_index, turn in enumerate(wrapper.responses):
                artifact = _write_audit(output_dir, f"model-{index:02d}/case-{case_index:02d}-response-{turn_index:02d}.json", turn.raw_response, str(getattr(case_provider, "api_key", "") or ""))
                case_result["audit_artifacts"].append(artifact)
            case_usage = [*actual_turns, *wrapper.failed_usage_turns, *wrapper.preflight_usage_turns]
            usage_turns.extend(case_usage)
            case_result["accounting"] = aggregate_usage(case_usage)
            model_result["cases"].append(case_result)
            model_result["request_count"] += case_result["request_count"]
            _write_receipt(output_dir, receipt)
        if model.input_token_count_mode == OPENROUTER_CONDITIONAL_COUNT_MODE:
            count_case = _counting_transport_case(provider, model, config.generation.max_turns, effective_probe_cap, config.generation.max_output_tokens,
                                                  short_request=production_settings)
            model_result["counting_cases"].append(count_case)
            model_result["request_count"] += count_case["request_count"]
            usage_turns.extend(_preflight_usage_turns(count_case["request_context"]))
        model_result["accounting"] = aggregate_usage(usage_turns)
        model_result["generation_request_count"] = sum(case["generation_request_count"] for case in model_result["cases"])
        model_result["context_count_request_count"] = sum(case["context_count_request_count"] for case in [*model_result["cases"], *model_result["counting_cases"]])
        if context_probe_budget is not None:
            model_result["context_probe_budget"] = context_probe_budget.snapshot(include_reservations=False)
        model_result["status"] = "passed" if all(item["status"] == "passed" for item in [*model_result["cases"], *model_result["counting_cases"]]) else "failed"
        model_result["capabilities"] = {
            "production_tool_arrays_and_replay": model_result["cases"][0]["status"] == "passed",
            "production_parallel_arrays_and_replay": bool(model_result["cases"][0]["parallel_arrays_and_continuation"] and model_result["cases"][0]["status"] == "passed"),
            "create_section_schema": model_result["cases"][1]["status"] == "passed",
            "create_report_schema": model_result["cases"][2]["status"] == "passed",
            "keep_section_schema": model_result["cases"][3]["status"] == "passed",
            "replace_section_schema": model_result["cases"][4]["status"] == "passed",
            "raw_native_conformance": all(item["native_conformance_raw"] for item in model_result["cases"]),
            "conditional_count_transport": model_result["counting_cases"][0]["status"] if model_result["counting_cases"] else "not_applicable",
            "full_seven_model_turn_sequence": "not_measured",
            "report_scale_reliability": "not_measured_stage_B_required",
            "reasoning_effort_support": "requires_endpoint_documentation_separate_from_token_telemetry",
            "server_runtime_revision": "external_model_owner_receipt_required",
        }
        if include_long_form:
            model_result["capabilities"]["synthetic_long_form_terminal_payload"] = model_result["cases"][-1]["status"]
    receipt["status"] = "passed" if all(model["status"] == "passed" for model in receipt["models"]) else "failed"
    receipt["request_count"] = sum(model["request_count"] for model in receipt["models"])
    receipt["retry_attempts"] = sum(sum(event["will_retry"] for event in case.get("retry_events", []))
                                      for model in receipt["models"] for case in model["cases"])
    _write_receipt(output_dir, receipt)
    return receipt


def _context_probe_request_ceiling(mode: str | None) -> int:
    if mode == "responses_probe":
        return MAX_REQUESTS_PER_MODEL  # Historical receipts only; runtime rejects this retired mode.
    if mode == OPENROUTER_CONDITIONAL_COUNT_MODE:
        return MAX_CONDITIONAL_COUNT_PROBES_PER_MODEL * OPENROUTER_PROBE_MAX_OBSERVED_OUTPUT_TOKENS
    return 0


def _qualification_probe_budget(model: Any, treatment_sha256: str, output_dir: Path, *, production_settings=False) -> Any:
    if model.input_token_count_mode != OPENROUTER_CONDITIONAL_COUNT_MODE:
        return None
    from benchmarks.benchrunner.probe_budget import ProbeBudgetLedger

    return ProbeBudgetLedger(
        output_dir, model_alias=model.alias, treatment_sha256=treatment_sha256,
        max_requests=model.context_probe_max_requests if production_settings else MAX_CONDITIONAL_COUNT_PROBES_PER_MODEL,
        max_cost_usd=model.context_probe_max_cost_usd,
    )


def _counting_transport_case(provider: Any, model: Any, max_turns: int, gate_cap: int, production_cap: int, *, short_request=False) -> dict[str, Any]:
    """Exercise conditional counting with the production request builder only.

    Deterministic English padding crosses the configured byte-estimate clamp
    boundary without changing the endpoint's declared context window. This
    verifies counting transport, not real-data or report-scale reliability.
    ``prepare_context`` discards any probe output and never performs the main
    generation request, so no tool or terminal can execute in this case.
    """

    episode, _, _ = _episode(CASE_SPECS[0], max_turns)
    threshold = model.context_window_tokens - model.context_safety_margin_tokens - gate_cap
    padding_characters = 0 if short_request else max(1, threshold + 1)
    padding = ("synthetic " * ((padding_characters + 9) // 10))[:padding_characters]
    episode.messages[-1]["content"] += (
        "\n\nSynthetic counting-only padding follows. This case measures token-count transport; "
        "its generated output is discarded and no semantic action will execute.\n" + padding
    )
    context: dict[str, Any] = {}
    failure = None
    try:
        counter = provider.probe_count_transport if short_request else provider.prepare_context
        context = counter(episode.messages, episode=episode)
    except Exception as exc:
        failure = _failure(exc)
        context = deepcopy(getattr(exc, "request_context", None) or {})
    budget = context.get("context_budget", {})
    preflight = budget.get("preflight", {})
    request_count = int(preflight.get("request_count", 0))
    passed = bool(
        failure is None
        and budget.get("count_kind") == "exact"
        and budget.get("probe_triggered") is True
        and 1 <= request_count <= (provider.context_probe_retry_policy.max_attempts if short_request else 1)
        and preflight.get("max_output_tokens") == OPENROUTER_PROBE_MAX_OUTPUT_TOKENS
        and preflight.get("actions_executed") == 0
        and not episode.turns
    )
    if failure is None and not passed:
        failure = {"code": "conditional_count_transport_not_verified", "retryable": False}
    return {
        "case_id": "conditional_context_count_transport",
        "status": "passed" if passed else "failed",
        "purpose": "verify conditional production counting transport; report-scale reliability is not measured",
        "generation_request_count": 0,
        "context_count_request_count": request_count,
        "request_count": request_count,
        "actions_executed": 0,
        "terminal_accepted": False,
        "scientific_score": None,
        "synthetic_padding_characters": padding_characters,
        "padding_policy": "none; short production transport request" if short_request else "repeated ASCII synthetic-space to one byte beyond window minus margin minus gate cap; production schemas add their actual wire bytes",
        "configured_context_window_tokens": model.context_window_tokens,
        "production_max_output_tokens": production_cap,
        "probe_effective_max_output_tokens": gate_cap,
        "prompt_sha256": sha256_json(episode.messages),
        "offered_production_schemas": {"sha256": sha256_json(semantic_tool_definitions(episode)), "definitions": semantic_tool_definitions(episode)},
        "request_context": context,
        "accounting": aggregate_usage(_preflight_usage_turns(context)),
        "failure": failure,
    }


def _preflight_usage_turns(context: dict[str, Any]) -> list[dict[str, Any]]:
    preflight = context.get("context_budget", {}).get("preflight", {})
    if not preflight.get("generation_requested") or not preflight.get("request_count"):
        return []
    return [{"usage": attempt.get("usage", {}), "provider_cost": attempt.get("provider_cost"), "latency_seconds": attempt.get("latency_seconds")}
            for attempt in preflight.get("attempts", [preflight]) if attempt.get("request_count")]


def _validate_config(config: StudyConfig) -> None:
    if (config.generation.action_protocol != "native_tools"
        or config.generation.terminal_protocol_version != SPLIT_TERMINAL_PROTOCOL
        or config.generation.turn_policy != RESERVE_FINAL_TURN
        or config.generation.max_turns != 8):
        raise ValueError("native-smoke requires the corrected native-tools 7+1 study contract")
    if not config.models or any(model.provider == "fixture" or model.action_output_contract is not None for model in config.models):
        raise ValueError("native-smoke requires production Responses profiles with native tools")
    for model in config.models:
        if model.final_turn_tool_choice_policy not in {"required", "auto"}:
            raise ValueError("native-smoke requires required or explicit auto terminal tool choice")


def _markdown(text: str, *, report: bool = False) -> str:
    return ("# Serving smoke\n\n" if report else "") + f"## Smoke section\n\n[{text}](dt.smoke.text)."


class _TerminalSchemaEpisode(Episode):
    """Fresh capability request under terminal policy, without invented turns."""

    @property
    def turn_phase(self) -> str:
        return "finalization"

    @property
    def active_allowed_tools(self) -> frozenset[str]:
        return frozenset({self._schema_tool})

    def turn_instruction(self) -> str:
        return ("SYNTHETIC TERMINAL-SCHEMA CHECK. This is one fresh request, "
                "with no preceding model turns or task decision to infer. "
                f"Use the offered {self._schema_tool} tool with schema-valid arguments. "
                "Markdown wording and punctuation are not graded.")


class _LongFormTerminalEpisode(_TerminalSchemaEpisode):
    def turn_instruction(self) -> str:
        return (
            "SYNTHETIC LONG-FORM TERMINAL CHECK. This is one fresh request with no "
            "preceding model turns. Call the only offered tool, create_report, once. "
            "Put the full synthetic report from the user message in its markdown "
            "argument, including headings, tables, newlines, quotes, backslashes and "
            "dollar signs. Do not shorten it to a small example. Wording is not scored."
        )


def _long_form_markdown() -> str:
    """Fictional transport fixture; no benchmark dataset or scientific claims."""
    sections = []
    for index in range(1, 17):
        sections.append(
            f"## Synthetic station {index:02d}\n\n"
            'The fictional reviewer described this station as "ready for review", '
            'with a nominal allocation of $5.5 billion. This invented amount is an '
            'escaping test, not a budget estimate or a statement about a real project. '
            'The station notes deliberately repeat ordinary prose so that the tool '
            'argument is large enough to exercise long-form JSON generation.\n\n'
            f"| Field | Synthetic value |\n| --- | --- |\n"
            f"| Archive | `C:\\climate\\station_{index:02d}\\report.md` |\n"
            '| Review label | "draft" |\n'
            '| Display amount | $5.50 |\n\n'
            'The next reviewer should retain all section headings and table rows. '
            'No data retrieval, arithmetic or external knowledge is necessary: all '
            'the requested text is already supplied. The words may vary, but the '
            'complete multi-section body and literal punctuation must survive the '
            'native tool-call encoding and decoding round trip.\n'
        )
    return "# Synthetic long-form serving report\n\n" + "\n".join(sections)


def _long_form_constraints(requested_cap: int, effective_cap: int, *, tool_choice: str = "required") -> dict[str, Any]:
    if tool_choice not in {"required", "auto", "per_model"}:
        raise ValueError("unsupported long-form tool-choice policy")
    markdown = _long_form_markdown()
    return {
        "enabled": True,
        "case_id": LONG_FORM_CASE_SPEC[0],
        "generation_request_ceiling_per_model": 1,
        "requested_max_output_tokens": requested_cap,
        "effective_max_output_tokens": effective_cap,
        "minimum_markdown_utf8_bytes": LONG_FORM_MIN_MARKDOWN_BYTES,
        "required_characters": ["\n", '"', "\\", "$"],
        "synthetic_source_utf8_bytes": len(markdown.encode("utf-8")),
        "synthetic_source_sha256": sha256_text(markdown),
        "required_tool": "create_report",
        "tool_choice": tool_choice,
        "parallel_tool_calls": False,
        "history_policy": "fresh_request_without_fabricated_turns",
        "retry_attempts": 0,
        "output_fidelity": "volume_and_character_classes_only; no exact_text_or_scientific_grading",
    }


def _long_form_episode(max_turns: int):
    episode, expected_tool, _ = _episode(LONG_FORM_CASE_SPEC, max_turns)
    episode = _LongFormTerminalEpisode(**{key: value for key, value in vars(episode).items() if key != "_schema_tool"})
    episode._schema_tool = expected_tool
    markdown = _long_form_markdown()
    episode.messages[-1]["content"] = (
        "This is a synthetic long-form serving-mechanics check. Submit the complete "
        "fictional report below through one native create_report call. The markdown "
        f"must be at least {LONG_FORM_MIN_MARKDOWN_BYTES} UTF-8 bytes long and include "
        "newlines, double quotes, literal backslashes and dollar signs. Use the "
        "supplied report as the body; do not summarize or shorten it. Exact wording "
        "is not scored. Preserve valid JSON encoding of the markdown argument. "
        "There are no other offered tools, no prior actions and no retry.\n\n"
        "BEGIN SYNTHETIC REPORT\n" + markdown + "\nEND SYNTHETIC REPORT"
    )
    return episode, expected_tool, markdown


def _long_form_conformance(trace: dict[str, Any] | None) -> dict[str, Any]:
    terminal = (trace or {}).get("terminal") or {}
    markdown = terminal.get("markdown")
    markdown = markdown if isinstance(markdown, str) else ""
    characters = {"newlines": "\n", "double_quotes": '"', "backslashes": "\\", "dollar_signs": "$"}
    present = {name: character in markdown for name, character in characters.items()}
    byte_count = len(markdown.encode("utf-8"))
    errors = []
    if byte_count < LONG_FORM_MIN_MARKDOWN_BYTES:
        errors.append("long_form_payload_below_minimum_bytes")
    errors.extend(f"long_form_payload_missing_{name}" for name, found in present.items() if not found)
    return {"valid": not errors, "errors": errors, "markdown_utf8_bytes": byte_count,
            "character_classes_present": present, "markdown_sha256": sha256_text(markdown) if markdown else None}


def _episode(spec: tuple, max_turns: int):
    name, kind, _limit, terminal_only, changed = spec
    text = CHANGED_TEXT if changed else TEXT
    expected_markdown = _markdown(text, report=kind == "report_create")
    expected_tool = "create_report" if kind == "report_create" else "replace_section" if changed else "keep_section" if kind == "section_update" else "create_section"
    nodes = {node_id: {"id": node_id, "kind": "scalar", "status": "available", "value": value, "unit": None}
             for node_id, value in ((EVIDENCE_IDS[0], text), (EVIDENCE_IDS[1], 4), ("dt.smoke.other", 3))}
    registry = {
        "calc.smoke_sum": {"id": "calc.smoke_sum", "operation_id": "sum", "input_ids": {"left": EVIDENCE_IDS[1], "right": "dt.smoke.other"}, "parameters": {}, "unit": None},
        "calc.smoke_difference": {"id": "calc.smoke_difference", "operation_id": "subtract", "input_ids": {"minuend": EVIDENCE_IDS[1], "subtrahend": "dt.smoke.other"}, "parameters": {}, "unit": None},
    }
    instructions = (
        "This is a synthetic serving-mechanics check, not a report-quality task. "
        f"Use section_id {SECTION_ID} wherever that argument is required. "
    )
    if not terminal_only:
        instructions += (
            f"Retrieve evidence with one get_data call containing ids {json.dumps(EVIDENCE_IDS)}, "
            f"and request one calculate call containing ids {json.dumps(CALCULATION_IDS)}. "
            "You may make these two calls together or in separate responses, in either order. "
            "Wait for both actual observations before calling create_section with any short nonempty Markdown. "
            "You have at most three responses, including that terminal call. "
        )
    else:
        instructions += f"Make one native {expected_tool} call now. "
        if expected_tool != "keep_section":
            instructions += "Supply any short nonempty Markdown string. Wording and punctuation are not scored. "
    episode = make_episode(
        episode_id=f"native-smoke.{name}", episode_kind=kind,
        twin={"project_id": "NATIVE_SMOKE", "nodes": nodes, "collections": {}}, reference={"nodes": {}},
        user_prompt=instructions, max_turns=max_turns,
        turn_policy=RESERVE_FINAL_TURN, terminal_protocol_version=SPLIT_TERMINAL_PROTOCOL,
        section_id=SECTION_ID if kind != "report_create" else None,
        original_markdown=_markdown(TEXT) if kind == "section_update" else None,
        calculation_registry=registry,
    )
    if terminal_only:
        episode = _TerminalSchemaEpisode(**vars(episode))
        episode._schema_tool = expected_tool
    return episode, expected_tool, expected_markdown


class _BoundedProvider:
    def __init__(self, provider: Any, *, limit: int, retry_policy=None) -> None:
        self.provider, self.limit = provider, limit
        self.requests = 0
        self.responses: list[ProviderTurn] = []
        self.schemas: list[list[dict[str, Any]]] = []
        self.usage_turns: list[dict[str, Any]] = []
        self.request_contexts: list[dict[str, Any]] = []
        self.preflight_usage_turns: list[dict[str, Any]] = []
        self.generation_requests = 0
        self.preflight_requests = 0
        self.count_consistency: list[dict[str, Any]] = []
        self.retry_policy = retry_policy or RetryPolicy(max_attempts=1)
        self.retry_events = []
        self.failed_usage_turns = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.provider, name)

    def complete(self, messages: list, *, episode: Any) -> ProviderTurn:
        if self.requests >= self.limit:
            raise _RequestLimitReached()
        self.schemas.append(semantic_tool_definitions(episode))
        self.requests += 1
        def failed(exc, attempt, decision):
            self._record_context(getattr(exc, "request_context", None) or {})
            if isinstance(exc, ProviderRequestError) and not isinstance(exc, ProviderContextBudgetError):
                self.generation_requests += 1
                self.failed_usage_turns.append({"usage": getattr(exc, "usage", None) or {}, "provider_cost": getattr(exc, "provider_cost", None), "latency_seconds": getattr(exc, "latency_seconds", None)})
            self.retry_events.append({"attempt": attempt, "will_retry": decision.retry,
                                      "delay_seconds": decision.delay_seconds, "reason": decision.reason,
                                      "failure": _failure(exc)})
        turn = retry_call(lambda: self.provider.complete(messages, episode=episode), self.retry_policy,
                          on_failure=failed)
        self.responses.append(turn)
        self.generation_requests += 1
        self._record_context(turn.request_context)
        self.usage_turns.append({"usage": turn.usage, "provider_cost": turn.provider_cost, "latency_seconds": turn.latency_seconds})
        budget = turn.request_context.get("context_budget", {})
        if budget.get("input_token_count_mode") == "vllm_responses":
            counted, observed = budget.get("input_tokens"), turn.usage.get("input_tokens")
            matched = type(counted) is int and type(observed) is int and counted == observed
            self.count_consistency.append({"counted_input_tokens": counted, "observed_input_tokens": observed, "matched": matched})
            if not matched:
                # Preserve the response and its costs, but do not execute tools
                # from an input whose count renderer has not been qualified.
                raise _CountConsistencyError()
        return turn

    def _record_context(self, context: dict[str, Any]) -> None:
        self.request_contexts.append(deepcopy(context))
        preflight = context.get("context_budget", {}).get("preflight", {})
        self.preflight_requests += int(preflight.get("request_count", 0))
        self.preflight_usage_turns.extend(_preflight_usage_turns(context))


def _raw_conformance(raw: Any, definitions: list[dict[str, Any]]) -> dict[str, Any]:
    schemas = {item["name"]: item["input_schema"] for item in definitions}
    errors: list[str] = []
    calls = []
    call_ids: set[str] = set()
    output = raw.get("output") if isinstance(raw, dict) else None
    if not isinstance(output, list):
        return {"valid": False, "errors": ["invalid_output_array"], "native_call_count": 0}
    for item in output:
        if not isinstance(item, dict):
            errors.append("nonobject_output_item")
            continue
        if item.get("type") == "reasoning":
            continue
        if item.get("type") == "message":
            # Plain assistant text is never accepted as a semantic call. A
            # model may accompany a genuine native call with ordinary prose.
            continue
        if item.get("type") != "function_call":
            errors.append("unexpected_action_carrier")
            continue
        name = item.get("name")
        calls.append(name)
        call_id = item.get("call_id")
        if not isinstance(call_id, str) or not call_id.strip():
            errors.append("missing_or_invalid_call_id")
        elif call_id in call_ids:
            errors.append("duplicate_call_id")
        else:
            call_ids.add(call_id)
        if item.get("status") is not None and item.get("status") != "completed":
            errors.append("incomplete_native_call")
        try:
            arguments = json.loads(item["arguments"])
        except (KeyError, TypeError, ValueError):
            errors.append("invalid_native_arguments_json")
            continue
        if not isinstance(name, str) or name not in schemas or not Draft202012Validator(schemas[name]).is_valid(arguments):
            errors.append("native_tool_schema_mismatch")
    if not calls:
        errors.append("no_native_function_calls")
    if any(isinstance(name, str) and name in TERMINAL_TOOLS for name in calls) and len(calls) != 1:
        errors.append("terminal_not_isolated")
    return {"valid": not errors, "errors": sorted(set(errors)), "native_call_count": len(calls)}


def _normalized_conformance(responses: list[ProviderTurn], schemas: list[list[dict]], turns: list[dict]) -> bool:
    if not responses or len(responses) != len(turns):
        return False
    for response, definitions, turn in zip(responses, schemas, turns):
        schema_by_name = {item["name"]: item["input_schema"] for item in definitions}
        if response.protocol_error or not response.tool_calls:
            return False
        call_ids = [call.call_id for call in response.tool_calls]
        if any(not isinstance(call_id, str) or not call_id.strip() for call_id in call_ids) or len(set(call_ids)) != len(call_ids):
            return False
        for call in response.tool_calls:
            if call.error or call.tool not in schema_by_name or not Draft202012Validator(schema_by_name[call.tool]).is_valid(call.arguments):
                return False
        if turn.get("status") == "protocol_error":
            return False
        for observation in turn.get("observations", []):
            if observation.get("status") not in {"completed", "available", "accepted"}:
                return False
            if any(item.get("status") != "available" for item in observation.get("results", [])):
                return False
    return True


def _continuation_conformance(turns: list[dict[str, Any]]) -> bool:
    """Require both real tool observations before finalization, in either order."""
    if len(turns) not in {2, 3}:
        return False
    calls = [call for turn in turns[:-1] for call in turn.get("calls", [])]
    expected = {"get_data": EVIDENCE_IDS, "calculate": CALCULATION_IDS}
    def expected_ids(call: dict[str, Any]) -> bool:
        arguments = call.get("arguments")
        ids = arguments.get("ids") if isinstance(arguments, dict) else None
        return bool(isinstance(ids, list) and all(isinstance(item, str) for item in ids)
                    and sorted(ids) == sorted(expected.get(call.get("tool"), [])))
    return bool(
        len(calls) == 2
        and {call.get("tool") for call in calls} == {"get_data", "calculate"}
        and all(expected_ids(call) for call in calls)
        and all(len(turn.get("observations", [])) == len(turn.get("calls", [])) for turn in turns[:-1])
        and len(turns[-1].get("calls", [])) == 1
        and turns[-1]["calls"][0].get("tool") == "create_section"
    )


def _failure(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, _CountConsistencyError):
        return {"code": "input_count_usage_mismatch", "retryable": False, "classification": "integration_probe_blocked"}
    if isinstance(exc, _RequestLimitReached):
        return {"code": "probe_request_limit", "retryable": False}
    if isinstance(exc, ProviderHTTPError):
        return {"code": "provider_http_error", "http_status": exc.status_code, "retryable": exc.retryable,
                **({"failure_evidence": deepcopy(exc.failure_evidence)} if getattr(exc, "failure_evidence", None) else {})}
    if isinstance(exc, ProviderContextBudgetError):
        return {"code": exc.code, "retryable": False, "generation_requested": False, "classification": "integration_probe_blocked"}
    if isinstance(exc, ProviderResponseError):
        code = exc.code if re.fullmatch(r"[a-zA-Z0-9_]{1,80}", exc.code) else "invalid_response"
        return {"code": code, "retryable": exc.retryable,
                **({"failure_evidence": deepcopy(exc.failure_evidence)} if getattr(exc, "failure_evidence", None) else {})}
    if isinstance(exc, ProviderRequestError):
        return {"code": "provider_request_error", "retryable": exc.retryable}
    return {"code": "configuration_or_runtime_error", "retryable": False}


def _runtime_source_hash() -> str:
    root = Path(tool_schemas.__file__).resolve().parent
    sources = {str(path.relative_to(root)): sha256_text(path.read_text(encoding="utf-8")) for path in sorted(root.rglob("*.py"))}
    sources["v2_react_system.md"] = sha256_text((PROMPT_ROOT / "v2_react_system.md").read_text(encoding="utf-8"))
    return sha256_json(sources)


def _write_receipt(output_dir: Path, receipt: dict[str, Any]) -> None:
    destination = output_dir / "native-smoke.json"
    temporary = output_dir / ".native-smoke.json.tmp"
    temporary.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(destination)


def _write_audit(output_dir: Path, relative: str, raw: Any, credential: str) -> dict[str, Any]:
    encoded = json.dumps(raw, ensure_ascii=False, sort_keys=True)
    digest = sha256_text(encoded)
    redacted = False

    def clean(value: Any) -> Any:
        nonlocal redacted
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if re.search(r"(?:authorization|api[_-]?key|password|access[_-]?token|refresh[_-]?token)", str(key), re.I):
                    result[key], redacted = "[REDACTED]", True
                else:
                    result[key] = clean(item)
            return result
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, str) and credential and credential in value:
            redacted = True
            return value.replace(credential, "[REDACTED]")
        return value

    cleaned = json.dumps(clean(raw), indent=2, ensure_ascii=False).encode("utf-8")
    result = {"raw_sha256": digest, "raw_sha256_basis": "canonicalized_provider_response_object", "raw_bytes": len(encoded.encode("utf-8")), "redacted": redacted}
    if len(cleaned) > MAX_AUDIT_BYTES_PER_RESPONSE:
        return {**result, "path": None, "status": "omitted_size_limit"}
    destination = output_dir / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(cleaned)
    return {**result, "path": relative, "status": "saved", "artifact_sha256": sha256_text(cleaned.decode("utf-8"))}
