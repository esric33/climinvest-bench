from __future__ import annotations

import json
import os
from copy import deepcopy
from time import monotonic
from typing import Any
from urllib import error, request

from ..tool_schemas import openai_chat_tools
from ..final_turn_policy import final_turn_policy_provenance, final_turn_tool_choice
from .base import ProviderToolCall, ProviderTurn, messages_for_current_turn


class OpenAICompatibleProvider:
    """Native chat-completions tool adapter for open-weight serving endpoints."""

    name = "openai_compatible"

    def __init__(
        self,
        *,
        model: str,
        endpoint: str,
        api_key: str | None = None,
        timeout_seconds: float = 180.0,
        max_tokens: int = 8000,
        final_turn_tool_choice_policy: str | None = None,
    ) -> None:
        self.model = model
        self.endpoint = endpoint
        self.api_key = api_key or os.environ.get("OPENAI_COMPATIBLE_API_KEY", "")
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens
        self.final_turn_tool_choice_policy = final_turn_tool_choice_policy
        self.final_turn_tool_choice_provenance = final_turn_policy_provenance(final_turn_tool_choice_policy)

    def complete(self, messages: list[dict[str, str]], *, episode: Any) -> ProviderTurn:
        tools = openai_chat_tools(episode)
        payload = {
            "model": self.model,
            "messages": build_chat_messages(
                messages_for_current_turn(messages, episode),
                episode.turns,
            ),
            "max_tokens": self.max_tokens,
        }
        if tools:
            payload.update(
                tools=tools,
                tool_choice=final_turn_tool_choice(
                    episode, self.final_turn_tool_choice_policy,
                    transport=self.name, ordinary_choice="required",
                ),
                parallel_tool_calls=True,
            )
            if self.final_turn_tool_choice_policy is not None and getattr(episode, "turn_phase", None) == "finalization":
                payload["parallel_tool_calls"] = False
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        call = request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers=headers,
        )
        started = monotonic()
        try:
            with request.urlopen(call, timeout=self.timeout_seconds) as response:
                value = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"OpenAI-compatible HTTP {exc.code}: {detail}"
            ) from exc
        choice = (value.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        tool_calls, text = extract_native_turn(message)
        usage = value.get("usage") or {}
        completion_details = usage.get("completion_tokens_details") or {}
        prompt_details = usage.get("prompt_tokens_details") or {}
        return ProviderTurn(
            text=text,
            tool_calls=tool_calls or None,
            protocol_error=(
                None
                if tool_calls or not tools
                else "OpenAI-compatible response contained no native tool_calls"
            ),
            raw_response=value,
            usage={
                "input_tokens": int(usage.get("prompt_tokens") or 0),
                "output_tokens": int(usage.get("completion_tokens") or 0),
                "reasoning_tokens": int(
                    completion_details.get("reasoning_tokens") or 0
                ),
                "cached_input_tokens": int(
                    prompt_details.get("cached_tokens") or 0
                ),
            },
            latency_seconds=monotonic() - started,
            provider_request_id=value.get("id"),
        )


def extract_native_turn(
    message: dict[str, Any],
) -> tuple[list[ProviderToolCall], str]:
    calls: list[ProviderToolCall] = []
    for item in message.get("tool_calls") or []:
        function = item.get("function") if isinstance(item, dict) else None
        function = function if isinstance(function, dict) else {}
        arguments, argument_error = parse_arguments(function.get("arguments"))
        calls.append(
            ProviderToolCall(
                call_id=str(item.get("id") or ""),
                tool=str(function.get("name") or ""),
                arguments=arguments,
                error=argument_error,
            )
        )
    content = message.get("content")
    return calls, content if isinstance(content, str) else ""


def parse_arguments(value: Any) -> tuple[dict[str, Any] | None, str | None]:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError as exc:
        return None, f"native tool arguments are invalid JSON: {exc.msg}"
    if not isinstance(parsed, dict):
        return None, "native tool arguments must decode to an object"
    return parsed, None


def build_chat_messages(
    messages: list[dict[str, str]],
    turns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = [
        deepcopy(item) for item in messages[:2]
    ]
    for turn in turns:
        raw_response = turn.get("raw_response")
        choice = (
            (raw_response.get("choices") or [{}])[0]
            if isinstance(raw_response, dict)
            else {}
        )
        message = choice.get("message")
        if isinstance(message, dict):
            converted.append(deepcopy(message))
        calls = turn.get("calls") or []
        observations = turn.get("observations") or []
        if calls:
            for index, call in enumerate(calls):
                call_id = call.get("provider_call_id")
                if not call_id:
                    continue
                observation = (
                    observations[index]
                    if index < len(observations)
                    else {
                        "status": "protocol_error",
                        "message": "tool call produced no observation",
                    }
                )
                converted.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": compact_output(observation),
                    }
                )
        elif turn.get("status") == "protocol_error":
            converted.append(
                {
                    "role": "user",
                    "content": (
                        "Protocol error: "
                        + str(turn.get("error") or "call a native tool")
                    ),
                }
            )
    return converted


def compact_output(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
