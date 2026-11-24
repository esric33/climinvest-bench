from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from ..paths import CATALOGUE_ROOT
from ..util import read_json
from .contract import load_compiled_contract
from .evidence import overlay_catalogue_entries
from .semantic_calculations import referenced_semantic_calculations


UNIT_OVERRIDES = {
    "calc.country_count": "countries",
    "calc.risk_count": "records",
    "calc.renewables_policy_gap_pct": "pp",
    "calc.renewable_policy_gap_pct": "pp",
    "calc.avoided_deforestation_rate_pct_per_year": "pp/year",
    "calc.selected_kpi_count": "records",
    "calc.simple_funding_per_implementation_year": "USD/year",
    "calc.simple_gcf_per_implementation_year": "USD/year",
    "calc.simple_funding_per_commitment_year": "USD/year",
    "calc.total_financing_per_tco2e_low": "USD/tCO2e",
    "calc.total_financing_per_tco2e_midpoint": "USD/tCO2e",
    "calc.total_financing_per_tco2e_high": "USD/tCO2e",
    "calc.gcf_financing_per_tco2e_low": "USD/tCO2e",
    "calc.gcf_financing_per_tco2e_mid": "USD/tCO2e",
    "calc.gcf_financing_per_tco2e_midpoint": "USD/tCO2e",
    "calc.gcf_financing_per_tco2e_high": "USD/tCO2e",
    "calc.annualised_ghg_target_low_tco2e": "tCO2e/year",
    "calc.annualised_ghg_target_mid_tco2e": "tCO2e/year",
    "calc.annualised_ghg_target_high_tco2e": "tCO2e/year",
    "calc.first_tranche_gcf_per_tco2e_low": "USD/tCO2e",
    "calc.first_tranche_gcf_per_tco2e_high": "USD/tCO2e",
    "calc.remaining_gcf_per_tco2e_low": "USD/tCO2e",
    "calc.remaining_gcf_per_tco2e_high": "USD/tCO2e",
    "calc.funding_per_enabled_mw_low": "USD/MW",
    "calc.funding_per_enabled_mw_high": "USD/MW",
    "calc.gcf_per_enabled_mw_low": "USD/MW",
    "calc.gcf_per_enabled_mw_high": "USD/MW",
    "calc.mobilized_capital_per_enabled_mw_low": "USD/MW",
    "calc.mobilized_capital_per_enabled_mw_high": "USD/MW",
    "calc.funding_per_explored_project": "USD/project",
    "calc.gcf_per_explored_project": "USD/project",
    "calc.gcf_financing_per_installed_mw": "USD/MW",
    "calc.beneficiaries_per_installed_mw": "people/MW",
    "calc.gcf_financing_per_service_connection": "USD/connection",
    "calc.direct_beneficiaries_per_service_connection": "people/connection",
    "calc.gcf_financing_per_livelihood_enterprise": "USD/enterprise",
    "calc.project_cost_per_reported_tco2e": "USD/tCO2e",
    "calc.gcf_financing_per_reported_tco2e": "USD/tCO2e",
    "calc.annualised_reported_ghg_target_tco2e": "tCO2e/year",
    "calc.project_cost_per_direct_beneficiary": "USD/person",
    "calc.gcf_financing_per_direct_beneficiary": "USD/person",
}


def calculation_registry(
    contract: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Bridge compiled TraceMark calculations to the existing calculate tool."""

    payload = contract or load_compiled_contract()
    registry: dict[str, dict[str, Any]] = {}
    for node in payload["generated_nodes"]:
        if node.get("tool") != "DOC_EXPRESSION":
            continue
        calculation_id = node["canonical_id"]
        registry[calculation_id] = {
            "id": calculation_id,
            "kind": "calculation_definition",
            "description": node["label"],
            "operation_id": "expression",
            "input_ids": deepcopy(node["input_ids"]),
            "parameters": {},
            "unit": UNIT_OVERRIDES.get(calculation_id, node.get("unit")),
            "compiler_unit": node.get("unit"),
            "expression": node["expression"],
            # Private execution data. It is deliberately omitted from the public
            # catalogue and compact v2 calculate request; agents submit only the
            # canonical calculation ID exposed by the public catalogue.
            "expression_ast": deepcopy(node["expression_ast"]),
            "calculation_depth": node["calculation_depth"],
        }
    for calculation_id, definition in referenced_semantic_calculations(
        payload
    ).items():
        if calculation_id in registry:
            raise ValueError(
                f"compiled and semantic calculations collide at {calculation_id}"
            )
        registry[calculation_id] = deepcopy(definition)
    return registry


def public_calculation_registry(
    contract: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    return {
        calculation_id: {
            key: deepcopy(value)
            for key, value in definition.items()
            if key not in {"expression_ast"}
        }
        for calculation_id, definition in calculation_registry(contract).items()
    }


def catalogue(contract: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the v2 public catalogue shown to both report and section agents."""

    return project_catalogue(contract=contract)


def project_catalogue(
    *,
    contract: dict[str, Any] | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Return a contract- and target-specific public catalogue.

    ``project_id=None`` preserves the original FP083-pilot helper. Population
    runtime paths always pass the resolved target explicitly.
    """

    payload = contract or load_compiled_contract()
    base = read_json(CATALOGUE_ROOT / "global_catalogue.json")
    overlay = overlay_catalogue_entries(project_id)
    collisions = sorted(set(base["data"]) & set(overlay))
    if collisions:
        raise ValueError(
            "v2 catalogue overlay collides with base evidence: "
            + ", ".join(collisions)
        )
    data = {**base["data"], **overlay}
    expression_signature = {
        "input_roles": "the exact canonical identifiers listed in input_ids",
        "parameters": {},
        "execution": (
            "the benchmark executes the pinned TraceMark expression; "
            "there is no alternate formula input"
        ),
    }
    registry = calculation_registry(payload)
    semantic_operations = {
        definition["operation_id"]: {
            "input_roles": list(definition["input_ids"]),
            "parameters": list(definition["parameters"]),
            "execution": (
                "copy the canonical calculation definition exactly; collection "
                "selection and tie handling are deterministic"
            ),
        }
        for definition in registry.values()
        if definition["operation_id"] != "expression"
    }
    return {
        "schema_version": "react_report.data_catalogue/v2",
        "benchmark_version": payload.get("benchmark_version", "v2"),
        "contract_id": payload.get("contract_id"),
        "project_id": project_id,
        "document_contract_source": "compiled TraceMark v2 gold document",
        "data": data,
        "calculations": public_calculation_registry(payload),
        "operations": {
            "expression": expression_signature,
            **semantic_operations,
        },
        "tools": {
            "get_data": {
                "terminal": False,
                "arguments": {
                    "ids": (
                        "one or more complete exact dt.*, reference.*, or "
                        "req.* evidence IDs; never calc.*"
                    )
                },
            },
            "calculate": {
                "terminal": False,
                "arguments": {
                    "ids": (
                        "non-empty array of complete exact calc.* catalogue "
                        "keys; registered dependencies resolve automatically"
                    )
                },
                "example": {"ids": ["calc.country_count"]},
            },
            "create_report": {
                "terminal": True,
                "arguments": {"markdown": "complete report Markdown"},
            },
            "create_section": {
                "terminal": True,
                "arguments": {
                    "section_id": "requested section ID",
                    "mode": (
                        "create for generation; keep or replace for an update"
                    ),
                    "markdown": (
                        "complete section Markdown for create or replace; "
                        "omit for keep"
                    ),
                },
            },
        },
        "citation_format": "[visible text](node_id)",
        "missing_format": "[missing](missing.node_id)",
        "not_applicable_format": "[not applicable](missing.node_id)",
    }


def dependency_filtered_catalogue(
    payload: dict[str, Any],
    dependency_ids: Iterable[str],
) -> dict[str, Any]:
    """Scope a public catalogue to disclosed roots and their calc closure.

    ``dependency_ids`` must originate from the public section contract.  A
    selected calculation recursively exposes its public input definitions so
    the model can request every operation needed to derive the result.  The
    source payload is never mutated, and unrelated project evidence remains
    available to the benchmark runtime and audit fixtures.
    """

    data = payload.get("data")
    calculations = payload.get("calculations")
    operations = payload.get("operations")
    if not all(isinstance(item, dict) for item in (data, calculations, operations)):
        raise ValueError("public catalogue lacks data, calculations, or operations")

    requested = list(dependency_ids)
    if any(not isinstance(item, str) or not item for item in requested):
        raise ValueError("catalogue dependency IDs must be non-empty strings")
    roots = sorted(set(requested))

    selected_data: set[str] = set()
    selected_calculations: set[str] = set()
    pending = list(reversed(roots))
    while pending:
        node_id = pending.pop()
        if node_id in data:
            selected_data.add(node_id)
            continue
        if node_id in selected_calculations:
            continue
        definition = calculations.get(node_id)
        if not isinstance(definition, dict):
            raise ValueError(
                f"public section dependency {node_id!r} is absent from the catalogue"
            )
        selected_calculations.add(node_id)
        input_ids = definition.get("input_ids")
        if not isinstance(input_ids, dict) or any(
            not isinstance(item, str) or not item
            for item in input_ids.values()
        ):
            raise ValueError(
                f"calculation {node_id!r} has invalid public input_ids"
            )
        pending.extend(
            dependency_id
            for dependency_id in reversed(list(input_ids.values()))
            if dependency_id not in selected_data
            and dependency_id not in selected_calculations
        )

    selected_operation_ids = {
        str(calculations[node_id]["operation_id"])
        for node_id in selected_calculations
    }
    missing_operations = selected_operation_ids - set(operations)
    if missing_operations:
        raise ValueError(
            "calculation closure references absent operations: "
            + ", ".join(sorted(missing_operations))
        )

    scoped = deepcopy(payload)
    scoped["data"] = {
        node_id: deepcopy(definition)
        for node_id, definition in data.items()
        if node_id in selected_data
    }
    scoped["calculations"] = {
        node_id: deepcopy(definition)
        for node_id, definition in calculations.items()
        if node_id in selected_calculations
    }
    scoped["operations"] = {
        operation_id: deepcopy(definition)
        for operation_id, definition in operations.items()
        if operation_id in selected_operation_ids
    }
    return scoped
