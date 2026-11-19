from __future__ import annotations

from typing import Any

from .calculations import calculation_registry, operation_signatures


SECTION_CONTRACT = [
    {
        "id": "project_overview",
        "heading": "Project overview",
        "required_blocks": [
            {
                "id": "project_overview.prose",
                "kind": "prose",
                "content_contract": {
                    "identity": (
                        "Identify the project by code and title, then state its "
                        "type, sector, size, countries and accredited entity."
                    ),
                    "intervention": (
                        "Briefly describe the intervention and intended climate "
                        "outcome using the project description."
                    ),
                    "finance_and_scale": (
                        "State total project cost, GCF financing, cofinance, the "
                        "implementation period, expected lifespan and canonical "
                        "GHG reduction."
                    ),
                    "scope": (
                        "Use only project front matter; do not discuss calculated "
                        "indicators, selected KPIs or risks."
                    ),
                    "format": "Use one Markdown paragraph.",
                },
            },
            {
                "id": "project_overview.characteristics_heading",
                "kind": "subsection",
                "heading": "Project characteristics",
            },
            {"id": "project_overview.characteristics_table", "kind": "table"},
        ],
    },
    {
        "id": "scale_and_calculated_indicators",
        "heading": "Scale and calculated indicators",
        "required_blocks": [
            {"id": "scale.calculation_table", "kind": "table"},
            {
                "id": "scale.interpretation",
                "kind": "prose",
                "content_contract": {
                    "finance": (
                        "Interpret total GCF funding, total funding sources, the "
                        "reconciliation gap and status, GCF and cofinance shares, "
                        "and cofinance per GCF dollar."
                    ),
                    "mitigation_efficiency": (
                        "State total and GCF cost per tCO2e and both inverse "
                        "tCO2e-per-dollar measures."
                    ),
                    "delivery_scale": (
                        "State nominal annual cost, the implementation-to-impact "
                        "ratio and country count."
                    ),
                    "reference_comparisons": (
                        "Compare project cost, GHG reduction, total cost per "
                        "tCO2e, implementation period, lifespan and country count "
                        "with their frozen twenty-project references. Include the "
                        "two project-to-reference ratios and every relative "
                        "position."
                    ),
                    "scope": (
                        "Use only scale, calculation and frozen-reference evidence; "
                        "do not discuss selected KPI records or individual risks."
                    ),
                    "format": "Use one Markdown paragraph.",
                },
            },
            {
                "id": "scale.reference_heading",
                "kind": "subsection",
                "heading": "Twenty-project baseline references",
            },
            {"id": "scale.reference_table", "kind": "table"},
            {"id": "scale.comparison_table", "kind": "table"},
        ],
    },
    {
        "id": "selected_performance_indicators",
        "heading": "Selected performance indicators",
        "required_blocks": [
            {"id": "kpis.table", "kind": "table"},
            {
                "id": "kpis.interpretation",
                "kind": "prose",
                "content_contract": {
                    "each_indicator": (
                        "Discuss all five selected indicators in table order. For "
                        "each, state its indicator name, baseline, intermediate "
                        "target, final target, verification method and assumption, "
                        "preserving any explicit missing states."
                    ),
                    "completeness": (
                        "State the selected-indicator count and the counts missing "
                        "a baseline, intermediate target, final target, verification "
                        "method and assumption."
                    ),
                    "scope": (
                        "Use only selected-KPI evidence and its deterministic "
                        "completeness counts; do not introduce project finance, "
                        "scale comparisons or risks."
                    ),
                    "format": "Use one Markdown paragraph after the KPI table.",
                },
            },
        ],
    },
    {
        "id": "priority_risks",
        "heading": "Priority risks",
        "required_blocks": [
            {"id": "risks.table", "kind": "table"},
            {
                "id": "risks.synthesis",
                "kind": "prose",
                "content_contract": {
                    "maximum_severity": (
                        "State the maximum severity score."
                    ),
                    "included_risks": (
                        "Identify every and only priority risk tied at that maximum "
                        "severity, and state the tied set."
                    ),
                    "discuss_each": (
                        "For each tied record, discuss its name, description and "
                        "mitigation."
                    ),
                    "excluded_risks": (
                        "Do not discuss or cite any risk that is not tied at the "
                        "maximum severity."
                    ),
                    "format": (
                        "Use one Markdown paragraph after the three-row risk table."
                    ),
                },
            },
        ],
    },
    {
        "id": "overall_evidence_summary",
        "heading": "Overall evidence summary",
        "required_blocks": [
            {
                "id": "summary.prose",
                "kind": "prose",
                "content_contract": {
                    "identity_and_scale": (
                        "Name the project and state total project cost and canonical "
                        "GHG reduction."
                    ),
                    "finance_and_efficiency": (
                        "Summarize funding reconciliation status, GCF financing "
                        "share, cofinance per GCF dollar, total cost per tCO2e and "
                        "its reference position."
                    ),
                    "reference_profile": (
                        "State the project cost, GHG reduction, implementation "
                        "period, lifespan and country-count positions relative to "
                        "the frozen reference."
                    ),
                    "kpi_evidence": (
                        "State the selected-indicator count and each deterministic "
                        "missing-field count."
                    ),
                    "risk_evidence": (
                        "State the maximum risk severity, the number of risks tied "
                        "at that severity and the complete tied risk set."
                    ),
                    "scope": (
                        "Synthesize only these specified cross-section facts; do "
                        "not select or rank a subjectively important KPI."
                    ),
                    "format": "Use one Markdown paragraph.",
                },
            },
        ],
    },
]

TABLE_CONTRACTS = {
    "project_overview.characteristics_table": {
        "headers": ["Project field", "Value"],
        "row_keys": [
            "Project code",
            "Project title",
            "Type",
            "Sector",
            "Size",
            "Countries",
            "Accredited entity",
            "Total project cost",
            "Implementation period",
            "Expected lifespan",
            "Canonical GHG reduction",
        ],
        "row_sources": {
            "Project code": "dt.project.code",
            "Project title": "dt.project.title",
            "Type": "dt.project.type",
            "Sector": "dt.project.sector",
            "Size": "dt.project.size",
            "Countries": "dt.project.countries",
            "Accredited entity": "dt.project.entity_name",
            "Total project cost": "dt.project.total_cost_usd",
            "Implementation period": "dt.project.implementation_years",
            "Expected lifespan": "dt.project.lifespan_years",
            "Canonical GHG reduction": "dt.project.ghg_reduction_tco2e",
        },
        "special_display": {
            "Countries": (
                "join exact country name field values in source order with ', ' "
                "and cite dt.project.countries"
            )
        },
    },
    "scale.calculation_table": {
        "headers": ["Calculated indicator", "Value"],
        "row_keys": [
            "GCF funding total",
            "Total funding sources",
            "Funding reconciliation gap",
            "Funding reconciliation status",
            "GCF financing share",
            "Cofinance share",
            "Cofinance per GCF dollar",
            "Total cost per tCO2e",
            "GCF cost per tCO2e",
            "tCO2e per total-cost dollar",
            "tCO2e per GCF dollar",
            "Nominal cost per implementation year",
            "Implementation-to-impact ratio",
            "Country count",
            "Selected KPI count",
            "Missing KPI baselines",
            "Missing KPI intermediate targets",
            "Missing KPI final targets",
            "Missing KPI verification methods",
            "Missing KPI assumptions",
            "Highest risk score",
            "Highest risks",
            "Highest risk count",
            "Project cost versus reference",
            "GHG reduction versus reference",
            "Project cost position",
            "GHG reduction position",
        ],
        "row_sources": {
            "GCF funding total": "calc.gcf_funding_total",
            "Total funding sources": "calc.total_funding_sources",
            "Funding reconciliation gap": "calc.funding_reconciliation_gap",
            "Funding reconciliation status": (
                "calc.funding_reconciliation_status"
            ),
            "GCF financing share": "calc.gcf_financing_share_pct",
            "Cofinance share": "calc.cofinance_share_pct",
            "Cofinance per GCF dollar": "calc.cofinance_per_gcf_dollar",
            "Total cost per tCO2e": "calc.total_cost_per_tco2e",
            "GCF cost per tCO2e": "calc.gcf_cost_per_tco2e",
            "tCO2e per total-cost dollar": (
                "calc.tco2e_per_total_cost_dollar"
            ),
            "tCO2e per GCF dollar": "calc.tco2e_per_gcf_dollar",
            "Nominal cost per implementation year": (
                "calc.nominal_cost_per_implementation_year"
            ),
            "Implementation-to-impact ratio": (
                "calc.implementation_to_impact_ratio"
            ),
            "Country count": "calc.country_count",
            "Selected KPI count": "calc.selected_kpi_count",
            "Missing KPI baselines": "calc.missing_kpi_baseline_count",
            "Missing KPI intermediate targets": (
                "calc.missing_kpi_intermediate_count"
            ),
            "Missing KPI final targets": "calc.missing_kpi_final_count",
            "Missing KPI verification methods": (
                "calc.missing_kpi_verification_count"
            ),
            "Missing KPI assumptions": "calc.missing_kpi_assumption_count",
            "Highest risk score": "calc.highest_risk_score",
            "Highest risks": "calc.highest_risks",
            "Highest risk count": "calc.highest_risk_count",
            "Project cost versus reference": "calc.project_cost_vs_reference",
            "GHG reduction versus reference": "calc.ghg_reduction_vs_reference",
            "Project cost position": "calc.project_cost_position",
            "GHG reduction position": "calc.ghg_reduction_position",
        },
    },
    "scale.reference_table": {
        "headers": ["Reference indicator", "Baseline reference"],
        "row_keys": [
            "Average project cost",
            "Average GHG reduction",
            "Average implementation period",
            "Average lifespan",
            "Average country count",
            "Average total cost per tCO2e",
        ],
        "row_sources": {
            "Average project cost": (
                "reference.climatefund20.v1.average_project_cost_usd"
            ),
            "Average GHG reduction": (
                "reference.climatefund20.v1.average_ghg_reduction_tco2e"
            ),
            "Average implementation period": (
                "reference.climatefund20.v1.average_implementation_years"
            ),
            "Average lifespan": (
                "reference.climatefund20.v1.average_lifespan_years"
            ),
            "Average country count": (
                "reference.climatefund20.v1.average_country_count"
            ),
            "Average total cost per tCO2e": (
                "reference.climatefund20.v1.average_total_cost_per_tco2e"
            ),
        },
    },
    "scale.comparison_table": {
        "headers": ["Metric", "Project", "Reference", "Relative position"],
        "row_keys": [
            "Total cost per tCO2e",
            "Implementation period",
            "Expected lifespan",
            "Country count",
        ],
        "row_sources": {
            "Total cost per tCO2e": {
                "Project": "calc.total_cost_per_tco2e",
                "Reference": (
                    "reference.climatefund20.v1."
                    "average_total_cost_per_tco2e"
                ),
                "Relative position": (
                    "calc.total_cost_per_tco2e_position"
                ),
            },
            "Implementation period": {
                "Project": "dt.project.implementation_years",
                "Reference": (
                    "reference.climatefund20.v1."
                    "average_implementation_years"
                ),
                "Relative position": (
                    "calc.implementation_period_position"
                ),
            },
            "Expected lifespan": {
                "Project": "dt.project.lifespan_years",
                "Reference": (
                    "reference.climatefund20.v1.average_lifespan_years"
                ),
                "Relative position": "calc.lifespan_position",
            },
            "Country count": {
                "Project": "calc.country_count",
                "Reference": (
                    "reference.climatefund20.v1.average_country_count"
                ),
                "Relative position": "calc.country_count_position",
            },
        },
    },
    "kpis.table": {
        "headers": [
            "Indicator",
            "Baseline",
            "Intermediate target",
            "Final target",
            "Verification",
            "Assumptions",
        ],
        "row_count": 5,
        "record_source": "dt.selected_kpis",
        "column_fields": {
            "Indicator": "indicator",
            "Baseline": "baseline",
            "Intermediate target": "intermediate_target",
            "Final target": "final_target",
            "Verification": "verification",
            "Assumptions": "assumptions",
        },
        "record_order": "collection source order",
    },
    "risks.table": {
        "headers": [
            "Risk",
            "Type",
            "Probability",
            "Impact",
            "Severity",
            "Description",
            "Mitigation",
        ],
        "row_count": 3,
        "record_source": "calc.priority_risks",
        "column_fields": {
            "Risk": "name",
            "Type": "type",
            "Probability": "probability",
            "Impact": "impact",
            "Severity": "severity",
            "Description": "description",
            "Mitigation": "mitigation",
        },
        "record_order": "calculated collection order",
    },
}


def report_output_contract() -> dict[str, Any]:
    return {
        "title": "Project Investment and Performance Profile",
        "sections": SECTION_CONTRACT,
        "tables": TABLE_CONTRACTS,
    }


def section_output_contract(section_id: str) -> dict[str, Any]:
    contract = next(
        item for item in SECTION_CONTRACT if item["id"] == section_id
    )
    block_ids = {item["id"] for item in contract["required_blocks"]}
    return {
        "section": contract,
        "tables": {
            table_id: table_contract
            for table_id, table_contract in TABLE_CONTRACTS.items()
            if table_id in block_ids
        },
    }


def build_catalogue(
    project_twins: list[dict[str, Any]], reference: dict[str, Any]
) -> dict[str, Any]:
    first = project_twins[0]
    data_entries: dict[str, Any] = {}
    for node_id, node in first["nodes"].items():
        data_entries[node_id] = {
            key: node.get(key)
            for key in ("id", "kind", "description", "unit")
        }
    for collection_id, item in first["collections"].items():
        data_entries[collection_id] = {
            "id": collection_id,
            "kind": "collection",
            "description": item["description"],
            "record_schema": item["record_schema"],
        }
    for node_id, node in reference["nodes"].items():
        data_entries[node_id] = {
            key: node.get(key)
            for key in ("id", "kind", "description", "unit")
        }
    return {
        "schema_version": "react_report.data_catalogue/v2",
        "report_title": "Project Investment and Performance Profile",
        "sections": SECTION_CONTRACT,
        "tables": TABLE_CONTRACTS,
        "data": data_entries,
        "calculations": calculation_registry(),
        "operations": operation_signatures(),
        "tools": {
            "get_data": {
                "terminal": False,
                "arguments": {"ids": "array of documented IDs"},
            },
            "calculate": {
                "terminal": False,
                "arguments": {
                    "operations": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": [
                                "result_id",
                                "operation_id",
                                "input_ids",
                                "parameters",
                            ],
                            "properties": {
                                "result_id": (
                                    "complete canonical calc.* ID; equal to the "
                                    "calculation catalogue key"
                                ),
                                "operation_id": (
                                    "copy exactly from that catalogue entry"
                                ),
                                "input_ids": (
                                    "copy the complete role-to-node-ID object "
                                    "exactly from that catalogue entry"
                                ),
                                "parameters": (
                                    "copy the complete parameters object exactly "
                                    "from that catalogue entry"
                                ),
                            },
                            "forbidden": [
                                "calculation_id",
                                "formula",
                                "value",
                            ],
                        },
                    }
                },
                "example": {
                    "operations": [
                        {
                            "result_id": "calc.country_count",
                            "operation_id": "count_records",
                            "input_ids": {
                                "records": "dt.project.countries",
                            },
                            "parameters": {},
                        }
                    ]
                },
            },
            "create_report": {
                "terminal": True,
                "arguments": {"markdown": "complete report Markdown"},
            },
            "create_section": {
                "terminal": True,
                "arguments": {
                    "section_id": "requested section ID",
                    "mode": "create, keep, or replace",
                    "markdown": "required for create and replace",
                },
            },
        },
        "citation_format": "[visible text](node_id)",
        "missing_format": "[missing](missing.node_id)",
        "output_rules": {
            "block_order": (
                "Emit exactly required_blocks in listed order, with no extra "
                "headings, prose blocks, or tables."
            ),
            "prose": (
                "Each required prose block is one Markdown paragraph. Prose may "
                "synthesize evidence, but citations wrap the supported visible "
                "claim rather than a generic label."
            ),
            "table_values": (
                "Use exact evidence or calculated values in table cells; do not "
                "paraphrase, rename, summarize, translate, or correct them."
            ),
            "table_citations": (
                "Wrap the complete displayed table-cell value as "
                "[exact value](node_id)."
            ),
            "table_text_normalization": (
                "Replace source newlines with spaces, escape literal | as \\|, "
                "and encode literal [ and ] inside a displayed value as &#91; "
                "and &#93;."
            ),
            "number_format": (
                "Use comma thousands separators for integers and two decimal "
                "places for floats. Use the same unit label, placement, and "
                "spacing as retrieved factoids with that unit; do not substitute "
                "symbols or aliases. Do not display a unit for dimensionless "
                "comparison or score values. Append x directly for ratio units."
            ),
        },
        "update_precedence": "The updated evidence store supersedes the prior report.",
    }
