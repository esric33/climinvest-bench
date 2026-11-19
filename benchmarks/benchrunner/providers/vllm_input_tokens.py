"""Inference-free counting through the pinned server's Responses renderer.

The middleware installs an ordinary FastAPI route, then delegates to the normal
middleware stack (including authentication). It never short-circuits that stack.
The route uses the same _make_request/_make_request_with_harmony and prompt
length helper as create_responses, before sampling or output parsing begins.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import inspect
import json
from typing import Any


SCHEMA_VERSION = "benchrunner.vllm_input_tokens/v1"
# 0.28.0 retains these production rendering hooks and the prompt-length helper.
# Its online_renderer still runs before sampling or engine generation.
SUPPORTED_VERSIONS = frozenset({"0.18.0", "0.22.1", "0.28.0"})
MAX_REQUEST_BYTES = 8 * 1024 * 1024
COUNT_PATH = "/v1/responses/input_tokens"


class CountRequestError(ValueError):
    def __init__(self, code: str, status: int = 400, *, diagnostic: dict[str, str] | None = None):
        self.code, self.status = code, status
        self.diagnostic = diagnostic
        super().__init__(code)


def _safe_exception_diagnostic(stage: str, error: Exception) -> dict[str, str]:
    """Keep type identity only: exception text/arguments may contain input."""
    result = {"stage": stage}
    for key, value in (("exception_class", type(error).__name__),
                       ("exception_module", type(error).__module__)):
        # Bound metadata even if a third-party exception has unusual type names.
        if isinstance(value, str) and len(value) <= 200 and all(part.isidentifier() for part in value.split(".")):
            result[key] = value
    return result


def _validate_payload(payload: Any) -> None:
    if not isinstance(payload, dict) or not isinstance(payload.get("model"), str):
        raise CountRequestError("invalid_count_request")
    if any(payload.get(key) for key in ("store", "stream", "background", "previous_response_id", "previous_input_messages")):
        raise CountRequestError("count_requires_stateless_request")
    if payload.get("truncation", "disabled") != "disabled":
        raise CountRequestError("count_prohibits_input_truncation")
    tools = payload.get("tools", [])
    if not isinstance(tools, list) or any(not isinstance(tool, dict) or tool.get("type") != "function" for tool in tools):
        raise CountRequestError("count_supports_function_tools_only")
    # Our benchmark is text-only. Do not let counting fetch files, images, or
    # other remote content through a multimodal renderer.
    def text_only(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("type") in {"input_image", "input_file", "input_audio", "input_video", "image_url", "file"}:
                raise CountRequestError("count_supports_text_only")
            for item in value.values():
                text_only(item)
        elif isinstance(value, list):
            for item in value:
                text_only(item)
    text_only(payload.get("input"))


async def count_response_input(
    serving: Any, payload: dict[str, Any], *, request_type: Any,
    version: str, payload_sha256: str, renderer_source_sha256: str,
) -> dict[str, Any]:
    """Render the real input with zero engine, sampling, or tool execution."""
    if version.split("+", 1)[0] not in SUPPORTED_VERSIONS:
        raise CountRequestError("unsupported_vllm_count_renderer", 503)
    _validate_payload(payload)
    # Only the output allowance used by renderer length validation changes.
    # Tools, choice, instructions, reasoning, and the complete input stay intact.
    # No tokens are generated: one is the minimum validation allowance, not a
    # generation request or a substitute larger tool-call budget.
    data = deepcopy(payload)
    data["max_output_tokens"] = 1
    try:
        native_request = request_type.model_validate(data)
    except Exception:
        raise CountRequestError("invalid_responses_count_schema") from None
    if await serving._check_model(native_request) is not None:
        raise CountRequestError("count_model_unavailable", 404)
    if serving._validate_create_responses_input(native_request) is not None:
        raise CountRequestError("invalid_responses_count_parameters")
    stage = "responses_make_request"
    try:
        if serving.use_harmony:
            _, prompts = serving._make_request_with_harmony(native_request, None)
        else:
            _, prompts = await serving._make_request(native_request, None)
        if not isinstance(prompts, (list, tuple)) or len(prompts) != 1:
            raise CountRequestError("invalid_count_prompt_batch")
        stage = "extract_prompt_len"
        count = serving._extract_prompt_len(prompts[0])
    except CountRequestError:
        raise
    except Exception as error:
        # Renderer exceptions may embed prompt text. Return a safe code; the
        # client retains bounded diagnostic metadata without scientific input.
        raise CountRequestError("responses_count_render_failed",
            diagnostic=_safe_exception_diagnostic(stage, error)) from None
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise CountRequestError("invalid_rendered_token_count")
    return {
        "object": "response.input_tokens", "input_tokens": count,
        "counting": {
            "schema_version": SCHEMA_VERSION, "method": "vllm_responses_renderer",
            "vllm_version": version, "model": payload["model"],
            "request_payload_sha256": payload_sha256,
            "renderer_source_sha256": renderer_source_sha256,
            "generation_requested": False, "actions_executed": 0,
            "input_payload_altered": False, "input_token_delta": 0,
            "render_only_overrides": {"max_output_tokens": 1},
        },
    }


async def _count_endpoint(request: Any) -> Any:
    from starlette.responses import JSONResponse
    try:
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_REQUEST_BYTES:
                raise CountRequestError("count_request_too_large", 413)
            body.extend(chunk)
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeError):
            raise CountRequestError("invalid_count_json") from None
        from vllm.entrypoints.openai.responses.protocol import ResponsesRequest
        from vllm.version import __version__
        serving = request.app.state.openai_serving_responses
        if serving is None:
            raise CountRequestError("responses_count_renderer_unavailable", 503)
        hook = serving._make_request_with_harmony if serving.use_harmony else serving._make_request
        renderer_digest = sha256(inspect.getsource(hook).encode()).hexdigest()
        result = await count_response_input(
            serving, payload, request_type=ResponsesRequest, version=__version__,
            payload_sha256=sha256(body).hexdigest(), renderer_source_sha256=renderer_digest,
        )
        return JSONResponse(result)
    except CountRequestError as exc:
        error = {"code": exc.code, "type": "input_token_count_error", "message": exc.code}
        if exc.diagnostic is not None:
            error["diagnostic"] = exc.diagnostic
        return JSONResponse({"error": error}, status_code=exc.status)
    except Exception:
        return JSONResponse({"error": {"code": "count_renderer_unavailable", "type": "input_token_count_error", "message": "count_renderer_unavailable"}}, status_code=503)


async def install_count_endpoint(request: Any, call_next: Any) -> Any:
    """vLLM --middleware hook; install before the first normal routed request."""
    if not getattr(request.app.state, "benchrunner_count_endpoint_installed", False):
        from starlette.requests import Request
        _count_endpoint.__annotations__["request"] = Request
        request.app.add_api_route(COUNT_PATH, _count_endpoint, methods=["POST"])
        request.app.state.benchrunner_count_endpoint_installed = True
    return await call_next(request)
