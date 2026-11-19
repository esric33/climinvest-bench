from __future__ import annotations

from copy import deepcopy
from typing import Any

from .ids import field_id, require_id
from .units import normalize_missing_literal, normalize_unit


def scalar(
    node_id: str,
    description: str,
    value: Any,
    *,
    unit: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_value = normalize_missing_literal(value)
    normalized_unit = normalize_unit(unit)
    available = normalized_value is not None
    node: dict[str, Any] = {
        "id": require_id(node_id),
        "kind": "scalar",
        "description": str(description),
        "status": "available" if available else "missing",
        "value": deepcopy(normalized_value) if available else None,
        "unit": normalized_unit,
    }
    if provenance:
        node["provenance"] = deepcopy(provenance)
    return node


def record(
    record_id: str,
    description: str,
    fields: dict[str, tuple[str, Any, str | None]],
    *,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    require_id(record_id)
    output_fields: dict[str, dict[str, Any]] = {}
    for name, (field_description, value, unit) in fields.items():
        output_fields[name] = scalar(
            field_id(record_id, name),
            field_description,
            value,
            unit=unit,
            provenance=provenance,
        )
    result: dict[str, Any] = {
        "id": record_id,
        "kind": "record",
        "description": description,
        "status": (
            "available"
            if any(item["status"] == "available" for item in output_fields.values())
            else "missing"
        ),
        "fields": output_fields,
    }
    if provenance:
        result["provenance"] = deepcopy(provenance)
    return result


def collection(
    collection_id: str,
    description: str,
    records: list[dict[str, Any]],
    *,
    record_schema: list[str],
) -> dict[str, Any]:
    require_id(collection_id)
    return {
        "id": collection_id,
        "kind": "collection",
        "description": description,
        "status": "available" if records else "missing",
        "record_schema": list(record_schema),
        "records": deepcopy(records),
    }


def node_value(node: dict[str, Any]) -> Any:
    if node.get("status") != "available":
        return None
    return node.get("value")
