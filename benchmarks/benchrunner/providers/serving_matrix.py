"""Shared Stage A: native mechanics and measured context, for both tool policies.

The four cells are synthetic report/section x required/auto. They do not load
benchmark data or grade prose. The selected study policy is never changed as a
fallback. A native-smoke receipt alone cannot satisfy this additional gate.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any, Callable
from urllib.request import urlopen

from benchmarks.react_report_building.runtime.accounting import aggregate_usage
from benchmarks.react_report_building.runtime.controller import run_episode
from benchmarks.react_report_building.runtime.providers.factory import create_provider
from benchmarks.react_report_building.runtime.tool_schemas import semantic_tool_definitions
from benchmarks.react_report_building.util import sha256_json, sha256_text
from ..artifacts import atomic_write_json
from ..config import StudyConfig, sanitized_config
from ..probe_budget import ProbeBudgetLedger
from . import native_smoke as native


SCHEMA = "benchrunner.serving_matrix/v1"
POLICIES = ("strict_required_v1", "strict_auto_v1")
SCOPES = ("report", "section")
CALIBRATION_LIMIT = 4
MAX_PADDING_BYTES = 20_000_000
EXACT_MODES = {"openai_responses", "vllm_responses", "openrouter_probe_on_clamp"}
PADDING = (
    "Synthetic station notes describe the river, road, building and woodland. "
    "The fictional archive records inspection dates, maintenance activities and "
    "staff observations. These notes are transport padding, not facts to report.\n"
)


def _integer(value: Any, minimum: int = 1) -> bool:
    return type(value) is int and value >= minimum


def treatment_hash(config: StudyConfig) -> str:
    value = sanitized_config(config)
    return sha256_json({"models": value["models"], "generation": value["generation"]})


def source_hash() -> str:
    return sha256_json({
        "matrix": sha256_text(Path(__file__).read_text()),
        "native": sha256_text(Path(native.__file__).read_text()),
        "runtime": native._runtime_source_hash(),
        "profiles": sha256_text(Path(native.profiles.__file__).read_text()),
        "probe_budget": sha256_text((Path(__file__).resolve().parents[1] / "probe_budget.py").read_text()),
    })


def requirements(config: StudyConfig, output_cap: int = 2048,
                 required_window: int | None = None, input_ceiling: int | None = None) -> dict:
    native._validate_config(config)
    if len(config.models) != 1:
        raise ValueError("serving-matrix requires one exact model treatment per config")
    model = config.models[0]
    if model.native_tool_policy not in POLICIES:
        raise ValueError("serving-matrix requires an explicit strict required/auto policy")
    window, margin = model.context_window_tokens, model.context_safety_margin_tokens
    if not _integer(window, 8192) or not _integer(margin, 256):
        raise ValueError("a configured context window and safety margin are required")
    if required_window is not None and (not _integer(required_window, 8192) or required_window < window):
        raise ValueError("required context window cannot weaken the study's configured window")
    if not _integer(output_cap, 256) or output_cap > 8192:
        raise ValueError("context probe output cap must be between 256 and 8192")
    cap = min(output_cap, config.generation.max_output_tokens)
    if cap < 256:
        raise ValueError("production output allowance must be at least 256 tokens")
    ceiling = window - margin - cap
    if input_ceiling is not None:
        if not _integer(input_ceiling, 1024):
            raise ValueError("the separately declared input limit must be a positive token count")
        ceiling = min(ceiling, input_ceiling)
    tolerance = min(4096, max(128, ceiling // 100))
    if ceiling - tolerance < 1024:
        raise ValueError("context probe leaves insufficient input headroom")
    return {
        "required_context_window_tokens": required_window or window,
        "configured_context_window_tokens": window,
        "safety_margin_tokens": margin,
        "generation_output_cap_tokens": cap,
        "minimum_measured_input_tokens": ceiling - tolerance,
        "maximum_measured_input_tokens": ceiling,
        "calibration_tolerance_tokens": tolerance,
        "context_count_attempts_per_cell": CALIBRATION_LIMIT + 1,
        "generation_attempts_per_cell": 1,
        "padding_byte_ceiling": MAX_PADDING_BYTES,
        "scopes": list(SCOPES), "policies": list(POLICIES),
        "scientific_quality": "not_measured",
        "qualification_limit": "near-window input acceptance and short native output; not full-window output or long-context reasoning quality",
    }


def fetch_endpoint(model_id: str, tag: str) -> dict:
    """Fresh public endpoint inventory; never a generation request or API key."""
    from urllib.parse import quote
    url = "https://openrouter.ai/api/v1/models/" + quote(model_id, safe="/") + "/endpoints"
    with urlopen(url, timeout=30) as response:
        body = response.read(10_000_001)
    if len(body) > 10_000_000:
        raise ValueError("endpoint inventory exceeded the size limit")
    data = json.loads(body)["data"]
    if data.get("id") != model_id:
        raise ValueError("endpoint inventory model differs from study")
    matched = [e for e in data["endpoints"] if e.get("tag") == tag]
    if len(matched) != 1:
        raise ValueError("exact provider tag is absent or ambiguous")
    return {"url": url, "observed_at": datetime.now(timezone.utc).isoformat(),
            "raw_sha256": hashlib.sha256(body).hexdigest(), "endpoint": matched[0]}


def inspect_endpoint(config: StudyConfig, limits: dict, req: dict,
                     fetcher: Callable = fetch_endpoint) -> dict:
    model = config.models[0]
    failures = []
    if limits.get("model") != model.model or limits.get("provider") != model.provider:
        raise ValueError("endpoint specification does not identify this study model/provider")
    if model.provider == "openrouter":
        route = model.openrouter
        if route is None or len(route.provider.only) != 1 or route.provider.allow_fallbacks or route.context_compression:
            raise ValueError("context qualification requires one pinned route without fallback/compression")
        if not route.provider.require_parameters or limits.get("tag") != route.provider.only[0]:
            raise ValueError("endpoint specification differs from the strict pinned route")
        evidence = fetcher(model.model, route.provider.only[0])
        endpoint = evidence["endpoint"]
        if endpoint.get("tag") != route.provider.only[0] or endpoint.get("model_id") != model.model:
            failures.append("endpoint_identity_mismatch")
        if endpoint.get("status") != 0:
            failures.append("endpoint_not_available")
        supported = set(endpoint.get("supported_parameters") or [])
        expected = {"tools", "tool_choice", "max_tokens"}
        if model.reasoning_effort is not None:
            expected.add("reasoning")
        if model.generation_seed is not None:
            expected.add("seed")
        failures.extend("unsupported_parameter:" + key for key in sorted(expected - supported))
        prices = endpoint.get("pricing", {})
        for key, ceiling in (("prompt", route.provider.max_price.prompt),
                             ("completion", route.provider.max_price.completion)):
            if key not in prices or Decimal(str(prices[key])) * 1_000_000 > Decimal(str(ceiling)):
                failures.append("price_exceeds_bound:" + key)
    else:
        # OpenAI's models listing has no context/output metadata. Keep the
        # reviewed official limits separate from the live count+generation proof.
        if model.provider != "openai" or not limits.get("source_url", "").startswith("https://developers.openai.com/"):
            raise ValueError("direct endpoint requires reviewed official OpenAI limit evidence")
        endpoint = {"context_length": limits.get("context_length"),
                    "max_completion_tokens": limits.get("max_completion_tokens"),
                    "max_prompt_tokens": limits.get("max_prompt_tokens"),
                    "supports_tool_choice": {"required": True, "auto": True}}
        evidence = {"source_url": limits["source_url"], "evidence_kind": "reviewed_documentation_not_live_attestation", "endpoint": endpoint}
    required = req["required_context_window_tokens"]
    if not _integer(endpoint.get("context_length")) or endpoint["context_length"] < required:
        failures.append("advertised_context_below_requirement")
    if required > req["configured_context_window_tokens"]:
        failures.append("study_context_below_requirement")
    if not _integer(endpoint.get("max_completion_tokens")) or endpoint["max_completion_tokens"] < config.generation.max_output_tokens:
        failures.append("advertised_output_below_study_cap")
    prompt_cap = endpoint.get("max_prompt_tokens")
    if prompt_cap is not None and (not _integer(prompt_cap) or prompt_cap < req["minimum_measured_input_tokens"]):
        failures.append("advertised_input_below_requirement")
    if model.input_token_count_mode not in EXACT_MODES:
        failures.append("production_counting_cannot_measure_context")
    return {"status": "passed" if not failures else "blocked", "failures": failures,
            "evidence": evidence, "strict_arguments": "requires_live_native_smoke",
            "tool_choices": endpoint.get("supports_tool_choice", {})}


def _context_provider(config: StudyConfig, output: Path, cap: int, factory: Callable):
    model = config.models[0]
    extra = {}
    ledger = None
    if model.input_token_count_mode == native.OPENROUTER_CONDITIONAL_COUNT_MODE:
        limit = min(model.context_probe_max_requests, len(SCOPES) * (CALIBRATION_LIMIT + 1))
        ledger = ProbeBudgetLedger(output, model_alias=model.alias,
                                  treatment_sha256=treatment_hash(config),
                                  max_requests=limit, max_cost_usd=model.context_probe_max_cost_usd)
        extra.update(context_probe_budget=ledger, context_probe_max_requests=limit,
                     context_probe_max_cost_usd=model.context_probe_max_cost_usd)
    provider = factory("openai_responses", model=model.model, profile_id=model.provider,
                       action_protocol=config.generation.action_protocol,
                       action_output_contract=model.action_output_contract,
                       timeout_seconds=config.generation.timeout_seconds, max_output_tokens=cap,
                       reasoning_effort=model.reasoning_effort, generation_seed=model.generation_seed,
                       diagnostic_content_scope="synthetic", openrouter_policy=model.openrouter,
                       native_tool_policy=model.native_tool_policy,
                       final_turn_tool_choice_policy=model.final_turn_tool_choice_policy,
                       context_window_tokens=model.context_window_tokens,
                       context_safety_margin_tokens=model.context_safety_margin_tokens,
                       input_token_count_mode=model.input_token_count_mode, **extra)
    return provider, ledger


def run_context_cell(config: StudyConfig, scope: str, provider: Any, req: dict, output: Path) -> dict:
    """Calibrate with real count requests, then make one bounded native call."""
    spec = native.CASE_SPECS[2 if scope == "report" else 1]
    episode, expected, _ = native._episode(spec, config.generation.max_turns)
    prefix = episode.messages[-1]["content"] + "\nIgnore the following synthetic transport padding. Return only a short native terminal call.\n"
    suffix = "\nEND PADDING. Now call " + expected + " with a short, nonempty Markdown body. Do not reproduce the padding."
    result = {"scope": scope, "policy": config.models[0].native_tool_policy,
              "status": "failed", "context_status": "unverified", "tool_status": "not_run",
              "calibrations": [], "audit_artifacts": [], "generation_request_count": 0,
              "context_count_request_count": 0, "scientific_score": None}
    usage = []
    chars = req["configured_context_window_tokens"] + 4096
    target = (req["minimum_measured_input_tokens"] + req["maximum_measured_input_tokens"]) // 2
    ready = False
    for _ in range(CALIBRATION_LIMIT):
        if not 1 <= chars <= MAX_PADDING_BYTES:
            result["failure"] = {"code": "context_padding_limit"}
            break
        episode.messages[-1]["content"] = prefix + (PADDING * ((chars + len(PADDING) - 1) // len(PADDING)))[:chars] + suffix
        context = {}
        failure = None
        try:
            context = provider.prepare_context(episode.messages, episode=episode)
        except Exception as exc:
            context = deepcopy(getattr(exc, "request_context", None) or {})
            failure = native._failure(exc)
        budget = context.get("context_budget", {})
        count = budget.get("input_tokens")
        result["calibrations"].append({"padding_bytes": chars, "request_context": context, "failure": failure})
        result["context_count_request_count"] += int(budget.get("preflight", {}).get("request_count", 0))
        usage.extend(native._preflight_usage_turns(context))
        exact = budget.get("count_kind") == "exact" and _integer(count)
        if not exact:
            result["failure"] = failure or {"code": "context_count_not_measured"}
            break
        if failure is None and req["minimum_measured_input_tokens"] <= count <= req["maximum_measured_input_tokens"] and not budget.get("output_was_clamped"):
            ready = True
            break
        # An exact count that exceeds local headroom can be recalibrated. A
        # provider rejection without a measured count never earns a smaller pass.
        if failure is not None and count <= req["maximum_measured_input_tokens"]:
            result["failure"] = failure
            break
        chars = max(1, round(chars * target / count))
    if ready:
        wrapper = native._BoundedProvider(provider, limit=1)
        trace = None
        try:
            trace = run_episode(episode, wrapper)
        except Exception as exc:
            result["failure"] = native._failure(exc)
        result["generation_request_count"] = wrapper.generation_requests
        result["context_count_request_count"] += wrapper.preflight_requests
        usage.extend(wrapper.usage_turns + wrapper.preflight_usage_turns)
        contexts = wrapper.request_contexts
        result["generation_contexts"] = contexts
        if wrapper.responses:
            turn = wrapper.responses[0]
            result["audit_artifacts"].append(native._write_audit(output, f"{scope}-response.json", turn.raw_response, str(getattr(provider, "api_key", "") or "")))
            measured = turn.usage.get("input_tokens")
            budget = turn.request_context.get("context_budget", {})
            result["measured_input_tokens"] = measured
            result["counted_input_tokens"] = budget.get("input_tokens")
            context_ok = (_integer(measured) and budget.get("count_kind") == "exact"
                          and measured == budget.get("input_tokens")
                          and req["minimum_measured_input_tokens"] <= measured <= req["maximum_measured_input_tokens"]
                          and budget.get("effective_max_output_tokens") == req["generation_output_cap_tokens"]
                          and not budget.get("output_was_clamped"))
            result["context_status"] = "passed" if context_ok else "failed"
            raw_ok = native._raw_conformance(turn.raw_response, semantic_tool_definitions(episode))["valid"]
            tool_ok = bool(raw_ok and trace and trace.get("status") == "completed" and
                           (trace.get("terminal") or {}).get("tool") == expected)
            result["tool_status"] = "passed" if tool_ok else "failed"
            result["status"] = "passed" if context_ok and tool_ok and "failure" not in result else "failed"
            if not context_ok:
                result["failure"] = {"code": "context_count_or_headroom_not_verified"}
            elif not tool_ok:
                result["failure"] = {"code": "long_context_tool_protocol_failure"}
    elif "failure" not in result:
        result["failure"] = {"code": "context_calibration_limit"}
    result["accounting"] = aggregate_usage(usage)
    result["request_count"] = result["generation_request_count"] + result["context_count_request_count"]
    return result


def run_serving_matrix(config: StudyConfig, output_dir: Path, limits: dict, *,
                       inspect_only: bool = False, required_window: int | None = None,
                       probe_output_cap: int = 2048, provider_factory: Callable = create_provider,
                       endpoint_fetcher: Callable = fetch_endpoint,
                       native_runner: Callable = native.run_native_smoke) -> dict:
    input_ceiling = limits.get("input_probe_ceiling_tokens")
    if input_ceiling is not None and (limits.get("provider") != "openai"
                                      or input_ceiling != limits.get("max_prompt_tokens")):
        raise ValueError("a separate input probe ceiling must equal the reviewed direct endpoint input limit")
    req = requirements(config, probe_output_cap, required_window, input_ceiling)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    destination = root / "serving-matrix.json"
    if destination.exists():
        raise ValueError("serving-matrix output already exists; use a fresh immutable directory")
    selected = config.models[0].native_tool_policy
    receipt = {"schema_version": SCHEMA, "status": "running", "matrix_status": "not_run",
               "started_at": datetime.now(timezone.utc).isoformat(),
               "selected_policy": selected, "treatment_sha256": treatment_hash(config),
               "source_sha256": source_hash(), "requirements": req,
               "endpoint_limits_sha256": sha256_json(limits),
               "study": sanitized_config(config), "policies": [], "request_count": 0,
               "retry_attempts": 0, "stage": "A_serving_and_context_matrix"}
    try:
        receipt["endpoint_check"] = inspect_endpoint(config, limits, req, endpoint_fetcher)
    except Exception as exc:
        receipt["endpoint_check"] = {"status": "blocked", "failure": native._failure(exc)}
    if receipt["endpoint_check"]["status"] != "passed" or inspect_only:
        receipt["status"] = "blocked" if receipt["endpoint_check"]["status"] != "passed" else "prepared_not_qualified"
        atomic_write_json(destination, receipt)
        return receipt
    for policy in POLICIES:
        choice = "auto" if policy == "strict_auto_v1" else "required"
        candidate = replace(config, models=(replace(config.models[0], native_tool_policy=policy,
                                                    final_turn_tool_choice_policy=choice),))
        # Preserve the normal native receipt location for the selected policy.
        path = root if policy == selected else root / "comparison" / policy
        path.mkdir(parents=True, exist_ok=True)
        row = {"policy": policy, "status": "running", "context_cases": []}
        receipt["policies"].append(row)
        try:
            small = native_runner(candidate, path, provider_factory=provider_factory,
                                  include_long_form=True, probe_max_output_tokens=probe_output_cap)
            row["native_status"] = small["status"]
            row["native_receipt"] = str((path / "native-smoke.json").relative_to(root))
            row["request_count"] = small["request_count"]
            context_path = path / "context"
            context_path.mkdir(exist_ok=True)
            provider, ledger = _context_provider(candidate, context_path, req["generation_output_cap_tokens"], provider_factory)
            for scope in SCOPES:
                case = run_context_cell(candidate, scope, provider, req, context_path)
                for artifact in case["audit_artifacts"]:
                    if artifact.get("path"):
                        artifact["path"] = str((context_path / artifact["path"]).relative_to(root))
                row["context_cases"].append(case)
                row["request_count"] += case["request_count"]
                atomic_write_json(destination, receipt)
            if ledger is not None:
                row["context_probe_budget"] = ledger.snapshot(include_reservations=False)
            row["status"] = "passed" if small["status"] == "passed" and all(c["status"] == "passed" for c in row["context_cases"]) else "failed"
        except Exception as exc:
            row.update(status="failed", failure=native._failure(exc))
        receipt["request_count"] += row.get("request_count", 0)
        atomic_write_json(destination, receipt)
    receipt["matrix_status"] = "passed" if all(p["status"] == "passed" for p in receipt["policies"]) else "failed"
    receipt["status"] = next(p["status"] for p in receipt["policies"] if p["policy"] == selected)
    receipt["selection_policy"] = "only_explicit_study_policy_can_qualify; comparison_never_changes_configuration"
    receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
    atomic_write_json(destination, receipt)
    return receipt
