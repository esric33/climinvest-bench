from __future__ import annotations

from copy import deepcopy
from time import monotonic
from typing import Any

from .accounting import aggregate_usage
from .episode import Episode, SPLIT_TERMINAL_PROTOCOL, TERMINAL_TOOLS
from .provider_cost import normalize_provider_cost
from .protocol import parse_textual_tool_turn, render_tool_observations
from .providers.base import ProviderToolCall
from .providers.base import Provider
from .tools import calculate as calculate_tool
from .tools import create_report as create_report_tool
from .tools import create_section as create_section_tool
from .tools import get_data as get_data_tool
from ..util import sha256_text


def run_episode(episode: Episode, provider: Provider) -> dict[str, Any]:
    fatal_protocol_error = False
    for _ in range(max(0, episode.max_turns - len(episode.turns))):
        if episode.terminal is not None:
            break
        started = monotonic()
        provider_turn = provider.complete(episode.messages, episode=episode)
        latency = provider_turn.latency_seconds or (monotonic() - started)
        action_protocol = provider_turn.action_protocol or (
            "native_tools"
            if provider_turn.tool_calls is not None
            or provider_turn.protocol_error is not None
            else "textual_json"
        )
        transport = provider_turn.transport or str(
            getattr(provider, "transport", getattr(provider, "name", "unknown"))
        )
        turn_record: dict[str, Any] = {
            "turn_index": len(episode.turns),
            "turn_phase": episode.turn_phase,
            "offered_tools": sorted(episode.active_allowed_tools),
            "raw_text": provider_turn.text,
            "raw_response": provider_turn.raw_response,
            "usage": provider_turn.usage,
            "latency_seconds": latency,
            "provider_request_id": provider_turn.provider_request_id,
            "status": "received",
            # ``protocol`` remains for v1 trace readers.  The explicit fields
            # separate the HTTP/API transport from the action representation.
            "protocol": action_protocol,
            "transport": transport,
            "action_protocol": action_protocol,
        }
        provider_cost = normalize_provider_cost(provider_turn.provider_cost)
        if provider_cost:
            # The checkpoint ledger remains authoritative for run-level billing.
            # Retain the same canonical value here so an episode artifact is
            # independently interpretable without recovering money from a raw
            # provider response.
            turn_record["provider_cost"] = provider_cost
        action_output_contract = getattr(
            provider, "action_output_contract", None
        )
        if action_output_contract:
            turn_record["action_output_contract"] = str(
                action_output_contract
            )
        if provider_turn.normalizations:
            turn_record["normalizations"] = provider_turn.normalizations
        if provider_turn.request_context:
            turn_record["request_context"] = provider_turn.request_context
        if provider_turn.protocol_error is not None:
            turn_record.update(
                status="protocol_error",
                error=provider_turn.protocol_error,
                calls=[],
            )
            episode.turns.append(turn_record)
            fatal_protocol_error = True
            break
        native_calls = provider_turn.tool_calls
        if native_calls is not None:
            calls = [_trace_call(call) for call in native_calls]
            _record_call_counts(
                turn_record,
                calls,
                normalizations=provider_turn.normalizations,
            )
            turn_record["action_batch"] = _action_batch_record(
                semantics="native_tool_batch",
                action_envelope_count=None,
                semantic_action_envelope_count=None,
                emitted_tool_call_count=turn_record["emitted_call_count"],
                semantic_tool_call_count=turn_record["semantic_call_count"],
            )
            malformed = [call for call in native_calls if call.error is not None]
            if malformed:
                observations = [
                    {
                        "tool": call.tool,
                        "status": "protocol_error",
                        "message": (
                            call.error
                            or "not executed because another native call was malformed"
                        ),
                    }
                    for call in native_calls
                ]
                turn_record.update(
                    status="protocol_error",
                    error="one or more native tool calls had malformed arguments",
                    calls=calls,
                    observations=observations,
                )
                turn_record["action_batch"].update(
                    status="rejected",
                    disposition="rejected_malformed_native_call",
                )
                episode.turns.append(turn_record)
                fatal_protocol_error = True
                break
        else:
            try:
                parsed = parse_textual_tool_turn(provider_turn.text)
                calls = parsed.calls
                turn_record["action_envelopes"] = parsed.envelopes
                turn_record["observation_boundary"] = {
                    "mode": "ordered_open_loop_batch",
                    "action_envelope_count": len(parsed.envelopes),
                    "call_count": len(calls),
                    "executed_call_count": 0,
                }
                _record_call_counts(
                    turn_record,
                    calls,
                    normalizations=provider_turn.normalizations,
                    semantic_envelope_count=len(parsed.envelopes),
                )
                turn_record["action_batch"] = _action_batch_record(
                    semantics="ordered_open_loop",
                    action_envelope_count=turn_record[
                        "raw_action_envelope_count"
                    ],
                    semantic_action_envelope_count=turn_record[
                        "semantic_action_envelope_count"
                    ],
                    emitted_tool_call_count=turn_record["emitted_call_count"],
                    semantic_tool_call_count=turn_record[
                        "semantic_call_count"
                    ],
                )
            except (ValueError, TypeError) as exc:
                turn_record.update(
                    status="protocol_error", error=str(exc), calls=[]
                )
                turn_record["action_batch"] = _action_batch_record(
                    semantics="ordered_open_loop",
                    action_envelope_count=None,
                    semantic_action_envelope_count=None,
                    emitted_tool_call_count=None,
                    semantic_tool_call_count=None,
                    status="rejected",
                    disposition="rejected_unparseable",
                    observation_round_count=1,
                )
                episode.turns.append(turn_record)
                episode.messages.append(
                    {"role": "assistant", "content": provider_turn.text}
                )
                episode.messages.append(
                    {
                        "role": "user",
                        "content": render_tool_observations(
                            [{"status": "protocol_error", "message": str(exc)}]
                        ),
                    }
                )
                continue
        terminal_calls = [call for call in calls if call["tool"] in TERMINAL_TOOLS]
        if terminal_calls and len(calls) != 1:
            observations = [
                {
                    "tool": call["tool"],
                    "status": "invalid_terminal_batch",
                    "message": "a terminal tool must be the only call in its turn",
                }
                for call in calls
            ]
            turn_record.update(
                status="protocol_error",
                error="a terminal tool was mixed with other calls",
                calls=calls,
                observations=observations,
            )
            turn_record["action_batch"].update(
                status="rejected",
                disposition="rejected_terminal_mix",
                executed_tool_call_count=0,
                observation_round_count=(0 if native_calls is not None else 1),
            )
            episode.turns.append(turn_record)
            if native_calls is not None:
                fatal_protocol_error = True
                break
            if native_calls is None:
                episode.messages.extend(
                    [
                        {"role": "assistant", "content": provider_turn.text},
                        {
                            "role": "user",
                            "content": render_tool_observations(observations),
                        },
                    ]
                )
            continue
        observations: list[dict[str, Any]] = []
        for call in calls:
            result = execute_call(episode, call)
            observations.append(result)
            if result.get("terminal") and result.get("status") == "accepted":
                episode.terminal = result
        turn_record["executed_call_count"] = len(calls)
        if "observation_boundary" in turn_record:
            turn_record["observation_boundary"]["executed_call_count"] = len(
                calls
            )
        turn_record.update(
            status="completed",
            calls=calls,
            observations=observations,
        )
        terminal_accepted = episode.terminal is not None
        if terminal_calls:
            disposition = (
                "terminal_accepted"
                if terminal_accepted
                else "terminal_rejected"
            )
        else:
            disposition = "executed_nonterminal_batch"
        turn_record["action_batch"].update(
            status="completed",
            disposition=disposition,
            executed_tool_call_count=len(calls),
            observation_round_count=(0 if terminal_accepted else 1),
        )
        episode.turns.append(turn_record)
        if (
            terminal_calls and not terminal_accepted
            and episode.terminal_protocol_version == SPLIT_TERMINAL_PROTOCOL
        ):
            # A rejected terminal schema is a protocol outcome, never a repair
            # opportunity. Preserve the rejected candidate and stop here.
            fatal_protocol_error = True
            break
        if native_calls is not None:
            if episode.terminal is not None:
                break
            continue
        episode.messages.append(
            {"role": "assistant", "content": provider_turn.text}
        )
        if episode.terminal is not None:
            break
        episode.messages.append(
            {"role": "user", "content": render_tool_observations(observations)}
        )

    status = (
        "completed"
        if episode.terminal is not None
        else (
            "protocol_failure"
            if fatal_protocol_error
            else "turn_limit_exhausted"
        )
    )
    action_protocol = str(
        getattr(provider, "action_protocol", "")
        or (
            episode.turns[0].get("action_protocol")
            if episode.turns
            else "unknown"
        )
    )
    transport = str(
        getattr(provider, "transport", "")
        or (
            episode.turns[0].get("transport")
            if episode.turns
            else getattr(provider, "name", "unknown")
        )
    )
    provider_provenance = {
        "provider": str(getattr(provider, "name", "unknown")),
        "model": str(getattr(provider, "model", "unknown")),
        "transport": transport,
        "action_protocol": action_protocol,
    }
    profile_id = getattr(provider, "profile_id", None)
    if profile_id:
        provider_provenance["profile_id"] = str(profile_id)
    provider_routing = getattr(provider, "provider_routing_provenance", None)
    if isinstance(provider_routing, dict):
        provider_provenance["provider_routing"] = deepcopy(provider_routing)
    action_interface_version = getattr(
        provider, "action_interface_version", None
    )
    if action_interface_version:
        provider_provenance["action_interface_version"] = str(
            action_interface_version
        )
    action_output_contract = getattr(provider, "action_output_contract", None)
    if action_output_contract:
        provider_provenance["action_output_contract"] = str(
            action_output_contract
        )
    action_output_schema_version = getattr(
        provider, "action_output_schema_version", None
    )
    if action_output_schema_version:
        provider_provenance["action_output_schema_version"] = str(
            action_output_schema_version
        )
    native_tool_policy = getattr(provider, "native_tool_policy_provenance", None)
    if native_tool_policy is not None:
        provider_provenance["native_tool_policy"] = deepcopy(native_tool_policy)
    final_turn_policy = getattr(provider, "final_turn_tool_choice_provenance", None)
    if final_turn_policy is not None:
        provider_provenance["final_turn_tool_choice_policy"] = deepcopy(final_turn_policy)
    return {
        "schema_version": "react_report.episode/v1",
        "episode_id": episode.episode_id,
        "episode_kind": episode.episode_kind,
        "benchmark_version": episode.benchmark_version,
        "turn_policy": episode.turn_policy,
        "terminal_protocol_version": episode.terminal_protocol_version,
        "project_id": episode.project_id,
        "section_id": episode.section_id,
        "status": status,
        "terminal": episode.terminal,
        "turns": episode.turns,
        "provider_provenance": provider_provenance,
        "accounting": aggregate_usage(episode.turns),
        "store_snapshot": episode.store.snapshot(),
    }


def _trace_call(call: ProviderToolCall) -> dict[str, Any]:
    return {
        "tool": call.tool,
        "arguments": call.arguments or {},
        "provider_call_id": call.call_id,
        **({"provider_error": call.error} if call.error else {}),
    }


def _record_call_counts(
    turn_record: dict[str, Any],
    calls: list[dict[str, Any]],
    *,
    normalizations: list[dict[str, Any]],
    semantic_envelope_count: int | None = None,
) -> None:
    """Record raw-emitted, semantic, and actually executed action counts."""

    semantic_calls = len(calls)
    emitted_calls = semantic_calls
    raw_envelopes = semantic_envelope_count
    for event in normalizations:
        if not isinstance(event, dict):
            continue
        original_calls = event.get("original_call_count")
        original_envelopes = event.get("original_action_envelope_count")
        if isinstance(original_calls, int) and original_calls >= 0:
            emitted_calls = original_calls
        if isinstance(original_envelopes, int) and original_envelopes >= 0:
            raw_envelopes = original_envelopes
    turn_record["emitted_call_count"] = emitted_calls
    turn_record["semantic_call_count"] = semantic_calls
    turn_record["executed_call_count"] = 0
    if semantic_envelope_count is not None:
        turn_record["semantic_action_envelope_count"] = semantic_envelope_count
        turn_record["raw_action_envelope_count"] = (
            raw_envelopes
            if raw_envelopes is not None
            else semantic_envelope_count
        )


def _action_batch_record(
    *,
    semantics: str,
    action_envelope_count: int | None,
    semantic_action_envelope_count: int | None,
    emitted_tool_call_count: int | None,
    semantic_tool_call_count: int | None,
    status: str = "parsed",
    disposition: str = "pending",
    observation_round_count: int = 0,
) -> dict[str, Any]:
    return {
        "schema_version": "react_report.action_batch/v1",
        "semantics": semantics,
        "status": status,
        "disposition": disposition,
        "action_envelope_count": action_envelope_count,
        "semantic_action_envelope_count": semantic_action_envelope_count,
        "emitted_tool_call_count": emitted_tool_call_count,
        "semantic_tool_call_count": semantic_tool_call_count,
        "executed_tool_call_count": 0,
        "observation_round_count": observation_round_count,
    }


def execute_call(episode: Episode, call: dict[str, Any]) -> dict[str, Any]:
    tool = call["tool"]
    arguments = call["arguments"]
    if tool not in episode.active_allowed_tools:
        return {
            "tool": tool,
            "status": "unavailable_tool",
            "message": (
                f"{tool!r} is unavailable during the current "
                f"{episode.turn_phase} turn"
            ),
        }
    if tool == "get_data":
        return get_data_tool.execute(episode.store, arguments)
    if tool == "calculate":
        return calculate_tool.execute(episode.calculator, arguments)
    if tool == "create_report":
        if episode.episode_kind not in {"report_create", "report_update", "oracle_report"}:
            return {
                "tool": tool,
                "status": "invalid_context",
                "message": "create_report is unavailable in this episode",
            }
        if (
            episode.terminal_protocol_version == SPLIT_TERMINAL_PROTOCOL
            and set(arguments) != {"markdown"}
        ):
            return {
                "tool": tool,
                "status": "invalid_arguments",
                "message": "arguments must contain exactly ['markdown']",
            }
        result = create_report_tool.validate(arguments)
        validator = episode.report_output_validator
        if result.get("status") != "accepted" or validator is None:
            return result
        # A syntactically valid terminal submission is final.  Output-contract
        # validation is an after-the-fact diagnostic saved with the trace; it
        # must never reject the candidate or become a repair observation.
        result["output_validation"] = _diagnose_terminal_output(
            validator,
            result["markdown"],
            episode,
            output_kind="report",
        )
        return result
    if tool in {"create_section", "replace_section", "keep_section"}:
        if episode.section_id is None:
            return {
                "tool": tool,
                "status": "invalid_context",
                "message": "create_section requires a section episode",
            }
        validate_section = create_section_tool.validate
        extra = {}
        if episode.terminal_protocol_version == SPLIT_TERMINAL_PROTOCOL:
            validate_section = create_section_tool.validate_split
            extra["tool"] = tool
        result = validate_section(
            arguments,
            **extra,
            expected_section_id=episode.section_id,
            episode_kind=episode.episode_kind,
            original_markdown=episode.original_markdown,
        )
        validator = episode.section_output_validator
        if result.get("status") != "accepted" or validator is None:
            return result
        # ``keep`` is a routing decision, not a request to regenerate a T1
        # section.  Only the v2 update constructor can opt out of T1 validation,
        # and it must carry the validation + hash proof created while the
        # canonical T0 was prepared.  Generic callers without that proof retain
        # the ordinary validator behavior below.
        if (
            result.get("mode") == "keep"
            and episode.retained_section_proof is not None
        ):
            validation = _validate_retained_section_proof(episode)
            result["output_validation"] = validation
            return result
        result["output_validation"] = _diagnose_terminal_output(
            validator,
            result["markdown"],
            episode,
            output_kind="section",
        )
        return result
    return {
        "tool": tool,
        "status": "unknown_tool",
        "message": f"Unknown tool {tool!r}",
    }


def _diagnose_terminal_output(
    validator: Any,
    markdown: str,
    episode: Episode,
    *,
    output_kind: str,
) -> dict[str, Any]:
    """Run post-submission diagnostics without changing terminal acceptance."""

    try:
        return validator(markdown, episode.store)
    except Exception as exc:  # pragma: no cover - defensive extension boundary
        return {
            "schema_version": "react_report.output_validation_diagnostic/v1",
            "valid": False,
            "errors": [
                {
                    "code": "output_validation_error",
                    "message": f"{output_kind} output validator failed: {exc}",
                }
            ],
        }


def _validate_retained_section_proof(episode: Episode) -> dict[str, Any]:
    proof = episode.retained_section_proof
    errors: list[dict[str, str]] = []
    if episode.episode_kind != "section_update":
        errors.append(
            {
                "code": "retained_proof_context",
                "message": "retained-section proofs require a section update",
            }
        )
    if not isinstance(proof, dict):
        errors.append(
            {
                "code": "retained_proof_missing",
                "message": "canonical retained-section proof is missing",
            }
        )
        proof = {}
    if proof.get("schema_version") != "react_report.retained_section_proof/v1":
        errors.append(
            {
                "code": "retained_proof_schema",
                "message": "retained-section proof schema is unsupported",
            }
        )
    if proof.get("valid") is not True:
        errors.append(
            {
                "code": "retained_proof_invalid",
                "message": "canonical T0 section did not pass prior validation",
            }
        )
    if proof.get("section_id") != episode.section_id:
        errors.append(
            {
                "code": "retained_proof_section",
                "message": "retained-section proof belongs to another section",
            }
        )
    original = episode.original_markdown
    if not isinstance(original, str) or proof.get("section_sha256") != sha256_text(
        original or ""
    ):
        errors.append(
            {
                "code": "retained_proof_hash",
                "message": "original section differs from its canonical T0 proof",
            }
        )
    for key in ("canonical_t0_sha256", "contract_sha256"):
        value = proof.get(key)
        if not isinstance(value, str) or len(value) != 64:
            errors.append(
                {
                    "code": "retained_proof_identity",
                    "message": f"retained-section proof has invalid {key}",
                }
            )
    return {
        "schema_version": "react_report.section_output_validation/v2",
        "section_id": episode.section_id,
        "valid": not errors,
        "errors": errors,
        "validation_basis": "canonical_t0_prevalidated_t1_skipped",
        "canonical_t0_sha256": proof.get("canonical_t0_sha256"),
        "section_sha256": proof.get("section_sha256"),
        "contract_sha256": proof.get("contract_sha256"),
    }
