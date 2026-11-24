from __future__ import annotations

from pathlib import Path
from statistics import median, quantiles
from typing import Any, Iterable

from ..paths import NORMALIZED_ROOT
from ..util import read_json, sha256_json, write_json
from .enrichment_all20 import (
    PROJECTS_OUTPUT_ROOT,
    build_all_project_enrichments,
    build_project_enrichment,
    project_output_path,
    validate_all_project_enrichments,
    validate_project_enrichment,
    write_all_project_enrichments,
)
from .source_normalization import OUTPUT_PATH as SOURCE_NORMALIZATION_PATH


V2_ROOT = Path(__file__).resolve().parent
OUTPUT_PATH = V2_ROOT / "data" / "evidence" / "fp083.enrichment.json"
PEER_PREFIX = "reference.climatefund20.v2.fp083_leave_one_out"
STUDIO_REVISION = "b1a7d14b9376ea40228f3d6ccd64dafa6147a5d1"
STUDIO_SOURCE_SHA256 = "bfaf46a6ef751419531ce0b7d4206a306f4e1b5da90688467957912a2b13107e"
REFERENCE_LABELS = {
    "sample_count": "Leave-one-out peer sample count",
    "median_total_cost_per_tco2e": "Peer median total cost per tCO2e",
    "q1_total_cost_per_tco2e": "Peer first-quartile total cost per tCO2e",
    "q3_total_cost_per_tco2e": "Peer third-quartile total cost per tCO2e",
    "median_project_cost_usd": "Peer median project cost",
    "median_ghg_reduction_tco2e": "Peer median GHG reduction",
    "median_implementation_years": "Peer median implementation period",
    "median_lifespan_years": "Peer median project lifespan",
    "median_country_count": "Peer median country count",
    "public_energy_sample_count": "Public-energy comparator sample count",
    "public_energy_median_total_cost_per_tco2e": (
        "Public-energy comparator median total cost per tCO2e"
    ),
}


def build_enrichment() -> dict[str, Any]:
    """Build explicit cross-repository supplements and robust peer references."""

    source_normalization = read_json(SOURCE_NORMALIZATION_PATH)
    project_nodes = _project_enrichment_nodes()
    projects = [read_json(path) for path in sorted(NORMALIZED_ROOT.glob("*.json"))]
    reference_nodes = _reference_nodes(projects)
    return {
        "schema_version": "react_report.evidence_enrichment/v2",
        "project_id": "FP083",
        "policy": {
            "overwrite_normalized_facts": False,
            "cross_project_values_are_project_facts": False,
            "synthetic_imputation_used": False,
            "description": (
                "Sibling-repository supplements remain explicitly marked; other "
                "projects contribute only frozen peer statistics and are never "
                "copied into FP083 project facts."
            ),
        },
        "inputs": {
            "source_normalization": {
                "path": "v2/data/evidence/fp083.source-normalized.json",
                "sha256": sha256_json(source_normalization),
            },
            "sibling_repository": {
                "repository": "climinvest-studio",
                "revision": STUDIO_REVISION,
                "path": "packages/climinvest-domain/demo-data-registry.js",
                "sha256": STUDIO_SOURCE_SHA256,
            },
            "peer_projects": [project["project_id"] for project in projects],
        },
        "project_nodes": project_nodes,
        "reference_nodes": reference_nodes,
    }


def write_enrichment(path: Path = OUTPUT_PATH) -> dict[str, Any]:
    payload = build_enrichment()
    write_json(path, payload)
    return payload


def _project_enrichment_nodes() -> dict[str, dict[str, Any]]:
    nodes: dict[str, dict[str, Any]] = {}
    schedules = {
        "gcf_soft_loan": [0.50, 0.30, 0.20, 0.00],
        "gcf_reimbursable_grant": [0.65, 0.35, 0.00, 0.00],
        "gcf_grant": [0.80, 0.20, 0.00, 0.00],
        "cofinance": [0.15, 0.35, 0.30, 0.20],
    }
    for source, shares in schedules.items():
        for period, share in enumerate(shares, start=1):
            node_id = f"dt.project.{source}_disbursement_period_{period}_share"
            nodes[node_id] = _studio_node(
                node_id,
                f"{source.replace('_', ' ').title()} disbursement share, period {period}",
                share,
                "x",
                f"fp083SourceNodeDefs.dt.{source}_schedule[{period - 1}]",
            )

    source_facts = {
        "dt.project.delivery_mechanism": (
            "Project delivery mechanism",
            (
                "A Geothermal Resource Risk Mitigation Facility provides debt "
                "financing for geothermal developers' resource-confirmation drilling."
            ),
            None,
            "fp083SourceNodeDefs.dt.project_mechanism",
        ),
        "dt.project.implementation_agency": (
            "Implementation agency and delivery unit",
            (
                "PT Sarana Multi Infrastruktur (SMI) is the implementing agency "
                "and is expected to establish a dedicated Project Management Unit."
            ),
            None,
            "fp083SourceNodeDefs.dt.implementation_agency",
        ),
        "dt.project.implementation_sequence": (
            "High-level implementation sequence",
            (
                "Candidate working areas proceed through due diligence, exploration "
                "and delineation drilling, resource confirmation, and then financial "
                "close for steam-field and power-plant development."
            ),
            None,
            "fp083SourceNodeDefs.dt.implementation_sequence",
        ),
        "dt.project.monitoring_reporting_process": (
            "Implementation monitoring and reporting process",
            (
                "The SMI project unit is expected to gather and analyse outputs and "
                "outcomes and submit quarterly progress reports to the World Bank."
            ),
            None,
            "fp083SourceNodeDefs.dt.monitoring_reporting_process",
        ),
        "dt.project.commitment_period_years": (
            "Facility commitment period",
            6,
            "years",
            "fp083SourceNodeDefs.dt.commitment_period_years",
        ),
        "dt.project.projects_explored_target": (
            "Geothermal projects explored target",
            17,
            "projects",
            "fp083SourceNodeDefs.dt.projects_explored_target",
        ),
        "dt.project.environmental_cobenefits": (
            "Expected environmental co-benefits",
            (
                "Expected co-benefits include lower local air-pollutant emissions, "
                "relatively low freshwater use, and a smaller land footprint than "
                "conventional energy extraction."
            ),
            None,
            "fp083SourceNodeDefs.dt.environmental_cobenefits",
        ),
        "dt.project.social_economic_cobenefits": (
            "Expected social and economic co-benefits",
            (
                "Expected co-benefits include greater energy security, employment "
                "around drilling locations, and opportunities for women engineers "
                "and project managers."
            ),
            None,
            "fp083SourceNodeDefs.dt.social_economic_cobenefits",
        ),
    }
    for node_id, (description, value, unit, locator) in source_facts.items():
        nodes[node_id] = _studio_node(node_id, description, value, unit, locator)

    evidence_gaps = {
        "req.project_status": "Current project status is not evidenced in the available FP083 twin.",
        "req.technical_feasibility_status": "A formal overall technical-feasibility conclusion is not exposed as structured evidence.",
        "req.permitting_status": "Permitting status is not exposed as structured evidence.",
        "req.detailed_implementation_schedule": "No dated activity-level schedule, dependencies, or critical path are exposed.",
        "req.revenue_model": "The revenue model is not exposed as structured evidence.",
        "req.lifecycle_opex": "Lifecycle OPEX is not evidenced.",
        "req.financial_returns": "ENPV, avoided-damage valuation, and EIRR are not evidenced.",
        "req.mrv_plan_status": "Formal MRV-plan status is not exposed as structured evidence.",
        "req.ghg_target_horizon": "The cumulative GHG range lacks a structured target year and fully specified calculation boundary.",
    }
    for node_id, statement in evidence_gaps.items():
        nodes[node_id] = _studio_node(
            node_id,
            node_id.removeprefix("req.").replace("_", " ").title(),
            statement,
            None,
            f"fp083SourceNodeDefs.missing.{node_id.removeprefix('req.')}",
            evidence_class="documented_source_gap",
        )
    return nodes


def _reference_nodes(projects: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    peers = [project for project in projects if project["project_id"] != "FP083"]
    if len(peers) != 19:
        raise ValueError(f"FP083 leave-one-out peer set requires 19 projects, got {len(peers)}")

    def value(project: dict[str, Any], node_id: str) -> float:
        node = project["nodes"][node_id]
        if node.get("status") != "available":
            raise ValueError(f"{project['project_id']}: unavailable peer input {node_id}")
        return float(node["value"])

    def country_count(project: dict[str, Any]) -> float:
        return float(len(project["collections"]["dt.project.countries"]["records"]))

    def cost_intensities(items: Iterable[dict[str, Any]]) -> list[float]:
        return [
            value(project, "dt.project.total_cost_usd")
            / value(project, "dt.project.ghg_reduction_tco2e")
            for project in items
        ]

    peer_cost_intensity = cost_intensities(peers)
    q1, _, q3 = quantiles(peer_cost_intensity, n=4, method="inclusive")
    public_energy = [
        project
        for project in peers
        if project["nodes"]["dt.project.sector"].get("value") == "public"
        and "Energy, mitigation and access"
        in project["nodes"]["dt.project.mitigation_areas"].get("value", [])
    ]
    facts = {
        "sample_count": (len(peers), "projects"),
        "median_total_cost_per_tco2e": (median(peer_cost_intensity), "USD/tCO2e"),
        "q1_total_cost_per_tco2e": (q1, "USD/tCO2e"),
        "q3_total_cost_per_tco2e": (q3, "USD/tCO2e"),
        "median_project_cost_usd": (
            median(value(project, "dt.project.total_cost_usd") for project in peers),
            "USD",
        ),
        "median_ghg_reduction_tco2e": (
            median(
                value(project, "dt.project.ghg_reduction_tco2e") for project in peers
            ),
            "tCO2e",
        ),
        "median_implementation_years": (
            median(
                value(project, "dt.project.implementation_years") for project in peers
            ),
            "years",
        ),
        "median_lifespan_years": (
            median(value(project, "dt.project.lifespan_years") for project in peers),
            "years",
        ),
        "median_country_count": (median(country_count(project) for project in peers), "countries"),
        "public_energy_sample_count": (len(public_energy), "projects"),
        "public_energy_median_total_cost_per_tco2e": (
            median(cost_intensities(public_energy)),
            "USD/tCO2e",
        ),
    }
    nodes = {
        f"{PEER_PREFIX}.{name}": _reference_node(name, result, unit, peers)
        for name, (result, unit) in facts.items()
    }
    methodology_id = f"{PEER_PREFIX}.methodology"
    nodes[methodology_id] = {
        "id": methodology_id,
        "kind": "scalar",
        "description": "FP083 peer-reference methodology",
        "status": "available",
        "value": (
            "Frozen leave-one-out medians and inclusive quartiles over the other "
            "19 normalized ClimateFund projects. The public-energy comparator is "
            "restricted to public projects tagged Energy, mitigation and access. "
            "It is not technology-matched and does not imply causal comparability."
        ),
        "unit": None,
        "evidence_class": "cross_project_reference_statistic",
        "provenance": {
            "source_kind": "cross_project_reference_statistic",
            "project_ids": [project["project_id"] for project in peers],
            "target_excluded": "FP083",
            "input_evidence_classes": ["normalized_project_source"],
            "synthetic_input_share": 0.0,
        },
    }
    return nodes


def _studio_node(
    node_id: str,
    description: str,
    value: Any,
    unit: str | None,
    locator: str,
    *,
    evidence_class: str = "sibling_repository_source_supplement",
) -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": "scalar",
        "description": description,
        "status": "available",
        "value": value,
        "unit": unit,
        "evidence_class": evidence_class,
        "provenance": {
            "source_kind": evidence_class,
            "repository": "climinvest-studio",
            "revision": STUDIO_REVISION,
            "path": "packages/climinvest-domain/demo-data-registry.js",
            "locator": locator,
        },
        "enrichment": {
            "imputed": False,
            "overwrites_normalized_node": False,
        },
    }


def _reference_node(
    name: str,
    value: float,
    unit: str,
    peers: list[dict[str, Any]],
) -> dict[str, Any]:
    node_id = f"{PEER_PREFIX}.{name}"
    return {
        "id": node_id,
        "kind": "scalar",
        "description": REFERENCE_LABELS[name],
        "status": "available",
        "value": value,
        "unit": unit,
        "evidence_class": "cross_project_reference_statistic",
        "provenance": {
            "source_kind": "cross_project_reference_statistic",
            "project_ids": [project["project_id"] for project in peers],
            "target_excluded": "FP083",
            "statistic": "median_or_inclusive_quartile",
            "input_evidence_classes": ["normalized_project_source"],
            "synthetic_input_share": 0.0,
        },
    }


def main() -> None:
    # Keep the committed FP083 pilot overlay reproducible while making this the
    # single public stage-two command for the authoritative all-20 study path.
    payload = write_enrichment()
    population_payloads = write_all_project_enrichments()
    project_node_count = sum(
        len(item["project_nodes"]) for item in population_payloads.values()
    )
    print(
        f"{PROJECTS_OUTPUT_ROOT} ({len(population_payloads)} study bundles, "
        f"{project_node_count} project nodes); legacy pilot {OUTPUT_PATH} "
        f"({len(payload['project_nodes'])} project nodes, "
        f"{len(payload['reference_nodes'])} reference nodes)"
    )


if __name__ == "__main__":
    main()
