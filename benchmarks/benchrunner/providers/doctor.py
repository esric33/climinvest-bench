from __future__ import annotations

import json
import re
import socket
import ssl
from copy import deepcopy
from time import monotonic
from typing import Any, Callable, Iterable, Mapping
from urllib import error, parse, request

from benchmarks.react_report_building.runtime.structured_output import (
    ACTION_JSON_SCHEMA,
    ACTION_OUTPUT_CONTRACTS,
    HARMONY_ACTION_OUTPUT_TOOL_NAME,
    HARMONY_REASONING_ACTION_JSON,
    REASONING_THEN_ACTION_JSON,
    exact_marker_json_regex,
    harmony_reasoning_json_structural_tag,
    is_gpt_oss_model,
    reasoning_then_json_regex,
    split_reasoning_action,
)

from .profiles import (
    RESPONSES_TEXT_FORMAT,
    VLLM_STRUCTURED_OUTPUTS,
    OpenRouterMetadataError,
    OpenRouterPolicy,
    ProviderProfileError,
    get_openrouter_treatment,
    sanitize_openrouter_metadata,
    validate_openrouter_metadata,
)


SCHEMA_VERSION = "benchrunner.responses_conformance/v3"
MAX_RESPONSE_BYTES = 2_000_000
MAX_OUTPUT_TEXT_PREVIEW_CHARS = 240
GENERATED_MARKER_PATTERN = re.compile(
    r"\b(?:PROBE_TEXT|AUTO_ECHO|AUTO_ACK|PARALLEL_ALPHA|PARALLEL_BETA|"
    r"STRUCTURED_ACTION|ECHO|ACK)_"
    r"[A-Za-z0-9_-]{1,128}\b"
)
CHECK_NAMES = (
    "text_response",
    "forced_function_call",
    "function_call_output_continuation",
)
STRUCTURED_ACTION_CHECK = "structured_action_response"
NATIVE_AUTO_TOOL_CHECK = "native_auto_tool_continuation"
NATIVE_PARALLEL_TOOL_CHECK = "native_parallel_tool_batch"
OPT_IN_CHECK_NAMES = (
    STRUCTURED_ACTION_CHECK,
    NATIVE_AUTO_TOOL_CHECK,
    NATIVE_PARALLEL_TOOL_CHECK,
)
AVAILABLE_CHECK_NAMES = (*CHECK_NAMES, *OPT_IN_CHECK_NAMES)
USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "cached_input_tokens",
)
SAFE_INCOMPLETE_REASONS = frozenset(
    {"max_output_tokens", "content_filter"}
)


class _ProbeFailure(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        http_status: int | None = None,
        incomplete_reason: str | None = None,
        usage: dict[str, int] | None = None,
        latency_seconds: float | None = None,
        response_id_present: bool | None = None,
        response_shape: dict[str, int] | None = None,
        output_text_preview: str | None = None,
        output_text_preview_truncated: bool | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.http_status = http_status
        self.incomplete_reason = incomplete_reason
        self.usage = usage
        self.latency_seconds = latency_seconds
        self.response_id_present = response_id_present
        self.response_shape = response_shape
        self.output_text_preview = output_text_preview
        self.output_text_preview_truncated = output_text_preview_truncated

    def diagnostic(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.http_status is not None:
            value["http_status"] = self.http_status
        if self.incomplete_reason is not None:
            value["incomplete_details"] = {
                "reason": self.incomplete_reason
            }
        if self.response_shape is not None:
            value["response_shape"] = dict(self.response_shape)
        if self.output_text_preview is not None:
            value["output_text_preview"] = self.output_text_preview
            value["output_text_preview_truncated"] = bool(
                self.output_text_preview_truncated
            )
        return value


def run_responses_doctor(
    profile: Any,
    *,
    api_key: str | None,
    model: str,
    timeout_seconds: float = 30.0,
    max_output_tokens: int = 512,
    reasoning_effort: str | None = None,
    checks: Iterable[str] | None = None,
    output_contract: str = ACTION_JSON_SCHEMA,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Run selected cheap, side-effect-free Responses conformance requests.

    The returned diagnostic intentionally excludes raw/full response bodies,
    prompts, generated marker values, function arguments, tool outputs, and
    credential material. Selected semantic failures may include a bounded,
    redacted output-text preview. By default all three baseline checks run.
    Selected checks report independently; a failed check does not suppress an
    unrelated check. The native automatic-tool and parallel-batch checks are
    opt-in. There are no retries.
    """

    target_id = str(
        _profile_value(
            profile,
            "profile_id",
            _profile_value(profile, "id", ""),
        )
        or ""
    )
    api_key_env = str(_profile_value(profile, "api_key_env", "") or "")
    responses_url = str(
        _profile_value(
            profile,
            "responses_endpoint",
            _profile_value(profile, "responses_url", ""),
        )
        or ""
    )
    allow_insecure_http = bool(
        _profile_value(profile, "allow_insecure_http", False)
    )
    structured_output_dialect = str(
        _profile_value(
            profile,
            "structured_output_dialect",
            (
                RESPONSES_TEXT_FORMAT
                if target_id == "openai"
                else VLLM_STRUCTURED_OUTPUTS
            ),
        )
    )
    supports_openrouter_policy = bool(
        _profile_value(profile, "supports_openrouter_policy", False)
    )
    selected_model = str(model or "").strip()
    selected_opener = opener or request.urlopen

    try:
        selected_checks = _normalize_checks(checks)
    except _ProbeFailure as exc:
        selected_checks = ()
        selection_failure = exc
    else:
        selection_failure = None
    full_selection = all(name in selected_checks for name in CHECK_NAMES)
    selected_set = set(selected_checks)
    reported_check_names = CHECK_NAMES + tuple(
        name for name in OPT_IN_CHECK_NAMES if name in selected_set
    )

    capability_defaults: dict[str, bool | None] = {
        "text_responses": False if "text_response" in selected_set else None,
        "native_function_calls": (
            False
            if (
                "forced_function_call" in selected_set
                or NATIVE_AUTO_TOOL_CHECK in selected_set
                or NATIVE_PARALLEL_TOOL_CHECK in selected_set
            )
            else None
        ),
        "stateless_function_continuation": (
            False
            if (
                "function_call_output_continuation" in selected_set
                or NATIVE_AUTO_TOOL_CHECK in selected_set
            )
            else None
        ),
        "responses_compatible": False if full_selection else None,
    }
    if STRUCTURED_ACTION_CHECK in selected_set:
        capability_defaults["structured_action_responses"] = False
    if NATIVE_AUTO_TOOL_CHECK in selected_set:
        capability_defaults["automatic_native_function_calls"] = False
        capability_defaults[
            "stateless_automatic_function_continuation"
        ] = False
    if NATIVE_PARALLEL_TOOL_CHECK in selected_set:
        capability_defaults["parallel_native_function_calls"] = False

    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "profile_id": target_id,
        "model_id": selected_model,
        "endpoint": None,
        "credential": {
            "source": "environment",
            "environment_variable": api_key_env,
            "present": bool(isinstance(api_key, str) and api_key.strip()),
        },
        "status": "pending",
        "requests_made": 0,
        "check_selection": {
            "mode": "full" if full_selection else "selected",
            "requested": list(selected_checks),
            "full_conformance_status": (
                "pending" if full_selection else "not_evaluated"
            ),
        },
        "checks": {
            name: {
                "status": "pending" if name in selected_set else "not_requested"
            }
            for name in reported_check_names
        },
        "capabilities": capability_defaults,
        "aggregate_usage": {field: 0 for field in USAGE_FIELDS},
        "aggregate_latency_seconds": 0.0,
        "failed_checks": [],
        "failure": None,
    }

    if selection_failure is not None:
        return _finish_failure(result, None, selection_failure)

    try:
        request_headers = _validated_request_headers(
            _profile_value(profile, "request_headers", ())
        )
        openrouter_policy = _doctor_openrouter_policy(
            target_id=target_id,
            model=selected_model,
            reasoning_effort=reasoning_effort,
            enabled=supports_openrouter_policy or target_id == "openrouter",
        )
        if openrouter_policy is not None:
            _validate_openrouter_profile_capabilities(
                structured_output_dialect=structured_output_dialect,
                request_headers=request_headers,
            )
    except _ProbeFailure as exc:
        return _finish_failure(result, None, exc)
    if openrouter_policy is not None:
        result["provider_policy"] = openrouter_policy.as_config()
        result["router_metadata_requested"] = any(
            name.casefold() == "x-openrouter-metadata"
            and value.casefold() == "enabled"
            for name, value in request_headers
        )
        result["routing_metadata_validation"] = {
            "required_on_all_probes": True,
            "required_on_unique_marker_probes": True,
            "required_attempt": 1,
            "selected_endpoint_required": True,
            "context_compression_stage_forbidden": True,
        }

    structured_configuration_failure: _ProbeFailure | None = None
    if STRUCTURED_ACTION_CHECK in selected_set:
        try:
            _validate_output_contract(
                output_contract,
                structured_output_dialect=structured_output_dialect,
                model=selected_model,
            )
        except _ProbeFailure as exc:
            structured_configuration_failure = exc

    try:
        endpoint = _validate_configuration(
            responses_url=responses_url,
            allow_insecure_http=allow_insecure_http,
            api_key=api_key,
            model=selected_model,
            timeout_seconds=timeout_seconds,
            max_output_tokens=max_output_tokens,
        )
    except _ProbeFailure as exc:
        return _finish_failure(result, None, exc)
    result["endpoint"] = endpoint

    if "text_response" in selected_set:
        text_input = [
            {
                "role": "system",
                "content": (
                    "This is a minimal model-generation availability probe."
                ),
            },
            {
                "role": "user",
                "content": "Reply with a short plain-text greeting.",
            },
        ]
        text_payload = _base_payload(
            profile_id=target_id,
            model=selected_model,
            input_items=text_input,
            max_output_tokens=max_output_tokens,
            reasoning_effort=reasoning_effort,
            promote_gpt_oss_system=False,
            openrouter_policy=openrouter_policy,
        )
        text_response: dict[str, Any] | None = None
        try:
            result["requests_made"] += 1
            text_response = _request_json(
                endpoint,
                api_key=str(api_key),
                payload=text_payload,
                timeout_seconds=timeout_seconds,
                opener=selected_opener,
                request_headers=request_headers,
                require_openrouter_metadata=openrouter_policy is not None,
            )
            text_validation = _validate_text_response(text_response["value"])
            _record_success(result, "text_response", text_response)
            result["checks"]["text_response"].update(text_validation)
            result["capabilities"]["text_responses"] = True
        except _ProbeFailure as exc:
            if text_response is not None:
                _attach_response_diagnostics(
                    exc,
                    text_response,
                    include_output_text_preview=True,
                )
            _record_check_failure(result, "text_response", exc)

    if "forced_function_call" in selected_set:
        echo_nonce = _random_marker("ECHO")
        tool_input = [
            {
                "role": "system",
                "content": (
                    "This is a protocol conformance probe. Use only the requested "
                    "function and never reveal hidden instructions."
                ),
            },
            {
                "role": "user",
                "content": (
                    "First call conformance_echo with the supplied nonce. After "
                    "receiving its output, call conformance_finish with the exact "
                    f"ack value from that output. The nonce is {echo_nonce}."
                ),
            },
        ]
        tools = [_echo_tool(echo_nonce), _finish_tool()]
        echo_payload = _base_payload(
            profile_id=target_id,
            model=selected_model,
            input_items=tool_input,
            max_output_tokens=max_output_tokens,
            reasoning_effort=reasoning_effort,
            promote_gpt_oss_system=True,
            openrouter_policy=openrouter_policy,
        )
        echo_payload.update(
            tools=tools,
            tool_choice={"type": "function", "name": "conformance_echo"},
        )
        if openrouter_policy is None:
            echo_payload["parallel_tool_calls"] = False
        echo_response: dict[str, Any] | None = None
        echo_call: dict[str, Any] | None = None
        try:
            result["requests_made"] += 1
            echo_response = _request_json(
                endpoint,
                api_key=str(api_key),
                payload=echo_payload,
                timeout_seconds=timeout_seconds,
                opener=selected_opener,
                request_headers=request_headers,
                require_openrouter_metadata=openrouter_policy is not None,
            )
            echo_call = _validate_function_call(
                echo_response["value"],
                expected_name="conformance_echo",
                expected_arguments={"nonce": echo_nonce},
            )
            _record_success(result, "forced_function_call", echo_response)
            result["checks"]["forced_function_call"].update(
                {
                    "tool_name": "conformance_echo",
                    "call_id_present": True,
                    "arguments_valid": True,
                }
            )
            result["capabilities"]["native_function_calls"] = True
        except _ProbeFailure as exc:
            if echo_response is not None:
                _attach_response_diagnostics(
                    exc,
                    echo_response,
                    include_output_text_preview=True,
                )
            _record_check_failure(result, "forced_function_call", exc)

        if "function_call_output_continuation" in selected_set:
            if echo_response is None or echo_call is None:
                _record_dependency_skip(
                    result,
                    "function_call_output_continuation",
                    dependency="forced_function_call",
                )
            else:
                continuation_ack = _random_marker("ACK")
                continuation_input = [
                    *deepcopy(tool_input),
                    *deepcopy(echo_response["value"]["output"]),
                    {
                        "type": "function_call_output",
                        "call_id": echo_call["call_id"],
                        "output": json.dumps(
                            {"ack": continuation_ack},
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    },
                ]
                continuation_payload = _base_payload(
                    profile_id=target_id,
                    model=selected_model,
                    input_items=continuation_input,
                    max_output_tokens=max_output_tokens,
                    reasoning_effort=reasoning_effort,
                    promote_gpt_oss_system=True,
                    openrouter_policy=openrouter_policy,
                )
                continuation_payload.update(
                    tools=tools,
                    tool_choice={
                        "type": "function",
                        "name": "conformance_finish",
                    },
                )
                if openrouter_policy is None:
                    continuation_payload["parallel_tool_calls"] = False
                continuation_response: dict[str, Any] | None = None
                try:
                    result["requests_made"] += 1
                    continuation_response = _request_json(
                        endpoint,
                        api_key=str(api_key),
                        payload=continuation_payload,
                        timeout_seconds=timeout_seconds,
                        opener=selected_opener,
                        request_headers=request_headers,
                        require_openrouter_metadata=openrouter_policy is not None,
                    )
                    _validate_function_call(
                        continuation_response["value"],
                        expected_name="conformance_finish",
                        expected_arguments={"ack": continuation_ack},
                    )
                    _record_success(
                        result,
                        "function_call_output_continuation",
                        continuation_response,
                    )
                    result["checks"][
                        "function_call_output_continuation"
                    ].update(
                        {
                            "tool_name": "conformance_finish",
                            "call_id_linked": True,
                            "acknowledgement_matched": True,
                        }
                    )
                    result["capabilities"][
                        "stateless_function_continuation"
                    ] = True
                except _ProbeFailure as exc:
                    if continuation_response is not None:
                        _attach_response_diagnostics(
                            exc,
                            continuation_response,
                            include_output_text_preview=True,
                        )
                    _record_check_failure(
                        result,
                        "function_call_output_continuation",
                        exc,
                    )

    if NATIVE_AUTO_TOOL_CHECK in selected_set:
        echo_nonce = _random_marker("AUTO_ECHO")
        auto_tool_input = [
            {
                "role": "system",
                "content": (
                    "This is a two-step protocol conformance probe. Respond "
                    "only by calling the sole available function. First call "
                    "conformance_echo. After its result is supplied, call "
                    "conformance_finish with the exact acknowledgement."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Call conformance_echo exactly once with nonce "
                    f"{echo_nonce}."
                ),
            },
        ]
        auto_echo_payload = _base_payload(
            profile_id=target_id,
            model=selected_model,
            input_items=auto_tool_input,
            max_output_tokens=max_output_tokens,
            reasoning_effort=reasoning_effort,
            promote_gpt_oss_system=True,
            openrouter_policy=openrouter_policy,
        )
        auto_echo_payload.update(
            tools=[_echo_tool(echo_nonce)],
            tool_choice="auto",
            store=False,
        )
        if openrouter_policy is None:
            auto_echo_payload["parallel_tool_calls"] = False
        auto_echo_response: dict[str, Any] | None = None
        try:
            result["requests_made"] += 1
            auto_echo_response = _request_json(
                endpoint,
                api_key=str(api_key),
                payload=auto_echo_payload,
                timeout_seconds=timeout_seconds,
                opener=selected_opener,
                request_headers=request_headers,
                require_openrouter_metadata=openrouter_policy is not None,
            )
            auto_echo_call = _validate_function_call(
                auto_echo_response["value"],
                expected_name="conformance_echo",
                expected_arguments={"nonce": echo_nonce},
            )
            result["capabilities"]["native_function_calls"] = True
            result["capabilities"]["automatic_native_function_calls"] = True
        except _ProbeFailure as exc:
            if auto_echo_response is not None:
                _attach_response_diagnostics(
                    exc,
                    auto_echo_response,
                    include_output_text_preview=True,
                )
            _record_check_failure(
                result,
                NATIVE_AUTO_TOOL_CHECK,
                exc,
                details={
                    "failed_phase": "automatic_tool_call",
                    "responses_made": 1,
                    "automatic_tool_call_passed": False,
                    "stateless_continuation_passed": False,
                },
            )
        else:
            continuation_ack = _random_marker("AUTO_ACK")
            auto_continuation_input = [
                *deepcopy(auto_tool_input),
                *deepcopy(auto_echo_response["value"]["output"]),
                {
                    "type": "function_call_output",
                    "call_id": auto_echo_call["call_id"],
                    "output": json.dumps(
                        {"ack": continuation_ack},
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                },
            ]
            auto_continuation_payload = _base_payload(
                profile_id=target_id,
                model=selected_model,
                input_items=auto_continuation_input,
                max_output_tokens=max_output_tokens,
                reasoning_effort=reasoning_effort,
                promote_gpt_oss_system=True,
                openrouter_policy=openrouter_policy,
            )
            auto_continuation_payload.update(
                tools=[_finish_tool()],
                tool_choice="auto",
                store=False,
            )
            if openrouter_policy is None:
                auto_continuation_payload["parallel_tool_calls"] = False
            auto_continuation_response: dict[str, Any] | None = None
            try:
                result["requests_made"] += 1
                auto_continuation_response = _request_json(
                    endpoint,
                    api_key=str(api_key),
                    payload=auto_continuation_payload,
                    timeout_seconds=timeout_seconds,
                    opener=selected_opener,
                    request_headers=request_headers,
                    require_openrouter_metadata=openrouter_policy is not None,
                )
                _validate_function_call(
                    auto_continuation_response["value"],
                    expected_name="conformance_finish",
                    expected_arguments={"ack": continuation_ack},
                )
                _record_combined_success(
                    result,
                    NATIVE_AUTO_TOOL_CHECK,
                    (auto_echo_response, auto_continuation_response),
                )
                result["checks"][NATIVE_AUTO_TOOL_CHECK].update(
                    {
                        "automatic_tool_choice": True,
                        "responses_made": 2,
                        "echo_tool_name": "conformance_echo",
                        "finish_tool_name": "conformance_finish",
                        "call_id_linked": True,
                        "arguments_valid": True,
                        "acknowledgement_matched": True,
                    }
                )
                result["capabilities"]["native_function_calls"] = True
                result["capabilities"][
                    "stateless_function_continuation"
                ] = True
                result["capabilities"][
                    "automatic_native_function_calls"
                ] = True
                result["capabilities"][
                    "stateless_automatic_function_continuation"
                ] = True
            except _ProbeFailure as exc:
                if auto_continuation_response is not None:
                    _attach_response_diagnostics(
                        exc,
                        auto_continuation_response,
                        include_output_text_preview=True,
                    )
                _record_check_failure(
                    result,
                    NATIVE_AUTO_TOOL_CHECK,
                    exc,
                    prior_responses=(auto_echo_response,),
                    details={
                        "failed_phase": "stateless_continuation",
                        "responses_made": 2,
                        "automatic_tool_call_passed": True,
                        "stateless_continuation_passed": False,
                    },
                )

    if NATIVE_PARALLEL_TOOL_CHECK in selected_set:
        first_marker = _random_marker("PARALLEL_ALPHA")
        second_marker = _random_marker("PARALLEL_BETA")
        parallel_tools = [
            _parallel_marker_tool("conformance_parallel_alpha", first_marker),
            _parallel_marker_tool("conformance_parallel_beta", second_marker),
        ]
        parallel_payload = _base_payload(
            profile_id=target_id,
            model=selected_model,
            input_items=[
                {
                    "role": "system",
                    "content": (
                        "This is a parallel native-function conformance probe. "
                        "Respond only by calling both available functions "
                        "exactly once in the same response. The calls are "
                        "independent and may be emitted together."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Call conformance_parallel_alpha and "
                        "conformance_parallel_beta now, using each function's "
                        "required marker."
                    ),
                },
            ],
            max_output_tokens=max_output_tokens,
            reasoning_effort=reasoning_effort,
            promote_gpt_oss_system=True,
            openrouter_policy=openrouter_policy,
        )
        parallel_payload.update(
            tools=parallel_tools,
            tool_choice="auto",
            store=False,
        )
        if openrouter_policy is None:
            parallel_payload["parallel_tool_calls"] = True
        parallel_response: dict[str, Any] | None = None
        try:
            result["requests_made"] += 1
            parallel_response = _request_json(
                endpoint,
                api_key=str(api_key),
                payload=parallel_payload,
                timeout_seconds=timeout_seconds,
                opener=selected_opener,
                request_headers=request_headers,
                require_openrouter_metadata=openrouter_policy is not None,
            )
            _validate_parallel_function_calls(
                parallel_response["value"],
                expected_markers={
                    "conformance_parallel_alpha": first_marker,
                    "conformance_parallel_beta": second_marker,
                },
            )
            _record_success(
                result,
                NATIVE_PARALLEL_TOOL_CHECK,
                parallel_response,
            )
            result["checks"][NATIVE_PARALLEL_TOOL_CHECK].update(
                {
                    "automatic_tool_choice": True,
                    "responses_made": 1,
                    "function_call_count": 2,
                    "tool_names": [
                        "conformance_parallel_alpha",
                        "conformance_parallel_beta",
                    ],
                    "call_ids_present": True,
                    "call_ids_unique": True,
                    "arguments_valid": True,
                }
            )
            result["capabilities"]["native_function_calls"] = True
            result["capabilities"]["parallel_native_function_calls"] = True
        except _ProbeFailure as exc:
            if parallel_response is not None:
                _attach_response_diagnostics(exc, parallel_response)
            _record_check_failure(
                result,
                NATIVE_PARALLEL_TOOL_CHECK,
                exc,
                details={"responses_made": 1},
            )

    if STRUCTURED_ACTION_CHECK in selected_set:
        if structured_configuration_failure is not None:
            _record_check_failure(
                result,
                STRUCTURED_ACTION_CHECK,
                structured_configuration_failure,
            )
        else:
            marker = _random_marker("STRUCTURED_ACTION")
            structured_payload = _structured_action_payload(
                profile_id=target_id,
                structured_output_dialect=structured_output_dialect,
                model=selected_model,
                marker=marker,
                max_output_tokens=max_output_tokens,
                reasoning_effort=reasoning_effort,
                output_contract=output_contract,
                openrouter_policy=openrouter_policy,
            )
            structured_response: dict[str, Any] | None = None
            try:
                result["requests_made"] += 1
                structured_response = _request_json(
                    endpoint,
                    api_key=str(api_key),
                    payload=structured_payload,
                    timeout_seconds=timeout_seconds,
                    opener=selected_opener,
                    request_headers=request_headers,
                    require_openrouter_metadata=openrouter_policy is not None,
                )
                structured_validation = _validate_structured_action_response(
                    structured_response["value"],
                    marker=marker,
                    output_contract=output_contract,
                )
                _record_success(
                    result,
                    STRUCTURED_ACTION_CHECK,
                    structured_response,
                )
                result["checks"][STRUCTURED_ACTION_CHECK].update(
                    structured_validation
                )
                result["capabilities"]["structured_action_responses"] = True
            except _ProbeFailure as exc:
                if structured_response is not None:
                    _attach_response_diagnostics(exc, structured_response)
                _record_check_failure(result, STRUCTURED_ACTION_CHECK, exc)

    return _finish_checks(result, full_selection=full_selection)


def run_doctor(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Compatibility alias for orchestration code."""

    return run_responses_doctor(*args, **kwargs)


def _normalize_checks(checks: Iterable[str] | None) -> tuple[str, ...]:
    if checks is None:
        return CHECK_NAMES
    requested = [checks] if isinstance(checks, str) else list(checks)
    if not requested:
        raise _ProbeFailure(
            "config.checks_missing",
            "At least one conformance check must be selected.",
        )
    if any(
        not isinstance(name, str) or name not in AVAILABLE_CHECK_NAMES
        for name in requested
    ):
        raise _ProbeFailure(
            "config.checks_invalid",
            "The conformance check selection contains an unsupported name.",
        )
    selected = tuple(
        name for name in AVAILABLE_CHECK_NAMES if name in set(requested)
    )
    if (
        "function_call_output_continuation" in selected
        and "forced_function_call" not in selected
    ):
        raise _ProbeFailure(
            "config.check_dependency_missing",
            "The continuation check requires the forced function-call check.",
        )
    return selected


def _profile_value(profile: Any, name: str, default: Any) -> Any:
    if isinstance(profile, Mapping):
        return profile.get(name, default)
    return getattr(profile, name, default)


def _doctor_openrouter_policy(
    *,
    target_id: str,
    model: str,
    reasoning_effort: str | None,
    enabled: bool,
) -> OpenRouterPolicy | None:
    if not enabled:
        return None
    if target_id != "openrouter":
        raise _ProbeFailure(
            "config.profile_invalid",
            "OpenRouter request policy is enabled only for the openrouter profile.",
        )
    try:
        treatment = get_openrouter_treatment(model)
    except ProviderProfileError:
        raise _ProbeFailure(
            "config.model_unsupported",
            "The OpenRouter model is not in the approved treatment registry.",
        ) from None
    if reasoning_effort != treatment.reasoning_effort:
        raise _ProbeFailure(
            "config.reasoning_effort_mismatch",
            "The reasoning effort does not match the approved OpenRouter treatment.",
        )
    return treatment.policy


def _validated_request_headers(value: Any) -> tuple[tuple[str, str], ...]:
    if isinstance(value, Mapping):
        items = tuple(value.items())
    elif isinstance(value, tuple):
        items = value
    else:
        raise _ProbeFailure(
            "config.request_headers_invalid",
            "Provider request headers are invalid.",
        )
    output: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, tuple) or len(raw) != 2:
            raise _ProbeFailure(
                "config.request_headers_invalid",
                "Provider request headers are invalid.",
            )
        name = str(raw[0]).strip()
        value = str(raw[1]).strip()
        normalized = name.casefold()
        if (
            not name
            or not value
            or normalized in {"authorization", "content-type"}
            or normalized in seen
            or "\r" in name
            or "\n" in name
            or "\r" in value
            or "\n" in value
        ):
            raise _ProbeFailure(
                "config.request_headers_invalid",
                "Provider request headers are invalid.",
            )
        seen.add(normalized)
        output.append((name, value))
    return tuple(output)


def _validate_openrouter_profile_capabilities(
    *,
    structured_output_dialect: str,
    request_headers: tuple[tuple[str, str], ...],
) -> None:
    headers = {
        name.casefold(): value.casefold()
        for name, value in request_headers
    }
    if (
        structured_output_dialect != RESPONSES_TEXT_FORMAT
        or headers.get("x-openrouter-metadata") != "enabled"
        or headers.get("x-openrouter-cache") != "false"
    ):
        raise _ProbeFailure(
            "config.profile_invalid",
            "The OpenRouter profile must use standard Responses output, request "
            "router metadata, and explicitly bypass the response cache.",
        )


def _validate_configuration(
    *,
    responses_url: str,
    allow_insecure_http: bool,
    api_key: str | None,
    model: str,
    timeout_seconds: float,
    max_output_tokens: int,
) -> str:
    if not isinstance(api_key, str) or not api_key.strip():
        raise _ProbeFailure(
            "credential.missing",
            "The configured API credential is missing.",
        )
    if not model:
        raise _ProbeFailure(
            "config.model_missing",
            "A non-empty model identifier is required.",
        )
    if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise _ProbeFailure(
            "config.timeout_invalid",
            "The request timeout must be positive.",
        )
    if (
        isinstance(max_output_tokens, bool)
        or not isinstance(max_output_tokens, int)
        or max_output_tokens <= 0
    ):
        raise _ProbeFailure(
            "config.max_output_tokens_invalid",
            "The maximum output token count must be a positive integer.",
        )
    try:
        parsed = parse.urlsplit(responses_url)
    except ValueError:
        raise _ProbeFailure(
            "config.endpoint_invalid",
            "The Responses endpoint URL is invalid.",
        ) from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not parsed.path
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise _ProbeFailure(
            "config.endpoint_invalid",
            "The Responses endpoint URL is invalid.",
        )
    if parsed.scheme == "http" and not allow_insecure_http:
        raise _ProbeFailure(
            "config.insecure_http_forbidden",
            "Plain HTTP is disabled for this provider profile.",
        )
    return parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, "", "")
    )


def _base_payload(
    *,
    profile_id: str,
    model: str,
    input_items: list[dict[str, Any]],
    max_output_tokens: int,
    reasoning_effort: str | None,
    promote_gpt_oss_system: bool,
    openrouter_policy: OpenRouterPolicy | None = None,
) -> dict[str, Any]:
    converted_input = deepcopy(input_items)
    payload: dict[str, Any] = {
        "model": model,
        "input": converted_input,
        "max_output_tokens": max_output_tokens,
    }
    if (
        promote_gpt_oss_system
        and profile_id == "ida"
        and is_gpt_oss_model(model)
        and converted_input
        and converted_input[0].get("role") == "system"
        and isinstance(converted_input[0].get("content"), str)
    ):
        # Harmony reserves system content for model identity. vLLM renders
        # top-level Responses instructions as the developer message where an
        # ordinary conformance instruction belongs.
        payload["instructions"] = converted_input.pop(0)["content"]
    if reasoning_effort:
        payload["reasoning"] = {"effort": reasoning_effort}
    if profile_id == "openai":
        # Match the benchmark adapter's stateless Responses contract. OpenAI
        # returns replayable reasoning items only when encrypted content is
        # requested explicitly.
        payload["store"] = False
        payload["include"] = ["reasoning.encrypted_content"]
    if openrouter_policy is not None:
        payload["store"] = False
        payload.update(openrouter_policy.request_fields())
    return payload


def _validate_output_contract(
    output_contract: str,
    *,
    structured_output_dialect: str,
    model: str,
) -> None:
    if structured_output_dialect not in {
        RESPONSES_TEXT_FORMAT,
        VLLM_STRUCTURED_OUTPUTS,
    }:
        raise _ProbeFailure(
            "config.output_contract_unsupported",
            "The provider structured-output dialect is unsupported.",
        )
    if (
        not isinstance(output_contract, str)
        or output_contract not in ACTION_OUTPUT_CONTRACTS
    ):
        raise _ProbeFailure(
            "config.output_contract_invalid",
            "The structured-action output contract is unsupported.",
        )
    if (
        output_contract
        in {HARMONY_REASONING_ACTION_JSON, REASONING_THEN_ACTION_JSON}
        and structured_output_dialect != VLLM_STRUCTURED_OUTPUTS
    ):
        raise _ProbeFailure(
            "config.output_contract_unsupported",
            "The selected reasoning output contract requires the vLLM "
            "structured-output extension.",
        )
    if (
        output_contract == HARMONY_REASONING_ACTION_JSON
        and not is_gpt_oss_model(model)
    ):
        raise _ProbeFailure(
            "config.output_contract_unsupported",
            "The Harmony reasoning output contract requires a GPT-OSS model.",
        )


def _structured_action_payload(
    *,
    profile_id: str,
    structured_output_dialect: str,
    model: str,
    marker: str,
    max_output_tokens: int,
    reasoning_effort: str | None,
    output_contract: str,
    openrouter_policy: OpenRouterPolicy | None = None,
) -> dict[str, Any]:
    reasoning_prefixed = output_contract == REASONING_THEN_ACTION_JSON
    harmony_carrier = output_contract == HARMONY_REASONING_ACTION_JSON
    system_instruction = (
        "This is a structured-output conformance probe. Continue the model's "
        "native reasoning normally; do not suppress or skip it. The chat "
        "template has already opened the reasoning region. When ready to "
        "answer, emit exactly one </think> boundary and then the required JSON "
        "object. Do not emit an opening <think> tag or any text after the JSON."
        if reasoning_prefixed
        else (
            "This is a structured-output conformance probe. Use the model's "
            "ordinary native Harmony analysis, then submit exactly the marker "
            "object through the synthetic action_output transport function."
            if harmony_carrier
            else
            "This is a structured-output conformance probe. Return only the "
            "JSON object required by the response constraint, with no prose or "
            "Markdown wrapper."
        )
    )
    payload = _base_payload(
        profile_id=profile_id,
        model=model,
        input_items=[
            {"role": "system", "content": system_instruction},
            {
                "role": "user",
                "content": "Produce the marker object required by the constraint.",
            },
        ],
        max_output_tokens=max_output_tokens,
        reasoning_effort=reasoning_effort,
        promote_gpt_oss_system=False,
        openrouter_policy=openrouter_policy,
    )
    payload["store"] = False
    if reasoning_prefixed:
        payload["structured_outputs"] = {
            "regex": reasoning_then_json_regex(
                exact_marker_json_regex(marker)
            )
        }
        return payload

    schema = {
        "type": "object",
        "properties": {
            "marker": {"type": "string", "enum": [marker]},
        },
        "required": ["marker"],
        "additionalProperties": False,
    }
    if harmony_carrier:
        tag = harmony_reasoning_json_structural_tag(schema)
        payload.update(
            tools=[
                {
                    "type": "function",
                    "name": HARMONY_ACTION_OUTPUT_TOOL_NAME,
                    "description": (
                        "Submit exactly one structured-output marker object."
                    ),
                    "parameters": deepcopy(schema),
                    "strict": True,
                }
            ],
            tool_choice="auto",
            parallel_tool_calls=False,
            structured_outputs={
                "structural_tag": json.dumps(
                    tag,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            },
        )
        return payload
    if structured_output_dialect == RESPONSES_TEXT_FORMAT:
        payload["text"] = {
            "format": {
                "type": "json_schema",
                "name": "benchrunner_structured_action_probe",
                "schema": schema,
                "strict": True,
            }
        }
    else:
        payload["structured_outputs"] = {"json": schema}
    return payload


def _validate_structured_action_response(
    value: dict[str, Any],
    *,
    marker: str,
    output_contract: str,
) -> dict[str, Any]:
    if value.get("status") != "completed" or value.get("error") is not None:
        raise _ProbeFailure(
            "structured.output_shape_invalid",
            "The structured response did not contain a completed envelope.",
        )
    reasoning_prefixed = output_contract == REASONING_THEN_ACTION_JSON
    harmony_carrier = output_contract == HARMONY_REASONING_ACTION_JSON
    harmony_reasoning_count = 0
    if harmony_carrier:
        rendered, harmony_reasoning_count = (
            _harmony_structured_output_arguments(value)
        )
    else:
        rendered = _structured_output_text(
            value,
            preserve_outer_whitespace=reasoning_prefixed,
        )
    if reasoning_prefixed:
        try:
            rendered = split_reasoning_action(rendered).action
        except ValueError:
            raise _ProbeFailure(
                "structured.reasoning_boundary_invalid",
                "The structured response did not contain exactly one valid "
                "reasoning boundary followed by JSON.",
            ) from None
    try:
        parsed = json.loads(rendered)
    except json.JSONDecodeError:
        raise _ProbeFailure(
            "structured.json_invalid",
            "The structured response was not one complete JSON value.",
        ) from None
    if parsed != {"marker": marker}:
        raise _ProbeFailure(
            "structured.marker_mismatch",
            "The structured response did not match the exact marker object.",
        )
    constraint_type = (
        "structural_tag"
        if harmony_carrier
        else ("regex" if reasoning_prefixed else "json_schema")
    )
    validation: dict[str, Any] = {
        "output_contract": output_contract,
        "constraint_type": constraint_type,
        "marker_matched": True,
        "json_consumed_to_eof": True,
    }
    if reasoning_prefixed:
        validation["reasoning_boundary_valid"] = True
    if harmony_carrier:
        validation.update(
            {
                "carrier_type": "function_call",
                "carrier_name": HARMONY_ACTION_OUTPUT_TOOL_NAME,
                "carrier_count": 1,
                "reasoning_item_count": harmony_reasoning_count,
                "native_reasoning_preserved": True,
            }
        )
    return validation


def _harmony_structured_output_arguments(
    value: dict[str, Any],
) -> tuple[str, int]:
    output = value["output"]
    if (
        not isinstance(output, list)
        or len(output) != 2
        or not all(isinstance(item, dict) for item in output)
        or output[0].get("type") != "reasoning"
        or output[1].get("type") != "function_call"
    ):
        raise _ProbeFailure(
            "structured.harmony_carrier_invalid",
            "The Harmony response did not contain exactly one reasoning item "
            "followed by one action carrier.",
        )
    reasoning_items = 1
    carrier = output[1]
    call_id = carrier.get("call_id")
    arguments = carrier.get("arguments")
    if (
        carrier.get("name") != HARMONY_ACTION_OUTPUT_TOOL_NAME
        or carrier.get("status") not in (None, "completed")
        or not isinstance(call_id, str)
        or not call_id
        or not isinstance(arguments, str)
        or not arguments
    ):
        raise _ProbeFailure(
            "structured.harmony_carrier_invalid",
            "The Harmony response action carrier had an invalid shape.",
        )
    return arguments, reasoning_items


def _structured_output_text(
    value: dict[str, Any],
    *,
    preserve_outer_whitespace: bool = False,
) -> str:
    if _function_calls(value):
        raise _ProbeFailure(
            "structured.unexpected_tool_call",
            "The structured-output probe unexpectedly returned a function call.",
        )
    message_texts: list[str] = []
    refusal = False
    for item in value["output"]:
        if not isinstance(item, dict):
            raise _ProbeFailure(
                "structured.output_shape_invalid",
                "The structured response contained an invalid output item.",
            )
        item_type = item.get("type")
        if item_type not in {"reasoning", "message", "refusal"}:
            raise _ProbeFailure(
                "structured.output_shape_invalid",
                "The structured response used an unexpected output item.",
            )
        if item_type == "refusal":
            refusal = True
        if item_type != "message":
            continue
        if item.get("status") not in (None, "completed"):
            raise _ProbeFailure(
                "structured.output_shape_invalid",
                "The structured response contained an incomplete message.",
            )
        content_parts: list[str] = []
        content_items = item.get("content")
        if not isinstance(content_items, list):
            continue
        for content in content_items:
            if not isinstance(content, dict):
                continue
            if content.get("type") == "refusal":
                refusal = True
            text = content.get("text")
            if isinstance(text, str):
                content_parts.append(text)
        if content_parts:
            message_texts.append("".join(content_parts))
    if refusal:
        raise _ProbeFailure(
            "structured.refusal",
            "The model refused the structured-output conformance probe.",
        )
    if not message_texts:
        raise _ProbeFailure(
            "structured.text_missing",
            "The provider response did not contain structured output text.",
        )
    if len(message_texts) != 1:
        raise _ProbeFailure(
            (
                "structured.reasoning_boundary_invalid"
                if preserve_outer_whitespace
                else "structured.output_shape_invalid"
            ),
            "The structured response must use exactly one nonempty message "
            "item.",
        )
    rendered = "".join(message_texts)
    return rendered


def _echo_tool(nonce: str) -> dict[str, Any]:
    return {
        "type": "function",
        "name": "conformance_echo",
        "description": "Echo the supplied protocol-conformance nonce.",
        "parameters": {
            "type": "object",
            "properties": {
                "nonce": {"type": "string", "enum": [nonce]},
            },
            "required": ["nonce"],
            "additionalProperties": False,
        },
        "strict": False,
    }


def _finish_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "name": "conformance_finish",
        "description": (
            "Finish the protocol-conformance probe using the acknowledgement "
            "returned by conformance_echo."
        ),
        "parameters": {
            "type": "object",
            "properties": {"ack": {"type": "string"}},
            "required": ["ack"],
            "additionalProperties": False,
        },
        "strict": False,
    }


def _parallel_marker_tool(name: str, marker: str) -> dict[str, Any]:
    return {
        "type": "function",
        "name": name,
        "description": "Submit this tool's required conformance marker.",
        "parameters": {
            "type": "object",
            "properties": {
                "marker": {"type": "string", "enum": [marker]},
            },
            "required": ["marker"],
            "additionalProperties": False,
        },
        "strict": True,
    }


def _request_json(
    endpoint: str,
    *,
    api_key: str,
    payload: dict[str, Any],
    timeout_seconds: float,
    opener: Callable[..., Any],
    request_headers: tuple[tuple[str, str], ...] = (),
    require_openrouter_metadata: bool = False,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    headers.update(dict(request_headers))
    call = request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    started = monotonic()
    try:
        with opener(call, timeout=timeout_seconds) as response:
            http_status = int(
                getattr(response, "status", getattr(response, "code", 200))
            )
            if http_status < 200 or http_status >= 300:
                raise _http_failure(http_status)
            try:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            except TypeError:
                raw = response.read()
    except _ProbeFailure:
        raise
    except error.HTTPError as exc:
        failure = _http_failure(int(exc.code))
        try:
            exc.close()
        except (OSError, ValueError):
            # Stream cleanup must not mask the stable, body-free probe result.
            pass
        raise failure from None
    except error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, socket.gaierror):
            failure = _ProbeFailure(
                "transport.dns",
                "The provider hostname could not be resolved.",
            )
        elif isinstance(reason, (TimeoutError, socket.timeout)):
            failure = _ProbeFailure(
                "transport.timeout",
                "The provider request timed out.",
                retryable=True,
            )
        elif isinstance(reason, ssl.SSLError):
            failure = _ProbeFailure(
                "transport.tls",
                "The provider TLS handshake failed.",
            )
        else:
            failure = _ProbeFailure(
                "transport.connect",
                "The provider connection failed.",
                retryable=True,
            )
        raise failure from None
    except (TimeoutError, socket.timeout):
        raise _ProbeFailure(
            "transport.timeout",
            "The provider request timed out.",
            retryable=True,
        ) from None
    except ssl.SSLError:
        raise _ProbeFailure(
            "transport.tls",
            "The provider TLS handshake failed.",
        ) from None
    except Exception:
        raise _ProbeFailure(
            "transport.unexpected",
            "The provider request failed before a valid response was received.",
        ) from None

    latency = monotonic() - started
    if not isinstance(raw, bytes):
        raise _ProbeFailure(
            "response.schema_invalid",
            "The provider response body was not bytes.",
        )
    if len(raw) > MAX_RESPONSE_BYTES:
        raise _ProbeFailure(
            "response.too_large",
            "The provider response exceeded the diagnostic size limit.",
        )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _ProbeFailure(
            "response.not_json",
            "The provider did not return a valid UTF-8 JSON response.",
        ) from None
    try:
        _validate_response_envelope(value)
    except _ProbeFailure as exc:
        if isinstance(value, dict):
            _attach_parsed_response_failure(
                exc,
                value,
                http_status=http_status,
                latency_seconds=latency,
            )
        raise
    try:
        usage = _normalize_usage(value.get("usage"))
    except _ProbeFailure as exc:
        _attach_parsed_response_failure(
            exc,
            value,
            http_status=http_status,
            latency_seconds=latency,
            include_usage=False,
        )
        raise
    if require_openrouter_metadata:
        try:
            routing_metadata = _validated_openrouter_metadata(
                value,
                request_payload=payload,
            )
        except _ProbeFailure as exc:
            _attach_parsed_response_failure(
                exc,
                value,
                http_status=http_status,
                latency_seconds=latency,
            )
            raise
    else:
        routing_metadata = sanitize_openrouter_metadata(
            value.get("openrouter_metadata")
        )
    return {
        "value": value,
        "http_status": http_status,
        "latency_seconds": latency,
        "response_id_present": isinstance(value.get("id"), str)
        and bool(value.get("id")),
        "usage": usage,
        "response_diagnostic": _safe_completed_response_diagnostic(
            value,
            payload=payload,
            api_key=api_key,
        ),
        **(
            {"openrouter_metadata": routing_metadata}
            if routing_metadata is not None
            else {}
        ),
    }


def _validated_openrouter_metadata(
    value: dict[str, Any],
    *,
    request_payload: dict[str, Any],
) -> dict[str, Any]:
    provider_policy = request_payload.get("provider")
    only = (
        provider_policy.get("only")
        if isinstance(provider_policy, dict)
        else None
    )
    expected_model = request_payload.get("model")
    if (
        not isinstance(only, list)
        or len(only) != 1
        or not isinstance(only[0], str)
        or not isinstance(expected_model, str)
    ):
        raise _ProbeFailure(
            "config.openrouter_policy_invalid",
            "The OpenRouter probe did not carry one exact provider and model.",
        )
    try:
        return validate_openrouter_metadata(
            value.get("openrouter_metadata"),
            expected_model=expected_model,
            expected_provider=only[0],
        )
    except OpenRouterMetadataError as exc:
        raise _ProbeFailure(exc.code, str(exc)) from None


def _attach_parsed_response_failure(
    failure: _ProbeFailure,
    value: dict[str, Any],
    *,
    http_status: int,
    latency_seconds: float,
    include_usage: bool = True,
) -> None:
    failure.http_status = http_status
    failure.latency_seconds = latency_seconds
    failure.response_id_present = isinstance(value.get("id"), str) and bool(
        value.get("id")
    )
    failure.response_shape = _safe_response_shape(value)
    if include_usage and value.get("usage") is not None:
        try:
            failure.usage = _normalize_usage(value.get("usage"))
        except _ProbeFailure:
            # Preserve the primary error and never copy malformed provider
            # usage data into the diagnostic.
            pass


def _http_failure(status: int) -> _ProbeFailure:
    if status == 401:
        return _ProbeFailure(
            "http.unauthorized",
            "The provider rejected the API credential.",
            http_status=status,
        )
    if status == 403:
        return _ProbeFailure(
            "http.forbidden",
            "The provider denied access to the requested resource.",
            http_status=status,
        )
    if status == 404:
        return _ProbeFailure(
            "http.endpoint_not_found",
            "The configured Responses endpoint was not found.",
            http_status=status,
        )
    if status == 429:
        return _ProbeFailure(
            "http.rate_limited",
            "The provider rate-limited the conformance request.",
            retryable=True,
            http_status=status,
        )
    if status == 501:
        return _ProbeFailure(
            "http.not_implemented",
            "The provider does not implement the requested Responses feature.",
            http_status=status,
        )
    if status >= 500:
        return _ProbeFailure(
            "http.server_error",
            "The provider returned a server error.",
            retryable=True,
            http_status=status,
        )
    return _ProbeFailure(
        "http.request_rejected",
        "The provider rejected the conformance request.",
        http_status=status,
    )


def _validate_response_envelope(value: Any) -> None:
    if not isinstance(value, dict) or not isinstance(value.get("output"), list):
        raise _ProbeFailure(
            "response.schema_invalid",
            "The provider response did not contain an output array.",
        )
    if value.get("error"):
        raise _ProbeFailure(
            "response.error_status",
            "The provider returned a Responses error object.",
        )
    status = value.get("status")
    if status == "incomplete":
        raise _ProbeFailure(
            "response.incomplete",
            "The provider response was incomplete.",
            incomplete_reason=_safe_incomplete_reason(
                value.get("incomplete_details")
            ),
        )
    if status not in {None, "completed"}:
        raise _ProbeFailure(
            "response.error_status",
            "The provider response did not complete successfully.",
        )


def _safe_incomplete_reason(value: Any) -> str | None:
    if not isinstance(value, dict) or value.get("reason") is None:
        return None
    reason = value.get("reason")
    if isinstance(reason, str) and reason in SAFE_INCOMPLETE_REASONS:
        return reason
    return "unknown"


def _validate_text_response(value: dict[str, Any]) -> dict[str, bool]:
    calls = _function_calls(value)
    if calls:
        raise _ProbeFailure(
            "text.unexpected_tool_call",
            "The plain-text probe unexpectedly returned a function call.",
        )
    text_parts: list[str] = []
    refusal = False
    for item in value["output"]:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "refusal":
            refusal = True
        if item.get("type") != "message":
            continue
        if item.get("status") not in (None, "completed"):
            raise _ProbeFailure(
                "text.message_incomplete",
                "The provider response contained an incomplete text message.",
            )
        content_items = item.get("content")
        if not isinstance(content_items, list):
            continue
        for content in content_items:
            if not isinstance(content, dict):
                continue
            if content.get("type") == "refusal":
                refusal = True
            if content.get("type") != "output_text":
                continue
            text = content.get("text")
            if isinstance(text, str):
                text_parts.append(text)
    if refusal:
        raise _ProbeFailure(
            "text.refusal",
            "The model refused the plain-text conformance probe.",
        )
    if not text_parts:
        raise _ProbeFailure(
            "text.missing",
            "The provider response did not contain output text.",
        )
    rendered = "".join(text_parts).strip()
    if not rendered:
        raise _ProbeFailure(
            "text.empty",
            "The provider response contained no nonempty output text.",
        )
    return {
        "output_text_present": True,
        "nonempty_output_text": True,
    }


def _validate_function_call(
    value: dict[str, Any],
    *,
    expected_name: str,
    expected_arguments: dict[str, str],
) -> dict[str, str]:
    calls = _function_calls(value)
    if not calls:
        raise _ProbeFailure(
            "tool.call_missing",
            "The native function call was missing.",
        )
    if len(calls) != 1:
        raise _ProbeFailure(
            "tool.multiple_calls",
            "The function-call probe returned more than one function call.",
        )
    call = calls[0]
    if call.get("name") != expected_name:
        raise _ProbeFailure(
            "tool.wrong_name",
            "The provider returned the wrong function name.",
        )
    call_id = call.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        raise _ProbeFailure(
            "tool.call_id_missing",
            "The native function call did not contain a call_id.",
        )
    raw_arguments = call.get("arguments")
    try:
        arguments = (
            json.loads(raw_arguments)
            if isinstance(raw_arguments, str)
            else raw_arguments
        )
    except json.JSONDecodeError:
        raise _ProbeFailure(
            "tool.arguments_not_json",
            "The native function arguments were not valid JSON.",
        ) from None
    if not isinstance(arguments, dict):
        raise _ProbeFailure(
            "tool.arguments_schema_invalid",
            "The native function arguments were not an object.",
        )
    if arguments != expected_arguments:
        code = (
            "continuation.ack_mismatch"
            if expected_name == "conformance_finish"
            else "tool.nonce_mismatch"
        )
        message = (
            "The continuation did not use the acknowledgement from the tool output."
            if expected_name == "conformance_finish"
            else "The function arguments did not preserve the probe nonce."
        )
        raise _ProbeFailure(code, message)
    return {"name": expected_name, "call_id": call_id}


def _validate_parallel_function_calls(
    value: dict[str, Any],
    *,
    expected_markers: Mapping[str, str],
) -> None:
    calls = _function_calls(value)
    if len(calls) != len(expected_markers):
        raise _ProbeFailure(
            "tool.parallel_call_count_invalid",
            "The parallel function-call probe did not return exactly two calls.",
        )

    seen_names: set[str] = set()
    seen_call_ids: set[str] = set()
    for call in calls:
        if call.get("status") not in (None, "completed"):
            raise _ProbeFailure(
                "tool.call_incomplete",
                "A parallel native function call was incomplete.",
            )
        name = call.get("name")
        if not isinstance(name, str) or name not in expected_markers:
            raise _ProbeFailure(
                "tool.parallel_name_invalid",
                "The parallel function-call probe returned an unexpected function.",
            )
        if name in seen_names:
            raise _ProbeFailure(
                "tool.parallel_name_duplicate",
                "The parallel function-call probe repeated a function.",
            )
        seen_names.add(name)

        call_id = call.get("call_id")
        if not isinstance(call_id, str) or not call_id:
            raise _ProbeFailure(
                "tool.call_id_missing",
                "A parallel native function call did not contain a call_id.",
            )
        if call_id in seen_call_ids:
            raise _ProbeFailure(
                "tool.parallel_call_id_duplicate",
                "The parallel native function calls reused a call_id.",
            )
        seen_call_ids.add(call_id)

        raw_arguments = call.get("arguments")
        try:
            arguments = (
                json.loads(raw_arguments)
                if isinstance(raw_arguments, str)
                else raw_arguments
            )
        except json.JSONDecodeError:
            raise _ProbeFailure(
                "tool.arguments_not_json",
                "Parallel native function arguments were not valid JSON.",
            ) from None
        if not isinstance(arguments, dict):
            raise _ProbeFailure(
                "tool.arguments_schema_invalid",
                "Parallel native function arguments were not an object.",
            )
        if arguments != {"marker": expected_markers[name]}:
            raise _ProbeFailure(
                "tool.marker_mismatch",
                "Parallel native function arguments did not preserve the marker.",
            )

    if seen_names != set(expected_markers):
        raise _ProbeFailure(
            "tool.parallel_name_invalid",
            "The parallel function-call probe did not call both functions.",
        )


def _function_calls(value: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in value.get("output") or []
        if isinstance(item, dict) and item.get("type") == "function_call"
    ]


def _normalize_usage(value: Any) -> dict[str, int]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise _ProbeFailure(
            "usage.invalid",
            "The provider usage object was invalid.",
        )
    output_details = value.get("output_tokens_details") or {}
    input_details = value.get("input_tokens_details") or {}
    if not isinstance(output_details, dict) or not isinstance(input_details, dict):
        raise _ProbeFailure(
            "usage.invalid",
            "The provider usage details were invalid.",
        )
    normalized = {
        "input_tokens": value.get("input_tokens", 0),
        "output_tokens": value.get("output_tokens", 0),
        "reasoning_tokens": output_details.get("reasoning_tokens", 0),
        "cached_input_tokens": input_details.get("cached_tokens", 0),
    }
    if any(
        isinstance(item, bool) or not isinstance(item, int) or item < 0
        for item in normalized.values()
    ):
        raise _ProbeFailure(
            "usage.invalid",
            "The provider usage counters were invalid.",
        )
    return normalized


def _record_success(
    result: dict[str, Any],
    check_name: str,
    response: dict[str, Any],
) -> None:
    usage = response["usage"]
    result["checks"][check_name] = {
        "status": "passed",
        "http_status": response["http_status"],
        "latency_seconds": response["latency_seconds"],
        "response_id_present": response["response_id_present"],
        "usage": usage,
    }
    if isinstance(response.get("openrouter_metadata"), dict):
        result["checks"][check_name]["openrouter_metadata"] = deepcopy(
            response["openrouter_metadata"]
        )
    result["aggregate_latency_seconds"] += response["latency_seconds"]
    for field in USAGE_FIELDS:
        result["aggregate_usage"][field] += int(usage.get(field) or 0)


def _record_combined_success(
    result: dict[str, Any],
    check_name: str,
    responses: tuple[dict[str, Any], ...],
) -> None:
    usage = {
        field: sum(
            int(response["usage"].get(field) or 0)
            for response in responses
        )
        for field in USAGE_FIELDS
    }
    latency_seconds = sum(
        float(response["latency_seconds"]) for response in responses
    )
    result["checks"][check_name] = {
        "status": "passed",
        "http_status": responses[-1]["http_status"],
        "latency_seconds": latency_seconds,
        "response_id_present": all(
            bool(response["response_id_present"]) for response in responses
        ),
        "usage": usage,
    }
    routing_metadata = [
        deepcopy(response["openrouter_metadata"])
        for response in responses
        if isinstance(response.get("openrouter_metadata"), dict)
    ]
    if routing_metadata:
        result["checks"][check_name]["openrouter_metadata"] = routing_metadata
    for response in responses:
        _record_response_accounting(result, response)


def _record_response_accounting(
    result: dict[str, Any],
    response: dict[str, Any],
) -> None:
    result["aggregate_latency_seconds"] += float(response["latency_seconds"])
    for field in USAGE_FIELDS:
        result["aggregate_usage"][field] += int(
            response["usage"].get(field) or 0
        )


def _attach_response_diagnostics(
    failure: _ProbeFailure,
    response: dict[str, Any],
    *,
    include_output_text_preview: bool = False,
) -> None:
    failure.http_status = int(response["http_status"])
    failure.latency_seconds = float(response["latency_seconds"])
    failure.response_id_present = bool(response["response_id_present"])
    failure.usage = dict(response["usage"])
    diagnostic = response.get("response_diagnostic")
    if isinstance(diagnostic, dict):
        shape = diagnostic.get("response_shape")
        if isinstance(shape, dict):
            failure.response_shape = dict(shape)
        preview = diagnostic.get("output_text_preview")
        if include_output_text_preview and isinstance(preview, str):
            failure.output_text_preview = preview
            failure.output_text_preview_truncated = bool(
                diagnostic.get("output_text_preview_truncated")
            )
    if failure.response_shape is None:
        failure.response_shape = _safe_response_shape(response["value"])


def _safe_response_shape(value: dict[str, Any]) -> dict[str, int]:
    """Summarize a response without retaining provider-controlled content."""

    shape = {
        "output_items": 0,
        "message_items": 0,
        "reasoning_items": 0,
        "function_call_items": 0,
        "refusal_items": 0,
        "unknown_items": 0,
        "content_items": 0,
        "output_text_fields": 0,
        "nonempty_output_text_fields": 0,
        "unknown_content_items": 0,
    }
    output = value.get("output")
    if not isinstance(output, list):
        return shape
    shape["output_items"] = len(output)
    for item in output:
        if not isinstance(item, dict):
            shape["unknown_items"] += 1
            continue
        item_type = item.get("type")
        counter = {
            "message": "message_items",
            "reasoning": "reasoning_items",
            "function_call": "function_call_items",
            "refusal": "refusal_items",
        }.get(item_type, "unknown_items")
        shape[counter] += 1
        content = item.get("content")
        if not isinstance(content, list):
            continue
        shape["content_items"] += len(content)
        for part in content:
            if not isinstance(part, dict):
                shape["unknown_content_items"] += 1
                continue
            part_type = part.get("type")
            if part_type not in {"output_text", "refusal"}:
                shape["unknown_content_items"] += 1
            text = part.get("text")
            if part_type == "output_text" and isinstance(text, str):
                shape["output_text_fields"] += 1
                if text.strip():
                    shape["nonempty_output_text_fields"] += 1
            if part_type == "refusal":
                shape["refusal_items"] += 1
    return shape


def _safe_completed_response_diagnostic(
    value: dict[str, Any],
    *,
    payload: dict[str, Any],
    api_key: str,
) -> dict[str, Any]:
    diagnostic: dict[str, Any] = {
        "response_shape": _safe_response_shape(value)
    }
    if value.get("status") not in {None, "completed"}:
        return diagnostic

    text_parts: list[str] = []
    for item in value.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if (
                isinstance(part, dict)
                and part.get("type") == "output_text"
                and isinstance(part.get("text"), str)
            ):
                text_parts.append(part["text"])
    rendered = _normalize_preview_text("".join(text_parts))
    if not rendered:
        return diagnostic

    for sensitive in sorted(
        _probe_sensitive_strings(
            payload,
            api_key=api_key,
            response_value=value,
        ),
        key=len,
        reverse=True,
    ):
        normalized = _normalize_preview_text(sensitive)
        if normalized:
            rendered = rendered.replace(normalized, "[redacted]")
    rendered = GENERATED_MARKER_PATTERN.sub("[redacted]", rendered)
    truncated = len(rendered) > MAX_OUTPUT_TEXT_PREVIEW_CHARS
    diagnostic["output_text_preview"] = rendered[
        :MAX_OUTPUT_TEXT_PREVIEW_CHARS
    ].rstrip()
    diagnostic["output_text_preview_truncated"] = truncated
    return diagnostic


def _normalize_preview_text(value: str) -> str:
    return " ".join(value.split())


def _probe_sensitive_strings(
    payload: dict[str, Any],
    *,
    api_key: str,
    response_value: dict[str, Any],
) -> set[str]:
    values = {api_key}
    instructions = payload.get("instructions")
    if isinstance(instructions, str):
        values.add(instructions)

    for item in payload.get("input") or []:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if isinstance(content, str):
            values.add(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and isinstance(
                    part.get("text"), str
                ):
                    values.add(part["text"])
        if item.get("type") == "function_call":
            _collect_sensitive_argument_values(item.get("arguments"), values)
        if item.get("type") == "function_call_output":
            _collect_sensitive_argument_values(item.get("output"), values)

    for item in response_value.get("output") or []:
        if isinstance(item, dict) and item.get("type") == "function_call":
            _collect_sensitive_argument_values(item.get("arguments"), values)

    def collect_constraints(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if key == "const" and isinstance(child, str):
                    values.add(child)
                elif key == "enum" and isinstance(child, list):
                    values.update(
                        member for member in child if isinstance(member, str)
                    )
                elif key == "description" and isinstance(child, str):
                    values.add(child)
                collect_constraints(child)
        elif isinstance(node, list):
            for child in node:
                collect_constraints(child)

    collect_constraints(payload.get("tools"))
    collect_constraints(payload.get("structured_outputs"))
    return {value for value in values if isinstance(value, str) and value}


def _collect_sensitive_argument_values(value: Any, values: set[str]) -> None:
    if isinstance(value, str):
        values.add(value)
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return
        _collect_sensitive_argument_values(parsed, values)
    elif isinstance(value, dict):
        for child in value.values():
            _collect_sensitive_argument_values(child, values)
    elif isinstance(value, list):
        for child in value:
            _collect_sensitive_argument_values(child, values)


def _record_check_failure(
    result: dict[str, Any],
    check_name: str,
    failure: _ProbeFailure,
    *,
    prior_responses: tuple[dict[str, Any], ...] = (),
    details: Mapping[str, Any] | None = None,
) -> None:
    diagnostic = failure.diagnostic()
    check_result: dict[str, Any] = {
        "status": "failed",
        "failure": diagnostic,
    }
    latency_seconds = sum(
        float(response["latency_seconds"]) for response in prior_responses
    )
    if failure.latency_seconds is not None:
        latency_seconds += failure.latency_seconds
    if prior_responses or failure.latency_seconds is not None:
        check_result["latency_seconds"] = latency_seconds

    response_ids = [
        bool(response["response_id_present"]) for response in prior_responses
    ]
    if prior_responses:
        response_ids.append(failure.response_id_present is True)
    elif failure.response_id_present is not None:
        response_ids.append(failure.response_id_present)
    if response_ids:
        check_result["response_id_present"] = all(response_ids)

    usage = {field: 0 for field in USAGE_FIELDS}
    has_usage = False
    for response in prior_responses:
        has_usage = True
        for field in USAGE_FIELDS:
            usage[field] += int(response["usage"].get(field) or 0)
    if failure.usage is not None:
        has_usage = True
        for field in USAGE_FIELDS:
            usage[field] += int(failure.usage.get(field) or 0)
    if has_usage:
        check_result["usage"] = usage

    if details is not None:
        check_result.update(details)
    result["checks"][check_name] = check_result
    for response in prior_responses:
        _record_response_accounting(result, response)
    if failure.latency_seconds is not None:
        result["aggregate_latency_seconds"] += failure.latency_seconds
    if failure.usage is not None:
        for field in USAGE_FIELDS:
            result["aggregate_usage"][field] += int(
                failure.usage.get(field) or 0
            )
    result["failed_checks"].append(check_name)
    if result["failure"] is None:
        result["failure"] = diagnostic


def _record_dependency_skip(
    result: dict[str, Any],
    check_name: str,
    *,
    dependency: str,
) -> None:
    result["checks"][check_name] = {
        "status": "skipped",
        "reason": "dependency_failed",
        "dependency": dependency,
    }


def _finish_checks(
    result: dict[str, Any],
    *,
    full_selection: bool,
) -> dict[str, Any]:
    failed_checks = result["failed_checks"]
    if failed_checks:
        result["status"] = "failed"
        if full_selection:
            result["check_selection"]["full_conformance_status"] = "failed"
        return result

    result["status"] = "passed"
    if full_selection:
        result["capabilities"]["responses_compatible"] = True
        result["check_selection"]["full_conformance_status"] = "passed"
    return result


def _finish_failure(
    result: dict[str, Any],
    check_name: str | None,
    failure: _ProbeFailure,
) -> dict[str, Any]:
    diagnostic = failure.diagnostic()
    if check_name is not None:
        check_result: dict[str, Any] = {
            "status": "failed",
            "failure": diagnostic,
        }
        if failure.latency_seconds is not None:
            check_result["latency_seconds"] = failure.latency_seconds
            result["aggregate_latency_seconds"] += failure.latency_seconds
        if failure.response_id_present is not None:
            check_result["response_id_present"] = (
                failure.response_id_present
            )
        if failure.usage is not None:
            check_result["usage"] = dict(failure.usage)
            for field in USAGE_FIELDS:
                result["aggregate_usage"][field] += int(
                    failure.usage.get(field) or 0
                )
        result["checks"][check_name] = check_result
    for value in result["checks"].values():
        if value.get("status") == "pending":
            value["status"] = "skipped"
    result["status"] = "failed"
    selection = result.get("check_selection") or {}
    if selection.get("full_conformance_status") == "pending":
        selection["full_conformance_status"] = "failed"
    result["failure"] = diagnostic
    return result


def _random_marker(prefix: str) -> str:
    # Imported lazily so tests can patch the entropy source without widening the
    # public doctor API.
    import secrets

    return f"{prefix}_{secrets.token_hex(16)}"


__all__ = [
    "AVAILABLE_CHECK_NAMES",
    "CHECK_NAMES",
    "NATIVE_AUTO_TOOL_CHECK",
    "NATIVE_PARALLEL_TOOL_CHECK",
    "STRUCTURED_ACTION_CHECK",
    "run_doctor",
    "run_responses_doctor",
]
