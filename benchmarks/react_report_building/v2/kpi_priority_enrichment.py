"""Explicit synthetic reporting-priority enrichment for normalized KPIs."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..domain.kpi_selection import canonical_indicator_name, classify_kpi
from ..domain.priority_calculations import KPI_PRIORITY_BY_FAMILY
from .enrichment_specs import GENERATOR_ID, GENERATOR_VERSION
from .study_design import synthetic_enrichment_metadata


COLLECTION_ID = "dt.kpi_reporting_priorities"
METHOD_VERSION = "kpi_reporting_priority_family_v2"
PRIORITY_BASIS = {
    "climate_impact": "Direct quantified climate-mitigation or emissions outcome",
    "climate_resilience": "Direct quantified climate-resilience outcome",
    "land_nature_outcome": "Core quantified land-use or nature outcome",
    "low_emission_capacity": "Core quantified low-emission capacity or output outcome",
    "beneficiaries_access": "Core quantified beneficiary or access outcome",
    "finance_investment": "Financing mobilisation or investment outcome",
    "employment_gender": "Employment, gender or inclusion outcome",
    "policy_governance": "Policy, regulatory or governance outcome",
    "institutional_capacity": "Institutional capacity or training outcome",
    "other": "Other project-specific output or outcome",
}

# These exceptions were identified by a record-by-record audit of the pinned
# 20-project corpus. Keys deliberately include both project and stable source
# path stored in ``source_id``; the exact-ish indicator guard makes a corpus change
# fail loudly instead of silently applying an obsolete override. Overrides live
# only in this synthetic benchmark sidecar and never mutate source-normalized KPI
# fields.
KPI_FAMILY_OVERRIDES: dict[tuple[str, str], dict[str, str]] = {
    ("FP039", "outcomes.3.kpis.0"): {
        "expected_indicator": "Completion of the model on the renewable energy injection capacity into the grid",
        "family": "other",
        "reason": "Model completion is an administrative deliverable, not delivered low-emission capacity.",
    },
    ("FP063", "outcomes.3.kpis.0"): {
        "expected_indicator": "Number of integrated ESI financing strategies developed",
        "family": "policy_governance",
        "reason": "A strategy-development count is a governance output, not a volume of finance mobilised.",
    },
    ("FP080", "outcomes.7.kpis.0"): {
        "expected_indicator": "Detailed rural energy access plans developed and adopted",
        "family": "policy_governance",
        "reason": "Plan adoption is a planning output, not evidence that households obtained access.",
    },
    ("FP081", "outcomes.2.kpis.0"): {
        "expected_indicator": "No. of funding proposals received by TCCL",
        "family": "other",
        "reason": "Proposal receipt is an administrative pipeline count, not finance deployed or mobilised.",
    },
    ("FP090", "outcomes.2.kpis.0"): {
        "expected_indicator": "M5.1 Enhanced capacity assess renewable energy technologies and set off-take tariffs for power purchaseAgreements (PPAs) for private sector funded investment",
        "family": "institutional_capacity",
        "reason": "The measured construct is assessment and tariff-setting capacity, not investment volume.",
    },
    ("FP106", "outcomes.2.kpis.1"): {
        "expected_indicator": "Number of Projects approved under the programme (Solar PV)",
        "family": "other",
        "reason": "Project approval is a pipeline milestone, not installed solar capacity or output.",
    },
    ("FP128", "outcomes.0.kpis.1"): {
        "expected_indicator": "Number of technologies and innovative solutions transferred or licensed to promote low-emission development as a result of Arbaro Fund support.",
        "family": "other",
        "reason": "Technology-transfer count is not a finance amount merely because Fund support is mentioned.",
    },
    ("FP148", "outcomes.2.kpis.0"): {
        "expected_indicator": "Outcome 1.1.1 % of companies receiving EARF funds report that they have reached precrisis sales levels as a result of EARF funding",
        "family": "other",
        "reason": "Sales recovery is a business-continuity outcome, not finance deployed or mobilised.",
    },
    ("FP148", "outcomes.3.kpis.0"): {
        "expected_indicator": "Outcome 1.2.1 % of companies in EARF portfolio that adopt a flexible work policy",
        "family": "other",
        "reason": "Flexible-work policy adoption is an administrative resilience output, not climate policy or governance.",
    },
    ("FP148", "outcomes.3.kpis.1"): {
        "expected_indicator": "Outcome 1.2.2 % of companies receiving EARF funds communicat e public health information regarding COVID-19 to their customer base",
        "family": "other",
        "reason": "Public-health communication is not a beneficiary-access outcome merely because customers are addressed.",
    },
    ("FP148", "outcomes.3.kpis.2"): {
        "expected_indicator": "Outcome 1.2.3 Essential service centers, such as health facilities, schools, and public service hubs, powered by companies receiving EARF funding",
        "family": "beneficiaries_access",
        "reason": "The measured outcome is powered essential services; the reference to funding does not make it a finance-volume indicator.",
    },
    ("FP148", "outcomes.4.kpis.2"): {
        "expected_indicator": "Outcome 2.1.3 # of energy access companies NOT receiving EARF funding who gain material insight into business continuity practices or other improved operational strategies",
        "family": "other",
        "reason": "Knowledge uptake is neither finance deployed nor policy adoption.",
    },
    ("FP148", "outcomes.5.kpis.0"): {
        "expected_indicator": "Outcome 2.2.1 # of organization s represented in EARFrelated strategy sessions, knowledge sessions, and/or working groups",
        "family": "other",
        "reason": "Participation in knowledge sessions is an administrative engagement count, not a policy or governance result.",
    },
    ("FP163", "outcomes.1.kpis.1"): {
        "expected_indicator": "Solar and wind park critical studies and the parks are ready for tendering",
        "family": "other",
        "reason": "Study and tender readiness is not installed renewable capacity.",
    },
    ("FP196", "outcomes.3.kpis.0"): {
        "expected_indicator": "Strengthened financing capacity of local FIs",
        "family": "institutional_capacity",
        "reason": "The indicator measures institutional capacity, not a finance amount.",
    },
}


def build_kpi_priority_collection(
    *,
    project_id: str,
    template_id: str,
    twin: dict[str, Any],
) -> dict[str, Any]:
    """Map every cleaned source KPI to a disclosed 1–5 benchmark priority."""

    source = twin.get("collections", {}).get("dt.kpis")
    if not isinstance(source, dict) or source.get("kind") != "collection":
        raise ValueError(f"{project_id}: normalized twin lacks dt.kpis")
    records: list[dict[str, Any]] = []
    applied_overrides: set[tuple[str, str]] = set()
    for index, kpi in enumerate(source.get("records", []), start=1):
        family_field = kpi.get("fields", {}).get("family", {})
        normalized_family = str(family_field.get("value") or "")
        if (
            family_field.get("status") != "available"
            or normalized_family not in KPI_PRIORITY_BY_FAMILY
        ):
            raise ValueError(
                f"{project_id}: {kpi.get('id')} lacks a recognized KPI family"
            )
        indicator_field = kpi.get("fields", {}).get("indicator", {})
        indicator = str(indicator_field.get("value") or "")
        classified_family = classify_kpi(indicator)
        if classified_family not in KPI_PRIORITY_BY_FAMILY:
            raise ValueError(
                f"{project_id}: {kpi.get('id')} classifier produced unknown family "
                f"{classified_family!r}"
            )
        source_id_field = kpi.get("fields", {}).get("source_id", {})
        source_id = str(source_id_field.get("value") or "")
        override_key = (project_id.upper(), source_id)
        override = KPI_FAMILY_OVERRIDES.get(override_key)
        if override is not None:
            if canonical_indicator_name(indicator) != canonical_indicator_name(
                override["expected_indicator"]
            ):
                raise ValueError(
                    f"{project_id}: stale KPI family override for {kpi.get('id')}"
                )
            family = override["family"]
            assignment_method = "project_source_id_override"
            assignment_reason = override["reason"]
            applied_overrides.add(override_key)
        else:
            family = classified_family
            assignment_method = "deterministic_indicator_classifier"
            assignment_reason = (
                "Effective family is assigned deterministically from the normalized "
                "indicator text; the source-normalized record is not mutated."
            )
        if family not in KPI_PRIORITY_BY_FAMILY:
            raise ValueError(
                f"{project_id}: {kpi.get('id')} override has unknown family {family!r}"
            )
        source_order_field = kpi.get("fields", {}).get("source_order", {})
        source_order = (
            source_order_field.get("value")
            if source_order_field.get("status") == "available"
            else index
        )
        record_id = f"{COLLECTION_ID}.priority_{index}"
        classification_dependencies = (
            str(source_id_field.get("id")),
            str(indicator_field.get("id")),
        )
        conditioned_on = (
            str(kpi.get("id")),
            str(source_id_field.get("id")),
            str(family_field.get("id")),
            str(indicator_field.get("id")),
            str(source_order_field.get("id")),
        )
        values = {
            "source_record_id": (str(kpi["id"]), None),
            "source_order": (int(source_order), None),
            "normalized_kpi_family": (normalized_family, None),
            "kpi_family": (family, None),
            "family_assignment_method": (assignment_method, None),
            "family_assignment_reason": (assignment_reason, None),
            "benchmark_reporting_priority": (
                KPI_PRIORITY_BY_FAMILY[family],
                "priority",
            ),
            "benchmark_priority_basis": (PRIORITY_BASIS[family], None),
            "priority_method_version": (METHOD_VERSION, None),
        }
        field_dependencies = {
            "source_record_id": (str(kpi.get("id")), str(source_id_field.get("id"))),
            "source_order": (str(source_order_field.get("id")),),
            "normalized_kpi_family": (str(family_field.get("id")),),
            "kpi_family": classification_dependencies,
            "family_assignment_method": classification_dependencies,
            "family_assignment_reason": classification_dependencies,
            "benchmark_reporting_priority": classification_dependencies,
            "benchmark_priority_basis": classification_dependencies,
            "priority_method_version": classification_dependencies,
        }
        fields = {
            name: _synthetic_field(
                project_id=project_id,
                template_id=template_id,
                node_id=f"{record_id}.{name}",
                description=name.replace("_", " ").title(),
                value=value,
                unit=unit,
                conditioned_on=field_dependencies[name],
            )
            for name, (value, unit) in values.items()
        }
        record_metadata = synthetic_enrichment_metadata(
            project_id=project_id,
            template_id=template_id,
            node_id=record_id,
            generator_id=GENERATOR_ID,
            generator_version=GENERATOR_VERSION,
            rule_id=METHOD_VERSION,
            conditioned_on=conditioned_on,
            constraints=(
                "record maps exactly one normalized KPI record",
                "priority is an integer from 1 to 5",
                "priority is a benchmark reporting assumption, not a source claim",
            ),
        )
        records.append(
            {
                "id": record_id,
                "kind": "record",
                "description": "Synthetic benchmark KPI reporting priority",
                "status": "available",
                "fields": fields,
                **record_metadata,
            }
        )

    expected_overrides = {
        key for key in KPI_FAMILY_OVERRIDES if key[0] == project_id.upper()
    }
    if applied_overrides != expected_overrides:
        missing = sorted(expected_overrides - applied_overrides)
        raise ValueError(f"{project_id}: KPI family overrides were not applied: {missing}")

    collection_metadata = synthetic_enrichment_metadata(
        project_id=project_id,
        template_id=template_id,
        node_id=COLLECTION_ID,
        generator_id=GENERATOR_ID,
        generator_version=GENERATOR_VERSION,
        rule_id=METHOD_VERSION,
        conditioned_on=("dt.kpis",),
        constraints=(
            "contains one priority record for every cleaned normalized KPI",
            "contains no source KPI values",
            "all priorities are explicit benchmark assumptions",
        ),
    )
    return {
        "id": COLLECTION_ID,
        "kind": "collection",
        "description": (
            "Synthetic benchmark reporting priorities kept separate from the "
            "normalized KPI collection"
        ),
        "status": "available" if records else "missing",
        "record_schema": [
            "source_record_id",
            "source_order",
            "normalized_kpi_family",
            "kpi_family",
            "family_assignment_method",
            "family_assignment_reason",
            "benchmark_reporting_priority",
            "benchmark_priority_basis",
            "priority_method_version",
        ],
        "records": records,
        **collection_metadata,
    }


def validate_kpi_priority_collection(
    collection: dict[str, Any],
    source_kpis: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    source_ids = [str(record["id"]) for record in source_kpis.get("records", [])]
    mapped_ids = [
        str(record.get("fields", {}).get("source_record_id", {}).get("value"))
        for record in collection.get("records", [])
    ]
    if mapped_ids != source_ids:
        errors.append("KPI priority mapping is not complete and source ordered")
    if len(mapped_ids) != len(set(mapped_ids)):
        errors.append("KPI priority mapping contains duplicate source records")
    for record in collection.get("records", []):
        field = record.get("fields", {}).get("benchmark_reporting_priority", {})
        value = field.get("value")
        if field.get("status") != "available" or not isinstance(value, int) or not 1 <= value <= 5:
            errors.append(f"{record.get('id')}: invalid benchmark reporting priority")
        fields = record.get("fields", {})
        family = fields.get("kpi_family", {}).get("value")
        if family not in KPI_PRIORITY_BY_FAMILY:
            errors.append(f"{record.get('id')}: invalid effective KPI family")
        elif value != KPI_PRIORITY_BY_FAMILY[family]:
            errors.append(f"{record.get('id')}: priority does not match effective KPI family")
        method = fields.get("family_assignment_method", {}).get("value")
        if method not in {
            "deterministic_indicator_classifier",
            "project_source_id_override",
        }:
            errors.append(f"{record.get('id')}: invalid family assignment method")
        reason = fields.get("family_assignment_reason", {}).get("value")
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"{record.get('id')}: missing family assignment reason")
    return errors


def _synthetic_field(
    *,
    project_id: str,
    template_id: str,
    node_id: str,
    description: str,
    value: Any,
    unit: str | None,
    conditioned_on: tuple[str, ...],
) -> dict[str, Any]:
    metadata = synthetic_enrichment_metadata(
        project_id=project_id,
        template_id=template_id,
        node_id=node_id,
        generator_id=GENERATOR_ID,
        generator_version=GENERATOR_VERSION,
        rule_id=METHOD_VERSION,
        conditioned_on=conditioned_on,
        constraints=(
            "value is deterministic under the published family rule",
            "value does not overwrite a normalized KPI field",
            "value is not a source claim",
        ),
    )
    return {
        "id": node_id,
        "kind": "scalar",
        "description": description,
        "status": "available",
        "value": deepcopy(value),
        "unit": unit,
        "dependencies": sorted(set(conditioned_on)),
        **metadata,
    }
