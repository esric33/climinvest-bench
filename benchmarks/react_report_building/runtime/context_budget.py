"""Explicit request budgeting; never truncates messages, evidence, or tools."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
import json
import re
from typing import Any, Callable
from .provider_cost import canonical_decimal_string


CONTEXT_BUDGET_POLICY_VERSION = "react_report.context_budget/v1"
CONDITIONAL_CONTEXT_BUDGET_POLICY_VERSION = "react_report.context_budget/v4"
OPENROUTER_PROBE_MAX_OUTPUT_TOKENS = 32
OPENROUTER_PROBE_MAX_OBSERVED_OUTPUT_TOKENS = 32
OPENROUTER_PROBE_ON_CLAMP = "openrouter_probe_on_clamp"
INPUT_TOKEN_COUNT_MODES = frozenset({"openai_responses", "responses_probe", "vllm_responses", "conservative_bytes", "injected", OPENROUTER_PROBE_ON_CLAMP})
MIN_CONTEXT_SAFETY_MARGIN_TOKENS = 256
MIN_EFFECTIVE_OUTPUT_TOKENS = 256
InputTokenCounter = Callable[[dict[str, Any]], int]


class ContextBudgetError(RuntimeError):
    """A content-free rejection before any generation request is made."""

    def __init__(self, code: str, receipt: dict[str, Any]) -> None:
        super().__init__(f"context budget rejected request before generation: {code}")
        self.code = code
        self.retryable = False
        self.receipt = deepcopy(receipt)


def serialize_request_payload(payload: dict[str, Any]) -> bytes:
    """Use the Responses adapter's actual wire serialization, including escaping."""
    return json.dumps(payload).encode("utf-8")


@dataclass(frozen=True)
class ContextBudget:
    context_window_tokens: int
    context_safety_margin_tokens: int
    input_token_count_mode: str
    input_token_counter_id: str | None = None
    context_probe_max_requests: int | None = None
    context_probe_max_cost_usd: str | None = None

    def __post_init__(self) -> None:
        for name, minimum in (
            ("context_window_tokens", MIN_CONTEXT_SAFETY_MARGIN_TOKENS + MIN_EFFECTIVE_OUTPUT_TOKENS),
            ("context_safety_margin_tokens", MIN_CONTEXT_SAFETY_MARGIN_TOKENS),
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}")
        if self.context_safety_margin_tokens + MIN_EFFECTIVE_OUTPUT_TOKENS > self.context_window_tokens:
            raise ValueError("context window must leave room beyond the safety margin")
        if not isinstance(self.input_token_count_mode, str) or self.input_token_count_mode not in INPUT_TOKEN_COUNT_MODES:
            raise ValueError("unsupported input_token_count_mode")
        if self.input_token_count_mode == "injected":
            if not isinstance(self.input_token_counter_id, str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,159}", self.input_token_counter_id
            ):
                raise ValueError("injected counting requires a versioned input_token_counter_id")
        elif self.input_token_counter_id is not None:
            raise ValueError("input_token_counter_id is supported only for injected counting")
        if self.input_token_count_mode == OPENROUTER_PROBE_ON_CLAMP:
            count = self.context_probe_max_requests
            if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 100000:
                raise ValueError("context_probe_max_requests must be an integer from 1 to 100000")
            cost = canonical_decimal_string(self.context_probe_max_cost_usd, field="context probe cost limit")
            amount = Decimal(cost)
            if amount <= 0 or amount > Decimal("1e12") or amount.as_tuple().exponent < -18:
                raise ValueError("context_probe_max_cost_usd must be positive, at most 1e12, and use at most 18 decimal places")
            object.__setattr__(self, "context_probe_max_cost_usd", cost)
        elif self.context_probe_max_requests is not None or self.context_probe_max_cost_usd is not None:
            raise ValueError("context probe limits require openrouter_probe_on_clamp")

    def provenance(self) -> dict[str, Any]:
        return {
            "schema_version": (CONDITIONAL_CONTEXT_BUDGET_POLICY_VERSION
                               if self.input_token_count_mode == OPENROUTER_PROBE_ON_CLAMP
                               else CONTEXT_BUDGET_POLICY_VERSION),
            "context_window_tokens": self.context_window_tokens,
            "context_safety_margin_tokens": self.context_safety_margin_tokens,
            "input_token_count_mode": self.input_token_count_mode,
            "minimum_effective_output_tokens": MIN_EFFECTIVE_OUTPUT_TOKENS,
            **({"input_token_counter_id": self.input_token_counter_id} if self.input_token_counter_id else {}),
            **({"probe_limits": {"max_requests": self.context_probe_max_requests,
                                 "max_cost_usd": self.context_probe_max_cost_usd,
                                 "requested_output_tokens": OPENROUTER_PROBE_MAX_OUTPUT_TOKENS,
                                 "max_observed_output_tokens": OPENROUTER_PROBE_MAX_OBSERVED_OUTPUT_TOKENS}}
               if self.input_token_count_mode == OPENROUTER_PROBE_ON_CLAMP else {}),
        }

    def prepare(
        self,
        payload: dict[str, Any],
        *,
        exact_counter: InputTokenCounter | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        requested = payload.get("max_output_tokens")
        if isinstance(requested, bool) or not isinstance(requested, int) or requested <= 0:
            raise ValueError("max_output_tokens must be a positive integer")
        body = serialize_request_payload(payload)
        receipt = {
            **self.provenance(),
            "requested_max_output_tokens": requested,
            "request_payload_bytes": len(body),
            "requested_payload_sha256": sha256(body).hexdigest(),
            "input_tokens": None,
            "effective_max_output_tokens": None,
            "count_kind": "estimate" if self.input_token_count_mode in {"conservative_bytes", OPENROUTER_PROBE_ON_CLAMP} else "exact",
        }
        conditional = self.input_token_count_mode == OPENROUTER_PROBE_ON_CLAMP
        if conditional:
            receipt.update(estimated_input_tokens=len(body), probe_triggered=(
                len(body) + requested + self.context_safety_margin_tokens > self.context_window_tokens
            ))
        if self.input_token_count_mode == "conservative_bytes" or (conditional and not receipt["probe_triggered"]):
            input_tokens = len(body)
            receipt["estimate_assumption"] = (
                "one token per UTF-8 byte of the complete JSON request; "
                "server template expansion is covered only by the configured margin; "
                "not a tokenizer count or a guaranteed model-specific bound"
            )
        else:
            if exact_counter is None:
                raise ContextBudgetError("input_token_counter_unavailable", receipt)
            try:
                # The counting implementation cannot alter production evidence.
                input_tokens = exact_counter(deepcopy(payload))
            except Exception:
                raise ContextBudgetError("input_token_count_failed", receipt) from None
            if isinstance(input_tokens, bool) or not isinstance(input_tokens, int) or input_tokens < 0:
                raise ContextBudgetError("invalid_input_token_count", receipt)
            receipt["count_kind"] = "exact"
        remaining = self.context_window_tokens - input_tokens - self.context_safety_margin_tokens
        effective = min(requested, remaining)
        receipt.update(input_tokens=input_tokens, effective_max_output_tokens=max(0, effective))
        if effective < MIN_EFFECTIVE_OUTPUT_TOKENS:
            raise ContextBudgetError("insufficient_output_budget", receipt)
        adjusted = deepcopy(payload)
        adjusted["max_output_tokens"] = effective
        receipt["output_was_clamped"] = effective != requested
        receipt["effective_payload_sha256"] = sha256(serialize_request_payload(adjusted)).hexdigest()
        return adjusted, receipt


def configured_context_budget(
    *,
    context_window_tokens: int | None = None,
    context_safety_margin_tokens: int | None = None,
    input_token_count_mode: str | None = None,
    input_token_counter_id: str | None = None,
    context_probe_max_requests: int | None = None,
    context_probe_max_cost_usd: str | None = None,
) -> ContextBudget | None:
    values = (context_window_tokens, context_safety_margin_tokens, input_token_count_mode)
    if all(value is None for value in values) and input_token_counter_id is None and context_probe_max_requests is None and context_probe_max_cost_usd is None:
        return None
    if any(value is None for value in values):
        raise ValueError("context window, safety margin and input token count mode must be configured together")
    return ContextBudget(
        context_window_tokens=context_window_tokens,
        context_safety_margin_tokens=context_safety_margin_tokens,
        input_token_count_mode=input_token_count_mode,
        input_token_counter_id=input_token_counter_id,
        context_probe_max_requests=context_probe_max_requests,
        context_probe_max_cost_usd=context_probe_max_cost_usd,
    )
