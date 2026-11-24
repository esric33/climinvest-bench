"""Sanitized, exact provider-reported monetary cost accounting."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, TypedDict


_COST_DETAIL_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,127}\Z")
_MAX_COST_LITERAL_CHARACTERS = 512
_MAX_COST_DIGITS = 256
_MAX_COST_EXPONENT_MAGNITUDE = 256


class ProviderCost(TypedDict, total=False):
    """Portable cost data attached to one successful provider response.

    Values are decimal strings rather than JSON numbers so checkpointing,
    SQLite, and aggregation never pass monetary values through binary floats.
    An empty object means the provider did not report cost for that response.
    """

    currency: str
    total: str | None
    details: dict[str, str | None]


def provider_cost_from_usage(
    usage: Any,
    *,
    currency: str = "USD",
) -> ProviderCost:
    """Extract ``usage.cost`` and ``usage.cost_details`` without float math.

    This is the adapter hook for providers such as OpenRouter. JSON-decoded
    numbers are canonicalized through their string representation immediately;
    callers should retain the returned object on ``ProviderTurn.provider_cost``.
    Missing cost fields return an empty object for compatibility with providers
    and historical checkpoints that only report token usage.
    """

    if not isinstance(usage, dict):
        raise ValueError("provider usage must be an object")
    if "cost" not in usage and "cost_details" not in usage:
        return {}
    return normalize_provider_cost(
        {
            "currency": currency,
            "total": usage.get("cost"),
            "details": (
                {}
                if usage.get("cost_details") is None
                else usage.get("cost_details")
            ),
        }
    )


def normalize_provider_cost(value: Any) -> ProviderCost:
    """Validate and canonicalize one portable provider-cost object."""

    if value is None or value == {}:
        return {}
    if not isinstance(value, dict):
        raise ValueError("provider cost must be an object")

    has_total = "total" in value
    raw_details = value.get("details")
    if raw_details is None:
        raw_details = {}
    if not isinstance(raw_details, dict):
        raise ValueError("provider cost details must be an object")
    if not has_total and not raw_details:
        return {}

    raw_currency = value.get("currency", "USD")
    if not isinstance(raw_currency, str):
        raise ValueError("provider cost currency must be a string")
    currency = raw_currency.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("provider cost currency must be a three-letter code")

    total = (
        None
        if not has_total or value.get("total") is None
        else canonical_decimal_string(value["total"], field="provider cost total")
    )
    details: dict[str, str | None] = {}
    for raw_key, raw_amount in raw_details.items():
        if not isinstance(raw_key, str) or not _COST_DETAIL_KEY.fullmatch(raw_key):
            raise ValueError("provider cost detail has an invalid key")
        details[raw_key] = (
            None
            if raw_amount is None
            else canonical_decimal_string(
                raw_amount,
                field=f"provider cost detail {raw_key}",
            )
        )
    return {
        "currency": currency,
        "total": total,
        "details": dict(sorted(details.items())),
    }


def empty_provider_cost_summary() -> dict[str, Any]:
    """Return an aggregation target that distinguishes unknown from zero."""

    return {
        "currency": None,
        "total": None,
        "details": {},
        "reported_response_turns": 0,
        "total_reported_response_turns": 0,
        "unreported_response_turns": 0,
    }


def add_provider_cost(
    summary: dict[str, Any],
    value: Any,
) -> None:
    """Add one normalized response cost to ``summary`` exactly in place."""

    cost = normalize_provider_cost(value)
    if not cost:
        summary["unreported_response_turns"] += 1
        return

    currency = cost["currency"]
    existing_currency = summary.get("currency")
    if existing_currency not in {None, currency}:
        raise ValueError(
            "provider cost aggregation cannot mix currencies: "
            f"{existing_currency!r} and {currency!r}"
        )
    summary["currency"] = currency
    summary["reported_response_turns"] += 1

    total = cost.get("total")
    if total is not None:
        summary["total"] = add_decimal_strings(summary.get("total"), total)
        summary["total_reported_response_turns"] += 1

    output_details = summary["details"]
    for key, amount in cost.get("details", {}).items():
        if amount is None:
            output_details.setdefault(key, None)
            continue
        output_details[key] = add_decimal_strings(output_details.get(key), amount)
    summary["details"] = dict(sorted(output_details.items()))


def canonical_decimal_string(value: Any, *, field: str = "cost") -> str:
    """Return a finite, non-negative decimal in non-exponent notation."""

    if isinstance(value, bool):
        raise ValueError(f"{field} must be a decimal number")
    literal = str(value).strip()
    if not literal or len(literal) > _MAX_COST_LITERAL_CHARACTERS:
        raise ValueError(f"{field} exceeds the supported decimal precision")
    try:
        number = Decimal(literal)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a decimal number") from exc
    if not number.is_finite() or number < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    if number.is_zero():
        return "0"
    decimal_tuple = number.as_tuple()
    if (
        len(decimal_tuple.digits) > _MAX_COST_DIGITS
        or abs(decimal_tuple.exponent) > _MAX_COST_EXPONENT_MAGNITUDE
    ):
        raise ValueError(f"{field} exceeds the supported decimal precision")
    rendered = format(number, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered in {"", "-0"} else rendered


def add_decimal_strings(left: Any, right: Any) -> str:
    """Add canonical decimal strings without introducing binary floats."""

    right_value = canonical_decimal_string(right)
    if left is None:
        return right_value
    left_value = canonical_decimal_string(left)
    left_coefficient, left_scale = _decimal_coefficient(left_value)
    right_coefficient, right_scale = _decimal_coefficient(right_value)
    scale = max(left_scale, right_scale)
    total = (
        left_coefficient * 10 ** (scale - left_scale)
        + right_coefficient * 10 ** (scale - right_scale)
    )
    digits = str(total).rjust(scale + 1, "0")
    rendered = (
        digits
        if scale == 0
        else f"{digits[:-scale]}.{digits[-scale:]}".rstrip("0").rstrip(".")
    )
    return canonical_decimal_string(rendered)


def _decimal_coefficient(value: str) -> tuple[int, int]:
    """Return an integer coefficient and scale for a canonical decimal."""

    whole, separator, fraction = value.partition(".")
    scale = len(fraction) if separator else 0
    return int(f"{whole}{fraction}"), scale


__all__ = [
    "ProviderCost",
    "add_decimal_strings",
    "add_provider_cost",
    "canonical_decimal_string",
    "empty_provider_cost_summary",
    "normalize_provider_cost",
    "provider_cost_from_usage",
]
