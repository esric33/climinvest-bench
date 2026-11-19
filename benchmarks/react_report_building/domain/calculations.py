from __future__ import annotations

from copy import deepcopy
from typing import Any


def calculation_registry() -> dict[str, dict[str, Any]]:
    """Return the single canonical calculation graph exposed to every model."""

    definitions: list[dict[str, Any]] = [
        _definition(
            "calc.gcf_funding_total",
            "Total GCF funding",
            "sum",
            {
                "canonical_gcf_financing": "dt.project.gcf_financing_usd",
            },
            "USD",
        ),
        _definition(
            "calc.total_funding_sources",
            "GCF funding plus cofinance",
            "sum",
            {
                "gcf": "calc.gcf_funding_total",
                "cofinance": "dt.project.cofinance_usd",
            },
            "USD",
        ),
        _definition(
            "calc.funding_reconciliation_gap",
            "Total project cost minus the sum of GCF funding and cofinance",
            "subtract",
            {
                "minuend": "dt.project.total_cost_usd",
                "subtrahend": "calc.total_funding_sources",
            },
            "USD",
        ),
        _definition(
            "calc.funding_reconciliation_status",
            "Whether funding sources reconcile with total project cost",
            "zero_status",
            {"value": "calc.funding_reconciliation_gap"},
            None,
        ),
        _definition(
            "calc.gcf_financing_share_pct",
            "GCF funding as a percentage of total project cost",
            "percentage",
            {
                "part": "calc.gcf_funding_total",
                "whole": "dt.project.total_cost_usd",
            },
            "%",
        ),
        _definition(
            "calc.cofinance_share_pct",
            "Cofinance as a percentage of total project cost",
            "percentage",
            {
                "part": "dt.project.cofinance_usd",
                "whole": "dt.project.total_cost_usd",
            },
            "%",
        ),
        _definition(
            "calc.cofinance_per_gcf_dollar",
            "Cofinance divided by total GCF funding",
            "divide",
            {
                "numerator": "dt.project.cofinance_usd",
                "denominator": "calc.gcf_funding_total",
            },
            "x",
        ),
        _definition(
            "calc.total_cost_per_tco2e",
            "Total project cost divided by canonical GHG reduction",
            "divide",
            {
                "numerator": "dt.project.total_cost_usd",
                "denominator": "dt.project.ghg_reduction_tco2e",
            },
            "USD/tCO2e",
        ),
        _definition(
            "calc.gcf_cost_per_tco2e",
            "Total GCF funding divided by canonical GHG reduction",
            "divide",
            {
                "numerator": "calc.gcf_funding_total",
                "denominator": "dt.project.ghg_reduction_tco2e",
            },
            "USD/tCO2e",
        ),
        _definition(
            "calc.tco2e_per_total_cost_dollar",
            "Canonical GHG reduction divided by total project cost",
            "divide",
            {
                "numerator": "dt.project.ghg_reduction_tco2e",
                "denominator": "dt.project.total_cost_usd",
            },
            "tCO2e/USD",
        ),
        _definition(
            "calc.tco2e_per_gcf_dollar",
            "Canonical GHG reduction divided by total GCF funding",
            "divide",
            {
                "numerator": "dt.project.ghg_reduction_tco2e",
                "denominator": "calc.gcf_funding_total",
            },
            "tCO2e/USD",
        ),
        _definition(
            "calc.nominal_cost_per_implementation_year",
            "Total project cost divided by implementation years",
            "divide",
            {
                "numerator": "dt.project.total_cost_usd",
                "denominator": "dt.project.implementation_years",
            },
            "USD/year",
        ),
        _definition(
            "calc.implementation_to_impact_ratio",
            "Implementation period divided by expected lifespan",
            "divide",
            {
                "numerator": "dt.project.implementation_years",
                "denominator": "dt.project.lifespan_years",
            },
            "x",
        ),
        _definition(
            "calc.country_count",
            "Number of records in the project country collection",
            "count_records",
            {"records": "dt.project.countries"},
            "countries",
        ),
        _definition(
            "calc.selected_kpi_count",
            "Number of records in the selected KPI collection",
            "count_records",
            {"records": "dt.selected_kpis"},
            "indicators",
        ),
        _definition(
            "calc.missing_kpi_baseline_count",
            "Selected KPI records without an available baseline",
            "count_unavailable_field",
            {"records": "dt.selected_kpis"},
            "indicators",
            {"field": "baseline"},
        ),
        _definition(
            "calc.missing_kpi_intermediate_count",
            "Selected KPI records without an available intermediate target",
            "count_unavailable_field",
            {"records": "dt.selected_kpis"},
            "indicators",
            {"field": "intermediate_target"},
        ),
        _definition(
            "calc.missing_kpi_final_count",
            "Selected KPI records without an available final target",
            "count_unavailable_field",
            {"records": "dt.selected_kpis"},
            "indicators",
            {"field": "final_target"},
        ),
        _definition(
            "calc.missing_kpi_verification_count",
            "Selected KPI records without an available verification method",
            "count_unavailable_field",
            {"records": "dt.selected_kpis"},
            "indicators",
            {"field": "verification"},
        ),
        _definition(
            "calc.missing_kpi_assumption_count",
            "Selected KPI records without an available assumption",
            "count_unavailable_field",
            {"records": "dt.selected_kpis"},
            "indicators",
            {"field": "assumptions"},
        ),
        _definition(
            "calc.scored_risks",
            "Risk collection with low=1, medium=2, high=3 and severity=probability×impact",
            "score_risks",
            {"records": "dt.risks"},
            None,
        ),
        _definition(
            "calc.priority_risks",
            "The three highest-severity risks, ties broken by source order",
            "top_by",
            {"records": "calc.scored_risks"},
            None,
            {
                "field": "severity",
                "order": "descending",
                "k": 3,
                "tie_break": "source_order",
            },
        ),
        _definition(
            "calc.highest_risk_score",
            "Maximum severity among the three priority risks",
            "max_field",
            {"records": "calc.priority_risks"},
            "score",
            {"field": "severity"},
        ),
        _definition(
            "calc.highest_risks",
            "Every priority risk tied at the maximum severity",
            "filter_equal",
            {
                "records": "calc.priority_risks",
                "target": "calc.highest_risk_score",
            },
            None,
            {"field": "severity"},
        ),
        _definition(
            "calc.highest_risk_count",
            "Number of priority risks tied at the maximum severity",
            "count_records",
            {"records": "calc.highest_risks"},
            "risks",
        ),
        _definition(
            "calc.project_cost_vs_reference",
            "Project cost divided by the frozen ClimateFund20 v1 baseline reference",
            "divide",
            {
                "numerator": "dt.project.total_cost_usd",
                "denominator": "reference.climatefund20.v1.average_project_cost_usd",
            },
            "x",
        ),
        _definition(
            "calc.ghg_reduction_vs_reference",
            "Canonical GHG reduction divided by the frozen baseline reference",
            "divide",
            {
                "numerator": "dt.project.ghg_reduction_tco2e",
                "denominator": "reference.climatefund20.v1.average_ghg_reduction_tco2e",
            },
            "x",
        ),
        _definition(
            "calc.project_cost_position",
            "Neutral comparison of project cost with the frozen baseline reference",
            "compare",
            {
                "left": "dt.project.total_cost_usd",
                "right": "reference.climatefund20.v1.average_project_cost_usd",
            },
            "comparison",
        ),
        _definition(
            "calc.ghg_reduction_position",
            "Neutral comparison of canonical GHG reduction with the frozen baseline reference",
            "compare",
            {
                "left": "dt.project.ghg_reduction_tco2e",
                "right": "reference.climatefund20.v1.average_ghg_reduction_tco2e",
            },
            "comparison",
        ),
        _definition(
            "calc.total_cost_per_tco2e_position",
            "Neutral comparison of project cost per tCO2e with the frozen baseline reference",
            "compare",
            {
                "left": "calc.total_cost_per_tco2e",
                "right": "reference.climatefund20.v1.average_total_cost_per_tco2e",
            },
            "comparison",
        ),
        _definition(
            "calc.implementation_period_position",
            "Neutral comparison of implementation years with the frozen baseline reference",
            "compare",
            {
                "left": "dt.project.implementation_years",
                "right": "reference.climatefund20.v1.average_implementation_years",
            },
            "comparison",
        ),
        _definition(
            "calc.lifespan_position",
            "Neutral comparison of lifespan with the frozen baseline reference",
            "compare",
            {
                "left": "dt.project.lifespan_years",
                "right": "reference.climatefund20.v1.average_lifespan_years",
            },
            "comparison",
        ),
        _definition(
            "calc.country_count_position",
            "Neutral comparison of country count with the frozen baseline reference",
            "compare",
            {
                "left": "calc.country_count",
                "right": "reference.climatefund20.v1.average_country_count",
            },
            "comparison",
        ),
    ]
    return {item["id"]: item for item in definitions}


def _definition(
    result_id: str,
    description: str,
    operation_id: str,
    input_ids: dict[str, str],
    unit: str | None,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": result_id,
        "kind": "calculation_definition",
        "description": description,
        "operation_id": operation_id,
        "input_ids": deepcopy(input_ids),
        "parameters": deepcopy(parameters or {}),
        "unit": unit,
    }


def operation_signatures() -> dict[str, dict[str, Any]]:
    return {
        "sum": {"input_roles": "one or more numeric roles", "parameters": {}},
        "subtract": {
            "input_roles": ["minuend", "subtrahend"],
            "parameters": {},
        },
        "divide": {
            "input_roles": ["numerator", "denominator"],
            "parameters": {},
        },
        "percentage": {
            "input_roles": ["part", "whole"],
            "parameters": {},
        },
        "count_records": {"input_roles": ["records"], "parameters": {}},
        "count_unavailable_field": {
            "input_roles": ["records"],
            "parameters": ["field"],
        },
        "zero_status": {
            "input_roles": ["value"],
            "parameters": {},
        },
        "score_risks": {"input_roles": ["records"], "parameters": {}},
        "top_by": {
            "input_roles": ["records"],
            "parameters": ["field", "order", "k", "tie_break"],
        },
        "max_field": {
            "input_roles": ["records"],
            "parameters": ["field"],
        },
        "filter_equal": {
            "input_roles": ["records", "target"],
            "parameters": ["field"],
        },
        "compare": {
            "input_roles": ["left", "right"],
            "parameters": {},
        },
    }
