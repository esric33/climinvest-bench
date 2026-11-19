"""Population, canary, and evidence metadata for the v2 study design.

This module deliberately does not resolve compiled document contracts. Once the
three contracts exist, ``contract_registry.ContractRegistry`` should consume the
authoritative twenty-project assignments exposed here and bind each
specialisation to its compiled artifact. The ten-project canary inherits those
assignments; it is never treated as the default study population.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

from ..paths import DATA_ROOT
from ..util import read_json, sha256_json


V2_ROOT = Path(__file__).resolve().parent
STUDY_ROOT = V2_ROOT / "data" / "study"
POPULATION_PATH = STUDY_ROOT / "twenty-project-study-population.json"
CANARY_PATH = STUDY_ROOT / "ten-project-section-canary.json"
ENRICHMENT_CONTRACT_PATH = STUDY_ROOT / "evidence-enrichment-contract.json"
EXPECTED_TEMPLATE_COUNTS = {
    "asset_delivery": 4,
    "financing_facility": 13,
    "land_use_nature": 3,
}


def load_population() -> dict[str, Any]:
    return read_json(POPULATION_PATH)


def load_canary() -> dict[str, Any]:
    return read_json(CANARY_PATH)


def load_cohort() -> dict[str, Any]:
    """Compatibility alias returning the full population, never the canary."""

    return load_population()


def load_enrichment_contract() -> dict[str, Any]:
    return read_json(ENRICHMENT_CONTRACT_PATH)


def project_specialisation_assignments(
    population: dict[str, Any] | None = None,
) -> dict[str, str]:
    payload = population if population is not None else load_population()
    return {
        project["project_id"]: project["template_id"]
        for project in payload["projects"]
    }


def projects_by_specialisation(
    population: dict[str, Any] | None = None,
) -> dict[str, tuple[str, ...]]:
    payload = population if population is not None else load_population()
    projects = payload.get("projects", [])
    return {
        template["template_id"]: tuple(
            project["project_id"]
            for project in projects
            if project.get("template_id") == template["template_id"]
        )
        for template in payload["templates"]
    }


def canary_project_ids(canary: dict[str, Any] | None = None) -> tuple[str, ...]:
    payload = canary if canary is not None else load_canary()
    return tuple(payload.get("project_ids", []))


def canary_specialisation_assignments(
    canary: dict[str, Any] | None = None,
    population: dict[str, Any] | None = None,
) -> dict[str, str]:
    assignments = project_specialisation_assignments(population)
    return {
        project_id: assignments[project_id]
        for project_id in canary_project_ids(canary)
        if project_id in assignments
    }


def validate_study_design(
    population: dict[str, Any] | None = None,
    canary: dict[str, Any] | None = None,
    contract: dict[str, Any] | None = None,
) -> list[str]:
    payload = population if population is not None else load_population()
    canary_payload = canary if canary is not None else load_canary()
    evidence_contract = contract if contract is not None else load_enrichment_contract()
    errors = validate_study_population(payload)
    errors.extend(validate_canary(canary_payload, population=payload))

    configured_contract = payload.get("evidence_enrichment_contract")
    if configured_contract != "v2/data/study/evidence-enrichment-contract.json":
        errors.append("population points at an unexpected evidence-enrichment contract")
    errors.extend(validate_enrichment_contract(evidence_contract))
    return errors


def validate_study_population(
    population: dict[str, Any] | None = None,
) -> list[str]:
    payload = population if population is not None else load_population()
    errors: list[str] = []

    projects = payload.get("projects", [])
    project_ids = [project.get("project_id") for project in projects]
    if len(project_ids) != 20:
        errors.append(
            f"study population must contain exactly 20 projects, got {len(project_ids)}"
        )
    if len(set(project_ids)) != len(project_ids):
        errors.append("study-population project IDs must be unique")

    templates = payload.get("templates", [])
    template_ids = [template.get("template_id") for template in templates]
    if set(template_ids) != set(EXPECTED_TEMPLATE_COUNTS):
        errors.append(
            "study-population templates must be exactly "
            + ", ".join(sorted(EXPECTED_TEMPLATE_COUNTS))
        )

    actual_counts = {
        template_id: sum(
            project.get("template_id") == template_id for project in projects
        )
        for template_id in EXPECTED_TEMPLATE_COUNTS
    }
    if actual_counts != EXPECTED_TEMPLATE_COUNTS:
        errors.append(
            "study-population template counts must be exactly "
            + ", ".join(
                f"{template_id}={count}"
                for template_id, count in EXPECTED_TEMPLATE_COUNTS.items()
            )
        )
    for project in projects:
        project_id = project.get("project_id", "<unknown>")
        if project.get("template_id") not in EXPECTED_TEMPLATE_COUNTS:
            errors.append(f"{project_id}: unknown template assignment")
        if not project.get("assignment_rationale"):
            errors.append(f"{project_id}: missing template-assignment rationale")

    dataset_manifest = payload.get("dataset_manifest", {})
    dataset_manifest_path = DATA_ROOT.parent / dataset_manifest.get("path", "")
    if not dataset_manifest_path.is_file():
        errors.append("study-population dataset manifest does not exist")
    else:
        actual_file_hash = hashlib.sha256(dataset_manifest_path.read_bytes()).hexdigest()
        if actual_file_hash != dataset_manifest.get("file_sha256"):
            errors.append("study-population dataset manifest hash does not match")
        dataset_project_ids = set(read_json(dataset_manifest_path).get("project_ids", []))
        if set(project_ids) != dataset_project_ids:
            errors.append(
                "study population must contain every project in the dataset manifest"
            )

    common_nodes = payload.get("source_coverage_contract", {}).get(
        "available_node_ids", []
    )
    common_collections = payload.get("source_coverage_contract", {}).get(
        "available_collection_ids", []
    )
    for project in projects:
        project_id = project.get("project_id")
        relative_path = project.get("normalized_twin_path", "")
        path = DATA_ROOT / relative_path.removeprefix("data/")
        if not path.is_file():
            errors.append(f"{project_id}: missing normalized twin {relative_path}")
            continue
        twin = read_json(path)
        if twin.get("project_id") != project_id:
            errors.append(f"{project_id}: twin project_id does not match")
        expected_hash = project.get("normalized_twin_sha256")
        if sha256_json(twin) != expected_hash:
            errors.append(f"{project_id}: normalized twin hash does not match")
        for node_id in common_nodes:
            node = twin.get("nodes", {}).get(node_id)
            if not node or node.get("status") != "available":
                errors.append(f"{project_id}: unavailable common node {node_id}")
        for collection_id in common_collections:
            collection = twin.get("collections", {}).get(collection_id)
            if not collection or collection.get("status") != "available":
                errors.append(
                    f"{project_id}: unavailable common collection {collection_id}"
                )
    return errors


def validate_canary(
    canary: dict[str, Any] | None = None,
    *,
    population: dict[str, Any] | None = None,
) -> list[str]:
    payload = canary if canary is not None else load_canary()
    population_payload = population if population is not None else load_population()
    errors: list[str] = []

    project_ids = payload.get("project_ids", [])
    if len(project_ids) != 10:
        errors.append(f"section canary must contain exactly 10 projects, got {len(project_ids)}")
    if len(set(project_ids)) != len(project_ids):
        errors.append("section-canary project IDs must be unique")

    population_assignments = project_specialisation_assignments(population_payload)
    unknown = sorted(set(project_ids) - set(population_assignments))
    if unknown:
        errors.append("section canary contains projects outside the study population")
    represented_templates = {
        population_assignments[project_id]
        for project_id in project_ids
        if project_id in population_assignments
    }
    if represented_templates != set(EXPECTED_TEMPLATE_COUNTS):
        errors.append("section canary must exercise all three specialisations")

    if "projects" in payload or "templates" in payload:
        errors.append(
            "section canary must inherit project-template assignments from the population"
        )
    design = payload.get("design", {})
    if design.get("is_study_population") is not False:
        errors.append("section canary must explicitly state that it is not the population")
    if design.get("project_template_assignments_are_inherited") is not True:
        errors.append("section canary must inherit population template assignments")

    reference = payload.get("population_manifest", {})
    if reference.get("path") != "v2/data/study/twenty-project-study-population.json":
        errors.append("section canary points at an unexpected population manifest")
    if reference.get("population_id") != population_payload.get("population_id"):
        errors.append("section canary population ID does not match")
    actual_population_hash = hashlib.sha256(POPULATION_PATH.read_bytes()).hexdigest()
    if reference.get("file_sha256") != actual_population_hash:
        errors.append("section canary population-manifest hash does not match")
    return errors


def validate_enrichment_contract(contract: dict[str, Any] | None = None) -> list[str]:
    payload = contract or load_enrichment_contract()
    errors: list[str] = []
    expected_classes = {
        "normalized_project_source",
        "same_project_source_extraction",
        "sibling_repository_source_supplement",
        "documented_source_gap",
        "synthetic_benchmark_enrichment",
        "cross_project_reference_statistic",
    }
    actual_classes = set(payload.get("evidence_classes", {}))
    if actual_classes != expected_classes:
        errors.append("evidence-class taxonomy is incomplete or contains unknown classes")
    if not payload.get("merge_policy", {}).get("node_id_collisions_are_errors"):
        errors.append("node ID collisions must be errors")
    if not payload.get("merge_policy", {}).get("observed_values_are_immutable"):
        errors.append("observed evidence must be immutable")
    generation = payload.get("synthetic_generation", {})
    if generation.get("evaluated_model_generation_permitted") is not False:
        errors.append("evaluated models must not generate synthetic benchmark truth")
    if generation.get("seed_algorithm") != "sha256":
        errors.append("synthetic seed algorithm must be sha256")
    if generation.get("seed_material_order") != [
        "contract_id",
        "contract_version",
        "generator_id",
        "generator_version",
        "project_id",
        "node_id",
    ]:
        errors.append("synthetic seed material order has changed")
    return errors


def evidence_class(
    node: dict[str, Any],
    *,
    container_default: str | None = None,
    contract: dict[str, Any] | None = None,
) -> str:
    """Resolve a node's auditable evidence class during the schema transition."""

    payload = contract or load_enrichment_contract()
    classification = payload["classification"]
    resolved = node.get(classification["canonical_field"])
    if resolved is None:
        legacy = node.get("provenance", {}).get("source_kind")
        resolved = legacy or container_default
    if resolved not in payload["evidence_classes"]:
        node_id = node.get("id", "<unknown>")
        raise ValueError(f"{node_id}: unknown or absent evidence class {resolved!r}")
    return str(resolved)


def evidence_reporting_bucket(
    node: dict[str, Any],
    *,
    container_default: str | None = None,
    contract: dict[str, Any] | None = None,
) -> str:
    payload = contract or load_enrichment_contract()
    resolved = evidence_class(
        node,
        container_default=container_default,
        contract=payload,
    )
    return str(payload["evidence_classes"][resolved]["reporting_bucket"])


def synthetic_seed(
    *,
    project_id: str,
    node_id: str,
    generator_id: str,
    generator_version: str,
    contract: dict[str, Any] | None = None,
) -> str:
    payload = contract or load_enrichment_contract()
    generation = payload["synthetic_generation"]
    material = {
        "contract_id": payload["contract_id"],
        "contract_version": payload["contract_version"],
        "generator_id": generator_id,
        "generator_version": generator_version,
        "project_id": project_id,
        "node_id": node_id,
    }
    ordered = [str(material[field]) for field in generation["seed_material_order"]]
    encoded = generation["seed_separator"].join(ordered).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def synthetic_enrichment_metadata(
    *,
    project_id: str,
    template_id: str,
    node_id: str,
    generator_id: str,
    generator_version: str,
    rule_id: str,
    conditioned_on: Iterable[str],
    constraints: Iterable[str],
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = contract or load_enrichment_contract()
    dependencies = sorted(set(conditioned_on))
    declared_constraints = sorted(set(constraints))
    return {
        "evidence_class": "synthetic_benchmark_enrichment",
        "generator_id": generator_id,
        "generator_version": generator_version,
        "seed": synthetic_seed(
            project_id=project_id,
            node_id=node_id,
            generator_id=generator_id,
            generator_version=generator_version,
            contract=payload,
        ),
        "conditioned_on": dependencies,
        "not_a_source_claim": True,
        "provenance": {
            "source_kind": "synthetic_benchmark_enrichment",
            "contract_id": payload["contract_id"],
            "project_id": project_id,
            "template_id": template_id,
            "rule_id": rule_id,
        },
        "enrichment": {
            "synthetic": True,
            "imputed": True,
            "overwrites_normalized_node": False,
            "constraints": declared_constraints,
        },
    }


def validate_synthetic_node(
    node: dict[str, Any],
    *,
    project_id: str,
    template_id: str,
    existing_node_ids: Iterable[str] = (),
    contract: dict[str, Any] | None = None,
) -> list[str]:
    payload = contract or load_enrichment_contract()
    errors: list[str] = []
    node_id = node.get("id")
    definition = payload["evidence_classes"]["synthetic_benchmark_enrichment"]
    for field in definition["required_node_fields"]:
        if field not in node:
            errors.append(f"{node_id}: missing synthetic node field {field}")
    provenance = node.get("provenance", {})
    for field in definition["required_provenance_fields"]:
        if field not in provenance:
            errors.append(f"{node_id}: missing synthetic provenance field {field}")
    enrichment = node.get("enrichment", {})
    for field in definition["required_enrichment_fields"]:
        if field not in enrichment:
            errors.append(f"{node_id}: missing synthetic enrichment field {field}")

    if node_id in set(existing_node_ids):
        errors.append(f"{node_id}: synthetic node collides with source-backed evidence")
    if node.get("evidence_class") != "synthetic_benchmark_enrichment":
        errors.append(f"{node_id}: incorrect synthetic evidence class")
    if node.get("not_a_source_claim") is not True:
        errors.append(f"{node_id}: not_a_source_claim must be true")
    if provenance.get("project_id") != project_id:
        errors.append(f"{node_id}: synthetic provenance has the wrong project")
    if provenance.get("template_id") != template_id:
        errors.append(f"{node_id}: synthetic provenance has the wrong template")
    if enrichment.get("synthetic") is not True or enrichment.get("imputed") is not True:
        errors.append(f"{node_id}: synthetic/imputed flags must be true")
    if enrichment.get("overwrites_normalized_node") is not False:
        errors.append(f"{node_id}: synthetic evidence may not overwrite source evidence")
    if not enrichment.get("constraints"):
        errors.append(f"{node_id}: at least one constraint is required")

    dependencies = node.get("conditioned_on", [])
    if not dependencies:
        errors.append(f"{node_id}: conditioned_on must not be empty")
    if dependencies != sorted(set(dependencies)):
        errors.append(f"{node_id}: conditioned_on must be sorted and unique")

    generator_id = node.get("generator_id")
    generator_version = node.get("generator_version")
    if node_id and generator_id and generator_version:
        expected_seed = synthetic_seed(
            project_id=project_id,
            node_id=node_id,
            generator_id=generator_id,
            generator_version=generator_version,
            contract=payload,
        )
        if node.get("seed") != expected_seed:
            errors.append(f"{node_id}: synthetic seed does not match the contract")
    return errors
