from __future__ import annotations

import math
import re
from typing import Any

from ..domain.catalogue import SECTION_CONTRACT
from ..domain.ids import missing_id
from .calculator import Calculator
from .evidence_store import EvidenceStore


CALCULATION_ROWS = [
    ("GCF funding total", "calc.gcf_funding_total"),
    ("Total funding sources", "calc.total_funding_sources"),
    ("Funding reconciliation gap", "calc.funding_reconciliation_gap"),
    ("Funding reconciliation status", "calc.funding_reconciliation_status"),
    ("GCF financing share", "calc.gcf_financing_share_pct"),
    ("Cofinance share", "calc.cofinance_share_pct"),
    ("Cofinance per GCF dollar", "calc.cofinance_per_gcf_dollar"),
    ("Total cost per tCO2e", "calc.total_cost_per_tco2e"),
    ("GCF cost per tCO2e", "calc.gcf_cost_per_tco2e"),
    ("tCO2e per total-cost dollar", "calc.tco2e_per_total_cost_dollar"),
    ("tCO2e per GCF dollar", "calc.tco2e_per_gcf_dollar"),
    (
        "Nominal cost per implementation year",
        "calc.nominal_cost_per_implementation_year",
    ),
    ("Implementation-to-impact ratio", "calc.implementation_to_impact_ratio"),
    ("Country count", "calc.country_count"),
    ("Selected KPI count", "calc.selected_kpi_count"),
    ("Missing KPI baselines", "calc.missing_kpi_baseline_count"),
    (
        "Missing KPI intermediate targets",
        "calc.missing_kpi_intermediate_count",
    ),
    ("Missing KPI final targets", "calc.missing_kpi_final_count"),
    (
        "Missing KPI verification methods",
        "calc.missing_kpi_verification_count",
    ),
    ("Missing KPI assumptions", "calc.missing_kpi_assumption_count"),
    ("Highest risk score", "calc.highest_risk_score"),
    ("Highest risks", "calc.highest_risks"),
    ("Highest risk count", "calc.highest_risk_count"),
    ("Project cost versus reference", "calc.project_cost_vs_reference"),
    ("GHG reduction versus reference", "calc.ghg_reduction_vs_reference"),
    ("Project cost position", "calc.project_cost_position"),
    ("GHG reduction position", "calc.ghg_reduction_position"),
]

REFERENCE_ROWS = [
    ("Average project cost", "reference.climatefund20.v1.average_project_cost_usd"),
    (
        "Average GHG reduction",
        "reference.climatefund20.v1.average_ghg_reduction_tco2e",
    ),
    (
        "Average implementation period",
        "reference.climatefund20.v1.average_implementation_years",
    ),
    ("Average lifespan", "reference.climatefund20.v1.average_lifespan_years"),
    ("Average country count", "reference.climatefund20.v1.average_country_count"),
    (
        "Average total cost per tCO2e",
        "reference.climatefund20.v1.average_total_cost_per_tco2e",
    ),
]

COMPARISON_ROWS = [
    (
        "Total cost per tCO2e",
        "calc.total_cost_per_tco2e",
        "reference.climatefund20.v1.average_total_cost_per_tco2e",
        "calc.total_cost_per_tco2e_position",
    ),
    (
        "Implementation period",
        "dt.project.implementation_years",
        "reference.climatefund20.v1.average_implementation_years",
        "calc.implementation_period_position",
    ),
    (
        "Expected lifespan",
        "dt.project.lifespan_years",
        "reference.climatefund20.v1.average_lifespan_years",
        "calc.lifespan_position",
    ),
    (
        "Country count",
        "calc.country_count",
        "reference.climatefund20.v1.average_country_count",
        "calc.country_count_position",
    ),
]


def canonical_operations(calculator: Calculator) -> list[dict[str, Any]]:
    return [
        {
            "result_id": definition["id"],
            "operation_id": definition["operation_id"],
            "input_ids": definition["input_ids"],
            "parameters": definition["parameters"],
        }
        for definition in calculator.registry.values()
    ]


def calculate_all(calculator: Calculator) -> dict[str, Any]:
    return calculator.execute(canonical_operations(calculator))


def display(node: dict[str, Any], *, digits: int = 2) -> str:
    node_id = str(node.get("id") or "")
    if _is_not_applicable(node):
        return f"[not applicable]({missing_id(node_id)})"
    if node.get("status") != "available":
        return f"[missing]({missing_id(node_id)})"
    value = node.get("value")
    if node.get("kind") == "collection":
        rendered = f"{len(node.get('records') or [])} records"
    elif node.get("kind") == "calculated" and isinstance(value, list):
        names = []
        for record in value:
            field = record.get("fields", {}).get("name", {})
            if field.get("status") == "available":
                names.append(str(field.get("value")))
        rendered = "; ".join(names) if names else "none"
    elif isinstance(value, list):
        rendered = ", ".join(str(item) for item in value) or "none"
    elif isinstance(value, float):
        rendered = f"{value:,.{digits}f}"
    elif isinstance(value, int) and not isinstance(value, bool):
        rendered = f"{value:,}"
    else:
        rendered = str(value)
    unit = node.get("unit")
    if unit and unit not in {"comparison", "score", "x"}:
        rendered = f"{rendered} {unit}"
    elif unit == "x":
        rendered = f"{rendered}x"
    return f"[{escape_link_text(rendered)}]({node_id})"


def field_display(record: dict[str, Any], field_name: str) -> str:
    field = record.get("fields", {}).get(field_name)
    if not isinstance(field, dict):
        return f"[missing]({missing_id(record['id'] + '.' + field_name)})"
    return display(field)


def escape_cell(value: object) -> str:
    return (
        str(value)
        .replace("|", "\\|")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def escape_link_text(value: object) -> str:
    return (
        escape_cell(value)
        .replace("[", "&#91;")
        .replace("]", "&#93;")
    )


def prose_excerpt(node: dict[str, Any], *, limit: int = 720) -> str:
    node_id = str(node.get("id") or "")
    if _is_not_applicable(node):
        return f"[not applicable]({missing_id(node_id)})"
    if node.get("status") != "available":
        return f"[missing]({missing_id(node_id)})"
    text = " ".join(str(node.get("value") or "").split())
    sentences = re.split(r"(?<=[.!?])\s+", text)
    outcome_pattern = re.compile(
        r"\b(project aims|project will|expected to|objective|designed to|seeks to)\b",
        re.I,
    )
    selected = next(
        (sentence for sentence in sentences if outcome_pattern.search(sentence)),
        "",
    )
    if selected:
        text = selected
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip() + "…"
    return f"[{escape_link_text(text)}]({node_id})"


def _is_not_applicable(node: dict[str, Any]) -> bool:
    if node.get("status") in {"not_applicable", "not_applicable_dependency"}:
        return True
    applicability = node.get("applicability")
    return bool(
        isinstance(applicability, dict)
        and applicability.get("status") == "not_applicable"
        and applicability.get("arithmetic_placeholder") is True
    )


def table(headers: list[str], rows: list[list[str]]) -> str:
    header = "| " + " | ".join(headers) + " |"
    marker = "| " + " | ".join("---" for _ in headers) + " |"
    body = [
        "| " + " | ".join(escape_cell(cell) for cell in row) + " |"
        for row in rows
    ]
    return "\n".join([header, marker, *body])


def render_section(section_id: str, store: EvidenceStore) -> str:
    if section_id == "project_overview":
        return render_overview(store)
    if section_id == "scale_and_calculated_indicators":
        return render_scale(store)
    if section_id == "selected_performance_indicators":
        return render_kpis(store)
    if section_id == "priority_risks":
        return render_risks(store)
    if section_id == "overall_evidence_summary":
        return render_summary(store)
    raise ValueError(f"unknown section {section_id!r}")


def render_report(store: EvidenceStore) -> str:
    sections = [render_section(item["id"], store) for item in SECTION_CONTRACT]
    return "# Project Investment and Performance Profile\n\n" + "\n\n".join(sections) + "\n"


def render_overview(store: EvidenceStore) -> str:
    code = store.get("dt.project.code")
    title = store.get("dt.project.title")
    entity = store.get("dt.project.entity_name")
    total_cost = store.get("dt.project.total_cost_usd")
    ghg = store.get("dt.project.ghg_reduction_tco2e")
    countries = store.get("dt.project.countries")
    country_names = [
        str(record["fields"]["name"]["value"])
        for record in countries.get("records", [])
        if record["fields"]["name"].get("status") == "available"
    ]
    country_display = (
        f"[{', '.join(country_names)}](dt.project.countries)"
        if country_names
        else f"[missing]({missing_id('dt.project.countries')})"
    )
    prose = (
        f"{display(code)} — {display(title)} is a {display(store.get('dt.project.type'))} "
        f"project in the {display(store.get('dt.project.sector'))} sector, classified "
        f"as {display(store.get('dt.project.size'))}, spanning {country_display} and "
        f"delivered with {display(entity)}. Its intervention is described as "
        f"{prose_excerpt(store.get('dt.project.description'))}. The project has a "
        f"total cost of {display(total_cost)}, comprising GCF financing of "
        f"{display(store.get('dt.project.gcf_financing_usd'))} and cofinance of "
        f"{display(store.get('dt.project.cofinance_usd'))}; implementation lasts "
        f"{display(store.get('dt.project.implementation_years'))}, expected impact "
        f"lasts {display(store.get('dt.project.lifespan_years'))}, and canonical "
        f"lifetime mitigation is {display(ghg)}."
    )
    rows = [
        ["Project code", display(code)],
        ["Project title", display(title)],
        ["Type", display(store.get("dt.project.type"))],
        ["Sector", display(store.get("dt.project.sector"))],
        ["Size", display(store.get("dt.project.size"))],
        ["Countries", country_display],
        ["Accredited entity", display(entity)],
        ["Total project cost", display(total_cost)],
        [
            "Implementation period",
            display(store.get("dt.project.implementation_years")),
        ],
        ["Expected lifespan", display(store.get("dt.project.lifespan_years"))],
        ["Canonical GHG reduction", display(ghg)],
    ]
    return (
        "## Project overview\n\n"
        + prose
        + "\n\n### Project characteristics\n\n"
        + table(["Project field", "Value"], rows)
    )


def render_scale(store: EvidenceStore) -> str:
    rows = [[label, display(store.get(node_id))] for label, node_id in CALCULATION_ROWS]
    interpretation = (
        f"GCF funding totals {display(store.get('calc.gcf_funding_total'))}, and "
        f"with cofinance the sources total {display(store.get('calc.total_funding_sources'))}; "
        f"the reconciliation gap is {display(store.get('calc.funding_reconciliation_gap'))}, "
        f"giving a status of {display(store.get('calc.funding_reconciliation_status'))}. "
        f"GCF supplies {display(store.get('calc.gcf_financing_share_pct'))} and "
        f"cofinance {display(store.get('calc.cofinance_share_pct'))} of project cost, "
        f"with {display(store.get('calc.cofinance_per_gcf_dollar'))} of cofinance per "
        f"GCF dollar. Total and GCF cost intensities are "
        f"{display(store.get('calc.total_cost_per_tco2e'))} and "
        f"{display(store.get('calc.gcf_cost_per_tco2e'))}, while the inverse "
        f"intensities are {display(store.get('calc.tco2e_per_total_cost_dollar'))} "
        f"and {display(store.get('calc.tco2e_per_gcf_dollar'))}. Nominal annual "
        f"cost is {display(store.get('calc.nominal_cost_per_implementation_year'))}, "
        f"the implementation-to-impact ratio is "
        f"{display(store.get('calc.implementation_to_impact_ratio'))}, and the "
        f"country count is {display(store.get('calc.country_count'))}. Relative to "
        f"average project cost {display(store.get('reference.climatefund20.v1.average_project_cost_usd'))}, "
        f"project cost is {display(store.get('calc.project_cost_vs_reference'))} and "
        f"has position {display(store.get('calc.project_cost_position'))}; relative "
        f"to average GHG reduction {display(store.get('reference.climatefund20.v1.average_ghg_reduction_tco2e'))}, "
        f"GHG reduction is {display(store.get('calc.ghg_reduction_vs_reference'))} "
        f"with position {display(store.get('calc.ghg_reduction_position'))}. Total "
        f"cost per tCO2e has position "
        f"{display(store.get('calc.total_cost_per_tco2e_position'))} against "
        f"{display(store.get('reference.climatefund20.v1.average_total_cost_per_tco2e'))}; "
        f"implementation has position {display(store.get('calc.implementation_period_position'))} "
        f"against {display(store.get('reference.climatefund20.v1.average_implementation_years'))}, "
        f"lifespan has position {display(store.get('calc.lifespan_position'))} "
        f"against {display(store.get('reference.climatefund20.v1.average_lifespan_years'))}, "
        f"and country count has position {display(store.get('calc.country_count_position'))} "
        f"against {display(store.get('reference.climatefund20.v1.average_country_count'))}."
    )
    reference_rows = [
        [label, display(store.get(node_id))]
        for label, node_id in REFERENCE_ROWS
    ]
    comparison_rows = [
        [
            label,
            display(store.get(project_id)),
            display(store.get(reference_id)),
            display(store.get(position_id)),
        ]
        for label, project_id, reference_id, position_id in COMPARISON_ROWS
    ]
    return (
        "## Scale and calculated indicators\n\n"
        + table(["Calculated indicator", "Value"], rows)
        + "\n\n"
        + interpretation
        + "\n\n### Twenty-project baseline references\n\n"
        + table(["Reference indicator", "Baseline reference"], reference_rows)
        + "\n\n"
        + table(
            ["Metric", "Project", "Reference", "Relative position"],
            comparison_rows,
        )
    )


def render_kpis(store: EvidenceStore) -> str:
    collection = store.get("dt.selected_kpis")
    rows = []
    for record in collection.get("records", []):
        rows.append(
            [
                field_display(record, "indicator"),
                field_display(record, "baseline"),
                field_display(record, "intermediate_target"),
                field_display(record, "final_target"),
                field_display(record, "verification"),
                field_display(record, "assumptions"),
            ]
        )
    discussions = []
    for record in collection.get("records", []):
        discussions.append(
            f"{field_display(record, 'indicator')} has baseline "
            f"{field_display(record, 'baseline')}, intermediate target "
            f"{field_display(record, 'intermediate_target')}, final target "
            f"{field_display(record, 'final_target')}, verification through "
            f"{field_display(record, 'verification')}, and assumption "
            f"{field_display(record, 'assumptions')}."
        )
    interpretation = " ".join(discussions) + (
        f" The selection contains {display(store.get('calc.selected_kpi_count'))}; "
        f"missing-field counts are {display(store.get('calc.missing_kpi_baseline_count'))} "
        f"for baselines, {display(store.get('calc.missing_kpi_intermediate_count'))} "
        f"for intermediate targets, {display(store.get('calc.missing_kpi_final_count'))} "
        f"for final targets, {display(store.get('calc.missing_kpi_verification_count'))} "
        f"for verification methods, and {display(store.get('calc.missing_kpi_assumption_count'))} "
        f"for assumptions."
    )
    return (
        "## Selected performance indicators\n\n"
        + table(
            [
                "Indicator",
                "Baseline",
                "Intermediate target",
                "Final target",
                "Verification",
                "Assumptions",
            ],
            rows,
        )
        + "\n\n"
        + interpretation
    )


def render_risks(store: EvidenceStore) -> str:
    priority = store.get("calc.priority_risks")
    rows = []
    if priority.get("status") == "available":
        for record in priority.get("value", []):
            rows.append(
                [
                    field_display(record, "name"),
                    field_display(record, "type"),
                    field_display(record, "probability"),
                    field_display(record, "impact"),
                    field_display(record, "severity"),
                    field_display(record, "description"),
                    field_display(record, "mitigation"),
                ]
            )
    else:
        rows = [
            [
                f"[missing]({missing_id('calc.priority_risks')})",
                "",
                "",
                "",
                "",
                "",
                "",
            ]
            for _ in range(3)
        ]
    highest = store.get("calc.highest_risks")
    discussion = []
    if highest.get("status") == "available":
        for record in highest.get("value", []):
            discussion.append(
                f"{field_display(record, 'name')} is described by "
                f"{field_display(record, 'description')} and is addressed through "
                f"{field_display(record, 'mitigation')}."
            )
    synthesis = (
        f"The highest severity is {display(store.get('calc.highest_risk_score'))}; "
        f"the {display(store.get('calc.highest_risk_count'))} at that severity are "
        f"{display(highest)}."
    )
    if discussion:
        synthesis += " " + " ".join(discussion)
    return (
        "## Priority risks\n\n"
        + table(
            [
                "Risk",
                "Type",
                "Probability",
                "Impact",
                "Severity",
                "Description",
                "Mitigation",
            ],
            rows,
        )
        + "\n\n"
        + synthesis
    )


def render_summary(store: EvidenceStore) -> str:
    return (
        "## Overall evidence summary\n\n"
        f"{display(store.get('dt.project.title'))} combines a project cost of "
        f"{display(store.get('dt.project.total_cost_usd'))} with canonical mitigation "
        f"of {display(store.get('dt.project.ghg_reduction_tco2e'))}. Funding is "
        f"{display(store.get('calc.funding_reconciliation_status'))}, the GCF share "
        f"is {display(store.get('calc.gcf_financing_share_pct'))}, and cofinance per "
        f"GCF dollar is {display(store.get('calc.cofinance_per_gcf_dollar'))}. Total "
        f"cost intensity is {display(store.get('calc.total_cost_per_tco2e'))} with "
        f"reference position {display(store.get('calc.total_cost_per_tco2e_position'))}; "
        f"the project-cost and GHG-reduction positions are "
        f"{display(store.get('calc.project_cost_position'))} and "
        f"{display(store.get('calc.ghg_reduction_position'))}, while implementation, "
        f"lifespan and country-count positions are "
        f"{display(store.get('calc.implementation_period_position'))}, "
        f"{display(store.get('calc.lifespan_position'))} and "
        f"{display(store.get('calc.country_count_position'))}. The KPI evidence "
        f"contains {display(store.get('calc.selected_kpi_count'))}, with missing "
        f"counts of {display(store.get('calc.missing_kpi_baseline_count'))} baselines, "
        f"{display(store.get('calc.missing_kpi_intermediate_count'))} intermediate "
        f"targets, {display(store.get('calc.missing_kpi_final_count'))} final targets, "
        f"{display(store.get('calc.missing_kpi_verification_count'))} verification "
        f"methods and {display(store.get('calc.missing_kpi_assumption_count'))} "
        f"assumptions. The highest risk severity is "
        f"{display(store.get('calc.highest_risk_score'))}, shared by "
        f"{display(store.get('calc.highest_risk_count'))}: "
        f"{display(store.get('calc.highest_risks'))}."
    )
