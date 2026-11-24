"""Zero-provider integrity checks for the released V2 benchmark."""

from __future__ import annotations

from typing import Any

import jsonschema

from .domain.calculations import calculation_registry
from .paths import (
    CATALOGUE_ROOT,
    DATA_ROOT,
    NORMALIZED_ROOT,
    RAW_CLIMATEFUND_PATH,
    REFERENCE_ROOT,
    SCHEMA_ROOT,
)
from .runtime.calculator import Calculator
from .runtime.evidence_store import EvidenceStore
from .runtime.rendering import calculate_all
from .util import read_json, read_yaml, sha256_json
from .v2.contract import contract_summary, validate_compiled_contract
from .v2.contract_registry import DEFAULT_CONTRACT_REGISTRY
from .v2.enrichment_all20 import (
    build_all_project_enrichments,
    project_output_path as enrichment_output_path,
)
from .v2.evidence import prepare_v2_reference, prepare_v2_twin
from .v2.oracle import DEFAULT_GOLD_ROOT, validate_resolved_gold_population
from .v2.perturbations import TOPOLOGY_CATEGORIES, validate_population_conditions
from .v2.preflight import preflight_study_population
from .v2.registry import calculation_registry as v2_calculation_registry
from .v2.source_normalization import (
    build_all_source_normalizations,
    project_output_path as source_normalization_output_path,
)
from .v2.study_design import validate_study_design


def validate_everything() -> dict[str, Any]:
    """Validate every immutable V2 input without making a provider call."""

    errors: list[str] = []
    v2_errors: list[str] = []
    v2_errors.extend(validate_population_conditions())
    v2_errors.extend(validate_study_design())

    family_summaries: dict[str, dict[str, Any]] = {}
    for contract_id in (
        "asset_delivery",
        "financing_facility",
        "land_use_nature",
    ):
        try:
            contract = DEFAULT_CONTRACT_REGISTRY.get(contract_id).load()
            contract_errors = validate_compiled_contract(contract)
            v2_errors.extend(
                f"{contract_id}: {message}" for message in contract_errors
            )
            summary = contract_summary(contract)
            summary["project_count"] = contract["population_binding"][
                "assigned_project_count"
            ]
            family_summaries[contract_id] = summary
        except (KeyError, OSError, TypeError, ValueError) as exc:
            v2_errors.append(f"{contract_id}: {exc}")
    errors.extend(f"v2 contract: {message}" for message in v2_errors)

    expected_normalizations = build_all_source_normalizations()
    for project_id, expected in expected_normalizations.items():
        path = source_normalization_output_path(project_id)
        if not path.is_file() or read_json(path) != expected:
            errors.append(f"v2 {project_id}: source normalization is stale")

    expected_enrichments = build_all_project_enrichments(
        source_normalizations=expected_normalizations
    )
    for project_id, expected in expected_enrichments.items():
        path = enrichment_output_path(project_id)
        if not path.is_file() or read_json(path) != expected:
            errors.append(f"v2 {project_id}: enrichment bundle is stale")

    population_preflight = preflight_study_population()
    if population_preflight.get("provider_calls") != 0:
        errors.append("v2 population preflight made provider calls")
    if population_preflight.get("project_count") != 20:
        errors.append("v2 population preflight did not cover all 20 projects")
    if population_preflight.get("ready_project_count") != 20:
        errors.append("v2 population preflight did not ready all 20 projects")
    if population_preflight.get("all_ready_for_provider_smoke") is not True:
        errors.append("v2 population preflight failed")

    dataset_manifest = read_json(DATA_ROOT / "manifest.json")
    expected_inputs = {
        "canonical_overrides": read_yaml(DATA_ROOT / "canonical_overrides.yaml") or {},
        "finance_enrichment": read_yaml(DATA_ROOT / "finance_enrichment.yaml") or {},
    }
    if RAW_CLIMATEFUND_PATH.is_file():
        expected_inputs["climatefund_twins"] = read_json(RAW_CLIMATEFUND_PATH)
    for input_id, value in expected_inputs.items():
        observed_hash = (
            dataset_manifest.get("inputs", {}).get(input_id, {}).get("sha256")
        )
        if observed_hash != sha256_json(value):
            errors.append(f"dataset input hash mismatch: {input_id}")

    twin_schema = read_json(SCHEMA_ROOT / "project_twin.schema.json")
    calculation_schema = read_json(SCHEMA_ROOT / "calculation_registry.schema.json")
    catalogue_schema = read_json(SCHEMA_ROOT / "data_catalogue.schema.json")
    reference_schema = read_json(SCHEMA_ROOT / "reference_registry.schema.json")
    for schema in (
        twin_schema,
        calculation_schema,
        catalogue_schema,
        reference_schema,
    ):
        jsonschema.Draft202012Validator.check_schema(schema)

    projects: list[dict[str, Any]] = []
    for path in sorted(NORMALIZED_ROOT.glob("fp*.json")):
        twin = read_json(path)
        projects.append(twin)
        for issue in jsonschema.Draft202012Validator(twin_schema).iter_errors(twin):
            errors.append(f"{path.name}: {issue.message}")
        kpis = twin["collections"]["dt.selected_kpis"]["records"]
        risks = twin["collections"]["dt.risks"]["records"]
        if len(kpis) != 5:
            errors.append(f"{twin['project_id']}: expected 5 selected KPIs")
        if len(risks) < 3:
            errors.append(f"{twin['project_id']}: expected at least 3 risks")
    if len(projects) != 20:
        errors.append(f"expected 20 projects, received {len(projects)}")

    manifest_projects = {
        item["project_id"]: item for item in dataset_manifest.get("projects", [])
    }
    for project in projects:
        entry = manifest_projects.get(project["project_id"])
        if entry is None or entry.get("sha256") != sha256_json(project):
            errors.append(f"{project['project_id']}: normalized project hash mismatch")

    by_project = {item["project_id"]: item for item in projects}
    if (
        by_project.get("FP071", {})
        .get("nodes", {})
        .get("dt.project.ghg_reduction_tco2e", {})
        .get("value")
        != 120_000_000
    ):
        errors.append("FP071 canonical GHG unit normalization is not applied")

    base_registry = calculation_registry()
    for issue in jsonschema.Draft202012Validator(calculation_schema).iter_errors(
        base_registry
    ):
        errors.append(f"calculation registry: {issue.message}")

    reference = read_json(REFERENCE_ROOT / "climatefund20-v1.json")
    for issue in jsonschema.Draft202012Validator(reference_schema).iter_errors(reference):
        errors.append(f"reference registry: {issue.message}")
    if reference.get("frozen") is not True or reference.get("version") != 1:
        errors.append("reference.climatefund20.v1 is not frozen at version 1")
    if dataset_manifest.get("reference", {}).get("sha256") != sha256_json(reference):
        errors.append("frozen reference hash mismatch")

    if "FP083" in by_project:
        v2_store = EvidenceStore(
            prepare_v2_twin(by_project["FP083"]),
            prepare_v2_reference(reference),
        )
        v2_result = calculate_all(
            Calculator(v2_store, registry=v2_calculation_registry())
        )
        v2_unavailable = sorted(
            item["id"]
            for item in v2_result["results"]
            if item.get("status") != "available"
        )
        if v2_unavailable:
            errors.append(
                "v2 FP083 calculations unavailable: " + ", ".join(v2_unavailable)
            )

    for project in projects:
        for node_id in (
            "dt.project.gcf_financing_usd",
            "dt.project.cofinance_usd",
        ):
            if project["nodes"][node_id]["status"] != "available":
                errors.append(
                    f"{project['project_id']}: complete evidence lacks {node_id}"
                )
        store = EvidenceStore(project, reference)
        calculate_all(Calculator(store))
        unavailable = sorted(
            node_id
            for node_id, node in store.calculated().items()
            if node.get("status") != "available"
        )
        if unavailable:
            errors.append(
                f"{project['project_id']}: complete calculations unavailable: "
                + ", ".join(unavailable)
            )

    catalogue = read_json(CATALOGUE_ROOT / "global_catalogue.json")
    for issue in jsonschema.Draft202012Validator(catalogue_schema).iter_errors(catalogue):
        errors.append(f"data catalogue: {issue.message}")
    if set(catalogue["calculations"]) != set(base_registry):
        errors.append("catalogue and calculation registry differ")
    if dataset_manifest.get("catalogue", {}).get("sha256") != sha256_json(catalogue):
        errors.append("global catalogue hash mismatch")

    executable_gold_errors = validate_resolved_gold_population(
        DEFAULT_GOLD_ROOT,
        require_conditions=True,
    )
    errors.extend(
        f"v2 executable gold: {message}" for message in executable_gold_errors
    )
    executable_gold_manifest = (
        read_json(DEFAULT_GOLD_ROOT / "manifest.json")
        if (DEFAULT_GOLD_ROOT / "manifest.json").is_file()
        else {}
    )

    return {
        "valid": not errors,
        "errors": errors,
        "project_count": len(projects),
        "calculation_count": len(base_registry),
        "v2_population_project_count": population_preflight["project_count"],
        "v2_population_ready_project_count": population_preflight[
            "ready_project_count"
        ],
        "v2_population_fully_resolved_project_count": population_preflight[
            "fully_resolved_project_count"
        ],
        "v2_population_fully_available_project_count": population_preflight[
            "fully_available_project_count"
        ],
        "v2_population_provider_calls": population_preflight["provider_calls"],
        "v2_family_contracts": family_summaries,
        "v2_executable_gold": {
            "project_count": executable_gold_manifest.get("project_count", 0),
            "gold_count": executable_gold_manifest.get("gold_count", 0),
            "conditions_included": executable_gold_manifest.get(
                "conditions_included", False
            ),
            "provider_calls": executable_gold_manifest.get("provider_calls", 0),
            "valid": not executable_gold_errors,
        },
        "v2_perturbation_mask_count": 20 * len(TOPOLOGY_CATEGORIES),
        "v2_perturbation_mutation_count": 20 * len(TOPOLOGY_CATEGORIES),
    }
