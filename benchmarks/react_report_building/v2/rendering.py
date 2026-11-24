from __future__ import annotations

import re
from typing import Any

from ..runtime.evidence_store import EvidenceStore
from ..runtime.rendering import display, field_display, prose_excerpt, table
from .document import compose_report, section_contracts
from .registry import catalogue, calculation_registry


HEADER_FIELD_ALIASES = {
    "indicator": "indicator",
    "risk": "name",
    "intermediate target": "intermediate_target",
    "final target": "final_target",
    "assumptions": "assumptions",
    "benchmark priority": "benchmark_reporting_priority",
    "priority basis": "benchmark_priority_basis",
    "mrv readiness": "mrv_readiness_status",
    "missing mrv fields": "mrv_missing_fields",
    "score status": "priority_scoring_status",
    "delta status": "target_delta_status",
    "absolute change": "target_absolute_change",
    "percentage change": "target_percentage_change_pct",
}


def render_report(
    store: EvidenceStore,
    generated_text: dict[str, str] | None = None,
    *,
    contract: dict[str, Any] | None = None,
    data_catalogue: dict[str, Any] | None = None,
) -> str:
    sections = {
        section["id"]: render_section(
            section["id"],
            store,
            generated_text=generated_text,
            contract=contract,
            data_catalogue=data_catalogue,
        )
        for section in section_contracts(contract)
    }
    title_node = store.get("dt.project.title")
    title = (
        str(title_node.get("value"))
        if title_node.get("status") == "available"
        else "Project Investment and Performance Profile"
    )
    return compose_report(sections, title=title, contract=contract)


def render_section(
    section_id: str,
    store: EvidenceStore,
    generated_text: dict[str, str] | None = None,
    *,
    contract: dict[str, Any] | None = None,
    data_catalogue: dict[str, Any] | None = None,
) -> str:
    section = next(
        (item for item in section_contracts(contract) if item["id"] == section_id),
        None,
    )
    if section is None:
        raise ValueError(f"unknown v2 section {section_id!r}")
    blocks = []
    for component in section["required_components"]:
        if component["kind"] == "subsection":
            blocks.append(f"### {component['heading']}")
        elif component["kind"] == "table":
            blocks.append(
                _render_table(
                    component,
                    store,
                    calculation_contract=contract,
                    data_catalogue=data_catalogue,
                )
            )
        else:
            blocks.append(
                (generated_text or {}).get(component["id"])
                or _render_llm(
                    component,
                    store,
                    calculation_contract=contract,
                    data_catalogue=data_catalogue,
                )
            )
    return f"## {section['heading']}\n\n" + "\n\n".join(blocks)


def _render_table(
    component: dict[str, Any],
    store: EvidenceStore,
    *,
    calculation_contract: dict[str, Any] | None,
    data_catalogue: dict[str, Any] | None,
) -> str:
    if component["table_type"] == "records":
        body = _record_rows(component, store)
    else:
        body = [
            [
                _label(
                    node_id,
                    contract=calculation_contract,
                    data_catalogue=data_catalogue,
                ),
                display(store.get(node_id)),
            ]
            for node_id in component["data_ids"]
        ]
    return table(component["headers"], body)


def _record_rows(
    component: dict[str, Any],
    store: EvidenceStore,
) -> list[list[str]]:
    if len(component["data_ids"]) != 1:
        raise ValueError(
            f"records table {component['id']} requires exactly one collection"
        )
    collection = store.get(component["data_ids"][0])
    if collection.get("status") != "available":
        return [[display(collection), *([""] * (len(component["headers"]) - 1))]]
    records = collection.get("records")
    if records is None and collection.get("kind") == "calculated":
        records = collection.get("value")
    if not isinstance(records, list):
        raise ValueError(
            f"{collection.get('id')}: available records table data is not a collection"
        )
    rows = []
    for record in records:
        rows.append(
            [
                field_display(record, _field_name(header))
                for header in component["headers"]
            ]
        )
    return rows


def _render_llm(
    component: dict[str, Any],
    store: EvidenceStore,
    *,
    calculation_contract: dict[str, Any] | None,
    data_catalogue: dict[str, Any] | None,
) -> str:
    claims = []
    # This renderer is a deterministic zero-provider fixture. Executable runs
    # generate prose from the prompt, where context IDs are not terminal-format
    # requirements. Keeping the context fallback here makes local fixtures
    # informative without turning every available input into a required claim.
    fixture_ids = component.get("required_ids") or component.get("context_ids") or []
    for node_id in fixture_ids:
        node = store.get(node_id)
        if node_id == "dt.project.description":
            value = prose_excerpt(node)
        elif node.get("kind") == "collection" and node.get("status") == "available":
            value = _collection_summary(node)
        else:
            value = display(node)
        claims.append(
            f"{_label(node_id, contract=calculation_contract, data_catalogue=data_catalogue)} "
            f"is {value}"
        )
    if not claims:
        return "No configured evidence was available for this generated component."
    return ". ".join(claims) + "."


def _collection_summary(collection: dict[str, Any]) -> str:
    records = collection.get("records")
    if records is None and collection.get("kind") == "calculated":
        records = collection.get("value")
    records = records if isinstance(records, list) else []
    fragments = []
    for record in records:
        fields = []
        for name, field in record.get("fields", {}).items():
            if name in {"source_order"}:
                continue
            fields.append(f"{name.replace('_', ' ')} {display(field)}")
        fragments.append("; ".join(fields))
    if not fragments:
        return display(collection)
    return "; ".join(fragments)


def _field_name(header: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", header.lower()).strip("_")
    return HEADER_FIELD_ALIASES.get(header.lower(), normalized)


def _label(
    node_id: str,
    *,
    contract: dict[str, Any] | None = None,
    data_catalogue: dict[str, Any] | None = None,
) -> str:
    if node_id.startswith("calc."):
        return calculation_registry(contract)[node_id]["description"]
    payload = data_catalogue or catalogue(contract)
    item = payload.get("data", {}).get(node_id, {})
    return item.get("description") or node_id
