from __future__ import annotations

import re


ID_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]{0,255}$")


def require_id(value: object, field: str = "id") -> str:
    text = str(value or "").strip()
    if not ID_PATTERN.fullmatch(text):
        raise ValueError(f"{field} is not a valid benchmark identifier: {text!r}")
    return text


def field_id(record_id: str, field: str) -> str:
    require_id(record_id, "record_id")
    require_id(field, "field")
    return f"{record_id}.{field}"


def missing_id(node_id: str) -> str:
    return f"missing.{require_id(node_id, 'node_id')}"

