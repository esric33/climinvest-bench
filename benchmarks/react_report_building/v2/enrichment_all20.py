"""Deterministic, audited evidence enrichment for the full study population."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..paths import NORMALIZED_ROOT
from ..util import read_json, sha256_json, write_json
from .enrichment_specs import (
    ASSET_CAPACITY_RELATIONSHIPS,
    ASSET_COMPARABLE_REPORTED_GHG,
    ASSET_GENERATION_BOUNDARIES,
    COMMON_REQUIREMENT_GAPS,
    FACILITY_ARCHETYPES,
    FACILITY_DEPLOYMENT_BASIS,
    FACILITY_INSTRUMENT_MIX,
    FACILITY_INSTRUMENT_OVERRIDES,
    FACILITY_MOBILISATION_NOT_APPLICABLE,
    FACILITY_PORTFOLIO_TYPES,
    FUNDING_SCOPE_MISMATCH,
    FUNDING_SCOPE_UNDETERMINED,
    GENERATOR_ID,
    GENERATOR_VERSION,
    LAND_DEFAULT_AREA_HA,
    LAND_MODES,
    LAND_PATHWAY_SHARES,
)
from .source_normalization import build_source_normalization
from .kpi_priority_enrichment import (
    COLLECTION_ID as KPI_PRIORITY_COLLECTION_ID,
    build_kpi_priority_collection,
    validate_kpi_priority_collection,
)
from .study_design import (
    load_enrichment_contract,
    load_population,
    project_specialisation_assignments,
    synthetic_enrichment_metadata,
    synthetic_seed,
    validate_synthetic_node,
)


V2_ROOT = Path(__file__).resolve().parent
PROJECTS_OUTPUT_ROOT = V2_ROOT / "data" / "evidence" / "projects"

INSTRUMENT_IDS = (
    "gcf_grant_usd",
    "gcf_concessional_loan_usd",
    "gcf_reimbursable_grant_usd",
    "gcf_guarantee_usd",
    "gcf_equity_usd",
)
LAND_CATEGORY_IDS = {
    "forest_protection": "forest_protection_area_target_ha",
    "restoration": "restoration_area_target_ha",
    "plantation_afforestation": "plantation_afforestation_area_target_ha",
    "sustainable_management": "sustainable_management_area_target_ha",
}
def project_output_path(project_id: str) -> Path:
    """Return the authoritative all-population enrichment path."""

    return PROJECTS_OUTPUT_ROOT / f"{project_id.lower()}.enrichment.json"


def source_normalization_output_path(project_id: str) -> Path:
    return PROJECTS_OUTPUT_ROOT / f"{project_id.lower()}.source-normalized.json"


def build_all_project_enrichments(
    *,
    population: dict[str, Any] | None = None,
    source_normalizations: Mapping[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build one bundle for every authoritative project-template assignment."""

    study = population if population is not None else load_population()
    assignments = project_specialisation_assignments(study)
    normalizations = dict(source_normalizations or {})
    outputs: dict[str, dict[str, Any]] = {}
    for project_id in assignments:
        source = normalizations.get(project_id)
        if source is None:
            source = build_source_normalization(project_id)
        outputs[project_id] = build_project_enrichment(
            project_id,
            population=study,
            source_normalization=source,
        )
    return outputs


def write_all_project_enrichments(
    *,
    population: dict[str, Any] | None = None,
    source_normalizations: Mapping[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    payloads = build_all_project_enrichments(
        population=population,
        source_normalizations=source_normalizations,
    )
    for project_id, payload in payloads.items():
        write_json(project_output_path(project_id), payload)
    return payloads


def build_project_enrichment(
    project_id: str,
    *,
    population: dict[str, Any] | None = None,
    source_normalization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    study = population if population is not None else load_population()
    assignments = project_specialisation_assignments(study)
    if project_id not in assignments:
        raise ValueError(f"{project_id}: not in the authoritative study population")
    template_id = assignments[project_id]
    twin = read_json(NORMALIZED_ROOT / f"{project_id.lower()}.json")
    source = source_normalization or build_source_normalization(project_id)
    if source.get("project_id") != project_id:
        raise ValueError(f"{project_id}: source-normalization project mismatch")

    builder = _ProjectBuilder(project_id, template_id, twin, source)
    _add_source_canonicalizations(builder)
    _add_common_nodes(builder)
    if template_id == "asset_delivery":
        _add_asset_nodes(builder)
    elif template_id == "financing_facility":
        _add_facility_nodes(builder)
    elif template_id == "land_use_nature":
        _add_land_nodes(builder)
    else:  # guarded by study-design validation; retained as a local invariant
        raise ValueError(f"{project_id}: unsupported template {template_id}")

    builder.assert_no_source_collisions()
    payload = {
        "schema_version": "react_report.evidence_enrichment/v3",
        "project_id": project_id,
        "template_id": template_id,
        "generator": {
            "id": GENERATOR_ID,
            "version": GENERATOR_VERSION,
            "evaluated_model_used": False,
        },
        "policy": {
            "overwrite_normalized_facts": False,
            "overwrite_source_normalized_facts": False,
            "cross_project_values_are_project_facts": False,
            "synthetic_imputation_used": True,
            "not_a_factual_due_diligence_record": True,
            "description": (
                "Source evidence is immutable. Missing contract inputs are filled "
                "only by labelled deterministic benchmark assumptions; explicit "
                "not-applicable values remain null."
            ),
        },
        "inputs": {
            "normalized_twin": {
                "path": f"data/normalized/projects/{project_id.lower()}.json",
                "sha256": sha256_json(twin),
            },
            "source_normalization": {
                "path": (
                    f"v2/data/evidence/projects/"
                    f"{project_id.lower()}.source-normalized.json"
                ),
                "sha256": sha256_json(source),
            },
            "study_population": {
                "path": "v2/data/study/twenty-project-study-population.json",
                "population_id": study["population_id"],
            },
        },
        "project_nodes": dict(sorted(builder.nodes.items())),
        "project_collections": dict(sorted(builder.collections.items())),
        "reference_nodes": {},
        "audit": builder.audit(),
    }
    errors = validate_project_enrichment(
        payload,
        twin=twin,
        source_normalization=source,
    )
    if errors:
        raise ValueError(f"{project_id}: invalid enrichment: " + "; ".join(errors))
    return payload


class _ProjectBuilder:
    def __init__(
        self,
        project_id: str,
        template_id: str,
        twin: dict[str, Any],
        source_normalization: dict[str, Any],
    ) -> None:
        self.project_id = project_id
        self.template_id = template_id
        self.twin = twin
        self.source = source_normalization
        self.nodes: dict[str, dict[str, Any]] = {}
        self.collections: dict[str, dict[str, Any]] = {}
        self.source_node_ids = set(twin.get("nodes", {})) | set(
            source_normalization.get("nodes", {})
        )
        self.source_collection_ids = set(twin.get("collections", {}))

    def resolved(self, node_id: str) -> bool:
        return node_id in self.source_node_ids or node_id in self.nodes

    def value(self, node_id: str, default: Any = None) -> Any:
        for container in (
            self.nodes,
            self.source.get("nodes", {}),
            self.twin.get("nodes", {}),
        ):
            node = container.get(node_id)
            if node and node.get("status") == "available":
                return node.get("value")
        return default

    def add(
        self,
        node_id: str,
        description: str,
        value: Any,
        unit: str | None,
        *,
        rule_id: str,
        conditioned_on: Iterable[str],
        constraints: Iterable[str],
    ) -> None:
        if node_id in self.source_node_ids:
            return
        if node_id in self.nodes:
            raise ValueError(f"{self.project_id}: duplicate generated node {node_id}")
        metadata = synthetic_enrichment_metadata(
            project_id=self.project_id,
            template_id=self.template_id,
            node_id=node_id,
            generator_id=GENERATOR_ID,
            generator_version=GENERATOR_VERSION,
            rule_id=rule_id,
            conditioned_on=conditioned_on,
            constraints=constraints,
        )
        self.nodes[node_id] = {
            "id": node_id,
            "kind": "scalar",
            "description": description,
            "status": "available",
            "value": value,
            "unit": unit,
            "applicability": {
                "status": "applicable",
                "basis": "benchmark-contract",
            },
            **metadata,
        }

    def add_na(
        self,
        node_id: str,
        description: str,
        unit: str | None,
        *,
        reason: str,
        basis: str = "benchmark-contract",
        conditioned_on: Iterable[str] = ("dt.project.code",),
        rule_id: str = "explicit_not_applicable",
    ) -> None:
        if node_id in self.source_node_ids:
            return
        if node_id in self.nodes:
            raise ValueError(f"{self.project_id}: duplicate generated node {node_id}")
        metadata = synthetic_enrichment_metadata(
            project_id=self.project_id,
            template_id=self.template_id,
            node_id=node_id,
            generator_id=GENERATOR_ID,
            generator_version=GENERATOR_VERSION,
            rule_id=rule_id,
            conditioned_on=conditioned_on,
            constraints=(
                "status is not_applicable",
                "value is null",
                f"unit remains {unit or 'unitless'} for schema compatibility",
            ),
        )
        self.nodes[node_id] = {
            "id": node_id,
            "kind": "scalar",
            "description": description,
            "status": "not_applicable",
            "value": None,
            "unit": unit,
            "applicability": {
                "status": "not_applicable",
                "reason": reason,
                "basis": basis,
            },
            **metadata,
        }

    def add_unused_balance_zero(
        self,
        node_id: str,
        description: str,
        *,
        reason: str,
        conditioned_on: Iterable[str],
    ) -> None:
        """Add the contract's narrow zero exception for exhaustive balances."""

        if node_id in self.source_node_ids:
            return
        if node_id in self.nodes:
            raise ValueError(f"{self.project_id}: duplicate generated node {node_id}")
        metadata = synthetic_enrichment_metadata(
            project_id=self.project_id,
            template_id=self.template_id,
            node_id=node_id,
            generator_id=GENERATOR_ID,
            generator_version=GENERATOR_VERSION,
            rule_id="unused_exhaustive_balance_category_zero",
            conditioned_on=conditioned_on,
            constraints=(
                "value equals zero USD",
                "value is used only in the exhaustive instrument reconciliation",
                "value is never used as a denominator",
                "applicability remains not_applicable",
            ),
        )
        self.nodes[node_id] = {
            "id": node_id,
            "kind": "scalar",
            "description": description,
            "status": "available",
            "value": 0.0,
            "unit": "USD",
            "applicability": {
                "status": "not_applicable",
                "reason": reason,
                "basis": "benchmark-contract exhaustive-balance exception",
                "arithmetic_placeholder": True,
            },
            **metadata,
        }

    def add_gap(self, node_id: str, statement: str) -> None:
        if node_id in self.source_node_ids:
            return
        if node_id in self.nodes:
            raise ValueError(f"{self.project_id}: duplicate gap node {node_id}")
        self.nodes[node_id] = {
            "id": node_id,
            "kind": "scalar",
            "description": node_id.removeprefix("req.").replace("_", " ").title(),
            "status": "available",
            "value": statement,
            "unit": None,
            "evidence_class": "documented_source_gap",
            "applicability": {
                "status": "applicable",
                "basis": "source-normalization absence audit",
            },
            "provenance": {
                "source_kind": "documented_source_gap",
                "project_id": self.project_id,
                "locator": f"source_normalization.absent:{node_id}",
            },
            "enrichment": {
                "synthetic": False,
                "imputed": False,
                "overwrites_normalized_node": False,
            },
        }

    def add_source_alias(
        self,
        target_id: str,
        source_id: str,
        *,
        description: str | None = None,
    ) -> None:
        """Expose an exact source atom under a semantically identical contract ID."""

        if target_id in self.source_node_ids:
            return
        source_node = self.source.get("nodes", {}).get(source_id)
        if not source_node or source_node.get("status") != "available":
            return
        if target_id in self.nodes:
            raise ValueError(f"{self.project_id}: duplicate canonical alias {target_id}")
        provenance = dict(source_node.get("provenance", {}))
        provenance["source_node_id"] = source_id
        self.nodes[target_id] = {
            **source_node,
            "id": target_id,
            "description": description or source_node.get("description") or target_id,
            "evidence_class": "same_project_source_extraction",
            "provenance": provenance,
            "applicability": {
                "status": "applicable",
                "basis": "source-backed canonical alias",
            },
            "normalization": {
                **source_node.get("normalization", {}),
                "canonical_alias": True,
                "source_node_id": source_id,
                "imputed": False,
                "overwrites_source_node": False,
            },
        }

    def add_source_derivation(
        self,
        target_id: str,
        source_ids: Iterable[str],
        value: float,
        unit: str,
        *,
        description: str,
        operation: str,
    ) -> None:
        """Expose an exact arithmetic canonicalization over source-backed atoms."""

        if target_id in self.source_node_ids:
            return
        ids = tuple(source_ids)
        source_nodes = [self.source.get("nodes", {}).get(source_id) for source_id in ids]
        if not source_nodes or any(
            not node or node.get("status") != "available" for node in source_nodes
        ):
            return
        if target_id in self.nodes:
            raise ValueError(f"{self.project_id}: duplicate source derivation {target_id}")
        first = source_nodes[0] or {}
        first_provenance = first.get("provenance", {})
        self.nodes[target_id] = {
            "id": target_id,
            "kind": "scalar",
            "description": description,
            "status": "available",
            "value": value,
            "unit": unit,
            "evidence_class": "same_project_source_extraction",
            "applicability": {
                "status": "applicable",
                "basis": "source-backed exact arithmetic canonicalization",
            },
            "provenance": {
                "source_kind": "same_project_source_extraction",
                "document_id": first_provenance.get(
                    "document_id", f"proposal.{self.project_id.lower()}"
                ),
                "locator": " + ".join(
                    str((node or {}).get("provenance", {}).get("locator", source_id))
                    for source_id, node in zip(ids, source_nodes)
                ),
                "source_node_ids": list(ids),
                "url": first_provenance.get("url"),
            },
            "normalization": {
                "method": operation,
                "canonical_alias": True,
                "source_node_ids": list(ids),
                "imputed": False,
                "overwrites_source_node": False,
            },
        }

    def add_collection(self, collection: dict[str, Any]) -> None:
        collection_id = str(collection["id"])
        if collection_id in self.source_collection_ids:
            return
        if collection_id in self.collections:
            raise ValueError(
                f"{self.project_id}: duplicate generated collection {collection_id}"
            )
        self.collections[collection_id] = collection

    def assert_no_source_collisions(self) -> None:
        node_collisions = sorted(set(self.nodes) & self.source_node_ids)
        collection_collisions = sorted(
            set(self.collections) & self.source_collection_ids
        )
        if node_collisions or collection_collisions:
            raise ValueError(
                f"{self.project_id}: enrichment/source collision: "
                f"nodes={node_collisions}, collections={collection_collisions}"
            )

    def audit(self) -> dict[str, Any]:
        nested_fields = list(_collection_field_nodes(self.collections))
        all_generated = list(self.nodes.values()) + nested_fields
        evidence_class_counts: dict[str, int] = {}
        for node in all_generated:
            evidence_class = str(node.get("evidence_class", "unclassified"))
            evidence_class_counts[evidence_class] = (
                evidence_class_counts.get(evidence_class, 0) + 1
            )
        return {
            "source_nodes_preserved": len(self.source_node_ids),
            "source_collections_preserved": len(self.source_collection_ids),
            "generated_project_node_count": len(self.nodes),
            "generated_collection_count": len(self.collections),
            "generated_collection_field_count": len(nested_fields),
            "synthetic_node_count": sum(
                node.get("evidence_class") == "synthetic_benchmark_enrichment"
                for node in all_generated
            ),
            "documented_gap_count": sum(
                node.get("evidence_class") == "documented_source_gap"
                for node in self.nodes.values()
            ),
            "source_backed_canonicalization_count": sum(
                node.get("evidence_class") == "same_project_source_extraction"
                for node in all_generated
            ),
            "project_evidence_class_counts": dict(sorted(evidence_class_counts.items())),
            "not_applicable_count": sum(
                node.get("applicability", {}).get("status") == "not_applicable"
                for node in all_generated
            ),
            "reference_node_count": 0,
            "node_id_collisions": [],
            "source_values_overwritten": False,
        }


def _add_source_canonicalizations(builder: _ProjectBuilder) -> None:
    """Map exact normalized atoms onto the revised document-contract vocabulary."""

    direct_aliases: dict[str, tuple[str, str]] = {
        "FP083": (
            "dt.project.gcf_concessional_loan_usd",
            "dt.project.gcf_soft_loan_usd",
        ),
        "FP090": (
            "dt.project.baseline_renewable_generation_pct",
            "dt.project.pre_project_renewable_generation_pct",
        ),
        "FP178": (
            "dt.project.gcf_guarantee_usd",
            "dt.project.partial_risk_guarantee_usd",
        ),
    }
    if builder.project_id in direct_aliases:
        target_id, source_id = direct_aliases[builder.project_id]
        builder.add_source_alias(target_id, source_id)
    if builder.project_id == "FP090":
        builder.add_source_alias(
            "dt.project.grid_loss_pct",
            "dt.project.grid_loss_target_pct",
            description="Target grid-loss percentage used by the asset model",
        )

    for target_suffix, source_suffix in (
        ("additional_capital_mobilized_min_usd", "mobilized_capital_min_usd"),
        ("additional_capital_mobilized_max_usd", "mobilized_capital_max_usd"),
    ):
        if builder.project_id == "FP083":
            builder.add_source_alias(
                f"dt.project.{target_suffix}",
                f"dt.project.{source_suffix}",
            )

    if builder.project_id == "FP071":
        source_id = "dt.project.expected_ee_investment_mobilization_usd"
        for suffix in ("min", "max"):
            builder.add_source_alias(
                f"dt.project.additional_capital_mobilized_{suffix}_usd",
                source_id,
                description=(
                    "Source-backed expected energy-efficiency investment mobilisation "
                    "point estimate used as both ends of a degenerate range"
                ),
            )

    if builder.project_id == "FP178":
        source_ids = (
            "dt.project.expected_ipp_debt_usd",
            "dt.project.expected_ipp_equity_usd",
        )
        values = [builder.value(source_id) for source_id in source_ids]
        if all(value is not None for value in values):
            mobilised = sum(float(value) for value in values)
            for suffix in ("min", "max"):
                builder.add_source_derivation(
                    f"dt.project.additional_capital_mobilized_{suffix}_usd",
                    source_ids,
                    mobilised,
                    "USD",
                    description=(
                        "Expected IPP debt plus equity mobilisation point estimate used "
                        "as both ends of a degenerate range"
                    ),
                    operation="exact sum of source-normalized debt and equity atoms",
                )

    if builder.project_id == "FP033":
        source_ids = (
            "dt.project.baseline_generation_coal_pct",
            "dt.project.baseline_generation_fuel_oil_pct",
        )
        values = [builder.value(source_id) for source_id in source_ids]
        if all(value is not None for value in values):
            builder.add_source_derivation(
                "dt.project.baseline_fossil_generation_pct",
                source_ids,
                sum(float(value) for value in values),
                "%",
                description="Source-backed coal plus fuel-oil generation share",
                operation="exact sum of source-normalized generation shares",
            )


def _add_common_nodes(builder: _ProjectBuilder) -> None:
    project_id = builder.project_id
    template_id = builder.template_id
    title = str(builder.value("dt.project.title", project_id))
    entity = str(builder.value("dt.project.entity_name", "the accredited entity"))
    point_ghg = float(builder.value("dt.project.ghg_reduction_tco2e"))
    lifespan = float(builder.value("dt.project.lifespan_years"))

    builder.add_collection(
        build_kpi_priority_collection(
            project_id=project_id,
            template_id=template_id,
            twin=builder.twin,
        )
    )

    mechanism = {
        "asset_delivery": "physical asset procurement, construction and commissioning",
        "financing_facility": "eligibility-screened financing and portfolio deployment",
        "land_use_nature": "area enrolment and pathway-specific land management",
    }[template_id]
    sequence = {
        "asset_delivery": "screen sites; procure assets; construct and connect; commission; monitor operations",
        "financing_facility": "establish eligibility; originate pipeline; approve allocations; utilise exposure; monitor portfolio",
        "land_use_nature": "confirm baseline; enrol mutually exclusive areas; implement land pathways; monitor carbon and co-benefits",
    }[template_id]
    common_text = {
        "dt.project.delivery_mechanism": (
            "Benchmark-scenario delivery mechanism",
            f"{title} is represented through {mechanism}.",
        ),
        "dt.project.implementation_agency": (
            "Benchmark-scenario implementation agency",
            f"A dedicated implementation unit coordinated with {entity} administers the benchmark scenario.",
        ),
        "dt.project.governance_arrangements": (
            "Benchmark-scenario governance arrangements",
            "A steering body approves material changes; an implementation unit maintains delivery, finance and evidence registers; independent assurance reviews scheduled reporting.",
        ),
        "dt.project.implementation_sequence": (
            "Benchmark-scenario implementation sequence",
            sequence,
        ),
        "dt.project.monitoring_reporting_process": (
            "Benchmark-scenario monitoring and reporting process",
            "Quarterly delivery and financing records feed an annual outcome review, with exceptions and boundary changes retained in an auditable evidence register.",
        ),
    }
    for node_id, (description, value) in common_text.items():
        builder.add(
            node_id,
            description,
            value,
            None,
            rule_id="specialisation_governance_fixture",
            conditioned_on=("dt.project.entity_name", "dt.project.title"),
            constraints=(
                "value is non-empty text",
                "text describes a benchmark scenario rather than a source claim",
            ),
        )

    if project_id in FUNDING_SCOPE_MISMATCH:
        comparability = "not_comparable"
        total_scope = "not_whole_project"
        qualification = (
            "The reported total, GCF financing and cofinance do not establish a "
            "common envelope; coverage and reconciliation classifications are N/A."
        )
    elif project_id in FUNDING_SCOPE_UNDETERMINED:
        comparability = "undetermined"
        total_scope = "undetermined"
        qualification = (
            "The amounts are preserved, but their envelope comparability is not "
            "established; ratio and reconciliation classifications are N/A."
        )
    else:
        comparability = "comparable"
        total_scope = "whole_project"
        qualification = (
            "For benchmark arithmetic, the reported aggregate amounts are treated "
            "as one committed financing envelope; this is not an audit conclusion."
        )
    scope_values = {
        "dt.project.total_cost_scope": total_scope,
        "dt.project.gcf_financing_scope": "stated aggregate GCF financing",
        "dt.project.cofinance_scope": "stated aggregate cofinance",
        "dt.project.funding_scope_comparability": comparability,
        "dt.project.funding_scope_qualification": qualification,
    }
    for node_id, value in scope_values.items():
        builder.add(
            node_id,
            node_id.removeprefix("dt.project.").replace("_", " ").title(),
            value,
            None,
            rule_id="reviewed_financing_scope_fixture",
            conditioned_on=(
                "dt.project.cofinance_usd",
                "dt.project.gcf_financing_usd",
                "dt.project.total_cost_usd",
            ),
            constraints=(
                "value is non-empty text",
                "comparability is comparable, not_comparable, or undetermined",
            ),
        )

    low = _round(point_ghg * 0.9, 3)
    high = _round(point_ghg * 1.1, 3)
    builder.add(
        "dt.project.ghg_reduction_min_tco2e",
        "Synthetic benchmark lower GHG scenario bound",
        low,
        "tCO2e",
        rule_id="symmetric_range_around_reported_point",
        conditioned_on=("dt.project.ghg_reduction_tco2e",),
        constraints=(
            "value is positive",
            "value is no greater than the reported point target",
            "unit is tCO2e",
        ),
    )
    builder.add(
        "dt.project.ghg_reduction_max_tco2e",
        "Synthetic benchmark upper GHG scenario bound",
        high,
        "tCO2e",
        rule_id="symmetric_range_around_reported_point",
        conditioned_on=("dt.project.ghg_reduction_tco2e",),
        constraints=(
            "value is no less than the reported point target",
            "lower bound is no greater than upper bound",
            "unit is tCO2e",
        ),
    )
    builder.add(
        "dt.project.ghg_target_horizon_years",
        "Synthetic benchmark GHG accounting horizon",
        lifespan,
        "years",
        rule_id="lifespan_anchored_accounting_horizon",
        conditioned_on=("dt.project.lifespan_years",),
        constraints=(
            "value is positive",
            "value equals the observed lifespan only as a benchmark scenario assumption",
            "unit is years",
        ),
    )
    builder.add(
        "dt.project.ghg_accounting_qualification",
        "GHG benchmark-range and horizon qualification",
        (
            "The normalized project value remains the reported point target. The "
            "lower and upper bounds and the lifespan-anchored accounting horizon "
            "are synthetic benchmark assumptions, not proposal claims."
        ),
        None,
        rule_id="synthetic_ghg_range_disclosure",
        conditioned_on=(
            "dt.project.ghg_reduction_tco2e",
            "dt.project.lifespan_years",
        ),
        constraints=("value preserves the source point target", "value is non-empty text"),
    )

    for node_id, statement in COMMON_REQUIREMENT_GAPS.items():
        builder.add_gap(node_id, statement)
    builder.add(
        "req.synthetic_evidence_disclosure",
        "Required synthetic evidence disclosure",
        (
            "This benchmark instance combines immutable normalized source evidence "
            "with visibly labelled deterministic synthetic assumptions. It is not "
            "a factual due-diligence record."
        ),
        None,
        rule_id="mandatory_synthetic_evidence_disclosure",
        conditioned_on=("dt.project.code",),
        constraints=(
            "value explicitly names deterministic synthetic assumptions",
            "value states that the bundle is not factual due diligence",
        ),
    )


def _add_asset_nodes(builder: _ProjectBuilder) -> None:
    project_id = builder.project_id
    implementation_years = float(builder.value("dt.project.implementation_years"))
    lifespan = float(builder.value("dt.project.lifespan_years"))
    total_cost = float(builder.value("dt.project.total_cost_usd"))
    ghg_point = float(builder.value("dt.project.ghg_reduction_tco2e"))
    u = lambda suffix: _unit_interval(project_id, f"dt.project.{suffix}")

    renewable = _round(12 + 22 * u("baseline_renewable_generation_pct"), 3)
    fossil = _round(100 - renewable, 3)
    baseline_factor = _round(0.72 + 0.34 * u("baseline_grid_emission_factor"), 6)
    project_factor = _round(0.02 + 0.07 * u("project_operating_emission_factor"), 6)
    capacity = _round(min(250.0, max(4.0, total_cost / 3_000_000)), 3)
    direct_beneficiaries = int(max(5_000, round(total_cost / 650)))
    service_connections = int(max(1_000, round(direct_beneficiaries / 5)))

    scalar_specs = {
        "baseline_electricity_access_pct": (
            _round(28 + 55 * u("baseline_electricity_access_pct"), 3), "%"
        ),
        "baseline_fossil_generation_pct": (fossil, "%"),
        "baseline_renewable_generation_pct": (renewable, "%"),
        "policy_renewable_target_pct": (min(90.0, _round(renewable + 25, 3)), "%"),
        "policy_target_year": ("2030", None),
        "baseline_grid_emission_factor_tco2e_per_mwh": (
            baseline_factor,
            "tCO2e/MWh",
        ),
        "project_operating_emission_factor_tco2e_per_mwh": (
            project_factor,
            "tCO2e/MWh",
        ),
        "installed_capacity_target_mw": (capacity, "MW"),
        "capacity_factor_pct": (_round(23 + 16 * u("capacity_factor_pct"), 3), "%"),
        "grid_loss_pct": (_round(4 + 7 * u("grid_loss_pct"), 3), "%"),
        "operating_horizon_years": (lifespan, "years"),
        "direct_beneficiaries_target": (direct_beneficiaries, "people"),
        "service_connections_target": (service_connections, "connections"),
    }
    for suffix, (value, unit) in scalar_specs.items():
        if builder.resolved(f"dt.project.{suffix}"):
            continue
        builder.add(
            f"dt.project.{suffix}",
            suffix.replace("_", " ").title() + " benchmark assumption",
            value,
            unit,
            rule_id="asset_physical_fixture",
            conditioned_on=(
                "dt.project.ghg_reduction_tco2e",
                "dt.project.lifespan_years",
                "dt.project.total_cost_usd",
            ),
            constraints=_numeric_or_text_constraints(value, unit),
        )

    shares = _normalised_shares(project_id, "capacity_commissioning", 4)
    for period, share in enumerate(shares, start=1):
        builder.add(
            f"dt.project.capacity_commissioning_period_{period}_share",
            f"Synthetic commissioned-capacity share in scenario period {period}",
            share,
            "x",
            rule_id="four_period_capacity_commissioning_profile",
            conditioned_on=(
                "dt.project.implementation_years",
                "dt.project.installed_capacity_target_mw",
            ),
            constraints=(
                "value is between zero and one inclusive",
                "all four capacity commissioning shares sum to one",
                "unit is x",
            ),
        )
    for period, years in enumerate(_period_years(implementation_years), start=1):
        builder.add(
            f"dt.project.delivery_period_{period}_years",
            f"Duration of ordered asset-delivery scenario period {period}",
            years,
            "years",
            rule_id="four_period_delivery_duration",
            conditioned_on=("dt.project.implementation_years",),
            constraints=(
                "value is positive",
                "all four period durations sum to implementation years",
                "period label is not a calendar year",
                "unit is years",
            ),
        )

    builder.add(
        "dt.project.capacity_delivery_relationship",
        "Capacity delivery relationship",
        ASSET_CAPACITY_RELATIONSHIPS[project_id],
        None,
        rule_id="reviewed_asset_boundary_fixture",
        conditioned_on=("dt.project.description",),
        constraints=("value distinguishes direct, financed, or enabled capacity",),
    )
    builder.add(
        "dt.project.generation_accounting_boundary",
        "Generation accounting boundary",
        ASSET_GENERATION_BOUNDARIES[project_id],
        None,
        rule_id="reviewed_asset_boundary_fixture",
        conditioned_on=("dt.project.description",),
        constraints=("value explicitly identifies excluded impact channels",),
    )
    comparable = project_id in ASSET_COMPARABLE_REPORTED_GHG
    builder.add(
        "dt.project.reported_ghg_comparison_status",
        "Reported-to-modelled GHG comparison status",
        "comparable" if comparable else "not_comparable",
        None,
        rule_id="reviewed_asset_boundary_fixture",
        conditioned_on=(
            "dt.project.description",
            "dt.project.generation_accounting_boundary",
        ),
        constraints=("value is comparable or not_comparable",),
    )
    qualification = (
        "The reported target and simplified mini-grid generation pathway share a "
        "compatible asset and operating-horizon boundary for benchmark comparison."
        if comparable
        else "The reported target contains enabled or adjacent effects beyond the restricted generation model; no reported-to-modelled ratio is evaluated."
    )
    for node_id, value in {
        "dt.project.reported_ghg_comparison_qualification": qualification,
        "dt.project.asset_impact_boundary_qualification": (
            "The physical model covers only generation inside the declared boundary; "
            "storage, reliability, network and policy effects are not converted to MWh."
        ),
        "dt.project.environmental_cobenefits": (
            "The benchmark narrative may discuss reduced local pollution and energy-system resilience, without monetising either outcome."
        ),
        "dt.project.social_cobenefits": (
            "The benchmark narrative may discuss electricity access, service reliability and local economic activity without treating beneficiaries as financial returns."
        ),
    }.items():
        builder.add(
            node_id,
            node_id.removeprefix("dt.project.").replace("_", " ").title(),
            value,
            None,
            rule_id="reviewed_asset_boundary_fixture",
            conditioned_on=(
                "dt.project.description",
                "dt.project.generation_accounting_boundary",
            ),
            constraints=("value is non-empty qualified text",),
        )

    # A sanity floor avoids a scenario whose full-build annual result exceeds
    # the reported lifetime point before the compiler applies period arithmetic.
    capacity_value = float(builder.value("dt.project.installed_capacity_target_mw", capacity))
    factor_value = float(builder.value("dt.project.capacity_factor_pct", 30)) / 100
    loss_value = float(builder.value("dt.project.grid_loss_pct", 7)) / 100
    delta = max(0.01, baseline_factor - project_factor)
    annual = capacity_value * 8_760 * factor_value * (1 - loss_value) * delta
    if annual * max(1.0, lifespan) > ghg_point * 5:
        raise ValueError(f"{project_id}: generated asset pathway is implausibly unbounded")


def _add_facility_nodes(builder: _ProjectBuilder) -> None:
    project_id = builder.project_id
    archetype = FACILITY_ARCHETYPES[project_id]
    basis = FACILITY_DEPLOYMENT_BASIS[archetype]
    gcf = float(builder.value("dt.project.gcf_financing_usd"))
    implementation_years = float(builder.value("dt.project.implementation_years"))
    entity = str(builder.value("dt.project.entity_name", "the accredited entity"))

    text_values = {
        "target_market_segment": (
            f"Eligible climate-aligned counterparties and transactions screened by {entity}."
        ),
        "market_financing_barrier": (
            "Insufficient tenor, risk appetite or affordable liquidity for otherwise eligible climate investments."
        ),
        "financial_additionality": (
            "The benchmark facility addresses the declared financing barrier through concessional terms, risk sharing or liquidity support, without assuming a financial return."
        ),
        "eligibility_criteria": (
            "Eligible uses must match the project mandate, pass environmental and social screening, and retain transaction-level financing and impact records."
        ),
        "instrument_terms_qualification": (
            "Instrument amounts are face-value benchmark allocations, not grant "
            "equivalents; pricing, repayment and subsidy values are not inferred. "
            "Unused exhaustive instrument categories are reported as not applicable; "
            "their zero amounts and zero-percent shares are arithmetic balance "
            "placeholders only."
        ),
        "facility_archetype": archetype,
        "facility_deployment_basis": basis,
    }
    for suffix, value in text_values.items():
        builder.add(
            f"dt.project.{suffix}",
            suffix.replace("_", " ").title(),
            value,
            None,
            rule_id="facility_archetype_fixture",
            conditioned_on=("dt.project.description", "dt.project.entity_name"),
            constraints=("value is non-empty text", "value preserves the facility archetype"),
        )

    mix = FACILITY_INSTRUMENT_OVERRIDES.get(
        project_id, FACILITY_INSTRUMENT_MIX[archetype]
    )
    existing_total = 0.0
    unresolved_applicable: list[str] = []
    for suffix in INSTRUMENT_IDS:
        node_id = f"dt.project.{suffix}"
        existing = builder.value(node_id)
        if existing is not None:
            existing_total += float(existing)
        elif suffix in mix:
            unresolved_applicable.append(suffix)
    remaining = gcf - existing_total
    if remaining < -max(1.0, gcf * 1e-9):
        raise ValueError(f"{project_id}: source-backed instrument amounts exceed GCF total")
    weight_total = sum(mix[suffix] for suffix in unresolved_applicable)
    running = 0.0
    for index, suffix in enumerate(unresolved_applicable):
        if index == len(unresolved_applicable) - 1:
            amount = _round(max(0.0, remaining - running), 3)
        else:
            amount = _round(remaining * mix[suffix] / weight_total, 3)
            running += amount
        builder.add(
            f"dt.project.{suffix}",
            suffix.replace("_", " ").title() + " benchmark allocation",
            amount,
            "USD",
            rule_id="archetype_instrument_face_value_mix",
            conditioned_on=(
                "dt.project.facility_archetype",
                "dt.project.gcf_financing_usd",
            ),
            constraints=(
                "value is non-negative",
                "applicable instrument amounts sum to aggregate GCF financing",
                "unit is USD",
            ),
        )
    for suffix in INSTRUMENT_IDS:
        node_id = f"dt.project.{suffix}"
        if not builder.resolved(node_id):
            builder.add_unused_balance_zero(
                node_id,
                suffix.replace("_", " ").title(),
                reason=f"The {archetype} scenario does not use this instrument type.",
                conditioned_on=("dt.project.facility_archetype",),
            )

    applicable_amounts = [
        float(builder.value(f"dt.project.{suffix}", 0.0) or 0.0)
        for suffix in INSTRUMENT_IDS
    ]
    grant = float(builder.value("dt.project.gcf_grant_usd", 0.0) or 0.0)
    envelope = _round(sum(applicable_amounts) - grant, 3)
    if envelope <= 0:
        envelope = _round(gcf, 3)
    profile_scope = (
        "initial deployment cycle only; repayments and recycled capital are excluded"
        if archetype == "revolving_initial_cycle"
        else "full configured deployment profile without recycling or released-capacity reuse"
    )
    recycling = (
        "The underlying mechanism is revolving, but this four-period benchmark profile covers only the initial cycle."
        if archetype == "revolving_initial_cycle"
        else "No repayments, released guarantees or capital reuse enter the four-period state chain."
    )
    for suffix, value, unit in (
        ("facility_deployment_envelope_usd", envelope, "USD"),
        ("facility_profile_scope", profile_scope, None),
        ("facility_recycling_qualification", recycling, None),
    ):
        builder.add(
            f"dt.project.{suffix}",
            suffix.replace("_", " ").title(),
            value,
            unit,
            rule_id="facility_deployment_scope_fixture",
            conditioned_on=tuple(
                ["dt.project.facility_archetype", "dt.project.gcf_financing_usd"]
                + [f"dt.project.{item}" for item in INSTRUMENT_IDS]
            ),
            constraints=_numeric_or_text_constraints(value, unit),
        )

    allocation = _normalised_shares(project_id, "facility_allocation", 4)
    for period, share in enumerate(allocation, start=1):
        builder.add(
            f"dt.project.facility_allocation_period_{period}_share",
            f"Synthetic new-allocation share in facility scenario period {period}",
            share,
            "x",
            rule_id="four_period_facility_allocation_profile",
            conditioned_on=(
                "dt.project.facility_deployment_envelope_usd",
                "dt.project.facility_profile_scope",
            ),
            constraints=(
                "value is between zero and one inclusive",
                "all four facility allocation shares sum to one",
                "unit is x",
            ),
        )
    previous = 0.0
    for period in range(1, 5):
        utilisation = _round(
            min(
                95.0,
                38.0 + period * 12.0 + 4.0 * _unit_interval(
                    project_id, f"facility_utilisation_period_{period}"
                ),
            ),
            3,
        )
        utilisation = max(previous, utilisation)
        previous = utilisation
        builder.add(
            f"dt.project.facility_utilisation_period_{period}_pct",
            f"Utilisation of available allocation in facility scenario period {period}",
            utilisation,
            "%",
            rule_id="monotonic_facility_utilisation_fixture",
            conditioned_on=(
                "dt.project.facility_archetype",
                "dt.project.facility_deployment_basis",
            ),
            constraints=(
                "value is between zero and one hundred inclusive",
                "period utilisation percentages are non-decreasing",
                "unit is %",
            ),
        )
    for period, years in enumerate(_period_years(implementation_years), start=1):
        builder.add(
            f"dt.project.facility_period_{period}_years",
            f"Duration of ordered facility scenario period {period}",
            years,
            "years",
            rule_id="four_period_facility_duration",
            conditioned_on=("dt.project.implementation_years",),
            constraints=(
                "value is positive",
                "all four period durations sum to implementation years",
                "period label is not a calendar year",
                "unit is years",
            ),
        )

    unit_type = FACILITY_PORTFOLIO_TYPES[project_id]
    known_count = {
        "FP039": 10,
        "FP063": 120,
        "FP064": 50,
        "FP071": 100,
        "FP080": 8,
        "FP081": 2_500,
        "FP083": 17,
        "FP106": 20,
        "FP140": 100,
        "FP148": 308,
        "FP163": 35,
        "FP178": 25,
        "FP196": 60,
    }[project_id]
    count_basis = (
        "identified demand pipeline; not a funded-borrower target"
        if project_id == "FP148"
        else "synthetic expected final portfolio for benchmark arithmetic"
    )
    portfolio_values = {
        "portfolio_unit_type": (unit_type, None),
        "portfolio_unit_count": (known_count, unit_type + "s"),
        "portfolio_unit_count_basis": (count_basis, None),
        "portfolio_unit_count_qualification": (
            "The count retains its stated type and basis; per-unit amounts are allocation intensities, not universal ticket sizes.",
            None,
        ),
    }
    for suffix, (value, unit) in portfolio_values.items():
        builder.add(
            f"dt.project.{suffix}",
            suffix.replace("_", " ").title(),
            value,
            unit,
            rule_id="typed_facility_portfolio_fixture",
            conditioned_on=(
                "dt.project.description",
                "dt.project.facility_deployment_envelope_usd",
            ),
            constraints=_numeric_or_text_constraints(value, unit),
        )

    mobilisation_applicable = project_id not in FACILITY_MOBILISATION_NOT_APPLICABLE
    builder.add(
        "dt.project.mobilization_applicability",
        "Additional-capital mobilisation applicability gate",
        "applicable" if mobilisation_applicable else "not_applicable",
        None,
        rule_id="facility_mobilisation_applicability_gate",
        conditioned_on=(
            "dt.project.description",
            "dt.project.facility_archetype",
        ),
        constraints=("value is applicable or not_applicable",),
    )
    if not mobilisation_applicable:
        reason = (
            "FP148 is a liquidity-relief mechanism; the source exposes demand and "
            "service-continuity populations but no distinct incremental-capital objective."
        )
        for suffix in (
            "additional_capital_mobilized_min_usd",
            "additional_capital_mobilized_max_usd",
        ):
            builder.add_na(
                f"dt.project.{suffix}",
                suffix.replace("_", " ").title(),
                "USD",
                reason=reason,
                basis="source-backed mechanism qualification",
                conditioned_on=(
                    "dt.project.description",
                    "dt.project.facility_archetype",
                ),
                rule_id="liquidity_relief_mobilisation_not_applicable",
            )
        builder.add(
            "dt.project.mobilization_qualification",
            "Mobilisation qualification",
            reason + " Mobilisation ratios are therefore not evaluated.",
            None,
            rule_id="liquidity_relief_mobilisation_not_applicable",
            conditioned_on=(
                "dt.project.description",
                "dt.project.facility_archetype",
            ),
            constraints=("value explains why mobilisation is not applicable",),
        )
    else:
        multiplier = 0.65 + 0.7 * _unit_interval(project_id, "mobilised_capital")
        low = _round(envelope * multiplier, 3)
        high = _round(low * 1.35, 3)
        for suffix, value in (
            ("additional_capital_mobilized_min_usd", low),
            ("additional_capital_mobilized_max_usd", high),
        ):
            if builder.resolved(f"dt.project.{suffix}"):
                continue
            builder.add(
                f"dt.project.{suffix}",
                suffix.replace("_", " ").title() + " benchmark range",
                value,
                "USD",
                rule_id="facility_incremental_capital_scenario_range",
                conditioned_on=(
                    "dt.project.facility_archetype",
                    "dt.project.facility_deployment_envelope_usd",
                ),
                constraints=(
                    "value is non-negative",
                    "lower value is no greater than upper value",
                    "value is incremental to the configured deployment envelope",
                    "unit is USD",
                ),
            )
        builder.add(
            "dt.project.mobilization_qualification",
            "Mobilisation qualification",
            (
                "The range is a deterministic benchmark objective for incremental "
                "capital outside the deployment envelope; it is not committed or "
                "realized finance and is not a return."
            ),
            None,
            rule_id="facility_incremental_capital_scenario_range",
            conditioned_on=(
                "dt.project.facility_archetype",
                "dt.project.facility_deployment_envelope_usd",
            ),
            constraints=("value preserves expected-versus-realized qualification",),
        )

    builder.add_collection(_facility_reach_collection(builder, known_count))


def _add_land_nodes(builder: _ProjectBuilder) -> None:
    project_id = builder.project_id
    mode = LAND_MODES[project_id]
    shares = LAND_PATHWAY_SHARES[project_id]
    implementation_years = float(builder.value("dt.project.implementation_years"))
    lifespan = float(builder.value("dt.project.lifespan_years"))
    total_cost = float(builder.value("dt.project.total_cost_usd"))

    builder.add(
        "dt.project.land_use_baseline",
        "Land-use baseline and scenario mode",
        {
            "jurisdictional_redd_plus": "Jurisdictional REDD+ baseline with deforestation reduction, restoration and sustainable-management pathways.",
            "sustainable_plantation": "Sustainable plantation on non-forested land; adjacent natural-forest conservation is outside the claimed carbon pathway.",
            "forest_enterprise": "Forest-enterprise support with avoided-deforestation accounting inside the simplified benchmark boundary.",
        }[mode],
        None,
        rule_id="reviewed_land_mode_fixture",
        conditioned_on=("dt.project.description",),
        constraints=("value identifies the land mode and carbon boundary",),
    )

    accounting_mode = (
        "jurisdictional"
        if mode == "jurisdictional_redd_plus"
        else "investment_portfolio"
        if mode == "sustainable_plantation"
        else "activity_area"
    )
    builder.add(
        "dt.project.land_accounting_mode",
        "Land accounting mode gate",
        accounting_mode,
        None,
        rule_id="reviewed_land_accounting_mode",
        conditioned_on=("dt.project.description", "dt.project.land_use_baseline"),
        constraints=(
            "value is jurisdictional, investment_portfolio, or activity_area",
            "value selects exactly one top-level accounting boundary",
        ),
    )
    applicability_by_category = {
        "protection": "forest_protection" in shares,
        "restoration": "restoration" in shares,
        "plantation_afforestation": "plantation_afforestation" in shares,
        "sustainable_management": "sustainable_management" in shares,
        "jurisdictional": accounting_mode == "jurisdictional",
    }
    for label, applicable in applicability_by_category.items():
        builder.add(
            f"dt.project.{label}_pathway_applicability",
            f"{label.replace('_', ' ').title()} pathway applicability gate",
            "applicable" if applicable else "not_applicable",
            None,
            rule_id="reviewed_land_pathway_gate",
            conditioned_on=(
                "dt.project.land_accounting_mode",
                "dt.project.land_use_baseline",
            ),
            constraints=("value is applicable or not_applicable",),
        )
    applicable_labels = [
        label for label, applicable in applicability_by_category.items() if applicable
    ]
    builder.add(
        "dt.project.land_pathway_applicability",
        "Land pathway applicability summary",
        (
            "Applicable pathway(s): " + ", ".join(applicable_labels)
            + "; every other pathway is explicitly not applicable."
        ),
        None,
        rule_id="reviewed_land_pathway_gate",
        conditioned_on=tuple(
            f"dt.project.{label}_pathway_applicability"
            for label in applicability_by_category
        ),
        constraints=("value lists applicable and excluded pathways",),
    )

    if accounting_mode == "jurisdictional":
        builder.add_na(
            "dt.project.intervention_area_target_ha",
            "Activity-area intervention target",
            "ha",
            reason="A national jurisdictional accounting boundary is not an activity-area allocation.",
            conditioned_on=("dt.project.land_accounting_mode",),
            rule_id="jurisdictional_activity_area_not_applicable",
        )
    else:
        existing_categories = {
            category: builder.value(f"dt.project.{suffix}")
            for category, suffix in LAND_CATEGORY_IDS.items()
            if category in shares
        }
        existing_total = builder.value("dt.project.intervention_area_target_ha")
        if existing_total is None:
            inferred_totals = [
                float(value) / shares[category]
                for category, value in existing_categories.items()
                if value is not None and shares[category] > 0
            ]
            total_area = (
                max(inferred_totals)
                if inferred_totals
                else LAND_DEFAULT_AREA_HA[project_id]
            )
            builder.add(
                "dt.project.intervention_area_target_ha",
                "Synthetic mutually exclusive intervention-area envelope",
                _round(total_area, 3),
                "ha",
                rule_id="land_mode_area_envelope",
                conditioned_on=("dt.project.description", "dt.project.land_use_baseline"),
                constraints=(
                    "value is positive",
                    "applicable mutually exclusive area categories sum to this value",
                    "unit is ha",
                ),
            )
        total_area = float(builder.value("dt.project.intervention_area_target_ha"))
        existing_sum = sum(
            float(value) for value in existing_categories.values() if value is not None
        )
        if existing_sum > total_area + max(1e-6, total_area * 1e-9):
            raise ValueError(f"{project_id}: source-backed land categories exceed total area")
        unresolved = [
            category for category in shares if existing_categories.get(category) is None
        ]
        remaining = total_area - existing_sum
        unresolved_weight = sum(shares[category] for category in unresolved)
        running = 0.0
        for index, category in enumerate(unresolved):
            suffix = LAND_CATEGORY_IDS[category]
            if index == len(unresolved) - 1:
                area = _round(max(0.0, remaining - running), 3)
            else:
                area = _round(remaining * shares[category] / unresolved_weight, 3)
                running += area
            builder.add(
                f"dt.project.{suffix}",
                suffix.replace("_", " ").title() + " benchmark allocation",
                area,
                "ha",
                rule_id="mutually_exclusive_land_pathway_allocation",
                conditioned_on=(
                    "dt.project.intervention_area_target_ha",
                    "dt.project.land_use_baseline",
                ),
                constraints=(
                    "value is non-negative",
                    "applicable mutually exclusive area categories sum to intervention area",
                    "unit is ha",
                ),
            )
    for category, suffix in LAND_CATEGORY_IDS.items():
        node_id = f"dt.project.{suffix}"
        if category not in shares and not builder.resolved(node_id):
            builder.add_na(
                node_id,
                suffix.replace("_", " ").title(),
                "ha",
                reason=(
                    f"The {mode} benchmark carbon boundary excludes the {category} pathway."
                ),
                conditioned_on=(
                    "dt.project.land_carbon_pathway_boundary",
                    "dt.project.land_use_baseline",
                ),
                rule_id="land_pathway_outside_declared_boundary",
            )

    jurisdictional_fields = (
        "jurisdictional_accounting_area_ha",
        "jurisdictional_reference_emissions_tco2e_per_year",
        "jurisdictional_program_emissions_tco2e_per_year",
    )
    if accounting_mode == "jurisdictional":
        # These are deliberately independent scenario inputs.  In the previous
        # fixture, reference and programme emissions were algebraically backed
        # out of the reported target, so the downstream "comparison" was a
        # calibrated identity rather than an informative diagnostic.
        accounting_area = _round(
            9_000_000
            + 4_000_000 * _unit_interval(project_id, "jurisdictional_accounting_area"),
            3,
        )
        reference_intensity = (
            0.35
            + 0.35
            * _unit_interval(project_id, "jurisdictional_reference_intensity")
        )
        programme_reduction_share = (
            0.18
            + 0.22
            * _unit_interval(project_id, "jurisdictional_programme_reduction_share")
        )
        reference_emissions = _round(accounting_area * reference_intensity, 3)
        program_emissions = _round(
            reference_emissions * (1.0 - programme_reduction_share),
            3,
        )
        for suffix, value, unit in (
            ("jurisdictional_accounting_area_ha", accounting_area, "ha"),
            (
                "jurisdictional_reference_emissions_tco2e_per_year",
                reference_emissions,
                "tCO2e/year",
            ),
            (
                "jurisdictional_program_emissions_tco2e_per_year",
                program_emissions,
                "tCO2e/year",
            ),
        ):
            builder.add(
                f"dt.project.{suffix}",
                suffix.replace("_", " ").title() + " benchmark scenario",
                value,
                unit,
                rule_id="independent_jurisdictional_emissions_scenario",
                conditioned_on=(
                    "dt.project.land_accounting_mode",
                    "dt.project.land_use_baseline",
                    "dt.project.countries",
                ),
                constraints=(
                    "value is positive",
                    f"unit is {unit}",
                    "reported GHG target is not a generation input",
                ),
            )
        builder.add(
            "dt.project.jurisdictional_accounting_qualification",
            "Jurisdictional accounting qualification",
            (
                "The national accounting area and annual reference/program emissions "
                "are independently seeded deterministic benchmark-scenario inputs; "
                "the reported GHG target was not an input. They are not source-derived "
                "FREL values, observed performance, or validation of the reported target."
            ),
            None,
            rule_id="independent_jurisdictional_emissions_scenario",
            conditioned_on=tuple(f"dt.project.{item}" for item in jurisdictional_fields),
            constraints=(
                "value distinguishes jurisdictional and activity-area evidence",
                "value states that the reported GHG target was not a generation input",
                "value disclaims observed performance and validation",
            ),
        )
    else:
        for suffix in jurisdictional_fields:
            unit = "ha" if suffix.endswith("_ha") else "tCO2e/year"
            builder.add_na(
                f"dt.project.{suffix}",
                suffix.replace("_", " ").title(),
                unit,
                reason=f"The {accounting_mode} mode does not use a jurisdictional reference level.",
                conditioned_on=("dt.project.land_accounting_mode",),
                rule_id="jurisdictional_pathway_not_applicable",
            )
        builder.add(
            "dt.project.jurisdictional_accounting_qualification",
            "Jurisdictional accounting qualification",
            "Jurisdictional accounting is not applicable to this activity-area or investment-portfolio scenario.",
            None,
            rule_id="jurisdictional_pathway_not_applicable",
            conditioned_on=("dt.project.land_accounting_mode",),
            constraints=("value explains why jurisdictional inputs are not applied",),
        )

    rate_fields = {
        "baseline_deforestation_rate_pct_per_year": (
            _round(1.3 + 1.2 * _unit_interval(project_id, "baseline_deforestation"), 4),
            "%/year",
            "forest_protection",
        ),
        "project_deforestation_rate_pct_per_year": (
            _round(0.25 + 0.35 * _unit_interval(project_id, "project_deforestation"), 4),
            "%/year",
            "forest_protection",
        ),
        "forest_carbon_stock_tco2e_per_ha": (
            _round(180 + 100 * _unit_interval(project_id, "forest_stock"), 4),
            "tCO2e/ha",
            "forest_protection",
        ),
        "restoration_sequestration_tco2e_per_ha_year": (
            _round(4 + 4 * _unit_interval(project_id, "restoration_factor"), 4),
            "tCO2e/ha/year",
            "restoration",
        ),
        "plantation_afforestation_sequestration_tco2e_per_ha_year": (
            _round(6 + 5 * _unit_interval(project_id, "plantation_factor"), 4),
            "tCO2e/ha/year",
            "plantation_afforestation",
        ),
        "sustainable_management_mitigation_tco2e_per_ha_year": (
            _round(1.5 + 3 * _unit_interval(project_id, "management_factor"), 4),
            "tCO2e/ha/year",
            "sustainable_management",
        ),
    }
    for suffix, (value, unit, category) in rate_fields.items():
        node_id = f"dt.project.{suffix}"
        if category in shares:
            builder.add(
                node_id,
                suffix.replace("_", " ").title() + " benchmark parameter",
                value,
                unit,
                rule_id="pathway_specific_land_carbon_parameter",
                conditioned_on=(
                    f"dt.project.{LAND_CATEGORY_IDS[category]}",
                    "dt.project.land_use_baseline",
                ),
                constraints=("value is non-negative", f"unit is {unit}"),
            )
        else:
            builder.add_na(
                node_id,
                suffix.replace("_", " ").title(),
                unit,
                reason=f"The {category} pathway is outside the {mode} carbon boundary.",
                conditioned_on=("dt.project.land_use_baseline",),
                rule_id="land_pathway_outside_declared_boundary",
            )

    adjustment_values = {
        "implementation_effectiveness_pct": 82 + 10 * _unit_interval(project_id, "effectiveness"),
        "leakage_deduction_pct": 6 + 8 * _unit_interval(project_id, "leakage"),
        "permanence_buffer_pct": 10 + 10 * _unit_interval(project_id, "buffer"),
    }
    adjustment_gate_ids = {
        "implementation_effectiveness_pct": "implementation_effectiveness_adjustment_applicability",
        "leakage_deduction_pct": "leakage_adjustment_applicability",
        "permanence_buffer_pct": "permanence_buffer_adjustment_applicability",
    }
    for suffix, value in adjustment_values.items():
        gate_id = adjustment_gate_ids[suffix]
        builder.add(
            f"dt.project.{gate_id}",
            gate_id.replace("_", " ").title(),
            "already_embedded" if accounting_mode == "jurisdictional" else "apply",
            None,
            rule_id="land_adjustment_applicability_gate",
            conditioned_on=(
                "dt.project.land_accounting_mode",
                "dt.project.land_use_baseline",
            ),
            constraints=("value is apply or already_embedded",),
        )
        if accounting_mode == "jurisdictional":
            builder.add_na(
                f"dt.project.{suffix}",
                suffix.replace("_", " ").title(),
                "%",
                reason=(
                    "The jurisdictional reference-versus-program emissions result "
                    "is already net of this adjustment; applying it again would "
                    "double deduct the result."
                ),
                conditioned_on=(
                    f"dt.project.{gate_id}",
                    "dt.project.land_accounting_mode",
                ),
                rule_id="jurisdictional_adjustment_already_embedded",
            )
        else:
            builder.add(
                f"dt.project.{suffix}",
                suffix.replace("_", " ").title() + " benchmark adjustment",
                _round(value, 4),
                "%",
                rule_id="land_accounting_adjustment_fixture",
                conditioned_on=(
                    f"dt.project.{gate_id}",
                    "dt.project.land_use_baseline",
                ),
                constraints=("value is between zero and one hundred", "unit is %"),
            )
    adjustment_qualification = (
        "The jurisdictional reference-versus-program emissions difference is "
        "already net of effectiveness, leakage and permanence treatment; all "
        "three numeric adjustments are N/A and no second deduction is permitted."
        if accounting_mode == "jurisdictional"
        else "Implementation effectiveness is applied first, followed by leakage "
        "and then the permanence reserve, exactly once to the gross result inside "
        f"the {accounting_mode} boundary."
    )
    builder.add(
        "dt.project.land_adjustment_scope_qualification",
        "Land accounting adjustment scope qualification",
        adjustment_qualification,
        None,
        rule_id="land_accounting_adjustment_fixture",
        conditioned_on=(
            "dt.project.implementation_effectiveness_adjustment_applicability",
            "dt.project.leakage_adjustment_applicability",
            "dt.project.permanence_buffer_adjustment_applicability",
        ),
        constraints=("value states the adjustment order and prevents double deduction",),
    )
    builder.add(
        "dt.project.reported_ghg_comparison_status",
        "Reported-to-modelled GHG comparison status",
        "comparable",
        None,
        rule_id="reviewed_land_boundary_fixture",
        conditioned_on=(
            "dt.project.ghg_reduction_tco2e",
            "dt.project.land_accounting_mode",
        ),
        constraints=("value is comparable or not_comparable",),
    )
    comparison_qualification = (
        "The independently seeded jurisdictional scenario uses the same declared "
        "land mode, impact channel and lifespan horizon as the reported point target, "
        "but the target was not an input to the scenario. The comparison is a boundary-"
        "compatible scenario diagnostic, not validation of either the synthetic FREL "
        "inputs or the reported target."
        if accounting_mode == "jurisdictional"
        else "The simplified benchmark model is configured to the same declared "
        "land mode, impact channel and lifespan horizon as the reported point "
        "target. Comparability is boundary compatibility, not validation of "
        "the synthetic rates or factors."
    )
    builder.add(
        "dt.project.reported_ghg_comparison_qualification",
        "Reported-to-modelled GHG comparison qualification",
        comparison_qualification,
        None,
        rule_id="reviewed_land_boundary_fixture",
        conditioned_on=(
            "dt.project.ghg_reduction_tco2e",
            "dt.project.land_accounting_mode",
            "dt.project.land_accounting_horizon_years",
        ),
        constraints=("value distinguishes boundary comparability from factual validation",),
    )

    enrolment = _normalised_shares(project_id, "land_enrolment", 4)
    for period, share in enumerate(enrolment, start=1):
        builder.add(
            f"dt.project.land_enrolment_period_{period}_share",
            f"Synthetic land-enrolment share in scenario period {period}",
            share,
            "x",
            rule_id="four_period_land_enrolment_profile",
            conditioned_on=("dt.project.intervention_area_target_ha",),
            constraints=(
                "value is between zero and one inclusive",
                "all four land enrolment shares sum to one",
                "unit is x",
            ),
        )
    for period, years in enumerate(_period_years(implementation_years), start=1):
        builder.add(
            f"dt.project.land_period_{period}_years",
            f"Duration of ordered land-enrolment scenario period {period}",
            years,
            "years",
            rule_id="four_period_land_duration",
            conditioned_on=("dt.project.implementation_years",),
            constraints=(
                "value is positive",
                "all four period durations sum to implementation years",
                "period label is not a calendar year",
                "unit is years",
            ),
        )
    builder.add(
        "dt.project.land_accounting_horizon_years",
        "Synthetic land-accounting horizon",
        lifespan,
        "years",
        rule_id="lifespan_anchored_land_accounting_horizon",
        conditioned_on=("dt.project.lifespan_years",),
        constraints=("value is positive", "unit is years", "value is a benchmark assumption"),
    )

    synthetic_cost_per_direct_beneficiary = (
        550
        + 450 * _unit_interval(project_id, "land_direct_beneficiary_allocation")
    )
    synthetic_direct_beneficiaries = int(
        max(5_000, round(total_cost / synthetic_cost_per_direct_beneficiary))
    )
    builder.add(
        "dt.project.direct_beneficiaries_target",
        "Direct Beneficiaries Target benchmark scenario",
        synthetic_direct_beneficiaries,
        "people",
        rule_id="land_beneficiary_allocation_scenario",
        conditioned_on=(
            "dt.project.intervention_area_target_ha",
            "dt.project.total_cost_usd",
        ),
        constraints=(
            "value is positive",
            "value is an ex-ante allocation scenario, not observed reach",
            "unit is people",
        ),
    )
    # Use the effective direct-beneficiary target after the source-preserving add.
    # This matters where the proposal supplies a direct count but not disaggregated
    # counts: synthetic subgroups must be based on the preserved source denominator.
    direct_beneficiaries = int(builder.value("dt.project.direct_beneficiaries_target"))
    women_share = 0.46 + 0.12 * _unit_interval(
        project_id, "women_beneficiary_allocation_share"
    )
    local_community_share = 0.58 + 0.27 * _unit_interval(
        project_id, "local_community_beneficiary_allocation_share"
    )
    enterprises = int(
        max(
            20,
            round(
                total_cost
                / (
                    350_000
                    + 400_000
                    * _unit_interval(project_id, "land_livelihood_enterprise_allocation")
                )
            ),
        )
    )
    people = {
        "women_beneficiaries_target": (
            int(round(direct_beneficiaries * women_share)),
            "people",
        ),
        "local_community_beneficiaries_target": (
            int(round(direct_beneficiaries * local_community_share)),
            "people",
        ),
        "livelihood_enterprises_target": (enterprises, "enterprises"),
    }
    for suffix, (value, unit) in people.items():
        value_constraints = (
            (
                "value is non-negative",
                "value is an ex-ante enterprise allocation scenario, not observed performance",
                f"unit is {unit}",
            )
            if suffix == "livelihood_enterprises_target"
            else (
                "value is non-negative",
                "beneficiary subgroup count is no greater than direct beneficiaries",
                "value is an ex-ante allocation scenario, not observed performance",
                f"unit is {unit}",
            )
        )
        builder.add(
            f"dt.project.{suffix}",
            suffix.replace("_", " ").title() + " benchmark scenario",
            value,
            unit,
            rule_id="land_beneficiary_allocation_scenario",
            conditioned_on=(
                "dt.project.direct_beneficiaries_target",
                "dt.project.total_cost_usd",
            ),
            constraints=value_constraints,
        )

    source_backed = builder.source_node_ids
    allocation_basis = ", ".join(
        f"{label}={'source-backed' if node_id in source_backed else 'synthetic scenario'}"
        for label, node_id in (
            ("direct", "dt.project.direct_beneficiaries_target"),
            ("women", "dt.project.women_beneficiaries_target"),
            ("local-community", "dt.project.local_community_beneficiaries_target"),
            ("livelihood-enterprise", "dt.project.livelihood_enterprises_target"),
        )
    )
    builder.add(
        "dt.project.beneficiary_allocation_qualification",
        "Beneficiary allocation scenario qualification",
        (
            f"Input basis: {allocation_basis}. Any synthetic counts are deterministic, "
            "project-specific ex-ante allocation scenarios. Women and local-community "
            "shares are allocation diagnostics only; they do not evidence delivery, "
            "participation, equity, benefit quality, or performance."
        ),
        None,
        rule_id="land_beneficiary_allocation_scenario_disclosure",
        conditioned_on=(
            "dt.project.direct_beneficiaries_target",
            "dt.project.women_beneficiaries_target",
            "dt.project.local_community_beneficiaries_target",
            "dt.project.livelihood_enterprises_target",
        ),
        constraints=(
            "value distinguishes source-backed and synthetic targets",
            "value calls calculated shares allocation diagnostics",
            "value disclaims delivery, equity, and performance evidence",
        ),
    )

    pathway_names = ", ".join(sorted(shares))
    carbon_boundary = (
        "The national jurisdictional reference-level pathway is the sole benchmark carbon boundary; activity-area pathways are excluded."
        if accounting_mode == "jurisdictional"
        else f"Only these mutually exclusive pathways enter the benchmark carbon model: {pathway_names}."
    )
    text = {
        "biodiversity_cobenefits": (
            "Potential habitat-connectivity and ecosystem-resilience benefits are narrative co-benefits and are not converted into carbon or monetary values."
        ),
        "livelihood_cobenefits": (
            "Potential livelihood diversification and local-enterprise benefits are reported separately from carbon outcomes and financial return."
        ),
        "land_carbon_pathway_boundary": carbon_boundary,
        "land_accounting_qualification": (
            "The pathway areas, rates, factors, enrolment profile and deductions are deterministic benchmark assumptions. Plantation is not relabelled as restoration, and co-benefits outside the boundary are excluded."
        ),
    }
    for suffix, value in text.items():
        builder.add(
            f"dt.project.{suffix}",
            suffix.replace("_", " ").title(),
            value,
            None,
            rule_id="reviewed_land_boundary_fixture",
            conditioned_on=("dt.project.description", "dt.project.land_use_baseline"),
            constraints=("value is non-empty qualified text",),
        )


def _facility_reach_collection(
    builder: _ProjectBuilder, portfolio_count: int
) -> dict[str, Any]:
    collection_id = "dt.project.facility_reach"
    if builder.project_id == "FP148":
        rows = (
            (
                ("borrower/company", "dt.project.portfolio_unit_type"),
                (308, "dt.project.portfolio_unit_count"),
                ("identified demand pipeline", "dt.project.portfolio_unit_count_basis"),
                ("proposal-stage demand assessment", None),
                (
                    "Companies expressed a financing need; the count is not a final borrower target.",
                    "dt.project.portfolio_unit_count_qualification",
                ),
            ),
            (
                ("customer", None),
                (85_000_000, "dt.project.people_reached_count"),
                (
                    "current customers of companies in the identified demand pipeline",
                    "dt.project.people_reach_basis",
                ),
                ("source-description current-state estimate", None),
                (
                    "The source states over 85 million current customers; this is not a new-beneficiary target.",
                    "dt.project.people_reach_qualification",
                ),
            ),
            (
                ("person", None),
                (16_300_000, "dt.project.people_at_risk_of_lost_access"),
                ("people whose renewable-energy access is at risk", None),
                ("COVID-19 counterfactual described in the source", None),
                ("At-risk access is not a new-access target.", None),
            ),
        )
    elif builder.project_id == "FP178":
        rows = (
            (
                ("person", None),
                (3_500_000, "dt.project.direct_beneficiaries_target"),
                ("expected direct-beneficiary target", None),
                ("facility outcome horizon", None),
                ("Source-backed target; not a realized result.", None),
            ),
            (
                ("woman", None),
                (1_750_000, "dt.project.women_beneficiaries_target"),
                ("women within the direct-beneficiary target", None),
                ("facility outcome horizon", None),
                ("A subgroup of direct beneficiaries; not additive to that total.", None),
            ),
            (
                ("person", None),
                (700_000, "dt.project.indirect_beneficiaries_target"),
                ("expected indirect-beneficiary target", None),
                ("facility outcome horizon", None),
                ("Reported separately from direct beneficiaries.", None),
            ),
        )
    else:
        rows = (
            (
                ("person", None),
                (int(max(1_000, portfolio_count * 500)), None),
                ("synthetic direct-reach scenario", None),
                ("end of configured facility profile", None),
                ("Benchmark reach scenario; not a source-backed beneficiary target.", None),
            ),
        )

    records = []
    used_classes: set[str] = set()
    field_names = (
        "population_type",
        "count",
        "basis",
        "time_reference",
        "qualification",
    )
    for index, row in enumerate(rows, start=1):
        record_id = f"{collection_id}.reach_{index}"
        fields: dict[str, dict[str, Any]] = {}
        for field_name, (fallback_value, source_id) in zip(field_names, row):
            node_id = f"{record_id}.{field_name}"
            source_node = (
                builder.source.get("nodes", {}).get(source_id) if source_id else None
            )
            if source_node and source_node.get("status") == "available":
                value = source_node["value"]
                unit = source_node.get("unit")
                provenance = dict(source_node.get("provenance", {}))
                provenance["source_node_id"] = source_id
                node = {
                    "id": node_id,
                    "kind": "scalar",
                    "description": field_name.replace("_", " ").title(),
                    "status": "available",
                    "value": value,
                    "unit": unit,
                    "evidence_class": "same_project_source_extraction",
                    "applicability": {
                        "status": "applicable",
                        "basis": "source-backed canonical collection field",
                    },
                    "provenance": provenance,
                    "normalization": {
                        "method": "canonical collection-field alias",
                        "source_node_id": source_id,
                        "imputed": False,
                        "overwrites_source_node": False,
                    },
                }
                used_classes.add("same_project_source_extraction")
            else:
                value = fallback_value
                unit = "people_or_organisations" if field_name == "count" else None
                metadata = synthetic_enrichment_metadata(
                    project_id=builder.project_id,
                    template_id=builder.template_id,
                    node_id=node_id,
                    generator_id=GENERATOR_ID,
                    generator_version=GENERATOR_VERSION,
                    rule_id="typed_facility_reach_fixture",
                    conditioned_on=(
                        "dt.project.portfolio_unit_count",
                        "dt.project.portfolio_unit_type",
                    ),
                    constraints=_numeric_or_text_constraints(value, unit),
                )
                node = {
                    "id": node_id,
                    "kind": "scalar",
                    "description": field_name.replace("_", " ").title(),
                    "status": "available",
                    "value": value,
                    "unit": unit,
                    "applicability": {
                        "status": "applicable",
                        "basis": "benchmark-contract",
                    },
                    **metadata,
                }
                used_classes.add("synthetic_benchmark_enrichment")
            fields[field_name] = node
        records.append(
            {
                "id": record_id,
                "kind": "record",
                "description": "Typed facility reach record",
                "status": "available",
                "fields": fields,
            }
        )
    primary_class = (
        "same_project_source_extraction"
        if "same_project_source_extraction" in used_classes
        else "synthetic_benchmark_enrichment"
    )
    return {
        "id": collection_id,
        "kind": "collection",
        "description": "Typed and qualified facility reach evidence",
        "status": "available",
        "record_schema": list(field_names),
        "records": records,
        "evidence_class": primary_class,
        "field_evidence_classes": sorted(used_classes),
        "contains_synthetic_fields": "synthetic_benchmark_enrichment" in used_classes,
        "not_a_source_claim": primary_class == "synthetic_benchmark_enrichment",
        "provenance": {
            "source_kind": primary_class,
            "project_id": builder.project_id,
            "rule_id": "typed_facility_reach_canonicalization",
        },
    }


def validate_project_enrichment(
    bundle: dict[str, Any],
    *,
    twin: dict[str, Any] | None = None,
    source_normalization: dict[str, Any] | None = None,
) -> list[str]:
    """Validate collision, provenance, range, schedule and applicability invariants."""

    project_id = str(bundle.get("project_id"))
    template_id = str(bundle.get("template_id"))
    source = source_normalization or build_source_normalization(project_id)
    project_twin = twin or read_json(NORMALIZED_ROOT / f"{project_id.lower()}.json")
    nodes = bundle.get("project_nodes", {})
    collections = bundle.get("project_collections", {})
    errors: list[str] = []

    collisions = set(nodes) & (
        set(project_twin.get("nodes", {})) | set(source.get("nodes", {}))
    )
    if collisions:
        errors.append("project nodes collide with source: " + ", ".join(sorted(collisions)))
    collection_collisions = set(collections) & set(project_twin.get("collections", {}))
    if collection_collisions:
        errors.append(
            "project collections collide with source: "
            + ", ".join(sorted(collection_collisions))
        )

    priority_collection = collections.get(KPI_PRIORITY_COLLECTION_ID)
    source_kpis = project_twin.get("collections", {}).get("dt.kpis")
    if not isinstance(priority_collection, dict):
        errors.append("KPI reporting-priority enrichment collection is missing")
    elif not isinstance(source_kpis, dict):
        errors.append("normalized KPI collection dt.kpis is missing")
    else:
        errors.extend(
            validate_kpi_priority_collection(priority_collection, source_kpis)
        )

    for node in list(nodes.values()) + list(_collection_field_nodes(collections)):
        if node.get("evidence_class") == "synthetic_benchmark_enrichment":
            errors.extend(
                validate_synthetic_node(
                    node,
                    project_id=project_id,
                    template_id=template_id,
                )
            )
        if node.get("status") == "not_applicable":
            applicability = node.get("applicability", {})
            if node.get("value") is not None:
                errors.append(f"{node.get('id')}: N/A value must be null")
            if applicability.get("status") != "not_applicable":
                errors.append(f"{node.get('id')}: missing N/A applicability status")
            if not applicability.get("reason") or not applicability.get("basis"):
                errors.append(f"{node.get('id')}: N/A reason and basis are required")

    def effective(node_id: str) -> Any:
        for container in (nodes, source.get("nodes", {}), project_twin.get("nodes", {})):
            node = container.get(node_id)
            if node and node.get("status") == "available":
                return node.get("value")
        return None

    low = effective("dt.project.ghg_reduction_min_tco2e")
    point = effective("dt.project.ghg_reduction_tco2e")
    high = effective("dt.project.ghg_reduction_max_tco2e")
    if not (float(low) <= float(point) <= float(high)):
        errors.append("GHG range does not preserve the observed point target")

    if template_id == "asset_delivery":
        errors.extend(_sum_invariant(effective, "capacity_commissioning_period_{}_share", 1.0))
        errors.extend(
            _sum_invariant(
                effective,
                "delivery_period_{}_years",
                float(effective("dt.project.implementation_years")),
            )
        )
    elif template_id == "financing_facility":
        available_instruments = [
            effective(f"dt.project.{suffix}") for suffix in INSTRUMENT_IDS
        ]
        instrument_sum = sum(float(value) for value in available_instruments if value is not None)
        gcf = float(effective("dt.project.gcf_financing_usd"))
        if not math.isclose(instrument_sum, gcf, rel_tol=0, abs_tol=max(1e-3, gcf * 1e-9)):
            errors.append("applicable facility instruments do not reconcile to GCF financing")
        errors.extend(_sum_invariant(effective, "facility_allocation_period_{}_share", 1.0))
        errors.extend(
            _sum_invariant(
                effective,
                "facility_period_{}_years",
                float(effective("dt.project.implementation_years")),
            )
        )
        utilisation = [
            float(effective(f"dt.project.facility_utilisation_period_{period}_pct"))
            for period in range(1, 5)
        ]
        if utilisation != sorted(utilisation):
            errors.append("facility utilisation percentages are not monotonic")
        mob_low = effective("dt.project.additional_capital_mobilized_min_usd")
        mob_high = effective("dt.project.additional_capital_mobilized_max_usd")
        if project_id == "FP148":
            if mob_low is not None or mob_high is not None:
                errors.append("FP148 mobilisation must be not applicable")
        elif float(mob_low) > float(mob_high):
            errors.append("facility mobilisation range is reversed")
    elif template_id == "land_use_nature":
        accounting_mode = effective("dt.project.land_accounting_mode")
        if accounting_mode == "jurisdictional":
            if effective("dt.project.jurisdictional_accounting_area_ha") is None:
                errors.append("jurisdictional mode requires an accounting area")
            if effective("dt.project.intervention_area_target_ha") is not None:
                errors.append("jurisdictional mode must not invent an activity-area total")
            reference_emissions = float(
                effective(
                    "dt.project.jurisdictional_reference_emissions_tco2e_per_year"
                )
            )
            programme_emissions = float(
                effective(
                    "dt.project.jurisdictional_program_emissions_tco2e_per_year"
                )
            )
            if not 0 < programme_emissions < reference_emissions:
                errors.append(
                    "jurisdictional scenario must have positive programme emissions "
                    "below positive reference emissions"
                )
            for node_id in (
                "dt.project.jurisdictional_accounting_area_ha",
                "dt.project.jurisdictional_reference_emissions_tco2e_per_year",
                "dt.project.jurisdictional_program_emissions_tco2e_per_year",
            ):
                node = nodes.get(node_id, {})
                if "dt.project.ghg_reduction_tco2e" in node.get(
                    "conditioned_on", []
                ):
                    errors.append(
                        f"{node_id}: reported GHG target must not calibrate the "
                        "jurisdictional scenario"
                    )
                if node.get("provenance", {}).get("rule_id") != (
                    "independent_jurisdictional_emissions_scenario"
                ):
                    errors.append(
                        f"{node_id}: jurisdictional scenario is not marked independent"
                    )
            jurisdictional_qualification = str(
                effective("dt.project.jurisdictional_accounting_qualification")
            ).lower()
            if (
                "target was not an input" not in jurisdictional_qualification
                or "validation" not in jurisdictional_qualification
            ):
                errors.append(
                    "jurisdictional qualification must disclose target independence "
                    "and disclaim validation"
                )
        else:
            area_values = [
                effective(f"dt.project.{suffix}")
                for suffix in LAND_CATEGORY_IDS.values()
            ]
            area_sum = sum(float(value) for value in area_values if value is not None)
            total_area = float(effective("dt.project.intervention_area_target_ha"))
            if not math.isclose(
                area_sum,
                total_area,
                rel_tol=0,
                abs_tol=max(1e-3, total_area * 1e-9),
            ):
                errors.append("applicable mutually exclusive land areas do not reconcile")

        direct_beneficiaries = float(
            effective("dt.project.direct_beneficiaries_target")
        )
        if direct_beneficiaries <= 0:
            errors.append("direct-beneficiary target must be positive")
        for node_id, lower, upper in (
            ("dt.project.women_beneficiaries_target", 0.45, 0.59),
            ("dt.project.local_community_beneficiaries_target", 0.57, 0.86),
        ):
            node = nodes.get(node_id)
            if not node or node.get("evidence_class") != (
                "synthetic_benchmark_enrichment"
            ):
                continue
            subgroup_count = float(effective(node_id))
            subgroup_share = subgroup_count / direct_beneficiaries
            if subgroup_count > direct_beneficiaries:
                errors.append(f"{node_id}: synthetic subgroup exceeds direct target")
            if not lower <= subgroup_share <= upper:
                errors.append(
                    f"{node_id}: synthetic allocation share is outside its "
                    "published plausible range"
                )
        allocation_qualification = str(
            effective("dt.project.beneficiary_allocation_qualification")
        ).lower()
        if (
            "allocation diagnostics only" not in allocation_qualification
            or "do not evidence" not in allocation_qualification
            or "performance" not in allocation_qualification
        ):
            errors.append(
                "beneficiary allocation qualification must disclose diagnostic-only "
                "status and disclaim performance evidence"
            )
        errors.extend(_sum_invariant(effective, "land_enrolment_period_{}_share", 1.0))
        errors.extend(
            _sum_invariant(
                effective,
                "land_period_{}_years",
                float(effective("dt.project.implementation_years")),
            )
        )

    return errors


def validate_all_project_enrichments(
    bundles: Mapping[str, dict[str, Any]] | None = None,
) -> list[str]:
    payloads = dict(bundles or build_all_project_enrichments())
    assignments = project_specialisation_assignments()
    errors: list[str] = []
    if set(payloads) != set(assignments):
        errors.append("enrichment bundle keys do not match the twenty-project population")
    for project_id, payload in payloads.items():
        if payload.get("template_id") != assignments.get(project_id):
            errors.append(f"{project_id}: enrichment template assignment changed")
        errors.extend(f"{project_id}: {error}" for error in validate_project_enrichment(payload))
    return errors


def _sum_invariant(
    effective: Any,
    suffix_pattern: str,
    expected: float,
) -> list[str]:
    values = [
        float(effective(f"dt.project.{suffix_pattern.format(period)}"))
        for period in range(1, 5)
    ]
    if not math.isclose(sum(values), expected, rel_tol=0, abs_tol=max(1e-9, abs(expected) * 1e-9)):
        return [f"{suffix_pattern}: values do not sum to {expected}"]
    if any(value < 0 for value in values):
        return [f"{suffix_pattern}: values must be non-negative"]
    return []


def _normalised_shares(project_id: str, group: str, count: int) -> list[float]:
    raw = [
        0.5 + 1.5 * _unit_interval(project_id, f"{group}_period_{index}")
        for index in range(1, count + 1)
    ]
    total = sum(raw)
    shares = [_round(value / total, 12) for value in raw[:-1]]
    shares.append(_round(1.0 - sum(shares), 12))
    return shares


def _period_years(total_years: float) -> list[float]:
    first = _round(total_years / 4, 12)
    values = [first, first, first]
    values.append(_round(total_years - sum(values), 12))
    return values


def _unit_interval(project_id: str, node_id: str) -> float:
    seed = synthetic_seed(
        project_id=project_id,
        node_id=node_id,
        generator_id=GENERATOR_ID,
        generator_version=GENERATOR_VERSION,
        contract=load_enrichment_contract(),
    )
    return int(seed[:13], 16) / float(0xFFFFFFFFFFFFF)


def _numeric_or_text_constraints(value: Any, unit: str | None) -> tuple[str, ...]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return ("value is finite and non-negative", f"unit is {unit or 'unitless'}")
    return ("value is non-empty text", f"unit is {unit or 'unitless'}")


def _collection_field_nodes(
    collections: Mapping[str, dict[str, Any]],
) -> Iterable[dict[str, Any]]:
    for collection in collections.values():
        for record in collection.get("records", []):
            yield from record.get("fields", {}).values()


def _round(value: float, places: int) -> float:
    rounded = round(float(value), places)
    return 0.0 if rounded == -0.0 else rounded


def main() -> None:
    payloads = write_all_project_enrichments()
    project_nodes = sum(len(payload["project_nodes"]) for payload in payloads.values())
    references = sum(len(payload["reference_nodes"]) for payload in payloads.values())
    print(
        f"{PROJECTS_OUTPUT_ROOT} ({len(payloads)} enrichment bundles, "
        f"{project_nodes} project nodes, {references} reference nodes)"
    )


if __name__ == "__main__":
    main()
