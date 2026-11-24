from __future__ import annotations

import json
import os
from copy import deepcopy
from time import monotonic
from typing import Any
from urllib import error, request

from ..tool_schemas import anthropic_tools
from ..final_turn_policy import final_turn_policy_provenance, final_turn_tool_choice
from .base import ProviderToolCall, ProviderTurn, messages_for_current_turn


class AnthropicMessagesProvider:
    name = "anthropic_messages"

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        endpoint: str = "https://api.anthropic.com/v1/messages",
        timeout_seconds: float = 180.0,
        max_tokens: int = 8000,
        final_turn_tool_choice_policy: str | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens
        self.final_turn_tool_choice_policy = final_turn_tool_choice_policy
        self.final_turn_tool_choice_provenance = final_turn_policy_provenance(final_turn_tool_choice_policy)

    def complete(self, messages: list[dict[str, str]], *, episode: Any) -> ProviderTurn:
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not configured")
        messages = messages_for_current_turn(messages, episode)
        tools = anthropic_tools(episode)
        system = "\n\n".join(
            item["content"] for item in messages if item["role"] == "system"
        )
        converted = build_anthropic_messages(messages, episode.turns)
        payload = {
            "model": self.model,
            "system": system,
            "messages": converted,
            "max_tokens": self.max_tokens,
        }
        if tools:
            payload.update(
                tools=tools,
                tool_choice=final_turn_tool_choice(
                    episode, self.final_turn_tool_choice_policy,
                    transport=self.name, ordinary_choice={"type": "any"},
                ),
            )
            if self.final_turn_tool_choice_policy is not None and getattr(episode, "turn_phase", None) == "finalization":
                payload["tool_choice"]["disable_parallel_tool_use"] = True
        call = request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
        )
        started = monotonic()
        try:
            with request.urlopen(call, timeout=self.timeout_seconds) as response:
                value = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Anthropic HTTP {exc.code}: {detail}") from exc
        tool_calls, text = extract_native_turn(value)
        usage = value.get("usage") or {}
        return ProviderTurn(
            text=text,
            tool_calls=tool_calls or None,
            protocol_error=(
                None
                if tool_calls or not tools
                else "Anthropic response contained no native tool_use blocks"
            ),
            raw_response=value,
            usage={
                "input_tokens": int(usage.get("input_tokens") or 0),
                "output_tokens": int(usage.get("output_tokens") or 0),
                "reasoning_tokens": 0,
                "cached_input_tokens": int(
                    usage.get("cache_read_input_tokens") or 0
                ),
            },
            latency_seconds=monotonic() - started,
            provider_request_id=value.get("id"),
        )


def extract_native_turn(
    value: dict[str, Any],
) -> tuple[list[ProviderToolCall], str]:
    calls: list[ProviderToolCall] = []
    text = "".join(
        str(item.get("text") or "")
        for item in value.get("content") or []
        if isinstance(item, dict) and item.get("type") == "text"
    )
    for item in value.get("content") or []:
        if not isinstance(item, dict) or item.get("type") != "tool_use":
            continue
        arguments = item.get("input")
        calls.append(
            ProviderToolCall(
                call_id=str(item.get("id") or ""),
                tool=str(item.get("name") or ""),
                arguments=arguments if isinstance(arguments, dict) else None,
                error=(
                    None
                    if isinstance(arguments, dict)
                    else "native tool input must be an object"
                ),
            )
        )
    return calls, text


def build_anthropic_messages(
    messages: list[dict[str, str]],
    turns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = [
        {
            "role": (
                "assistant" if item["role"] == "assistant" else "user"
            ),
            "content": item["content"],
        }
        for item in messages[:2]
        if item["role"] != "system"
    ]
    for turn in turns:
        raw_response = turn.get("raw_response")
        content = (
            deepcopy(raw_response.get("content") or [])
            if isinstance(raw_response, dict)
            else []
        )
        if content:
            converted.append({"role": "assistant", "content": content})
        calls = turn.get("calls") or []
        observations = turn.get("observations") or []
        if calls:
            results = []
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
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call_id,
                        "content": compact_output(observation),
                        "is_error": observation_is_error(observation),
                    }
                )
            if results:
                converted.append({"role": "user", "content": results})
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


def observation_is_error(observation: dict[str, Any]) -> bool:
    return observation.get("status") not in {
        "accepted",
        "available",
        "completed",
    }


def compact_output(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
