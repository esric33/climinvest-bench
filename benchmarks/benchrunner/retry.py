"""Typed, bounded retry decisions for scheduler work attempts."""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from benchmarks.react_report_building.runtime.provider_cost import (
    normalize_provider_cost,
)


RETRYABLE_HTTP_STATUSES = frozenset(
    {408, 409, 425, 429, 500, 502, 503, 504, 524, 529}
)
RETRYABLE_FAILED_RESPONSE_CODES = frozenset(
    {"server_error", "timeout", "timeout_error"}
)
FAILED_RESPONSE_ACCOUNTING_SCHEMA_VERSION = (
    "benchrunner.failed_provider_response_accounting/v1"
)
FAILED_RESPONSE_USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "cached_input_tokens",
)
FAILED_RESPONSE_COST_DETAIL_KEYS = frozenset(
    {
        "upstream_inference_cost",
        "upstream_inference_input_cost",
        "upstream_inference_output_cost",
    }
)


def failed_response_accounting_metadata(
    *,
    usage: Any,
    provider_cost: Any,
    latency_seconds: Any,
) -> dict[str, Any]:
    """Return the safe numeric receipt persisted for a failed response."""

    usage_reported = usage is not None
    normalized_usage: dict[str, int] | None = None
    if usage_reported:
        if not isinstance(usage, dict):
            raise ValueError("failed response usage must be an object or null")
        if not {"input_tokens", "output_tokens"}.issubset(usage):
            raise ValueError(
                "failed response usage requires input_tokens and output_tokens"
            )
        normalized_usage = {}
        for field_name in FAILED_RESPONSE_USAGE_FIELDS:
            raw = usage.get(field_name, 0)
            if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
                raise ValueError(
                    f"failed response {field_name} must be a non-negative integer"
                )
            normalized_usage[field_name] = raw
    latency = float(latency_seconds)
    if not math.isfinite(latency) or latency < 0:
        raise ValueError(
            "failed response latency must be finite and non-negative"
        )
    normalized_cost = normalize_provider_cost(provider_cost)
    if normalized_cost:
        details = {
            key: amount
            for key, amount in normalized_cost.get("details", {}).items()
            if key in FAILED_RESPONSE_COST_DETAIL_KEYS
        }
        total = normalized_cost.get("total")
        normalized_cost = (
            {
                "currency": normalized_cost["currency"],
                "total": total,
                "details": details,
            }
            if total is not None or details
            else {}
        )
    return {
        "schema_version": FAILED_RESPONSE_ACCOUNTING_SCHEMA_VERSION,
        "usage": normalized_usage,
        "usage_reported": usage_reported,
        "provider_cost": normalized_cost,
        "latency_seconds": latency,
    }


def failed_response_accounting_from_error(error: Any) -> dict[str, Any] | None:
    """Read and revalidate a sanitized failed-response receipt."""

    if not isinstance(error, dict):
        return None
    metadata = error.get("metadata")
    if not isinstance(metadata, dict):
        return None
    value = metadata.get("failed_response_accounting")
    if value is None:
        return None
    if (
        not isinstance(value, dict)
        or value.get("schema_version")
        != FAILED_RESPONSE_ACCOUNTING_SCHEMA_VERSION
    ):
        raise ValueError("failed response accounting has an invalid schema")
    normalized = failed_response_accounting_metadata(
        usage=value.get("usage"),
        provider_cost=value.get("provider_cost"),
        latency_seconds=value.get("latency_seconds"),
    )
    if value.get("usage_reported") is not normalized["usage_reported"]:
        raise ValueError(
            "failed response accounting usage-report marker is inconsistent"
        )
    return normalized


class WorkExecutionError(RuntimeError):
    """Sanitized failure safe to persist in scheduler artifacts."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        retry_after_seconds: float | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        code_value = str(code or "").strip()
        message_value = str(message or "").strip()
        if not code_value or not message_value:
            raise ValueError("work errors require non-empty code and message")
        if retry_after_seconds is not None and retry_after_seconds < 0:
            raise ValueError("retry_after_seconds cannot be negative")
        super().__init__(message_value)
        self.code = code_value
        self.message = message_value
        self.retryable = bool(retryable)
        self.retry_after_seconds = (
            float(retry_after_seconds)
            if retry_after_seconds is not None
            else None
        )
        self.metadata = dict(metadata or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            **(
                {"retry_after_seconds": self.retry_after_seconds}
                if self.retry_after_seconds is not None
                else {}
            ),
            **({"metadata": self.metadata} if self.metadata else {}),
        }


class RetryableWorkError(WorkExecutionError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retry_after_seconds: float | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(
            code,
            message,
            retryable=True,
            retry_after_seconds=retry_after_seconds,
            metadata=metadata,
        )


class PermanentWorkError(WorkExecutionError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(
            code,
            message,
            retryable=False,
            metadata=metadata,
        )


class ProviderRequestError(WorkExecutionError):
    """Typed provider transport/HTTP failure without a raw response body."""

    def __init__(
        self,
        *,
        status_code: int | None = None,
        retry_after_seconds: float | None = None,
        code: str | None = None,
        message: str | None = None,
    ) -> None:
        status = int(status_code) if status_code is not None else None
        retryable = status is None or status in RETRYABLE_HTTP_STATUSES
        resolved_code = code or (
            "provider.transport_error"
            if status is None
            else f"provider.http_{status}"
        )
        resolved_message = message or (
            "The provider request failed before a valid response was received."
            if status is None
            else "The provider returned an unsuccessful HTTP status."
        )
        super().__init__(
            resolved_code,
            resolved_message,
            retryable=retryable,
            retry_after_seconds=retry_after_seconds,
            metadata=({"http_status": status} if status is not None else None),
        )
        self.status_code = status


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 4
    base_delay_seconds: float = 2.0
    multiplier: float = 2.0
    max_delay_seconds: float = 60.0
    max_total_delay_seconds: float = 180.0
    jitter: str = "full"

    def __post_init__(self) -> None:
        if isinstance(self.max_attempts, bool) or not 1 <= self.max_attempts <= 20:
            raise ValueError("max_attempts must be between 1 and 20")
        for name, value in (
            ("base_delay_seconds", self.base_delay_seconds),
            ("multiplier", self.multiplier),
            ("max_delay_seconds", self.max_delay_seconds),
            ("max_total_delay_seconds", self.max_total_delay_seconds),
        ):
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if self.base_delay_seconds < 0:
            raise ValueError("base_delay_seconds cannot be negative")
        if self.multiplier < 1:
            raise ValueError("retry multiplier must be at least one")
        if self.max_delay_seconds < 0:
            raise ValueError("max_delay_seconds cannot be negative")
        if self.max_total_delay_seconds < 0:
            raise ValueError("max_total_delay_seconds cannot be negative")
        if self.jitter not in {"none", "full"}:
            raise ValueError("retry jitter must be 'none' or 'full'")


@dataclass(frozen=True, slots=True)
class RetryDecision:
    retry: bool
    delay_seconds: float = 0.0
    reason: str = ""


def policy_from_spec(spec: Any) -> RetryPolicy:
    """Use the study's exact bounded retry settings at every request boundary."""
    return RetryPolicy(max_attempts=spec.max_attempts,
                       base_delay_seconds=spec.base_delay_seconds,
                       max_delay_seconds=spec.max_delay_seconds,
                       max_total_delay_seconds=spec.max_total_delay_seconds)


def retry_call(operation: Callable, policy: RetryPolicy, *, on_failure: Callable,
               sleep: Callable | None = None):
    """Retry typed transient failures only; persist evidence before waiting."""
    waited = 0.0
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return operation()
        except Exception as exc:
            decision = decide_retry(normalize_execution_error(exc), policy,
                                    attempt=attempt, prior_delay_seconds=waited)
            on_failure(exc, attempt, decision)
            if not decision.retry:
                raise
            (sleep or time.sleep)(decision.delay_seconds)
            waited += decision.delay_seconds


def decide_retry(
    error: WorkExecutionError,
    policy: RetryPolicy,
    *,
    attempt: int,
    prior_delay_seconds: float = 0.0,
    random_value: Callable[[], float] = random.random,
) -> RetryDecision:
    """Decide the next retry without exceeding attempt or delay budgets."""

    if attempt < 1:
        raise ValueError("attempt must be at least one")
    if prior_delay_seconds < 0:
        raise ValueError("prior_delay_seconds cannot be negative")
    if not error.retryable:
        return RetryDecision(False, reason="non_retryable")
    if attempt >= policy.max_attempts:
        return RetryDecision(False, reason="attempt_limit")

    exponent = max(0, attempt - 1)
    try:
        raw_delay = policy.base_delay_seconds * math.pow(
            policy.multiplier, exponent
        )
    except OverflowError:
        raw_delay = policy.max_delay_seconds
    raw_delay = min(policy.max_delay_seconds, raw_delay)
    minimum_delay = 0.0
    if error.retry_after_seconds is not None:
        # Retry-After is the provider's minimum, not a suggestion to cap down.
        # If it exceeds our total waiting budget, decline the retry below.
        minimum_delay = error.retry_after_seconds
        raw_delay = max(raw_delay, minimum_delay)
    if policy.jitter == "full" and raw_delay:
        sample = float(random_value())
        if not 0 <= sample <= 1:
            raise ValueError("retry random value must be between zero and one")
        delay = minimum_delay + ((raw_delay - minimum_delay) * sample)
    else:
        delay = raw_delay

    if prior_delay_seconds + delay > policy.max_total_delay_seconds:
        return RetryDecision(False, reason="delay_budget")
    return RetryDecision(True, delay_seconds=delay, reason="retryable")


def normalize_execution_error(exc: BaseException) -> WorkExecutionError:
    """Convert unknown executor exceptions into safe, non-retryable records."""

    if isinstance(exc, WorkExecutionError):
        return exc
    retryable = getattr(exc, "retryable", None)
    if isinstance(retryable, bool):
        status = getattr(exc, "status_code", None)
        retry_after = getattr(exc, "retry_after_seconds", None)
        upstream_code = getattr(exc, "code", None)
        transport = str(getattr(exc, "transport", "provider") or "provider")
        code = str(
            upstream_code
            or (
                f"provider.http_{int(status)}"
                if isinstance(status, int)
                else "provider.request_error"
            )
        )
        metadata: dict[str, Any] = {"transport": transport}
        if isinstance(status, int):
            metadata["http_status"] = status
        request_id = getattr(exc, "provider_request_id", None)
        response_latency = getattr(exc, "latency_seconds", None)
        if (
            isinstance(request_id, str)
            and request_id
            and response_latency is None
        ):
            metadata["provider_request_id"] = request_id
        response_usage = getattr(exc, "usage", None)
        if response_latency is not None:
            metadata["response_received"] = True
            if isinstance(upstream_code, str) and upstream_code:
                metadata["provider_error_code"] = upstream_code
            metadata["failed_response_accounting"] = (
                failed_response_accounting_metadata(
                    usage=response_usage,
                    provider_cost=getattr(exc, "provider_cost", None),
                    latency_seconds=response_latency,
                )
            )
        return WorkExecutionError(
            code,
            "The provider request failed before a valid turn was received.",
            retryable=retryable,
            retry_after_seconds=(
                float(retry_after)
                if isinstance(retry_after, (int, float))
                and math.isfinite(float(retry_after))
                and float(retry_after) >= 0
                else None
            ),
            metadata=metadata,
        )
    return PermanentWorkError(
        "executor.unhandled",
        "The work executor raised an unhandled exception.",
        metadata={"exception_type": type(exc).__name__},
    )
