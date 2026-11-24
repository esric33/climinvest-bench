"""Shared semantic-calculation specification used by compiler and runtime."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from ..util import read_json


SPEC_PATH = Path(__file__).resolve().parent / "data" / "semantic_calculations.json"

# Completeness counters are diagnostic companions to the KPI ranking root. They
# are exposed whenever a contract consumes the prioritized KPI register, even
# when prose/table templates do not render the counters directly. This keeps
# partial-ranking behavior inspectable through the existing calculate tool
# without adding a document component or editing TraceMark templates.
RUNTIME_COMPANIONS = {
    "calc.prioritized_kpis": (
        "calc.available_kpi_priority_count",
        "calc.incomplete_kpi_priority_count",
    ),
}


def semantic_calculation_registry() -> dict[str, dict[str, Any]]:
    payload = read_json(SPEC_PATH)
    if payload.get("schema_version") != "react_report.semantic_calculations/v1":
        raise ValueError("unexpected semantic-calculation schema")
    registry: dict[str, dict[str, Any]] = {}
    for item in payload.get("calculations", []):
        definition = deepcopy(item)
        calculation_id = str(definition.get("id") or "")
        if not calculation_id.startswith("calc."):
            raise ValueError(f"invalid semantic calculation ID {calculation_id!r}")
        if calculation_id in registry:
            raise ValueError(f"duplicate semantic calculation ID {calculation_id}")
        definition["kind"] = "calculation_definition"
        registry[calculation_id] = definition
    _validate_dependencies(registry)
    return registry


def referenced_semantic_calculations(
    contract: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Return the transitive semantic subset consumed by one contract."""

    registry = semantic_calculation_registry()
    roots = set(contract.get("semantic_calculation_ids") or [])
    for artifact in contract.get("artifacts", []):
        roots.update(artifact.get("canonical_dependencies") or [])
        roots.update(artifact.get("data_ids") or [])
    for node in contract.get("generated_nodes", []):
        roots.update(node.get("canonical_dependencies") or [])

    selected: set[str] = set()

    def visit(calculation_id: str) -> None:
        if calculation_id not in registry or calculation_id in selected:
            return
        selected.add(calculation_id)
        for dependency in registry[calculation_id]["input_ids"].values():
            visit(str(dependency))

    for root in roots:
        visit(str(root))
    for trigger, companions in RUNTIME_COMPANIONS.items():
        if trigger in selected:
            for calculation_id in companions:
                visit(calculation_id)
    return {
        calculation_id: deepcopy(definition)
        for calculation_id, definition in registry.items()
        if calculation_id in selected
    }


def semantic_source_ids(
    definitions: Iterable[dict[str, Any]] | None = None,
) -> set[str]:
    items = definitions or semantic_calculation_registry().values()
    return {
        str(node_id)
        for definition in items
        for node_id in definition["input_ids"].values()
        if not str(node_id).startswith("calc.")
    }


def _validate_dependencies(registry: dict[str, dict[str, Any]]) -> None:
    visited: set[str] = set()
    active: set[str] = set()

    def visit(calculation_id: str) -> None:
        if calculation_id in visited:
            return
        if calculation_id in active:
            raise ValueError(f"semantic calculation cycle at {calculation_id}")
        active.add(calculation_id)
        definition = registry[calculation_id]
        required = {
            "description",
            "operation_id",
            "input_ids",
            "parameters",
            "unit",
            "value_type",
        }
        missing = sorted(required - set(definition))
        if missing:
            raise ValueError(
                f"{calculation_id}: missing semantic fields {', '.join(missing)}"
            )
        for dependency in definition["input_ids"].values():
            dependency_id = str(dependency)
            if dependency_id.startswith("calc."):
                if dependency_id not in registry:
                    raise ValueError(
                        f"{calculation_id}: unknown semantic dependency {dependency_id}"
                    )
                visit(dependency_id)
        active.remove(calculation_id)
        visited.add(calculation_id)

    for calculation_id in registry:
        visit(calculation_id)
