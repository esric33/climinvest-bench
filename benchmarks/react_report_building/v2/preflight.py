from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Iterable

from ..runtime.episode_factory import load_reference
from ..paths import NORMALIZED_ROOT
from ..runtime.calculator import Calculator
from ..runtime.evidence_store import EvidenceStore
from ..runtime.rendering import calculate_all
from ..util import read_json
from .contract_registry import DEFAULT_CONTRACT_REGISTRY, ContractRegistry
from .document import section_contracts
from .evidence import (
    evidence_bundle_metadata,
    load_enrichment,
    load_source_normalization,
    prepare_v2_reference,
    prepare_v2_twin,
)
from .registry import calculation_registry
from .study_design import evidence_class, load_population


PROJECT_TOKEN = re.compile(r"fp\d{3}", re.I)


def required_source_ids(contract: dict[str, Any]) -> set[str]:
    """Return the transitive non-calculation inputs required by the contract."""

    calculations = {
        calculation_id: list(definition.get("input_ids", {}).values())
        for calculation_id, definition in calculation_registry(contract).items()
    }
    memo: dict[str, set[str]] = {}

    def sources(node_id: str, active: frozenset[str] = frozenset()) -> set[str]:
        if node_id not in calculations:
            if node_id.startswith("calc."):
                raise ValueError(f"unknown calculation dependency {node_id!r}")
            return {node_id}
        if node_id in memo:
            return memo[node_id]
        if node_id in active:
            raise ValueError(f"calculation dependency cycle at {node_id!r}")
        found: set[str] = set()
        next_active = active | {node_id}
        for dependency in calculations[node_id]:
            found.update(sources(dependency, next_active))
        memo[node_id] = found
        return found

    roots = set(calculations)
    for artifact in contract.get("artifacts", []):
        if artifact.get("type") in {"table", "llm"}:
            roots.update(artifact.get("canonical_dependencies") or [])
    output: set[str] = set()
    for root in roots:
        output.update(sources(root))
    return output


def preflight_project_contract(
    *,
    twin: dict[str, Any],
    reference: dict[str, Any],
    contract: dict[str, Any],
    require_all_available: bool = True,
    evidence_metadata: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Run a deterministic readiness gate before any provider invocation.

    A strict smoke requires every direct input and calculation to be resolved.
    Explicitly qualified ``not_applicable`` inputs and their calculation
    descendants are resolved states, not fabricated zeros. With
    ``require_all_available=False``, explicitly missing source nodes and their
    ``missing_dependency`` descendants are also allowed; unknown IDs, invalid
    calculations, project leakage, and malformed contracts always fail.
    """

    project_id = str(twin.get("project_id") or "").upper()
    errors = _contract_errors(contract, project_id=project_id)
    errors.extend(
        _metadata_errors(
            evidence_metadata,
            project_id=project_id,
            template_id=contract.get("template_id") or contract.get("contract_id"),
        )
    )
    try:
        source_ids = required_source_ids(contract)
    except ValueError as exc:
        errors.append(_error("invalid_dependency_graph", str(exc)))
        source_ids = set()

    store = EvidenceStore(twin, reference)
    allowed_not_applicable = set(
        contract.get("applicability_contract", {}).get(
            "allowed_not_applicable_ids", []
        )
    )
    source_statuses: dict[str, str] = {}
    unknown_ids = []
    missing_ids = []
    not_applicable_ids = []
    disallowed_not_applicable_ids = []
    invalid_not_applicable_ids = []
    unavailable_ids = []
    provenance_mismatches = []
    for node_id in sorted(source_ids):
        node = store.get(node_id)
        status = str(node.get("status") or "unknown")
        source_statuses[node_id] = status
        if status == "unknown_id":
            unknown_ids.append(node_id)
        elif status == "missing":
            missing_ids.append(node_id)
        elif status == "not_applicable":
            not_applicable_ids.append(node_id)
            if node_id not in allowed_not_applicable:
                disallowed_not_applicable_ids.append(node_id)
            applicability = node.get("applicability")
            if not (
                isinstance(applicability, dict)
                and applicability.get("status") == "not_applicable"
                and applicability.get("reason")
                and applicability.get("basis")
            ):
                invalid_not_applicable_ids.append(node_id)
        elif status != "available":
            unavailable_ids.append(node_id)
        provenance_mismatches.extend(
            _provenance_mismatches(node, project_id=project_id)
        )

    registry = calculation_registry(contract)
    calculation_result = calculate_all(Calculator(store, registry=registry))
    calculation_statuses = {
        item["id"]: str(item.get("status") or "unknown")
        for item in calculation_result.get("results", [])
    }
    not_applicable_calculations = sorted(
        node_id
        for node_id, status in calculation_statuses.items()
        if status == "not_applicable_dependency"
    )
    unresolved_calculations = sorted(
        node_id
        for node_id, status in calculation_statuses.items()
        if status not in {"available", "not_applicable_dependency"}
    )
    invalid_calculations = sorted(
        node_id
        for node_id, status in calculation_statuses.items()
        if status
        not in {
            "available",
            "missing_dependency",
            "not_applicable_dependency",
        }
    )

    if unknown_ids:
        errors.append(
            _error(
                "unknown_required_ids",
                f"{len(unknown_ids)} required IDs are absent from the evidence store",
                ids=unknown_ids,
            )
        )
    if unavailable_ids:
        errors.append(
            _error(
                "invalid_required_status",
                "required IDs have neither available nor explicit missing status",
                ids=unavailable_ids,
            )
        )
    if invalid_not_applicable_ids:
        errors.append(
            _error(
                "invalid_not_applicable_metadata",
                "not-applicable evidence requires a status, reason, and basis",
                ids=invalid_not_applicable_ids,
            )
        )
    if disallowed_not_applicable_ids:
        errors.append(
            _error(
                "not_applicable_not_allowed",
                "contract does not permit not-applicable status for these IDs",
                ids=disallowed_not_applicable_ids,
            )
        )
    if provenance_mismatches:
        errors.append(
            _error(
                "foreign_project_provenance",
                "required evidence contains provenance for a different target project",
                mismatches=provenance_mismatches,
            )
        )
    if invalid_calculations:
        errors.append(
            _error(
                "invalid_calculations",
                "one or more calculations failed for reasons other than explicit missingness",
                ids=invalid_calculations,
            )
        )
    if require_all_available and missing_ids:
        errors.append(
            _error(
                "missing_required_ids",
                f"{len(missing_ids)} required IDs are explicitly missing",
                ids=missing_ids,
            )
        )
    if require_all_available and unresolved_calculations:
        errors.append(
            _error(
                "unavailable_calculations",
                f"{len(unresolved_calculations)} calculations are unresolved",
                ids=unresolved_calculations,
            )
        )

    return {
        "schema_version": "react_report.preflight/v2",
        "project_id": project_id,
        "benchmark_version": contract.get("benchmark_version"),
        "require_all_available": require_all_available,
        "ready_for_provider_smoke": not errors,
        "fully_available": not (
            unknown_ids
            or missing_ids
            or not_applicable_ids
            or unavailable_ids
            or not_applicable_calculations
            or unresolved_calculations
        ),
        "fully_resolved": not (
            unknown_ids
            or missing_ids
            or invalid_not_applicable_ids
            or disallowed_not_applicable_ids
            or unavailable_ids
            or unresolved_calculations
        ),
        "errors": errors,
        "direct_evidence": {
            "required_count": len(source_ids),
            "status_counts": dict(sorted(Counter(source_statuses.values()).items())),
            "unknown_ids": unknown_ids,
            "missing_ids": missing_ids,
            "not_applicable_ids": not_applicable_ids,
            "invalid_not_applicable_ids": invalid_not_applicable_ids,
            "disallowed_not_applicable_ids": disallowed_not_applicable_ids,
            "unavailable_ids": unavailable_ids,
        },
        "calculations": {
            "required_count": len(registry),
            "status_counts": dict(
                sorted(Counter(calculation_statuses.values()).items())
            ),
            "unavailable_ids": unresolved_calculations,
            "not_applicable_ids": not_applicable_calculations,
            "invalid_ids": invalid_calculations,
        },
        "provenance_mismatches": provenance_mismatches,
    }


def preflight_study_population(
    *,
    project_ids: Iterable[str] | None = None,
    population: dict[str, Any] | None = None,
    registry: ContractRegistry = DEFAULT_CONTRACT_REGISTRY,
    require_all_available: bool = True,
) -> dict[str, Any]:
    """Preflight the fixed population without constructing or calling a provider.

    Coverage is computed over transitive direct evidence requirements, so the
    evidence-class totals describe what each compiled report actually consumes.
    Explicit N/A is resolved only through ``preflight_project_contract``'s
    contract-declared allow-list.
    """

    study = population if population is not None else load_population()
    assignments = {
        str(item["project_id"]).upper(): str(item["template_id"])
        for item in study.get("projects", [])
    }
    authoritative = tuple(assignments)
    if project_ids is None:
        selected = authoritative
    else:
        selected = tuple(str(item).strip().upper() for item in project_ids)
        if not selected:
            raise ValueError("preflight project selection must not be empty")
        duplicates = sorted(
            project_id
            for project_id, count in Counter(selected).items()
            if count > 1
        )
        if duplicates:
            raise ValueError(
                "preflight project selection contains duplicates: "
                + ", ".join(duplicates)
            )
        unsupported = sorted(set(selected) - set(authoritative))
        if unsupported:
            raise ValueError(
                "preflight projects are outside the authoritative population: "
                + ", ".join(unsupported)
            )

    base_reference = load_reference()
    projects: list[dict[str, Any]] = []
    class_totals: Counter[str] = Counter()
    status_totals: Counter[str] = Counter()
    template_class_totals: dict[str, Counter[str]] = defaultdict(Counter)
    template_status_totals: dict[str, Counter[str]] = defaultdict(Counter)

    for project_id in selected:
        template_id = assignments[project_id]
        try:
            binding = registry.resolve(project_id=project_id)
            if binding.contract_id != template_id:
                raise ValueError(
                    f"registry resolved {binding.contract_id!r}, population "
                    f"assigns {template_id!r}"
                )
            contract = binding.load()
            source = load_source_normalization(project_id)
            enrichment = load_enrichment(project_id)
            twin = prepare_v2_twin(
                read_json(NORMALIZED_ROOT / f"{project_id.lower()}.json"),
                source_normalization=source,
                enrichment=enrichment,
            )
            reference = prepare_v2_reference(
                base_reference,
                project_id=project_id,
                enrichment=enrichment,
            )
            result = preflight_project_contract(
                twin=twin,
                reference=reference,
                contract=contract,
                require_all_available=require_all_available,
                evidence_metadata=evidence_bundle_metadata(project_id),
            )
            coverage = _direct_evidence_coverage(
                twin=twin,
                reference=reference,
                contract=contract,
            )
        except (KeyError, OSError, TypeError, ValueError) as exc:
            result = {
                "schema_version": "react_report.preflight/v2",
                "project_id": project_id,
                "ready_for_provider_smoke": False,
                "fully_available": False,
                "fully_resolved": False,
                "errors": [
                    _error(
                        "population_preflight_setup_error",
                        str(exc),
                    )
                ],
                "direct_evidence": {
                    "required_count": 0,
                    "status_counts": {},
                },
                "calculations": {
                    "required_count": 0,
                    "status_counts": {},
                },
            }
            coverage = {
                "required_count": 0,
                "by_evidence_class": {},
                "by_status": {},
                "by_evidence_class_and_status": {},
            }

        class_totals.update(coverage["by_evidence_class"])
        status_totals.update(coverage["by_status"])
        template_class_totals[template_id].update(coverage["by_evidence_class"])
        template_status_totals[template_id].update(coverage["by_status"])
        projects.append(
            {
                "project_id": project_id,
                "template_id": template_id,
                "contract_id": template_id,
                "ready_for_provider_smoke": result[
                    "ready_for_provider_smoke"
                ],
                "fully_available": result["fully_available"],
                "fully_resolved": result["fully_resolved"],
                "evidence_coverage": coverage,
                "preflight": result,
            }
        )

    by_project = {
        item["project_id"]: {
            "template_id": item["template_id"],
            "ready_for_provider_smoke": item["ready_for_provider_smoke"],
            **item["evidence_coverage"],
        }
        for item in projects
    }
    by_template: dict[str, Any] = {}
    for template_id in sorted(set(assignments.values())):
        members = [item for item in projects if item["template_id"] == template_id]
        by_template[template_id] = {
            "project_count": len(members),
            "ready_project_count": sum(
                item["ready_for_provider_smoke"] for item in members
            ),
            "fully_resolved_project_count": sum(
                item["fully_resolved"] for item in members
            ),
            "by_evidence_class": dict(
                sorted(template_class_totals[template_id].items())
            ),
            "by_status": dict(
                sorted(template_status_totals[template_id].items())
            ),
        }

    ready_count = sum(item["ready_for_provider_smoke"] for item in projects)
    fully_resolved_count = sum(item["fully_resolved"] for item in projects)
    fully_available_count = sum(item["fully_available"] for item in projects)
    return {
        "schema_version": "react_report.population_preflight/v2",
        "population_id": study.get("population_id"),
        "provider_calls": 0,
        "project_count": len(projects),
        "ready_project_count": ready_count,
        "fully_resolved_project_count": fully_resolved_count,
        "fully_available_project_count": fully_available_count,
        "all_ready_for_provider_smoke": ready_count == len(projects),
        "require_all_available": require_all_available,
        "coverage": {
            "by_evidence_class": dict(sorted(class_totals.items())),
            "by_status": dict(sorted(status_totals.items())),
            "by_template": by_template,
            "by_project": by_project,
        },
        "projects": projects,
    }


def _direct_evidence_coverage(
    *,
    twin: dict[str, Any],
    reference: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    store = EvidenceStore(twin, reference)
    by_class: Counter[str] = Counter()
    by_status: Counter[str] = Counter()
    cross: dict[str, Counter[str]] = defaultdict(Counter)
    for node_id in sorted(required_source_ids(contract)):
        node = store.get(node_id)
        default = (
            None if node_id.startswith("reference.") else "normalized_project_source"
        )
        resolved_class = evidence_class(node, container_default=default)
        status = str(node.get("status") or "unknown")
        by_class[resolved_class] += 1
        by_status[status] += 1
        cross[resolved_class][status] += 1
    return {
        "required_count": sum(by_class.values()),
        "by_evidence_class": dict(sorted(by_class.items())),
        "by_status": dict(sorted(by_status.items())),
        "by_evidence_class_and_status": {
            class_id: dict(sorted(counts.items()))
            for class_id, counts in sorted(cross.items())
        },
    }


def _contract_errors(
    contract: dict[str, Any],
    *,
    project_id: str,
) -> list[dict[str, Any]]:
    errors = []
    if contract.get("schema_version") != "react_report.compiled_contract/v2":
        errors.append(
            _error("invalid_contract_schema", "unexpected compiled-contract schema")
        )
    declared_project = contract.get("project_code")
    if declared_project and str(declared_project).upper() != project_id:
        errors.append(
            _error(
                "contract_project_mismatch",
                f"contract declares {declared_project}, twin declares {project_id}",
            )
        )
    try:
        sections = section_contracts(contract)
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(_error("invalid_section_contracts", str(exc)))
        return errors
    section_ids = [item.get("id") for item in sections]
    duplicates = sorted(
        section_id
        for section_id, count in Counter(section_ids).items()
        if count > 1
    )
    if duplicates:
        errors.append(
            _error(
                "duplicate_section_ids",
                f"duplicate visible section IDs: {', '.join(duplicates)}",
            )
        )
    for section in sections:
        components = section.get("required_components", [])
        llm_count = sum(item.get("kind") == "llm" for item in components)
        if llm_count != 1:
            errors.append(
                _error(
                    "llm_component_count",
                    f"section {section.get('id')} requires exactly one llm component",
                    section_id=section.get("id"),
                )
            )
        for component in components:
            if component.get("kind") == "subsection":
                if not component.get("heading"):
                    errors.append(
                        _error(
                            "invalid_subsection_component",
                            f"subsection {component.get('id')} lacks a heading",
                            section_id=section.get("id"),
                            component_id=component.get("id"),
                        )
                    )
                continue
            key = "data_ids" if component.get("kind") == "table" else "required_ids"
            if not isinstance(component.get(key), list):
                errors.append(
                    _error(
                        "invalid_component_dependencies",
                        f"component {component.get('id')} requires a {key} list",
                        section_id=section.get("id"),
                        component_id=component.get("id"),
                    )
                )
    return errors


def _metadata_errors(
    metadata_items: Iterable[dict[str, Any]],
    *,
    project_id: str,
    template_id: str | None = None,
) -> list[dict[str, Any]]:
    errors = []
    for index, metadata in enumerate(metadata_items):
        declared = metadata.get("project_id") or metadata.get("target_project_id")
        if declared and str(declared).upper() != project_id:
            errors.append(
                _error(
                    "evidence_bundle_project_mismatch",
                    f"evidence metadata {index} declares {declared}, expected {project_id}",
                    metadata_index=index,
                )
            )
        declared_template = metadata.get("template_id")
        if (
            declared_template
            and template_id
            and str(declared_template) != str(template_id)
        ):
            errors.append(
                _error(
                    "evidence_bundle_template_mismatch",
                    f"evidence metadata {index} declares template "
                    f"{declared_template}, expected {template_id}",
                    metadata_index=index,
                )
            )
    return errors


def _provenance_mismatches(
    node: dict[str, Any],
    *,
    project_id: str,
) -> list[dict[str, Any]]:
    provenance = node.get("provenance") or {}
    node_id = str(node.get("id") or "")
    mismatches = []
    declared = provenance.get("project_id") or provenance.get("target_project_id")
    if declared and str(declared).upper() != project_id:
        mismatches.append(
            {"node_id": node_id, "field": "project_id", "value": declared}
        )
    excluded = provenance.get("target_excluded")
    if node_id.startswith("reference.") and excluded:
        if str(excluded).upper() != project_id:
            mismatches.append(
                {"node_id": node_id, "field": "target_excluded", "value": excluded}
            )
        return mismatches
    if node_id.startswith("reference."):
        return mismatches
    for field in ("document_id", "locator", "url"):
        value = provenance.get(field)
        if not value:
            continue
        tokens = {item.upper() for item in PROJECT_TOKEN.findall(str(value))}
        foreign = sorted(token for token in tokens if token != project_id)
        if foreign:
            mismatches.append(
                {"node_id": node_id, "field": field, "value": value, "tokens": foreign}
            )
    return mismatches


def _error(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **details}
