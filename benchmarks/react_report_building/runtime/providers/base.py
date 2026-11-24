from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Protocol

from ..provider_cost import ProviderCost, normalize_provider_cost


RETRYABLE_HTTP_STATUS_CODES = frozenset(
    {408, 409, 425, 429, 500, 502, 503, 504, 524, 529}
)


class ProviderRequestError(RuntimeError):
    """Sanitized provider failure suitable for retry classification.

    Raw scientific error bodies are not retained. Versioned failure_evidence may
    contain bounded, redacted provider fields and a body hash/size; synthetic
    qualification may additionally retain a sanitized body. Exception messages
    remain stable typed summaries.
    """

    def __init__(
        self,
        message: str,
        *,
        transport: str,
        retryable: bool,
        provider_request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.transport = transport
        self.retryable = retryable
        self.provider_request_id = provider_request_id


class ProviderHTTPError(ProviderRequestError):
    """A non-success HTTP response with optional sanitized failure evidence."""

    def __init__(
        self,
        *,
        transport: str,
        status_code: int,
        provider_request_id: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        retryable = status_code in RETRYABLE_HTTP_STATUS_CODES
        suffix = "retryable" if retryable else "not retryable"
        super().__init__(
            f"{transport} request failed with HTTP {status_code} ({suffix})",
            transport=transport,
            retryable=retryable,
            provider_request_id=provider_request_id,
        )
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


class ProviderConnectionError(ProviderRequestError):
    """A retryable failure before a valid provider response was received."""

    def __init__(self, *, transport: str) -> None:
        super().__init__(
            f"{transport} request failed before receiving an HTTP response",
            transport=transport,
            retryable=True,
        )


class ProviderResponseError(ProviderRequestError):
    """A sanitized invalid or explicitly failed provider response."""

    def __init__(
        self,
        *,
        transport: str,
        code: str,
        retryable: bool = False,
        usage: dict[str, int] | None = None,
        provider_cost: ProviderCost | None = None,
        latency_seconds: float | None = None,
    ) -> None:
        super().__init__(
            (
                f"{transport} returned a retryable failed response"
                if retryable
                else f"{transport} returned an invalid response"
            ),
            transport=transport,
            retryable=retryable,
        )
        self.code = code
        self.usage = _normalized_response_usage(usage)
        self.provider_cost = normalize_provider_cost(provider_cost)
        if latency_seconds is None:
            self.latency_seconds = None
        else:
            latency = float(latency_seconds)
            if not isfinite(latency) or latency < 0:
                raise ValueError(
                    "provider response latency must be finite and non-negative"
                )
            self.latency_seconds = latency


def _normalized_response_usage(value: Any) -> dict[str, int] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("provider response usage must be an object")
    if not {"input_tokens", "output_tokens"}.issubset(value):
        raise ValueError(
            "provider response usage requires input_tokens and output_tokens"
        )
    output: dict[str, int] = {}
    for field_name in (
        "input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "cached_input_tokens",
    ):
        raw = value.get(field_name, 0)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise ValueError(
                f"provider response {field_name} must be a non-negative integer"
            )
        output[field_name] = raw
    return output


@dataclass
class ProviderToolCall:
    call_id: str
    tool: str
    arguments: dict[str, Any] | None
    error: str | None = None


@dataclass
class ProviderTurn:
    text: str = ""
    tool_calls: list[ProviderToolCall] | None = None
    protocol_error: str | None = None
    raw_response: Any = None
    usage: dict[str, int] = field(default_factory=dict)
    latency_seconds: float = 0.0
    provider_request_id: str | None = None
    transport: str | None = None
    action_protocol: str | None = None
    normalizations: list[dict[str, Any]] = field(default_factory=list)
    # Sanitized size-only request metadata.  Providers may populate this so
    # traces can explain context growth without duplicating prompt contents.
    request_context: dict[str, Any] = field(default_factory=dict)
    # Provider-reported money is separate from integer token usage.  Adapters
    # must canonicalize it with ``provider_cost_from_usage`` before returning.
    provider_cost: ProviderCost = field(default_factory=dict)


class Provider(Protocol):
    name: str
    model: str

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        episode: Any,
    ) -> ProviderTurn:
        ...


def messages_for_current_turn(
    messages: list[dict[str, str]],
    episode: Any,
) -> list[dict[str, str]]:
    """Copy initial messages and append the episode's dynamic phase rule."""

    copied = deepcopy(messages)
    instruction_factory = getattr(episode, "turn_instruction", None)
    instruction = (
        instruction_factory() if callable(instruction_factory) else None
    )
    if not instruction:
        return copied
    for item in copied:
        if item.get("role") == "system":
            item["content"] = (
                f"{str(item.get('content') or '').rstrip()}\n\n{instruction}"
            )
            return copied
    copied.insert(0, {"role": "system", "content": instruction})
    return copied
