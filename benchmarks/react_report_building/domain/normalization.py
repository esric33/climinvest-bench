from __future__ import annotations

from typing import Any

from .finance import project_finance
from .kpi_selection import clean_kpis, select_kpis_from_candidates
from .records import collection, record, scalar


EXCLUDED_PROJECT = "FP105"


def source_provenance(project: dict[str, Any], locator: str) -> dict[str, Any]:
    return {
        "document_id": f"proposal.{str(project.get('code') or '').lower()}",
        "url": project.get("proposal"),
        "locator": locator,
    }


def normalize_project(
    project: dict[str, Any],
    finance_enrichment: dict[str, Any],
    canonical_overrides: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    project_id = str(project["code"])
    if project_id == EXCLUDED_PROJECT:
        raise ValueError("FP105 is excluded from this benchmark")
    basic = project.get("basic_info") or {}
    impact = project.get("impact_area") or {}
    mitigation = impact.get("mitigation") or {}
    adaptation = impact.get("adaptation") or {}
    entity = project.get("entity") or {}
    countries = project.get("countries") or []
    finance = project_finance(project_id, finance_enrichment)
    project_overrides = (canonical_overrides or {}).get(project_id) or {}
    ghg_override = project_overrides.get("ghg_reduction_tco2e") or {}
    ghg_value = (
        ghg_override.get("value")
        if "value" in ghg_override
        else mitigation.get("ghg_reduction")
    )
    nodes: dict[str, dict[str, Any]] = {}

    def add(node: dict[str, Any]) -> None:
        nodes[node["id"]] = node

    direct_fields = [
        ("dt.project.code", "Project code", project_id, None),
        ("dt.project.title", "Project title", str(basic.get("title") or "").strip(), None),
        ("dt.project.description", "Project description", basic.get("description"), None),
        ("dt.project.type", "Project type", basic.get("type"), None),
        ("dt.project.sector", "Project sector", basic.get("sector"), None),
        ("dt.project.size", "Project size", basic.get("size"), None),
        ("dt.project.entity_name", "Accredited entity name", entity.get("name"), None),
        ("dt.project.entity_code", "Accredited entity code", entity.get("code"), None),
        ("dt.project.entity_type", "Accredited entity type", entity.get("type"), None),
        ("dt.project.entity_size", "Accredited entity size", entity.get("size"), None),
        ("dt.project.entity_sector", "Accredited entity sector", entity.get("sector"), None),
        ("dt.project.total_cost_usd", "Total approved project cost", basic.get("cost"), "USD"),
        (
            "dt.project.implementation_years",
            "Expected implementation period",
            basic.get("expected_implementation_period"),
            "years",
        ),
        (
            "dt.project.lifespan_years",
            "Expected project or asset lifespan",
            basic.get("expected_lifespan"),
            "years",
        ),
        (
            "dt.project.ghg_reduction_tco2e",
            "Canonical expected lifetime GHG reduction",
            ghg_value,
            "tCO2e",
        ),
        (
            "dt.project.mitigation_areas",
            "Mitigation areas",
            sorted(key for key, enabled in (mitigation.get("areas") or {}).items() if enabled),
            None,
        ),
        (
            "dt.project.energy_technologies",
            "Energy technologies",
            sorted(key for key, enabled in (mitigation.get("energy") or {}).items() if enabled),
            None,
        ),
        (
            "dt.project.adaptation_areas",
            "Adaptation areas",
            sorted(key for key, enabled in (adaptation.get("areas") or {}).items() if enabled),
            None,
        ),
    ]
    for node_id, description, value, unit in direct_fields:
        add(
            scalar(
                node_id,
                description,
                value,
                unit=unit,
                provenance=source_provenance(project, node_id),
            )
        )
    if ghg_override:
        nodes["dt.project.ghg_reduction_tco2e"]["provenance"] = source_provenance(
            project,
            str(ghg_override.get("locator") or "canonical_overrides.ghg_reduction_tco2e"),
        )
        nodes["dt.project.ghg_reduction_tco2e"]["normalization"] = {
            "source_value": mitigation.get("ghg_reduction"),
            "reason": ghg_override.get("reason"),
        }

    for field, item in finance.items():
        locator = str(item.get("locator") or f"enrichment.{field}")
        provenance = source_provenance(project, locator)
        if locator.startswith("GCF project "):
            provenance["document_id"] = f"gcf_portfolio.{project_id.lower()}"
            provenance["url"] = project.get("url")
        add(
            scalar(
                f"dt.project.{field}",
                field.replace("_", " ").replace("usd", "USD").title(),
                item["value"],
                unit="USD",
                provenance=provenance,
            )
        )

    country_records = []
    for index, country in enumerate(countries):
        country_records.append(
            record(
                f"dt.project.countries.country_{index + 1}",
                "Project country",
                {
                    "code": ("Country code", country.get("code"), None),
                    "name": ("Country name", country.get("name"), None),
                    "region": ("Country region", country.get("region"), None),
                    "subregion": ("Country subregion", country.get("subregion"), None),
                },
                provenance=source_provenance(project, f"countries.{index}"),
            )
        )
    collections: dict[str, dict[str, Any]] = {
        "dt.project.countries": collection(
            "dt.project.countries",
            "Countries in which the project operates",
            country_records,
            record_schema=["code", "name", "region", "subregion"],
        )
    }

    kpi_candidates, kpi_audit = clean_kpis(project)
    selected_kpis = select_kpis_from_candidates(
        kpi_candidates,
        count=5,
        project_code=project_id,
    )

    def kpi_record(kpi: dict[str, Any], record_id: str) -> dict[str, Any]:
        def unpack(field_name: str) -> tuple[Any, str | None]:
            item = kpi.get(field_name)
            if isinstance(item, dict):
                return item.get("value"), item.get("unit")
            return item, None

        baseline, baseline_unit = unpack("baseline")
        intermediate, intermediate_unit = unpack("intermediate_target")
        final, final_unit = unpack("final_target")
        return record(
            record_id,
            "Project performance indicator",
            {
                "source_id": ("Original KPI path", kpi["_path"], None),
                "source_order": (
                    "Source order",
                    int(kpi["_source_order"]) + 1,
                    None,
                ),
                "family": ("Canonical KPI family", kpi["_family"], None),
                "indicator": ("Indicator name", kpi.get("name"), None),
                "baseline": ("Baseline", baseline, baseline_unit),
                "intermediate_target": (
                    "Intermediate target",
                    intermediate,
                    intermediate_unit,
                ),
                "final_target": ("Final target", final, final_unit),
                "verification": (
                    "Means of verification",
                    kpi.get("means_of_verification"),
                    None,
                ),
                "assumptions": ("Assumptions", kpi.get("assumptions"), None),
                "parent_outcome": ("Parent outcome", kpi["_outcome_id"], None),
            },
            provenance=source_provenance(project, kpi["_path"]),
        )

    kpi_schema = [
        "source_id",
        "source_order",
        "family",
        "indicator",
        "baseline",
        "intermediate_target",
        "final_target",
        "verification",
        "assumptions",
        "parent_outcome",
    ]
    all_kpi_records = [
        kpi_record(kpi, f"dt.kpis.kpi_{index + 1}")
        for index, kpi in enumerate(kpi_candidates)
    ]
    collections["dt.kpis"] = collection(
        "dt.kpis",
        "Complete cleaned and deduplicated normalized KPI collection",
        all_kpi_records,
        record_schema=kpi_schema,
    )

    kpi_records = [
        kpi_record(kpi, f"dt.selected_kpis.kpi_{index + 1}")
        for index, kpi in enumerate(selected_kpis)
    ]
    collections["dt.selected_kpis"] = collection(
        "dt.selected_kpis",
        "Legacy five-row KPI diversity sample retained for compatibility",
        kpi_records,
        record_schema=kpi_schema,
    )

    risk_records = []
    for index, risk in enumerate(project.get("risk") or []):
        description = str(risk.get("description") or "").strip()
        risk_name = str(risk.get("type") or f"Risk {index + 1}").strip()
        if description:
            first_sentence = description.split(".", 1)[0].strip()
            if 0 < len(first_sentence) <= 90:
                risk_name = first_sentence
        risk_records.append(
            record(
                f"dt.risks.risk_{index + 1}",
                "Project risk record",
                {
                    "name": ("Risk name", risk_name, None),
                    "type": ("Risk type", risk.get("type"), None),
                    "probability": ("Risk probability", risk.get("probability"), None),
                    "impact": ("Risk impact", risk.get("impact"), None),
                    "description": ("Risk description", risk.get("description"), None),
                    "mitigation": ("Risk mitigation", risk.get("mitigation"), None),
                    "source_order": ("Source order", index + 1, None),
                },
                provenance=source_provenance(project, f"risk.{index}"),
            )
        )
    collections["dt.risks"] = collection(
        "dt.risks",
        "Complete normalized project risk collection",
        risk_records,
        record_schema=[
            "name",
            "type",
            "probability",
            "impact",
            "description",
            "mitigation",
            "source_order",
        ],
    )

    twin = {
        "schema_version": "react_report.project_twin/v1",
        "project_id": project_id,
        "source_url": project.get("url"),
        "proposal_url": project.get("proposal"),
        "nodes": nodes,
        "collections": collections,
    }
    audit = {
        "project_id": project_id,
        "selected_kpi_paths": [
            {"path": item["_path"], "family": item["_family"]}
            for item in selected_kpis
        ],
        "cleaned_kpi_count": len(kpi_candidates),
        "excluded_kpi_count": sum(not item["eligible"] for item in kpi_audit),
        "kpi_candidates": kpi_audit,
        "risk_count": len(risk_records),
        "canonical_overrides": project_overrides,
    }
    return twin, audit
