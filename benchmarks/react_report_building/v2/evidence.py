from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from ..util import read_json, sha256_json
from .enrichment_all20 import project_output_path as enrichment_output_path
from .source_normalization import (
    project_output_path as source_normalization_output_path,
)
from .study_design import project_specialisation_assignments


PROJECT_TOKEN = re.compile(r"fp\d{3}", re.I)
_PREPARED_KEY = "_v2_evidence_overlay"


def load_source_normalization(project_id: str | None = None) -> dict[str, Any]:
    """Load one source-normalization bundle.

    The no-argument compatibility form resolves FP083 through the same
    authoritative all-population path as every other project.
    """

    path = source_normalization_output_path(
        _normalize_project_id(project_id or "FP083")
    )
    return _read_required_bundle(path, label="source-normalization")


def load_enrichment(project_id: str | None = None) -> dict[str, Any]:
    """Load one target project's enrichment bundle.

    The no-argument compatibility form resolves authoritative FP083 evidence.
    """

    path = enrichment_output_path(_normalize_project_id(project_id or "FP083"))
    return _read_required_bundle(path, label="enrichment")


def prepare_v2_twin(
    twin: dict[str, Any],
    *,
    source_normalization: dict[str, Any] | None = None,
    enrichment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge one project's immutable source and enrichment bundles.

    Every collision is rejected. A value prepared by this function is marked,
    so passing that exact prepared twin through the runtime a second time is an
    idempotent validation step rather than a second merge.
    """

    project_id = _normalize_project_id(twin.get("project_id"))
    template_id = _template_for_project(project_id)
    source = source_normalization or load_source_normalization(project_id)
    enriched = enrichment or load_enrichment(project_id)
    _validate_bundle_headers(
        project_id=project_id,
        template_id=template_id,
        source=source,
        enrichment=enriched,
    )

    marker = twin.get(_PREPARED_KEY)
    expected_marker = _overlay_marker(project_id, template_id, source, enriched)
    if marker is not None:
        if marker == expected_marker:
            return deepcopy(twin)
        if _is_legacy_fp083_marker(marker, project_id=project_id):
            twin = _strip_legacy_fp083_overlay(twin)
        else:
            raise ValueError(
                f"{project_id}: prepared evidence marker does not match the "
                "authoritative bundles"
            )

    output = deepcopy(twin)
    nodes = output.setdefault("nodes", {})
    collections = output.setdefault("collections", {})
    source_nodes = _validated_items(
        source.get("nodes"),
        container="source-normalization nodes",
        project_id=project_id,
        reference=False,
    )
    project_nodes = _validated_items(
        enriched.get("project_nodes"),
        container="enrichment project_nodes",
        project_id=project_id,
        reference=False,
    )
    project_collections = _validated_items(
        enriched.get("project_collections", {}),
        container="enrichment project_collections",
        project_id=project_id,
        reference=False,
    )

    _assert_disjoint(
        {
            "normalized twin nodes": set(nodes),
            "normalized twin collections": set(collections),
            "source-normalization nodes": set(source_nodes),
            "enrichment project nodes": set(project_nodes),
            "enrichment project collections": set(project_collections),
        },
        project_id=project_id,
    )
    nodes.update(deepcopy(source_nodes))
    nodes.update(deepcopy(project_nodes))
    collections.update(deepcopy(project_collections))
    rebased_changes = output.pop("_v2_rebased_scalar_changes", {})
    for node_id, changes in rebased_changes.items():
        if node_id not in nodes:
            raise ValueError(
                f"{project_id}: legacy mutation target {node_id!r} is absent "
                "from the family evidence bundle"
            )
        nodes[node_id].update(deepcopy(changes))
    output[_PREPARED_KEY] = expected_marker
    return output


def prepare_v2_reference(
    reference: dict[str, Any],
    *,
    project_id: str | None = None,
    enrichment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge target-excluded peer references for exactly one project."""

    if project_id is None:
        enriched = enrichment or load_enrichment("FP083")
        project = _normalize_project_id(enriched.get("project_id") or "FP083")
    else:
        project = _normalize_project_id(project_id)
        enriched = enrichment or load_enrichment(project)
        if enriched.get("schema_version") != "react_report.evidence_enrichment/v3":
            raise ValueError(f"{project}: unexpected enrichment schema")
    template_id = _template_for_project(project)
    if enriched.get("project_id") != project:
        raise ValueError(
            f"{project}: enrichment bundle declares {enriched.get('project_id')!r}"
        )
    declared_template = enriched.get("template_id")
    if declared_template is not None and declared_template != template_id:
        raise ValueError(
            f"{project}: enrichment bundle declares template "
            f"{declared_template!r}, expected {template_id!r}"
        )

    output = deepcopy(reference)
    nodes = output.setdefault("nodes", {})
    reference_nodes = _validated_items(
        enriched.get("reference_nodes"),
        container="enrichment reference_nodes",
        project_id=project,
        reference=True,
    )
    _assert_disjoint(
        {
            "base reference nodes": set(nodes),
            "enrichment reference nodes": set(reference_nodes),
        },
        project_id=project,
    )
    nodes.update(deepcopy(reference_nodes))
    output[_PREPARED_KEY] = {
        "project_id": project,
        "template_id": template_id,
        "enrichment_sha256": sha256_json(enriched),
    }
    return output


def overlay_catalogue_entries(
    project_id: str | None = None,
    *,
    source_normalization: dict[str, Any] | None = None,
    enrichment: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return catalogue entries for one project and its peer references."""

    if project_id is None:
        source = source_normalization or load_source_normalization("FP083")
        enriched = enrichment or load_enrichment("FP083")
        project = _normalize_project_id(enriched.get("project_id") or "FP083")
    else:
        project = _normalize_project_id(project_id)
        source = source_normalization or load_source_normalization(project)
        enriched = enrichment or load_enrichment(project)
        _validate_bundle_headers(
            project_id=project,
            template_id=_template_for_project(project),
            source=source,
            enrichment=enriched,
        )
    groups = {
        "source-normalization nodes": _validated_items(
            source.get("nodes"),
            container="source-normalization nodes",
            project_id=project,
            reference=False,
        ),
        "enrichment project nodes": _validated_items(
            enriched.get("project_nodes"),
            container="enrichment project_nodes",
            project_id=project,
            reference=False,
        ),
        "enrichment project collections": _validated_items(
            enriched.get("project_collections", {}),
            container="enrichment project_collections",
            project_id=project,
            reference=False,
        ),
        "enrichment reference nodes": _validated_items(
            enriched.get("reference_nodes"),
            container="enrichment reference_nodes",
            project_id=project,
            reference=True,
        ),
    }
    _assert_disjoint(
        {name: set(items) for name, items in groups.items()},
        project_id=project,
    )
    nodes = {
        node_id: node
        for items in groups.values()
        for node_id, node in items.items()
    }
    return {
        node_id: {
            "id": node_id,
            "kind": node.get("kind", "scalar"),
            "description": node.get("description") or node_id,
            "status": node.get("status", "available"),
            "unit": node.get("unit"),
            "evidence_class": node.get("evidence_class")
            or node.get("provenance", {}).get("source_kind"),
        }
        for node_id, node in nodes.items()
    }


def evidence_bundle_metadata(project_id: str) -> tuple[dict[str, Any], ...]:
    """Return the bundle identities consumed by deterministic preflight."""

    project = _normalize_project_id(project_id)
    source = load_source_normalization(project)
    enriched = load_enrichment(project)
    return (
        {
            "schema_version": source.get("schema_version"),
            "project_id": source.get("project_id"),
            "bundle_kind": "source_normalization",
        },
        {
            "schema_version": enriched.get("schema_version"),
            "project_id": enriched.get("project_id"),
            "template_id": enriched.get("template_id"),
            "bundle_kind": "enrichment",
        },
    )


def _read_required_bundle(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"required {label} bundle is missing: {path}")
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"{label} bundle must be a JSON object: {path}")
    return payload


def _normalize_project_id(project_id: Any) -> str:
    project = str(project_id or "").strip().upper()
    if not project:
        raise ValueError("project_id must be non-empty")
    return project


def _template_for_project(project_id: str) -> str:
    assignments = project_specialisation_assignments()
    try:
        return assignments[project_id]
    except KeyError as exc:
        raise ValueError(
            f"{project_id}: project is outside the authoritative study population"
        ) from exc


def _validate_bundle_headers(
    *,
    project_id: str,
    template_id: str,
    source: dict[str, Any],
    enrichment: dict[str, Any],
    allow_legacy_fp083: bool = False,
) -> None:
    if source.get("schema_version") != "react_report.source_normalization/v2":
        raise ValueError(f"{project_id}: unexpected source-normalization schema")
    if source.get("project_id") != project_id:
        raise ValueError(
            f"{project_id}: source-normalization bundle declares "
            f"{source.get('project_id')!r}"
        )
    allowed_enrichment_schemas = {"react_report.evidence_enrichment/v3"}
    if allow_legacy_fp083 and project_id == "FP083":
        allowed_enrichment_schemas.add("react_report.evidence_enrichment/v2")
    if enrichment.get("schema_version") not in allowed_enrichment_schemas:
        raise ValueError(f"{project_id}: unexpected enrichment schema")
    if enrichment.get("project_id") != project_id:
        raise ValueError(
            f"{project_id}: enrichment bundle declares "
            f"{enrichment.get('project_id')!r}"
        )
    if (
        enrichment.get("template_id") != template_id
        and not (
            allow_legacy_fp083
            and project_id == "FP083"
            and enrichment.get("template_id") is None
        )
    ):
        raise ValueError(
            f"{project_id}: enrichment bundle declares template "
            f"{enrichment.get('template_id')!r}, expected {template_id!r}"
        )


def _validated_items(
    value: Any,
    *,
    container: str,
    project_id: str,
    reference: bool,
) -> Mapping[str, dict[str, Any]]:
    if not isinstance(value, dict):
        raise ValueError(f"{project_id}: {container} must be an object")
    for node_id, node in value.items():
        if not isinstance(node, dict) or node.get("id") != node_id:
            raise ValueError(
                f"{project_id}: {container} entry {node_id!r} has a mismatched ID"
            )
        if reference != node_id.startswith("reference."):
            expected = "reference" if reference else "project"
            raise ValueError(
                f"{project_id}: {container} entry {node_id!r} is not a {expected} ID"
            )
        _validate_node_isolation(node, project_id=project_id, reference=reference)
        _validate_nested_isolation(
            node,
            project_id=project_id,
            reference=reference,
        )
    return value


def _validate_nested_isolation(
    node: dict[str, Any],
    *,
    project_id: str,
    reference: bool,
) -> None:
    children: list[dict[str, Any]] = []
    if node.get("kind") == "collection":
        records = node.get("records", [])
        if not isinstance(records, list):
            raise ValueError(
                f"{project_id}: {node.get('id')} collection records must be a list"
            )
        children.extend(records)
    if node.get("kind") == "record":
        fields = node.get("fields", {})
        if not isinstance(fields, dict):
            raise ValueError(
                f"{project_id}: {node.get('id')} record fields must be an object"
            )
        children.extend(fields.values())
    for child in children:
        if not isinstance(child, dict) or not child.get("id"):
            raise ValueError(
                f"{project_id}: {node.get('id')} contains a malformed nested item"
            )
        child_id = str(child["id"])
        if reference != child_id.startswith("reference."):
            expected = "reference" if reference else "project"
            raise ValueError(
                f"{project_id}: nested entry {child_id!r} is not a {expected} ID"
            )
        _validate_node_isolation(
            child,
            project_id=project_id,
            reference=reference,
        )
        _validate_nested_isolation(
            child,
            project_id=project_id,
            reference=reference,
        )


def _validate_node_isolation(
    node: dict[str, Any],
    *,
    project_id: str,
    reference: bool,
) -> None:
    node_id = str(node.get("id") or "<unknown>")
    provenance = node.get("provenance") or {}
    if not isinstance(provenance, dict):
        raise ValueError(f"{project_id}: {node_id} provenance must be an object")
    if reference:
        if node.get("evidence_class") != "cross_project_reference_statistic":
            raise ValueError(
                f"{project_id}: {node_id} is not classified as a peer reference"
            )
        if provenance.get("target_excluded") != project_id:
            raise ValueError(
                f"{project_id}: {node_id} does not declare the target exclusion"
            )
        raw_peer_ids = provenance.get("project_ids")
        if not isinstance(raw_peer_ids, list):
            raise ValueError(
                f"{project_id}: {node_id} peer project_ids must be a list"
            )
        peer_ids = {
            _normalize_project_id(item)
            for item in raw_peer_ids
        }
        if project_id in peer_ids:
            raise ValueError(
                f"{project_id}: {node_id} leaks the target into peer evidence"
            )
        return

    declared = provenance.get("project_id") or provenance.get("target_project_id")
    if (
        node.get("evidence_class") == "synthetic_benchmark_enrichment"
        and declared is None
    ):
        raise ValueError(
            f"{project_id}: {node_id} synthetic provenance lacks project_id"
        )
    if declared is not None and _normalize_project_id(declared) != project_id:
        raise ValueError(
            f"{project_id}: {node_id} provenance declares foreign project {declared}"
        )
    for field in ("document_id", "locator", "url"):
        raw = provenance.get(field)
        if not raw:
            continue
        foreign = sorted(
            token.upper()
            for token in set(PROJECT_TOKEN.findall(str(raw)))
            if token.upper() != project_id
        )
        if foreign:
            raise ValueError(
                f"{project_id}: {node_id} {field} contains foreign project IDs "
                + ", ".join(foreign)
            )


def _assert_disjoint(
    groups: Mapping[str, set[str]],
    *,
    project_id: str,
) -> None:
    owners: dict[str, str] = {}
    collisions: dict[str, list[str]] = {}
    for group, ids in groups.items():
        for node_id in ids:
            if node_id in owners:
                collisions.setdefault(node_id, [owners[node_id]]).append(group)
            else:
                owners[node_id] = group
    if collisions:
        rendered = "; ".join(
            f"{node_id} ({', '.join(containers)})"
            for node_id, containers in sorted(collisions.items())
        )
        raise ValueError(f"{project_id}: evidence node ID collision: {rendered}")


def _overlay_marker(
    project_id: str,
    template_id: str,
    source: dict[str, Any],
    enrichment: dict[str, Any],
) -> dict[str, str]:
    return {
        "project_id": project_id,
        "template_id": template_id,
        "source_normalization_sha256": sha256_json(source),
        "enrichment_sha256": sha256_json(enrichment),
    }


def _is_legacy_fp083_marker(marker: Any, *, project_id: str) -> bool:
    if project_id != "FP083" or not isinstance(marker, dict):
        return False
    source = load_source_normalization()
    enrichment = load_enrichment()
    return marker == _overlay_marker(
        "FP083",
        _template_for_project("FP083"),
        source,
        enrichment,
    )


def _strip_legacy_fp083_overlay(twin: dict[str, Any]) -> dict[str, Any]:
    """Rebase a marked pilot twin onto family evidence without silent mixing."""

    source = load_source_normalization()
    enrichment = load_enrichment()
    output = deepcopy(twin)
    changed_scalars: dict[str, dict[str, Any]] = {}
    legacy_nodes = {
        **source.get("nodes", {}),
        **enrichment.get("project_nodes", {}),
    }
    for node_id, expected in legacy_nodes.items():
        actual = output.get("nodes", {}).get(node_id)
        if actual is None:
            raise ValueError(
                f"FP083: marked legacy overlay is missing node {node_id!r}"
            )
        if actual != expected:
            changed_scalars[node_id] = {
                key: deepcopy(actual.get(key)) for key in ("status", "value")
            }
        del output["nodes"][node_id]
    for collection_id, expected in enrichment.get("project_collections", {}).items():
        actual = output.get("collections", {}).get(collection_id)
        if actual is None:
            raise ValueError(
                f"FP083: marked legacy overlay is missing collection {collection_id!r}"
            )
        if actual != expected:
            raise ValueError(
                f"FP083: cannot rebase a mutated legacy collection {collection_id!r}"
            )
        del output["collections"][collection_id]
    output.pop(_PREPARED_KEY, None)
    if changed_scalars:
        output["_v2_rebased_scalar_changes"] = changed_scalars
    return output
