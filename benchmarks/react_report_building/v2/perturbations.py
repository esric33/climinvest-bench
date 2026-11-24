from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
import hashlib
import math
from pathlib import Path
from typing import Any

from ..domain.priority_calculations import (
    CollectionCalculationUnavailable,
    filter_equal_available,
    maximum_available_field,
    score_risks,
)
from ..paths import NORMALIZED_ROOT, REFERENCE_ROOT
from ..runtime.calculator import Calculator
from ..runtime.evidence_store import EvidenceStore
from ..runtime.rendering import calculate_all
from ..util import read_json, sha256_json, write_json
from .contract import V2_ROOT, load_compiled_contract
from .contract_registry import (
    DEFAULT_CONTRACT_REGISTRY,
    ContractRegistry,
    normalize_project_id,
)
from .evidence import (
    load_enrichment,
    load_source_normalization,
    prepare_v2_reference,
    prepare_v2_twin,
)
from .document import section_contracts
from .registry import (
    calculation_registry,
    catalogue as v2_catalogue,
    project_catalogue,
)
from .rendering import render_section
from .study_design import POPULATION_PATH, load_population
from .source_aliases import (
    ALIAS_INTERVENTION_POLICY,
    expand_source_alias_changes,
    expand_source_alias_ids,
)


PILOT_PATH = V2_ROOT / "data" / "conditions" / "fp083.topology-pilot.json"
POPULATION_CONDITIONS_PATH = (
    V2_ROOT / "data" / "conditions" / "climatefund20.topology-conditions.json"
)

# The category names define the experimental strata. Concrete targets are
# always resolved from each project's registered compiled graph; this mapping
# is retained only to keep a stable category order for compatibility outputs.
CATEGORY_TARGETS = {
    "value_without_dependents.single_section": "dt.project.size",
    "value_without_dependents.cross_section": "dt.project.code",
    "value_with_dependents.single_section": "dt.project.energy_mix_coal_pct",
    "value_with_dependents.cross_section": "dt.project.total_cost_usd",
    "collection_with_dependents.cross_section": "dt.project.countries",
}
TOPOLOGY_CATEGORIES = tuple(CATEGORY_TARGETS)

# This is the complete allow-list for the authoritative change packet shown to
# a model.  Topology, impact, selection, and constraint annotations are private
# evaluation data.  In particular, neither ``affected_section_ids`` nor fields
# from which the benchmark already derived that answer may cross this boundary.
PUBLIC_MUTATION_CHANGE_FIELDS = frozenset(
    {
        "node_id",
        "operation",
        "old_status",
        "new_status",
        "old_value",
        "new_value",
        "record_id",
        "old_record",
        "new_record",
    }
)


# These are semantic tie-breakers, not a second dependency map. Every preferred
# target is accepted only after the compiled graph proves its category and the
# prepared project evidence proves that it is applicable and available.
POPULATION_TARGET_PREFERENCES = {
    "value_without_dependents.single_section": (
        "dt.project.governance_arrangements",
        "dt.project.delivery_mechanism",
        "dt.project.description",
    ),
    "value_without_dependents.cross_section": (
        "dt.project.implementation_sequence",
        "dt.project.monitoring_reporting_process",
        "dt.project.ghg_accounting_qualification",
    ),
    "value_with_dependents.single_section": (
        "dt.project.service_connections_target",
        "dt.project.direct_beneficiaries_target",
    ),
    "value_with_dependents.cross_section": (
        # One safe, deep process input per family. Inactive land pathways are
        # excluded by the availability/applicability gate before tie-breaking.
        "dt.project.installed_capacity_target_mw",
        "dt.project.portfolio_unit_count",
        "dt.project.jurisdictional_reference_emissions_tco2e_per_year",
        "dt.project.plantation_afforestation_sequestration_tco2e_per_ha_year",
        "dt.project.forest_carbon_stock_tco2e_per_ha",
        "dt.project.total_cost_usd",
    ),
    "collection_with_dependents.cross_section": (
        "dt.risks",
        "dt.kpis",
        "dt.project.countries",
    ),
}


def topology_index(
    contract: dict[str, Any] | None = None,
    *,
    twin: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    payload = contract or load_compiled_contract()
    registry = calculation_registry(payload)
    calculations = {
        calculation_id: {
            "canonical_id": calculation_id,
            "canonical_dependencies": list(
                definition.get("input_ids", {}).values()
            ),
            "calculation_depth": 0,
        }
        for calculation_id, definition in registry.items()
    }

    depth_memo: dict[str, int] = {}

    def depth(calculation_id: str, active: frozenset[str] = frozenset()) -> int:
        if calculation_id in depth_memo:
            return depth_memo[calculation_id]
        if calculation_id in active:
            raise ValueError(f"calculation dependency cycle at {calculation_id}")
        dependencies = calculations[calculation_id]["canonical_dependencies"]
        resolved = 1 + max(
            (
                depth(dependency, active | {calculation_id})
                for dependency in dependencies
                if dependency in calculations
            ),
            default=0,
        )
        depth_memo[calculation_id] = resolved
        return resolved

    for calculation_id in calculations:
        calculations[calculation_id]["calculation_depth"] = depth(calculation_id)
    reverse: dict[str, set[str]] = defaultdict(set)
    for calculation_id, node in calculations.items():
        for dependency in node["canonical_dependencies"]:
            reverse[dependency].add(calculation_id)

    source_components: dict[str, set[str]] = defaultdict(set)
    source_sections: dict[str, set[str]] = defaultdict(set)
    for artifact in payload["artifacts"]:
        if artifact["type"] not in {"table", "llm"}:
            continue
        sources = set()
        for dependency in artifact["canonical_dependencies"]:
            sources.update(_upstream_sources(dependency, calculations))
        for source_id in sources:
            source_components[source_id].add(artifact["id"])
            source_sections[source_id].add(artifact["section_id"])

    catalogue = v2_catalogue() if twin is None else None
    output = {}
    for source_id in sorted(source_sections):
        descendants = _descendants(source_id, reverse)
        calculation_descendants = sorted(
            item for item in descendants if item.startswith("calc.")
        )
        sections = sorted(source_sections[source_id])
        if twin is not None and source_id in twin.get("collections", {}):
            kind = "collection"
        elif twin is not None and source_id in twin.get("nodes", {}):
            kind = twin["nodes"][source_id].get("kind", "scalar")
        else:
            kind = (
                (catalogue or {}).get("data", {}).get(source_id, {}).get(
                    "kind", "scalar"
                )
            )
        has_dependents = bool(calculation_descendants)
        locality = "cross_section" if len(sections) > 1 else "single_section"
        category_prefix = (
            "collection_with_dependents"
            if kind == "collection" and has_dependents
            else "value_with_dependents"
            if has_dependents
            else "value_without_dependents"
        )
        output[source_id] = {
            "source_id": source_id,
            "value_kind": kind,
            "has_calculation_dependents": has_dependents,
            "calculation_descendant_ids": calculation_descendants,
            "max_descendant_depth": max(
                (
                    calculations[item]["calculation_depth"]
                    for item in calculation_descendants
                ),
                default=0,
            ),
            "affected_component_ids": sorted(source_components[source_id]),
            "affected_section_ids": sections,
            "section_fanout": len(sections),
            "locality": locality,
            "category": f"{category_prefix}.{locality}",
        }
    return output


def prepare_perturbation_twin(
    project_id: str,
    twin: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Prepare the authoritative all-population evidence for one condition.

    Explicit bundles are important for FP083: the no-argument evidence helper
    deliberately retains the old pilot overlay, whereas population conditions
    must use the same all-20 evidence as the registered family runtime.
    """

    project = normalize_project_id(project_id)
    base = deepcopy(twin) if twin is not None else read_json(
        NORMALIZED_ROOT / f"{project.lower()}.json"
    )
    if normalize_project_id(base.get("project_id")) != project:
        raise ValueError(
            f"{project}: perturbation twin declares {base.get('project_id')!r}"
        )
    return prepare_v2_twin(
        base,
        source_normalization=load_source_normalization(project),
        enrichment=load_enrichment(project),
    )


def build_project_conditions(
    project_id: str,
    *,
    twin: dict[str, Any] | None = None,
    contract: dict[str, Any] | None = None,
    contract_registry: ContractRegistry = DEFAULT_CONTRACT_REGISTRY,
) -> dict[str, Any]:
    """Build deterministic graph-derived masks and mutations for one project."""

    project = normalize_project_id(project_id)
    binding = contract_registry.resolve(project_id=project)
    expected_contract = binding.load()
    payload = contract or expected_contract
    if payload.get("contract_id") != binding.contract_id:
        raise ValueError(
            f"{project}: contract {payload.get('contract_id')!r} does not match "
            f"the registered family {binding.contract_id!r}"
        )
    if sha256_json(payload) != sha256_json(expected_contract):
        raise ValueError(
            f"{project}: supplied contract differs from the registered compiled "
            f"artifact for {binding.contract_id!r}"
        )
    assigned = set(
        payload.get("population_binding", {}).get("assigned_project_ids", [])
    )
    if project not in assigned:
        raise ValueError(
            f"{project}: compiled contract {binding.contract_id!r} does not bind target"
        )

    prepared = prepare_perturbation_twin(project, twin)
    contract_sha256 = sha256_json(payload)
    prepared_evidence_sha256 = sha256_json(prepared)
    topology = topology_index(payload, twin=prepared)
    reference = prepare_v2_reference(
        read_json(REFERENCE_ROOT / "climatefund20-v1.json"),
        project_id=project,
        enrichment=load_enrichment(project),
    )
    data_catalogue = project_catalogue(
        contract=payload,
        project_id=project,
    )
    base_store = _calculated_project_store(
        prepared,
        reference,
        payload,
    )
    required_sources = set(
        payload.get("source_contract", {}).get("required_source_ids", [])
    )
    masks: list[dict[str, Any]] = []
    mutations: list[dict[str, Any]] = []
    unavailable: list[dict[str, str]] = []

    for category in TOPOLOGY_CATEGORIES:
        candidates = [
            _target_metadata(prepared, entry)
            for entry in topology.values()
            if entry["category"] == category
            and entry["source_id"] in required_sources
            and _is_available_applicable_target(prepared, entry["source_id"])
            and _supports_semantic_mutation(prepared, entry["source_id"])
        ]
        selected = next(
            (
                entry
                for entry in _ordered_population_candidates(category, candidates)
                if not entry["has_calculation_dependents"]
                or _has_active_project_influence(
                    prepared,
                    reference,
                    payload,
                    data_catalogue,
                    base_store,
                    binding.contract_id,
                    entry,
                    topology,
                    contract_sha256=contract_sha256,
                    prepared_evidence_sha256=prepared_evidence_sha256,
                )
            ),
            None,
        )
        if selected is None:
            unavailable.append(
                {
                    "category": category,
                    "reason": (
                        "the compiled graph has no applicable, available target "
                        "that supports a semantically valid benchmark mutation "
                        "with project-resolved active influence"
                    ),
                }
            )
            continue
        selected = _alias_impact_topology(selected, topology, prepared)
        masks.append(
            _population_mask_condition(
                project,
                binding.contract_id,
                selected,
                contract_sha256=contract_sha256,
                prepared_evidence_sha256=prepared_evidence_sha256,
            )
        )
        mutation_topology = _alias_impact_topology(_mutation_impact_topology(selected, topology), topology, prepared)
        mutations.append(
            _population_mutation_condition(
                prepared,
                binding.contract_id,
                mutation_topology,
                contract_sha256=contract_sha256,
                prepared_evidence_sha256=prepared_evidence_sha256,
            )
        )

    return {
        "schema_version": "react_report.project_perturbations/v2",
        "benchmark_version": payload.get("benchmark_version", "v2"),
        "project_id": project,
        "contract_id": binding.contract_id,
        "contract_sha256": contract_sha256,
        "prepared_evidence_sha256": prepared_evidence_sha256,
        "selection": (
            "compiled-graph category representatives restricted to applicable, "
            "available project evidence, semantically valid mutations, and "
            "project-resolved active influence"
        ),
        "categories": list(TOPOLOGY_CATEGORIES),
        "supported_categories": [item["category"] for item in masks],
        "unavailable_categories": unavailable,
        "masks": masks,
        "mutations": mutations,
    }


def build_population_conditions(
    *,
    population: dict[str, Any] | None = None,
    contract_registry: ContractRegistry = DEFAULT_CONTRACT_REGISTRY,
) -> dict[str, Any]:
    """Build the complete all-20 condition manifest without provider calls."""

    population_payload = population if population is not None else load_population()
    projects = [
        build_project_conditions(
            item["project_id"],
            contract_registry=contract_registry,
        )
        for item in population_payload["projects"]
    ]
    unavailable = [
        {
            "project_id": project["project_id"],
            "contract_id": project["contract_id"],
            **entry,
        }
        for project in projects
        for entry in project["unavailable_categories"]
    ]
    template_ids = sorted({item["contract_id"] for item in projects})
    benchmark_versions = {item["benchmark_version"] for item in projects}
    if len(benchmark_versions) != 1:
        raise ValueError(
            "registered family contracts disagree on benchmark version: "
            + ", ".join(sorted(benchmark_versions))
        )
    by_template = {
        template_id: {
            "project_ids": [
                item["project_id"]
                for item in projects
                if item["contract_id"] == template_id
            ],
            "project_count": sum(
                item["contract_id"] == template_id for item in projects
            ),
            "supported_project_count_by_category": {
                category: sum(
                    item["contract_id"] == template_id
                    and category in item["supported_categories"]
                    for item in projects
                )
                for category in TOPOLOGY_CATEGORIES
            },
        }
        for template_id in template_ids
    }
    return {
        "schema_version": "react_report.perturbation_population/v2",
        "benchmark_version": next(iter(benchmark_versions)),
        "population_id": population_payload["population_id"],
        "population_manifest": {
            "path": "v2/data/study/twenty-project-study-population.json",
            "sha256": hashlib.sha256(POPULATION_PATH.read_bytes()).hexdigest(),
        },
        "selection_policy": {
            "alias_intervention_policy": ALIAS_INTERVENTION_POLICY,
            "graph_source": "registered project-neutral compiled family contract",
            "evidence_source": "authoritative all-20 prepared evidence",
            "requires_target_status": "available",
            "requires_applicability_status": "applicable",
            "requires_active_influence": (
                "for targets with calculation dependents, both the mask and "
                "semantic mutation must change a descendant calculation and "
                "their observable section changes must equal graph-declared impact"
            ),
            "mutation_policy": (
                "one deterministic, type-preserving sensitivity change; collection "
                "removal must leave at least one record"
            ),
            "provider_calls": 0,
        },
        "categories": list(TOPOLOGY_CATEGORIES),
        "project_count": len(projects),
        "mask_count": sum(len(item["masks"]) for item in projects),
        "mutation_count": sum(len(item["mutations"]) for item in projects),
        "all_categories_supported": not unavailable,
        "unavailable_categories": unavailable,
        "coverage": {
            "by_template": by_template,
            "supported_project_count_by_category": {
                category: sum(
                    category in item["supported_categories"] for item in projects
                )
                for category in TOPOLOGY_CATEGORIES
            },
        },
        "projects": projects,
    }


def write_population_conditions(
    path: Path = POPULATION_CONDITIONS_PATH,
) -> dict[str, Any]:
    payload = build_population_conditions()
    write_json(path, payload)
    return payload


def validate_population_conditions(
    path: Path = POPULATION_CONDITIONS_PATH,
) -> list[str]:
    if not path.is_file():
        return ["v2 all-20 perturbation manifest is missing"]
    committed = read_json(path)
    expected = build_population_conditions()
    errors: list[str] = []
    if committed != expected:
        errors.append("v2 all-20 perturbation manifest is stale")
    if committed.get("project_count") != 20:
        errors.append("v2 perturbation manifest must cover all 20 projects")
    if not committed.get("all_categories_supported"):
        errors.append("v2 perturbation manifest has unavailable topology categories")
    expected_count = 20 * len(TOPOLOGY_CATEGORIES)
    if committed.get("mask_count") != expected_count:
        errors.append(f"v2 perturbation manifest requires {expected_count} masks")
    if committed.get("mutation_count") != expected_count:
        errors.append(f"v2 perturbation manifest requires {expected_count} mutations")
    return errors


def build_pilot(
    twin: dict[str, Any] | None = None,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = build_project_conditions(
        "FP083",
        twin=twin,
        contract=contract,
    )
    return {
        "schema_version": "react_report.perturbation_pilot/v2",
        "benchmark_version": payload["benchmark_version"],
        "project_id": "FP083",
        "contract_id": payload["contract_id"],
        "contract_sha256": payload["contract_sha256"],
        "prepared_evidence_sha256": payload["prepared_evidence_sha256"],
        "selection": payload["selection"],
        "categories": payload["categories"],
        "masks": payload["masks"],
        "mutations": payload["mutations"],
    }


def write_pilot(path: Path = PILOT_PATH) -> dict[str, Any]:
    payload = build_pilot()
    write_json(path, payload)
    return payload


def validate_pilot(path: Path = PILOT_PATH) -> list[str]:
    errors = []
    if not path.is_file():
        return ["v2 perturbation pilot is missing"]
    committed = read_json(path)
    expected = build_pilot()
    if committed != expected:
        errors.append("v2 perturbation pilot is stale")
    if committed.get("categories") != list(CATEGORY_TARGETS):
        errors.append("v2 perturbation categories differ from the fixed design")
    for group in ("masks", "mutations"):
        conditions = committed.get(group, [])
        if len(conditions) != len(CATEGORY_TARGETS):
            errors.append(f"v2 perturbation pilot requires five {group}")
            continue
        if {item.get("category") for item in conditions} != set(CATEGORY_TARGETS):
            errors.append(f"v2 {group} do not cover every topology category")
        if any(not item.get("affected_section_ids") for item in conditions):
            errors.append(f"v2 {group} contain an empty affected-section set")
    return errors


def apply_mutation(
    twin: dict[str, Any],
    condition: dict[str, Any],
) -> dict[str, Any]:
    """Apply one pinned counterfactual mutation and fail closed on stale state."""

    project_id = normalize_project_id(twin.get("project_id"))
    condition_project = normalize_project_id(condition.get("project_id"))
    if project_id != condition_project:
        raise ValueError(
            f"mutation for {condition_project} cannot be applied to {project_id}"
        )
    declared_contract = condition.get("contract_id")
    prepared_marker = twin.get("_v2_evidence_overlay", {})
    prepared_template = (
        prepared_marker.get("template_id")
        if isinstance(prepared_marker, dict)
        else None
    )
    if declared_contract and prepared_template and declared_contract != prepared_template:
        raise ValueError(
            f"mutation contract {declared_contract!r} cannot be applied to "
            f"prepared template {prepared_template!r}"
        )
    expected_contract_hash = condition.get("contract_sha256")
    if expected_contract_hash:
        binding = DEFAULT_CONTRACT_REGISTRY.resolve(
            project_id=project_id,
            contract_id=declared_contract,
        )
        actual_contract_hash = sha256_json(binding.load())
        if actual_contract_hash != expected_contract_hash:
            raise ValueError(
                f"mutation contract hash is stale for {project_id}: expected "
                f"{expected_contract_hash}, got {actual_contract_hash}"
            )
    expected_evidence_hash = condition.get("prepared_evidence_sha256")
    if expected_evidence_hash and sha256_json(twin) != expected_evidence_hash:
        raise ValueError(
            f"mutation prepared-evidence hash is stale for {project_id}"
        )
    changes = condition.get("changes")
    if not isinstance(changes, list) or not changes:
        raise ValueError("mutation requires at least one declared change")
    alias_policy = condition.get("alias_intervention_policy")
    if alias_policy is not None:
        if alias_policy != ALIAS_INTERVENTION_POLICY:
            raise ValueError("unsupported source-alias intervention policy")
        expanded = expand_source_alias_changes(twin, changes)
        if expanded != changes:
            raise ValueError("mutation condition omits an equivalent source alias")
    if condition.get("target_id") not in {None, changes[0].get("node_id")}:
        raise ValueError("mutation target_id differs from its primary change")
    updated = deepcopy(twin)
    for change in changes:
        operation = change.get("operation")
        node_id = change.get("node_id")
        if operation == "replace_value":
            node = _locate(updated, node_id)
            if "old_status" in change and node.get("status") != change["old_status"]:
                raise ValueError(f"{node_id}: mutation old_status is stale")
            if "old_value" in change and node.get("value") != change["old_value"]:
                raise ValueError(f"{node_id}: mutation old_value is stale")
            node["status"] = change["new_status"]
            node["value"] = deepcopy(change["new_value"])
            _mark_counterfactual(node, condition=condition, change=change)
            continue
        if operation == "remove_record":
            collection = updated["collections"].get(node_id)
            if not isinstance(collection, dict):
                raise ValueError(f"{node_id}: mutation collection is absent")
            matches = [
                item
                for item in collection.get("records", [])
                if item.get("id") == change.get("record_id")
            ]
            if len(matches) != 1:
                raise ValueError(
                    f"{node_id}: mutation record {change.get('record_id')!r} "
                    "is absent or duplicated"
                )
            if "old_record" in change and matches[0] != change["old_record"]:
                raise ValueError(f"{node_id}: mutation old_record is stale")
            requires_nonempty = bool(
                change.get("constraint_checks", {}).get(
                    "collection_remains_nonempty"
                )
            )
            if requires_nonempty and len(collection.get("records", [])) <= 1:
                raise ValueError(f"{node_id}: mutation would empty the collection")
            collection["records"] = [
                item
                for item in collection["records"]
                if item["id"] != change["record_id"]
            ]
            _mark_counterfactual(collection, condition=condition, change=change)
            continue
        raise ValueError(f"unsupported v2 mutation operation {operation!r}")
    _validate_mutation_postconditions(twin, updated, condition)
    return updated


def public_mutation_event(condition: dict[str, Any]) -> dict[str, Any]:
    """Project one private mutation condition into the model-visible event.

    Condition IDs encode the experimental topology category, so the public ID
    is deliberately an opaque content hash instead of the private condition ID.
    The projection is an allow-list: adding private metadata to a future
    condition cannot accidentally expose it to an agent prompt.
    """

    project_id = normalize_project_id(condition.get("project_id"))
    changes = condition.get("changes")
    if condition.get("kind") != "mutation":
        raise ValueError("public update event requires a v2 mutation condition")
    if not isinstance(changes, list) or not changes:
        raise ValueError("public update event requires at least one change")
    public_changes = []
    for index, change in enumerate(changes):
        if not isinstance(change, dict):
            raise ValueError(f"mutation changes[{index}] must be an object")
        projected = {
            key: deepcopy(change[key])
            for key in PUBLIC_MUTATION_CHANGE_FIELDS
            if key in change
        }
        if not projected.get("node_id") or not projected.get("operation"):
            raise ValueError(
                f"mutation changes[{index}] requires node_id and operation"
            )
        public_changes.append(projected)
    public_identity = {
        "project_id": project_id,
        "changes": public_changes,
    }
    return {
        "schema_version": "react_report.public_update_event/v2",
        "update_id": f"upd_{sha256_json(public_identity)[:20]}",
        "project_id": project_id,
        "precedence": "the new authoritative state supersedes the old state",
        "changes": public_changes,
    }


def public_mutation_twin(
    mutated_twin: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any]:
    """Remove private condition provenance from model-retrievable evidence."""

    if event.get("schema_version") != "react_report.public_update_event/v2":
        raise ValueError("public mutation twin requires a public v2 update event")
    if normalize_project_id(mutated_twin.get("project_id")) != normalize_project_id(
        event.get("project_id")
    ):
        raise ValueError("public mutation twin project differs from update event")
    operations = {
        change["node_id"]: change["operation"]
        for change in event.get("changes", [])
        if isinstance(change, dict)
        and change.get("node_id")
        and change.get("operation")
    }
    output = deepcopy(mutated_twin)
    for node_id, operation in operations.items():
        node = _target_node(output, node_id)
        if "benchmark_counterfactual" not in node:
            raise ValueError(
                f"{node_id}: applied mutation lacks counterfactual provenance"
            )
        node["benchmark_counterfactual"] = {
            "update_id": event["update_id"],
            "operation": operation,
            "not_a_source_claim": True,
        }
    return output


def _population_mask_condition(
    project_id: str,
    contract_id: str,
    topology: dict[str, Any],
    *,
    contract_sha256: str,
    prepared_evidence_sha256: str,
) -> dict[str, Any]:
    slug = topology["category"].replace(".", "_")
    return {
        "schema_version": "react_report.condition/v2",
        "condition_id": f"{project_id.lower()}.v2.population.mask.{slug}",
        "project_id": project_id,
        "contract_id": contract_id,
        "contract_sha256": contract_sha256,
        "prepared_evidence_sha256": prepared_evidence_sha256,
        "kind": "missingness",
        "category": topology["category"],
        "alias_intervention_policy": ALIAS_INTERVENTION_POLICY,
        "masked_ids": topology.get("alias_closure_ids", [topology["source_id"]]),
        "target_status_before": topology["target_status"],
        "target_applicability_status": topology["target_applicability_status"],
        "target_evidence_class": topology["target_evidence_class"],
        "selection_reason": topology["selection_reason"],
        **_impact(topology),
    }


def _population_mutation_condition(
    twin: dict[str, Any],
    contract_id: str,
    topology: dict[str, Any],
    *,
    contract_sha256: str,
    prepared_evidence_sha256: str,
) -> dict[str, Any]:
    node_id = topology["source_id"]
    slug = topology["category"].replace(".", "_")
    if node_id in twin["collections"]:
        records = twin["collections"][node_id]["records"]
        if len(records) < 2:
            raise ValueError(
                f"{twin['project_id']}/{node_id}: collection mutation would "
                "remove its only record"
            )
        record = _collection_mutation_record(node_id, records)
        is_risk_priority_mutation = node_id == "dt.risks"
        changes = [{
            "node_id": node_id,
            "operation": "remove_record",
            "record_id": record["id"],
            "old_record": deepcopy(record),
            "new_record": None,
            "semantic_rule": (
                "remove_last_source_order_maximum_available_risk_priority"
                if is_risk_priority_mutation
                else "remove_one_record_preserving_nonempty_collection"
            ),
            "constraint_checks": {
                "record_count_before": len(records),
                "record_count_after": len(records) - 1,
                "collection_remains_nonempty": True,
                **(
                    {
                        "selected_risk_priority_is_available": True,
                        "selected_risk_priority_is_maximum": True,
                        "incomplete_risk_priorities_excluded": True,
                    }
                    if is_risk_priority_mutation
                    else {}
                ),
            },
        }]
    elif node_id == "dt.project.facility_period_1_years":
        first = twin["nodes"][node_id]
        second_id = "dt.project.facility_period_2_years"
        second = twin["nodes"][second_id]
        first_value = float(first["value"])
        second_value = float(second["value"])
        delta = min(first_value * 0.05, second_value * 0.25)
        first_new = round(first_value + delta, 12)
        second_new = round(second_value - delta, 12)
        period_ids = [
            f"dt.project.facility_period_{period}_years" for period in range(1, 5)
        ]
        implementation_years = float(
            twin["nodes"]["dt.project.implementation_years"]["value"]
        )
        total_before = sum(float(twin["nodes"][item]["value"]) for item in period_ids)
        total_after = total_before - first_value - second_value + first_new + second_new
        shared_checks = {
            "finite": all(math.isfinite(item) for item in (first_new, second_new)),
            "both_periods_positive": first_new > 0 and second_new > 0,
            "period_total_before_equals_implementation_years": math.isclose(
                total_before, implementation_years, rel_tol=0.0, abs_tol=1e-9
            ),
            "period_total_after_equals_implementation_years": math.isclose(
                total_after, implementation_years, rel_tol=0.0, abs_tol=1e-9
            ),
        }
        if not all(shared_checks.values()):
            raise ValueError(
                f"{twin['project_id']}: facility-period mutation violates duration "
                "constraints"
            )
        changes = [
            {
                "node_id": node_id,
                "operation": "replace_value",
                "old_status": first["status"],
                "new_status": "available",
                "old_value": deepcopy(first["value"]),
                "new_value": first_new,
                "semantic_rule": "paired_period_reallocation_increase_period_1",
                "constraint_checks": {
                    **shared_checks,
                    "type_preserved": isinstance(first["value"], float),
                },
            },
            {
                "node_id": second_id,
                "operation": "replace_value",
                "old_status": second["status"],
                "new_status": "available",
                "old_value": deepcopy(second["value"]),
                "new_value": second_new,
                "semantic_rule": "paired_period_reallocation_decrease_period_2",
                "constraint_checks": {
                    **shared_checks,
                    "type_preserved": isinstance(second["value"], float),
                },
            },
        ]
    else:
        node = twin["nodes"][node_id]
        new_value, semantic_rule, checks = _safe_mutated_value(
            node_id,
            node.get("value"),
        )
        if node_id == "dt.project.direct_beneficiaries_target":
            women = float(twin["nodes"]["dt.project.women_beneficiaries_target"]["value"])
            local = float(
                twin["nodes"]["dt.project.local_community_beneficiaries_target"][
                    "value"
                ]
            )
            checks.update(
                {
                    "women_not_above_direct": women <= float(new_value),
                    "local_community_not_above_direct": local <= float(new_value),
                }
            )
            if not all(checks.values()):
                raise ValueError(
                    f"{twin['project_id']}/{node_id}: beneficiary mutation violates "
                    "declared bounds"
                )
        changes = [{
            "node_id": node_id,
            "operation": "replace_value",
            "old_status": node["status"],
            "new_status": "available",
            "old_value": deepcopy(node.get("value")),
            "new_value": new_value,
            "semantic_rule": semantic_rule,
            "constraint_checks": checks,
        }]
    changes = expand_source_alias_changes(twin, changes)
    condition = {
        "schema_version": "react_report.mutation/v2",
        "condition_id": (
            f"{twin['project_id'].lower()}.v2.population.mutation.{slug}"
        ),
        "project_id": twin["project_id"],
        "contract_id": contract_id,
        "contract_sha256": contract_sha256,
        "prepared_evidence_sha256": prepared_evidence_sha256,
        "kind": "mutation",
        "category": topology["category"],
        "alias_intervention_policy": ALIAS_INTERVENTION_POLICY,
        "target_status_before": topology["target_status"],
        "target_applicability_status": topology["target_applicability_status"],
        "target_evidence_class": topology["target_evidence_class"],
        "selection_reason": topology["selection_reason"],
        "changes": changes,
        "changed_ids": [change["node_id"] for change in changes],
        **_impact(topology),
    }
    apply_mutation(twin, condition)
    return condition


def _collection_mutation_record(
    node_id: str,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Choose a deterministic record whose removal exercises the topology.

    Risk consumers outside the detailed risk section use the maximum-priority
    set rather than every source record.  Removing an arbitrary trailing risk
    can therefore leave those consumers unchanged even though ``dt.risks`` is
    in their static dependency graph.  Select the final source-order member of
    the maximum available probability-times-impact set so the concrete
    mutation exercises that declared cross-section dependency.  Risks with an
    incomplete or invalid score remain unranked; they are never coerced to
    zero.
    """

    if not records:
        raise ValueError(f"{node_id}: collection mutation requires a record")
    if node_id != "dt.risks":
        return records[-1]

    scored = score_risks(records)
    try:
        maximum = maximum_available_field(scored, "priority_score")
    except CollectionCalculationUnavailable as exc:
        raise ValueError(
            "dt.risks: collection mutation requires at least one risk with "
            "available probability and impact scores"
        ) from exc
    maximum_risks = filter_equal_available(
        scored,
        "priority_score",
        float(maximum),
    )
    if not maximum_risks:
        raise ValueError("dt.risks: maximum-priority risk selection is empty")
    selected_id = str(maximum_risks[-1].get("source_record_id") or "")
    matches = [record for record in records if record.get("id") == selected_id]
    if len(matches) != 1:
        raise ValueError(
            "dt.risks: maximum-priority selection does not map to exactly one "
            "source record"
        )
    return matches[0]


def _mutation_impact_topology(
    primary: dict[str, Any],
    topology: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Return the union impact for a coherent multi-node mutation."""

    if primary["source_id"] != "dt.project.facility_period_1_years":
        return {**primary, "changed_source_ids": [primary["source_id"]]}
    secondary_id = "dt.project.facility_period_2_years"
    secondary = topology.get(secondary_id)
    if secondary is None or secondary.get("category") != primary.get("category"):
        raise ValueError(
            "facility duration reallocation requires period 2 in the same topology "
            "category as period 1"
        )
    components = sorted(
        set(primary["affected_component_ids"])
        | set(secondary["affected_component_ids"])
    )
    sections = sorted(
        set(primary["affected_section_ids"])
        | set(secondary["affected_section_ids"])
    )
    descendants = sorted(
        set(primary["calculation_descendant_ids"])
        | set(secondary["calculation_descendant_ids"])
    )
    if len(sections) != 1:
        raise ValueError(
            "paired facility-period mutation must remain a single-section condition"
        )
    return {
        **primary,
        "changed_source_ids": [primary["source_id"], secondary_id],
        "calculation_descendant_ids": descendants,
        "max_descendant_depth": max(
            primary["max_descendant_depth"], secondary["max_descendant_depth"]
        ),
        "affected_component_ids": components,
        "affected_section_ids": sections,
        "section_fanout": len(sections),
        "locality": "single_section",
    }


def _alias_impact_topology(
    primary: dict[str, Any],
    topology: dict[str, dict[str, Any]],
    twin: dict[str, Any],
) -> dict[str, Any]:
    """Union explicit-copy impact without silently changing a study stratum."""
    expanded = expand_source_alias_ids(twin, primary.get("changed_source_ids", [primary["source_id"]]))
    entries = [primary, *(topology[node_id] for node_id in expanded if node_id in topology)]
    sections = sorted({value for entry in entries for value in entry["affected_section_ids"]})
    components = sorted({value for entry in entries for value in entry["affected_component_ids"]})
    descendants = sorted({value for entry in entries for value in entry["calculation_descendant_ids"]})
    locality = "cross_section" if len(sections) > 1 else "single_section"
    prefix = ("collection_with_dependents" if primary["value_kind"] == "collection" and descendants
              else "value_with_dependents" if descendants else "value_without_dependents")
    category = f"{prefix}.{locality}"
    if category != primary["category"]:
        raise ValueError(f"{primary['source_id']}: alias closure changes intended topology stratum from {primary['category']} to {category}")
    return {**primary, "alias_closure_ids": expanded,
            "affected_section_ids": sections, "affected_component_ids": components,
            "calculation_descendant_ids": descendants, "has_calculation_dependents": bool(descendants),
            "max_descendant_depth": max(entry["max_descendant_depth"] for entry in entries),
            "section_fanout": len(sections), "locality": locality}


def _target_metadata(
    twin: dict[str, Any],
    topology: dict[str, Any],
) -> dict[str, Any]:
    target = _target_node(twin, topology["source_id"])
    return {
        **topology,
        "target_status": target.get("status"),
        "target_applicability_status": target.get("applicability", {}).get(
            "status", "applicable"
        ),
        "target_evidence_class": target.get("evidence_class")
        or target.get("provenance", {}).get("source_kind"),
        "selection_reason": (
            "preferred semantically stable representative validated against "
            "the registered compiled graph, prepared project evidence, and "
            "project-resolved active influence"
        ),
    }


def _calculated_project_store(
    twin: dict[str, Any],
    reference: dict[str, Any],
    contract: dict[str, Any],
    *,
    masked_ids: set[str] | None = None,
) -> EvidenceStore:
    store = EvidenceStore(
        twin,
        reference,
        masked_ids=masked_ids or set(),
    )
    calculate_all(
        Calculator(store, registry=calculation_registry(contract))
    )
    return store


def _has_active_project_influence(
    twin: dict[str, Any],
    reference: dict[str, Any],
    contract: dict[str, Any],
    data_catalogue: dict[str, Any],
    base_store: EvidenceStore,
    contract_id: str,
    candidate: dict[str, Any],
    topology: dict[str, dict[str, Any]],
    *,
    contract_sha256: str,
    prepared_evidence_sha256: str,
) -> bool:
    """Reject graph edges that are inert for this project's guarded state.

    Compiled TraceMark dependencies describe every potential path through a
    conditional expression.  A project-level gate can make some paths inert;
    for example, cost reconciliation correctly remains not applicable when
    funding scopes are not comparable.  A ``with_dependents`` benchmark cell
    must therefore prove both a real descendant-calculation change and the
    exact section impact declared by the graph under its concrete mask and
    semantic mutation.
    """

    candidate = _alias_impact_topology(candidate, topology, twin)
    masked_store = _calculated_project_store(
        twin,
        reference,
        contract,
        masked_ids=set(candidate["alias_closure_ids"]),
    )
    mutation_topology = _alias_impact_topology(_mutation_impact_topology(candidate, topology), topology, twin)
    mutation = _population_mutation_condition(
        twin,
        contract_id,
        mutation_topology,
        contract_sha256=contract_sha256,
        prepared_evidence_sha256=prepared_evidence_sha256,
    )
    mutated_store = _calculated_project_store(
        apply_mutation(twin, mutation),
        reference,
        contract,
    )

    mask_descendants = candidate["calculation_descendant_ids"]
    mutation_descendants = mutation_topology["calculation_descendant_ids"]
    if not _has_changed_calculation(
        base_store,
        masked_store,
        mask_descendants,
    ):
        return False
    if not _has_changed_calculation(
        base_store,
        mutated_store,
        mutation_descendants,
    ):
        return False

    mask_sections = _observed_section_changes(
        base_store,
        masked_store,
        contract=contract,
        data_catalogue=data_catalogue,
    )
    mutation_sections = _observed_section_changes(
        base_store,
        mutated_store,
        contract=contract,
        data_catalogue=data_catalogue,
    )
    return (
        mask_sections == set(candidate["affected_section_ids"])
        and mutation_sections
        == set(mutation_topology["affected_section_ids"])
    )


def _has_changed_calculation(
    before: EvidenceStore,
    after: EvidenceStore,
    calculation_ids: list[str],
) -> bool:
    return any(
        _calculation_outcome(before.get(calculation_id))
        != _calculation_outcome(after.get(calculation_id))
        for calculation_id in calculation_ids
    )


def _calculation_outcome(node: dict[str, Any]) -> tuple[Any, Any]:
    return node.get("status"), node.get("value")


def _observed_section_changes(
    before: EvidenceStore,
    after: EvidenceStore,
    *,
    contract: dict[str, Any],
    data_catalogue: dict[str, Any],
) -> set[str]:
    return {
        section["id"]
        for section in section_contracts(contract)
        if render_section(
            section["id"],
            before,
            contract=contract,
            data_catalogue=data_catalogue,
        )
        != render_section(
            section["id"],
            after,
            contract=contract,
            data_catalogue=data_catalogue,
        )
    }


def _select_population_target(
    category: str,
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    ordered = _ordered_population_candidates(category, candidates)
    return ordered[0] if ordered else None


def _ordered_population_candidates(
    category: str,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return semantic preferences followed by strongest graph fallbacks."""

    by_id = {item["source_id"]: item for item in candidates}
    ordered: list[dict[str, Any]] = []
    for node_id in POPULATION_TARGET_PREFERENCES.get(category, ()):
        if node_id in by_id:
            ordered.append(by_id.pop(node_id))
    # This is intentionally deterministic and favours a deeper calculation
    # cascade only after semantic eligibility has been established.
    ordered.extend(
        sorted(
            by_id.values(),
            key=lambda item: (
                -item["max_descendant_depth"],
                -item["section_fanout"],
                item["source_id"],
            ),
        )
    )
    return ordered


def _is_available_applicable_target(
    twin: dict[str, Any],
    node_id: str,
) -> bool:
    try:
        node = _target_node(twin, node_id)
    except KeyError:
        return False
    if node.get("status") != "available":
        return False
    applicability = node.get("applicability")
    return not isinstance(applicability, dict) or applicability.get(
        "status", "applicable"
    ) == "applicable"


def _supports_semantic_mutation(twin: dict[str, Any], node_id: str) -> bool:
    try:
        node = _target_node(twin, node_id)
    except KeyError:
        return False
    if node_id in twin.get("collections", {}):
        return len(node.get("records", [])) >= 2
    constraints = " ".join(
        str(item).lower()
        for item in node.get("enrichment", {}).get("constraints", [])
    )
    if node_id == "dt.project.facility_period_1_years":
        second = twin.get("nodes", {}).get("dt.project.facility_period_2_years", {})
        return (
            second.get("status") == "available"
            and isinstance(node.get("value"), float)
            and isinstance(second.get("value"), float)
            and float(node["value"]) > 0
            and float(second["value"]) > 0
        )
    if node_id == "dt.project.direct_beneficiaries_target":
        companion_ids = (
            "dt.project.women_beneficiaries_target",
            "dt.project.local_community_beneficiaries_target",
        )
        companions = [twin.get("nodes", {}).get(item, {}) for item in companion_ids]
        direct_value = node.get("value")
        return (
            isinstance(direct_value, (int, float))
            and not isinstance(direct_value, bool)
            and math.isfinite(float(direct_value))
            and float(direct_value) > 0
            and all(
                companion.get("status") == "available"
                and isinstance(companion.get("value"), (int, float))
                and not isinstance(companion.get("value"), bool)
                for companion in companions
            )
        )
    if node_id.startswith("dt.project.facility_period_") or any(
        phrase in constraints for phrase in ("equals", "sum to")
    ):
        return False
    value = node.get("value")
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, str):
        # Enumerated gates must not be turned into invalid free text. The
        # preferred narrative fields do not use these suffixes.
        categorical_tokens = (
            "_applicability",
            "_status",
            "_mode",
            "_scope",
            "_basis",
            "_type",
        )
        return bool(value.strip()) and not node_id.endswith(categorical_tokens)
    if isinstance(value, (int, float)):
        return math.isfinite(float(value)) and float(value) > 0
    if isinstance(value, list):
        return True
    return False


def _safe_mutated_value(
    node_id: str,
    value: Any,
) -> tuple[Any, str, dict[str, Any]]:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{node_id}: value cannot be mutated semantically")
    if isinstance(value, int):
        delta = max(1, round(abs(value) * 0.05))
        new_value = value + delta
        return (
            new_value,
            "positive_integer_sensitivity_increase",
            {
                "type_preserved": True,
                "finite": True,
                "positive": new_value > 0,
            },
        )
    if isinstance(value, float):
        multiplier = 1.05
        new_value = round(value * multiplier, 12)
        if not math.isfinite(new_value) or new_value <= 0:
            raise ValueError(f"{node_id}: numeric mutation is not finite and positive")
        return (
            new_value,
            "positive_numeric_sensitivity_increase_5pct",
            {
                "type_preserved": True,
                "finite": True,
                "positive": True,
            },
        )
    if isinstance(value, str):
        new_value = value.rstrip() + " (benchmark sensitivity variant)"
        return (
            new_value,
            "qualified_text_sensitivity_variant",
            {"type_preserved": True, "nonempty": True},
        )
    if isinstance(value, list):
        new_value = [*deepcopy(value), "Benchmark sensitivity variant"]
        return (
            new_value,
            "list_extension_sensitivity_variant",
            {
                "type_preserved": True,
                "original_items_preserved": True,
                "item_count_delta": 1,
            },
        )
    raise ValueError(f"{node_id}: unsupported mutation value {type(value).__name__}")


def _target_node(twin: dict[str, Any], node_id: str) -> dict[str, Any]:
    if node_id in twin.get("nodes", {}):
        return twin["nodes"][node_id]
    if node_id in twin.get("collections", {}):
        return twin["collections"][node_id]
    raise KeyError(node_id)


def _mark_counterfactual(
    node: dict[str, Any],
    *,
    condition: dict[str, Any],
    change: dict[str, Any],
) -> None:
    """Make a changed value visibly counterfactual without erasing its baseline provenance."""

    node["not_a_source_claim"] = True
    node["benchmark_counterfactual"] = {
        "condition_id": condition.get("condition_id"),
        "operation": change.get("operation"),
        "semantic_rule": change.get("semantic_rule"),
        "baseline_evidence_class": condition.get("target_evidence_class"),
        "not_a_source_claim": True,
    }


def _validate_mutation_postconditions(
    original: dict[str, Any],
    updated: dict[str, Any],
    condition: dict[str, Any],
) -> None:
    """Validate exact application plus the declared coupled evidence constraints."""

    for change in condition["changes"]:
        checks = change.get("constraint_checks", {})
        if checks and not all(bool(value) for value in checks.values()):
            raise ValueError(
                f"{change['node_id']}: mutation declares a failed constraint check"
            )
        if change["operation"] == "replace_value":
            node = _locate(updated, change["node_id"])
            if node.get("status") != change["new_status"]:
                raise ValueError(f"{change['node_id']}: mutation status was not applied")
            if node.get("value") != change["new_value"]:
                raise ValueError(f"{change['node_id']}: mutation value was not applied")
            marker = node.get("benchmark_counterfactual", {})
            if marker.get("condition_id") != condition.get("condition_id"):
                raise ValueError(
                    f"{change['node_id']}: counterfactual provenance marker is absent"
                )
        elif change["operation"] == "remove_record":
            records = updated["collections"][change["node_id"]]["records"]
            if any(item.get("id") == change["record_id"] for item in records):
                raise ValueError(f"{change['node_id']}: mutation record remains present")
            if len(records) != len(
                original["collections"][change["node_id"]]["records"]
            ) - 1:
                raise ValueError(
                    f"{change['node_id']}: mutation removed an unexpected record count"
                )

    changed_ids = set(condition.get("changed_ids") or [])
    if "dt.project.facility_period_1_years" in changed_ids:
        period_ids = [
            f"dt.project.facility_period_{period}_years" for period in range(1, 5)
        ]
        periods = [float(updated["nodes"][item]["value"]) for item in period_ids]
        implementation = float(
            updated["nodes"]["dt.project.implementation_years"]["value"]
        )
        if not all(item > 0 for item in periods) or not math.isclose(
            sum(periods), implementation, rel_tol=0.0, abs_tol=1e-9
        ):
            raise ValueError(
                "paired facility-period mutation does not preserve positive periods "
                "summing to implementation years"
            )
    if "dt.project.direct_beneficiaries_target" in changed_ids:
        direct = float(
            updated["nodes"]["dt.project.direct_beneficiaries_target"]["value"]
        )
        women = float(
            updated["nodes"]["dt.project.women_beneficiaries_target"]["value"]
        )
        local = float(
            updated["nodes"]["dt.project.local_community_beneficiaries_target"][
                "value"
            ]
        )
        if women > direct or local > direct:
            raise ValueError(
                "beneficiary mutation violates subordinate beneficiary bounds"
            )


def _mask_condition(project_id: str, topology: dict[str, Any]) -> dict[str, Any]:
    slug = topology["category"].replace(".", "_")
    return {
        "schema_version": "react_report.condition/v2",
        "condition_id": f"{project_id.lower()}.v2.mask.{slug}",
        "project_id": project_id,
        "kind": "missingness",
        "category": topology["category"],
        "masked_ids": [topology["source_id"]],
        **_impact(topology),
    }


def _mutation_condition(
    twin: dict[str, Any],
    topology: dict[str, Any],
) -> dict[str, Any]:
    node_id = topology["source_id"]
    slug = topology["category"].replace(".", "_")
    if node_id in twin["collections"]:
        record = twin["collections"][node_id]["records"][-1]
        change = {
            "node_id": node_id,
            "operation": "remove_record",
            "record_id": record["id"],
            "old_record": deepcopy(record),
            "new_record": None,
        }
    else:
        node = twin["nodes"][node_id]
        change = {
            "node_id": node_id,
            "operation": "replace_value",
            "old_status": node["status"],
            "new_status": "available",
            "old_value": deepcopy(node.get("value")),
            "new_value": _mutated_value(node_id, node.get("value")),
        }
    return {
        "schema_version": "react_report.mutation/v2",
        "condition_id": f"{twin['project_id'].lower()}.v2.mutation.{slug}",
        "project_id": twin["project_id"],
        "kind": "mutation",
        "category": topology["category"],
        "changes": [change],
        **_impact(topology),
    }


def _impact(topology: dict[str, Any]) -> dict[str, Any]:
    return {
        "target_id": topology["source_id"],
        "value_kind": topology["value_kind"],
        "has_calculation_dependents": topology["has_calculation_dependents"],
        "calculation_descendant_ids": topology["calculation_descendant_ids"],
        "max_descendant_depth": topology["max_descendant_depth"],
        "affected_component_ids": topology["affected_component_ids"],
        "affected_section_ids": topology["affected_section_ids"],
        "section_fanout": topology["section_fanout"],
        "locality": topology["locality"],
    }


def _upstream_sources(
    node_id: str,
    calculations: dict[str, dict[str, Any]],
    visiting: set[str] | None = None,
) -> set[str]:
    if node_id not in calculations:
        return {node_id}
    active = set(visiting or ())
    if node_id in active:
        raise ValueError(f"cycle in compiled v2 graph at {node_id}")
    active.add(node_id)
    output = set()
    for dependency in calculations[node_id]["canonical_dependencies"]:
        output.update(_upstream_sources(dependency, calculations, active))
    return output


def _descendants(node_id: str, reverse: dict[str, set[str]]) -> set[str]:
    output = {node_id}
    queue = deque([node_id])
    while queue:
        current = queue.popleft()
        for dependent in reverse.get(current, set()):
            if dependent in output:
                continue
            output.add(dependent)
            queue.append(dependent)
    return output


def _mutated_value(node_id: str, value: Any) -> Any:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) * 1.05
    if isinstance(value, list):
        addition = (
            "Solar energy"
            if node_id == "dt.project.energy_technologies"
            else "Benchmark pilot addition"
        )
        return [*deepcopy(value), addition]
    return f"{value} (revised)"


def _locate(twin: dict[str, Any], node_id: str) -> dict[str, Any]:
    if node_id in twin["nodes"]:
        return twin["nodes"][node_id]
    for collection in twin["collections"].values():
        for record in collection["records"]:
            if record["id"] == node_id:
                return record
            for field in record.get("fields", {}).values():
                if field["id"] == node_id:
                    return field
    raise ValueError(f"unknown v2 mutation node {node_id!r}")
