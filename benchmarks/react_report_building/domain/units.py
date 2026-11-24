from __future__ import annotations

from typing import Any


NULL_LITERALS = {
    "",
    "n/a",
    "na",
    "nil",
    "none",
    "not applicable",
    "null",
}

UNIT_ALIASES = {
    "US$": "USD",
    "USD": "USD",
    "tCO2eq": "tCO2e",
    "tCO2e": "tCO2e",
    "years": "years",
    "year": "years",
}


def normalize_unit(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.casefold() in NULL_LITERALS:
        return None
    return UNIT_ALIASES.get(text, text or None)


def normalize_missing_literal(value: Any) -> Any:
    if isinstance(value, str) and value.strip().casefold() in NULL_LITERALS:
        return None
    return value


def numeric(value: Any) -> float | int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip().replace(",", "")
    try:
        parsed = float(text)
    except ValueError:
        return None
    return int(parsed) if parsed.is_integer() else parsed
