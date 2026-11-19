from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..domain.ids import missing_id


MODEL_VISIBLE_NODE_FIELDS = (
    "id",
    "kind",
    "status",
    "value",
    "unit",
    "records",
    "fields",
    "missing_id",
    "evidence_class",
    "applicability",
    "not_a_source_claim",
    "operation_id",
    "missing_dependencies",
    "message",
    "suggested_result_id",
    "expected_request",
    "source_record_id",
)
MODEL_VISIBLE_APPLICABILITY_FIELDS = (
    "status",
    "reason",
    "arithmetic_placeholder",
)


def model_visible_node(
    node: dict[str, Any],
    *,
    _nested: bool = False,
    _inherited_evidence_class: Any = None,
    _inherited_not_a_source_claim: Any = None,
) -> dict[str, Any]:
    """Project an internal evidence node into the compact tool wire format.

    Provenance, enrichment recipes, generator seeds, descriptions, schemas and
    dependency internals remain in the store for deterministic execution and
    audit.  The model receives the claim identity/value/status fields needed to
    cite and interpret the result, including explicit synthetic-evidence and
    applicability markers.
    """

    if not isinstance(node, dict):
        raise TypeError("model-visible evidence must be projected from an object")

    output: dict[str, Any] = {}
    evidence_class = node.get("evidence_class", _inherited_evidence_class)
    not_a_source_claim = node.get(
        "not_a_source_claim",
        _inherited_not_a_source_claim,
    )
    for key in MODEL_VISIBLE_NODE_FIELDS:
        if key not in node:
            continue
        value = node[key]
        # Nested collection records and fields dominate observation size.  Their
        # shape already identifies the node kind, while ``available`` and a null
        # unit are the documented wire defaults.  Keep those fields on roots so
        # every top-level result remains self-describing, and retain every
        # non-default status/unit below it.
        if _nested and key == "kind":
            continue
        if _nested and key == "status" and value == "available":
            continue
        if _nested and key == "unit" and value is None:
            continue
        # Synthetic/source classification is inherited down a collection.  Do
        # not repeat identical markers on every record and scalar field; an
        # override still survives at the exact node where it changes.
        if (
            _nested
            and key == "evidence_class"
            and value == _inherited_evidence_class
        ):
            continue
        if (
            _nested
            and key == "not_a_source_claim"
            and value == _inherited_not_a_source_claim
        ):
            continue
        if key == "fields":
            if isinstance(value, dict):
                output[key] = {
                    str(name): model_visible_node(
                        field,
                        _nested=True,
                        _inherited_evidence_class=evidence_class,
                        _inherited_not_a_source_claim=not_a_source_claim,
                    )
                    for name, field in value.items()
                    if isinstance(field, dict)
                }
            continue
        if key == "records":
            if isinstance(value, list):
                output[key] = [
                    model_visible_node(
                        record,
                        _nested=True,
                        _inherited_evidence_class=evidence_class,
                        _inherited_not_a_source_claim=not_a_source_claim,
                    )
                    for record in value
                    if isinstance(record, dict)
                ]
            continue
        if key == "value" and isinstance(value, list):
            output[key] = [
                model_visible_node(
                    item,
                    _nested=True,
                    _inherited_evidence_class=evidence_class,
                    _inherited_not_a_source_claim=not_a_source_claim,
                )
                if isinstance(item, dict)
                else deepcopy(item)
                for item in value
            ]
            continue
        if key == "applicability":
            if isinstance(value, dict):
                output[key] = {
                    field: deepcopy(value[field])
                    for field in MODEL_VISIBLE_APPLICABILITY_FIELDS
                    if field in value
                }
            continue
        output[key] = deepcopy(value)
    return output


class EvidenceStore:
    """Run-scoped data store shared by retrieval and deterministic calculation."""

    def __init__(
        self,
        twin: dict[str, Any],
        reference: dict[str, Any],
        *,
        masked_ids: set[str] | None = None,
    ) -> None:
        self.project_id = str(twin["project_id"])
        self._nodes: dict[str, dict[str, Any]] = {
            **deepcopy(twin["nodes"]),
            **deepcopy(twin["collections"]),
            **deepcopy(reference["nodes"]),
        }
        self._calculated: dict[str, dict[str, Any]] = {}
        self.masked_ids = set(masked_ids or ())
        self._apply_masks()

    def _apply_masks(self) -> None:
        for node_id in sorted(self.masked_ids):
            if node_id in self._nodes:
                self._mask_node(self._nodes[node_id])
                continue
            parent = self._find_record_or_field(node_id)
            if parent is None:
                raise ValueError(f"mask references unknown node {node_id!r}")
            self._mask_node(parent)

    def _find_record_or_field(self, node_id: str) -> dict[str, Any] | None:
        for item in [*self._nodes.values(), *self._calculated.values()]:
            if item.get("kind") == "collection":
                records = item.get("records", [])
            elif item.get("kind") == "calculated" and isinstance(
                item.get("value"), list
            ):
                records = item["value"]
            else:
                continue
            for record in records:
                if record["id"] == node_id:
                    return record
                for field in record.get("fields", {}).values():
                    if field["id"] == node_id:
                        return field
        return None

    @staticmethod
    def _mask_node(node: dict[str, Any]) -> None:
        node["status"] = "missing"
        if node.get("kind") == "scalar":
            node["value"] = None
        elif node.get("kind") == "record":
            for field in node.get("fields", {}).values():
                field["status"] = "missing"
                field["value"] = None
        elif node.get("kind") == "collection":
            for record in node.get("records", []):
                EvidenceStore._mask_node(record)

    def get(self, node_id: str) -> dict[str, Any]:
        item = self._calculated.get(node_id) or self._nodes.get(node_id)
        if item is None:
            nested = self._find_record_or_field(node_id)
            if nested is not None:
                item = nested
        if item is None:
            return {
                "id": node_id,
                "kind": "error",
                "status": "unknown_id",
                "message": f"Unknown data ID {node_id!r}",
            }
        result = deepcopy(item)
        if result.get("status") in {"missing", "not_applicable"}:
            result["missing_id"] = missing_id(result["id"])
        return result

    def get_model_view(self, node_id: str) -> dict[str, Any]:
        """Return a compact model-visible copy without altering audit data."""

        return model_visible_node(self.get(node_id))

    def put_calculated(self, node: dict[str, Any]) -> None:
        self._calculated[node["id"]] = deepcopy(node)

    def calculated(self) -> dict[str, dict[str, Any]]:
        return deepcopy(self._calculated)

    def all_ids(self) -> set[str]:
        output: set[str] = set()

        def visit(item: dict[str, Any]) -> None:
            node_id = item.get("id")
            if node_id:
                output.add(str(node_id))
            if item.get("kind") == "collection":
                for record in item.get("records", []):
                    visit(record)
            if item.get("kind") == "record":
                for field in item.get("fields", {}).values():
                    visit(field)
            if item.get("kind") == "calculated" and isinstance(item.get("value"), list):
                for record in item["value"]:
                    if isinstance(record, dict):
                        visit(record)

        for item in [*self._nodes.values(), *self._calculated.values()]:
            visit(item)
        return output

    def snapshot(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "masked_ids": sorted(self.masked_ids),
            "calculated": self.calculated(),
        }
