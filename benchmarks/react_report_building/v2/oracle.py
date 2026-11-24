from __future__ import annotations

"""Executable, provider-free gold for the v2 report benchmark.

The authored Markdown reports are useful QA artefacts, but they are not an
answer key.  This module resolves the compiled document contract against one
evidence store and emits the actual answer key: the typed document structure,
the dependency DAG, exact table cells, calculated/missing states, and local
semantic obligations for each prompt-controlled component.
"""

from collections import defaultdict, deque
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable, Mapping

from ..evaluation.report_tree import parse_markdown
from ..evaluation.tables import LINK_PATTERN, display_text, parse_quantity
from ..runtime.evidence_store import EvidenceStore
from ..runtime.calculator import Calculator
from ..runtime.rendering import display
from ..runtime.rendering import calculate_all
from ..paths import NORMALIZED_ROOT
from ..util import read_json, sha256_json, write_json
from .contract import V2_ROOT
from .registry import calculation_registry
from .rendering import render_report


EXECUTABLE_GOLD_SCHEMA = "react_report.executable_gold/v1"
GOLD_POPULATION_SCHEMA = "react_report.executable_gold_population/v1"
DEFAULT_GOLD_ROOT = V2_ROOT / "data" / "gold"
VISIBLE_COMPONENT_TYPES = {"table", "llm"}
AVAILABLE_STATUSES = {"available"}


def build_executable_gold(
    store: EvidenceStore,
    *,
    contract: dict[str, Any],
    data_catalogue: dict[str, Any] | None = None,
    condition_id: str | None = None,
    obligation_specs: Mapping[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Resolve a compiled contract into a JSON-serialisable answer key.

    No provider is called and no expected prose is retained.  The deterministic
    renderer is used only to resolve the table surfaces governed by the same
    formatting contract presented to candidates.

    ``obligation_specs`` is an optional sidecar keyed by a fully-qualified
    artifact ID, ``section_id.component_id``, or short component ID.  Compiled
    artifacts may alternatively carry a ``semantic_obligations`` list.  When
    neither is present, instruction dependencies become conservative node-claim
    obligations.  That fallback keeps old contracts executable while allowing
    redesigned contracts to specify genuinely selective nuggets.
    """

    components = _visible_artifacts(contract)
    structure = _resolved_structure(contract, components)
    tables = _resolved_tables(
        store,
        contract=contract,
        data_catalogue=data_catalogue,
        components=components,
    )
    obligations = _resolved_obligations(
        store,
        contract=contract,
        components=components,
        obligation_specs=obligation_specs or {},
    )
    dag = _build_dag(contract, structure, components)
    calculations = _calculation_states(store, contract)

    relevant_ids = set()
    for artifact in components:
        relevant_ids.update(artifact.get("canonical_dependencies") or ())
        relevant_ids.update(artifact.get("data_ids") or ())
    for node in contract.get("generated_nodes", []):
        canonical_id = node.get("canonical_id")
        if canonical_id:
            relevant_ids.add(str(canonical_id))
        relevant_ids.update(node.get("canonical_dependencies") or ())
    for calculation_id, definition in calculation_registry(contract).items():
        relevant_ids.add(str(calculation_id))
        relevant_ids.update(
            str(node_id) for node_id in definition.get("input_ids", {}).values()
        )
    resolved_states = {
        node_id: _node_state(store.get(node_id))
        for node_id in sorted(relevant_ids)
    }
    missing_states = {
        node_id: state
        for node_id, state in resolved_states.items()
        if state["status"] not in AVAILABLE_STATUSES
    }
    required_missing_targets = sorted(
        set(_table_missing_targets(tables))
        | set(_obligation_missing_targets(obligations))
    )
    resolved_evidence_sha256 = sha256_json(
        {
            node_id: state
            for node_id, state in resolved_states.items()
            if not node_id.startswith("calc.")
        }
    )
    resolved_state_sha256 = sha256_json(
        {
            "states": resolved_states,
            "tables": tables,
            "calculations": calculations,
        }
    )

    payload: dict[str, Any] = {
        "schema_version": EXECUTABLE_GOLD_SCHEMA,
        "benchmark_version": contract.get("benchmark_version", "v2"),
        "project_id": str(store.project_id).upper(),
        "template_id": contract.get("template_id")
        or contract.get("contract_id"),
        "contract_id": contract.get("contract_id"),
        "contract_sha256": sha256_json(contract),
        "resolved_evidence_sha256": resolved_evidence_sha256,
        "resolved_state_sha256": resolved_state_sha256,
        "condition_id": condition_id,
        "structure": structure,
        "dag": dag,
        "resolved": {
            "tables": tables,
            "calculation_states": calculations,
            "missing_states": missing_states,
            "required_missing_targets": required_missing_targets,
        },
        "llm_obligations": obligations,
        "evaluation_contract": {
            "expected_title": _expected_title(store),
            "section_id_map": {
                section["id"]: _parser_section_id(section["title"])
                for section in structure["sections"]
            },
            "table_ids_by_section": {
                section["id"]: [
                    component["id"]
                    for component in section["components"]
                    if component["kind"] == "table"
                ]
                for section in structure["sections"]
            },
            "parsed_table_ids_by_section": {
                _parser_section_id(section["title"]): [
                    component["id"]
                    for component in section["components"]
                    if component["kind"] == "table"
                ]
                for section in structure["sections"]
            },
            "calculation_table_ids": [
                table_id
                for table_id, table in tables.items()
                if table["contains_calculations"]
            ],
            "allowed_ids": sorted(store.all_ids()),
        },
    }
    payload["gold_sha256"] = sha256_json(payload)
    return payload


def validate_executable_gold(gold: dict[str, Any]) -> list[str]:
    """Return answer-key invariant violations without requiring source files."""

    errors: list[str] = []
    if gold.get("schema_version") != EXECUTABLE_GOLD_SCHEMA:
        errors.append("unexpected executable-gold schema")
    expected_hash = gold.get("gold_sha256")
    unhashed = {key: value for key, value in gold.items() if key != "gold_sha256"}
    if expected_hash != sha256_json(unhashed):
        errors.append("executable-gold hash differs")
    for key in (
        "contract_sha256",
        "resolved_evidence_sha256",
        "resolved_state_sha256",
    ):
        value = gold.get(key)
        if not isinstance(value, str) or len(value) != 64:
            errors.append(f"executable gold lacks a valid {key}")
    dag = gold.get("dag") or {}
    if dag.get("acyclic") is not True:
        errors.append("gold dependency graph is not acyclic")
    node_ids = {item.get("id") for item in dag.get("nodes", [])}
    for edge in dag.get("edges", []):
        if edge.get("from") not in node_ids or edge.get("to") not in node_ids:
            errors.append("gold dependency graph contains a dangling edge")
            break
    sections = gold.get("structure", {}).get("sections", [])
    component_ids = [
        component.get("id")
        for section in sections
        for component in section.get("components", [])
    ]
    if len(component_ids) != len(set(component_ids)):
        errors.append("gold component IDs are not unique")
    known_components = set(component_ids)
    for obligation in gold.get("llm_obligations", []):
        if obligation.get("component_id") not in known_components:
            errors.append("gold obligation references an unknown component")
            break
    return errors


def write_resolved_gold_population(
    output_root: Path = DEFAULT_GOLD_ROOT,
    *,
    include_conditions: bool = False,
) -> dict[str, Any]:
    """Write immutable zero-provider gold manifests for all twenty projects.

    Baseline gold is always written.  ``include_conditions=True`` additionally
    resolves every frozen missingness and mutation condition; this is useful for
    a full pre-smoke audit but intentionally opt-in because the complete typed
    DAG is sizeable.
    """

    # Local imports avoid a module cycle: runner imports this module lazily only
    # from its update scorer.
    from .perturbations import (
        POPULATION_CONDITIONS_PATH,
        apply_mutation,
    )
    from .runner import resolve_runtime_context
    from .study_design import load_population

    root = Path(output_root)
    population = load_population()
    condition_manifest = (
        read_json(POPULATION_CONDITIONS_PATH) if include_conditions else None
    )
    conditions_by_project = {
        str(item["project_id"]).upper(): item
        for item in (condition_manifest or {}).get("projects", [])
    }
    project_summaries = []
    gold_count = 0
    for project_entry in population["projects"]:
        project_id = str(project_entry["project_id"]).upper()
        context = resolve_runtime_context(
            read_json(NORMALIZED_ROOT / f"{project_id.lower()}.json")
        )
        baseline_store = _calculated_gold_store(
            context.twin,
            context.reference,
            contract=context.contract,
        )
        baseline = build_executable_gold(
            baseline_store,
            contract=context.contract,
            data_catalogue=context.catalogue,
        )
        errors = validate_executable_gold(baseline)
        if errors:
            raise ValueError(f"{project_id}: invalid baseline gold: {'; '.join(errors)}")
        project_root = root / "projects" / project_id.lower()
        baseline_path = project_root / "baseline.json"
        write_json(baseline_path, baseline)
        gold_count += 1
        conditions = []
        if include_conditions:
            project_conditions = conditions_by_project.get(project_id)
            if project_conditions is None:
                raise ValueError(f"{project_id}: condition manifest entry is absent")
            for group in ("masks", "mutations"):
                for condition in project_conditions.get(group, []):
                    condition_id = str(condition["condition_id"])
                    if group == "masks":
                        condition_twin = context.twin
                        masked_ids = set(condition.get("masked_ids") or ())
                    else:
                        condition_twin = apply_mutation(context.twin, condition)
                        masked_ids = set()
                    condition_store = _calculated_gold_store(
                        condition_twin,
                        context.reference,
                        contract=context.contract,
                        masked_ids=masked_ids,
                    )
                    condition_gold = build_executable_gold(
                        condition_store,
                        contract=context.contract,
                        data_catalogue=context.catalogue,
                        condition_id=condition_id,
                    )
                    errors = validate_executable_gold(condition_gold)
                    if errors:
                        raise ValueError(
                            f"{project_id}/{condition_id}: invalid gold: "
                            + "; ".join(errors)
                        )
                    relative = Path("conditions") / f"{_safe_filename(condition_id)}.json"
                    write_json(project_root / relative, condition_gold)
                    conditions.append(
                        {
                            "condition_id": condition_id,
                            "kind": condition.get("kind"),
                            "path": str(relative),
                            "gold_sha256": condition_gold["gold_sha256"],
                        }
                    )
                    gold_count += 1
        project_summaries.append(
            {
                "project_id": project_id,
                "template_id": context.template_id,
                "baseline_path": "baseline.json",
                "baseline_gold_sha256": baseline["gold_sha256"],
                "condition_count": len(conditions),
                "conditions": conditions,
            }
        )
    manifest: dict[str, Any] = {
        "schema_version": GOLD_POPULATION_SCHEMA,
        "population_id": population.get("population_id"),
        "provider_calls": 0,
        "project_count": len(project_summaries),
        "gold_count": gold_count,
        "conditions_included": include_conditions,
        "projects": project_summaries,
    }
    manifest["manifest_sha256"] = sha256_json(manifest)
    write_json(root / "manifest.json", manifest)
    return manifest


def validate_resolved_gold_population(
    root: Path = DEFAULT_GOLD_ROOT,
    *,
    require_conditions: bool = False,
) -> list[str]:
    """Reject missing, corrupt, or stale committed executable gold files."""

    committed_root = Path(root)
    manifest_path = committed_root / "manifest.json"
    if not manifest_path.is_file():
        return ["v2 executable-gold population manifest is missing"]
    errors: list[str] = []
    try:
        committed_manifest = read_json(manifest_path)
    except (OSError, ValueError) as exc:
        return [f"v2 executable-gold manifest is unreadable: {exc}"]
    if committed_manifest.get("schema_version") != GOLD_POPULATION_SCHEMA:
        errors.append("v2 executable-gold population schema differs")
    if committed_manifest.get("project_count") != 20:
        errors.append("v2 executable gold must cover all 20 projects")
    if require_conditions and committed_manifest.get("conditions_included") is not True:
        errors.append("v2 executable gold does not include frozen conditions")
    resolve_conditions = bool(committed_manifest.get("conditions_included"))

    try:
        with tempfile.TemporaryDirectory() as directory:
            expected_root = Path(directory)
            expected_manifest = write_resolved_gold_population(
                expected_root,
                include_conditions=resolve_conditions,
            )
            if committed_manifest != expected_manifest:
                errors.append("v2 executable-gold population manifest is stale")
            expected_files = {
                path.relative_to(expected_root)
                for path in expected_root.rglob("*.json")
            }
            committed_files = {
                path.relative_to(committed_root)
                for path in committed_root.rglob("*.json")
            }
            missing_files = sorted(expected_files - committed_files)
            if missing_files:
                errors.append(
                    "v2 executable gold is missing files: "
                    + ", ".join(str(path) for path in missing_files)
                )
            unexpected_files = sorted(committed_files - expected_files)
            if unexpected_files:
                errors.append(
                    "v2 executable gold has unexpected files: "
                    + ", ".join(str(path) for path in unexpected_files)
                )
            for relative in sorted(expected_files & committed_files):
                try:
                    committed = read_json(committed_root / relative)
                    expected = read_json(expected_root / relative)
                except (OSError, ValueError) as exc:
                    errors.append(f"{relative}: executable gold is unreadable: {exc}")
                    continue
                if committed != expected:
                    errors.append(f"{relative}: executable gold is stale")
    except (OSError, TypeError, ValueError) as exc:
        errors.append(f"could not freshly resolve v2 executable gold: {exc}")
    return errors


def _calculated_gold_store(
    twin: dict[str, Any],
    reference: dict[str, Any],
    *,
    contract: dict[str, Any],
    masked_ids: set[str] | None = None,
) -> EvidenceStore:
    store = EvidenceStore(twin, reference, masked_ids=masked_ids)
    calculate_all(Calculator(store, registry=calculation_registry(contract)))
    return store


def _safe_filename(value: str) -> str:
    return re.sub(r"[^a-z0-9_.-]+", "_", value.casefold()).strip("_")


def _parser_section_id(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(title).casefold()).strip("_")


def _visible_artifacts(contract: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        (
            artifact
            for artifact in contract.get("artifacts", [])
            if artifact.get("type") in VISIBLE_COMPONENT_TYPES
            and artifact.get("section_id") != "front_matter"
        ),
        key=lambda item: int(item.get("start") or 0),
    )


def _component_id(artifact: dict[str, Any]) -> str:
    return str(artifact["id"]).rsplit(".", 1)[-1]


def _resolved_structure(
    contract: dict[str, Any],
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    by_section: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for artifact in artifacts:
        by_section[str(artifact["section_id"])].append(artifact)

    sections = []
    seen_components: set[str] = set()
    for section_index, raw_section in enumerate(
        contract.get("structure", {}).get("sections", [])
    ):
        section_id = str(raw_section.get("id") or "")
        if section_id == "front_matter":
            continue
        section_artifacts = by_section.get(section_id, [])
        component_rows = []
        for component_index, artifact in enumerate(section_artifacts):
            component_id = _component_id(artifact)
            if component_id in seen_components:
                raise ValueError(
                    f"compiled contract has duplicate visible component ID "
                    f"{component_id!r}"
                )
            seen_components.add(component_id)
            component_rows.append(
                {
                    "id": component_id,
                    "artifact_id": artifact["id"],
                    "kind": artifact["type"],
                    "title": artifact.get("title"),
                    "section_id": section_id,
                    "subsection_id": artifact.get("subsection_id") or section_id,
                    "order": component_index,
                    "contains_ids": list(
                        artifact.get("data_ids")
                        if artifact.get("type") == "table"
                        else artifact.get("instruction_dependency_ids")
                        or artifact.get("canonical_dependencies")
                        or ()
                    ),
                    **(
                        {
                            "table_type": artifact.get("table_type"),
                            "headers": deepcopy(artifact.get("headers") or []),
                        }
                        if artifact.get("type") == "table"
                        else {"prompt_field": "instructions"}
                    ),
                }
            )

        subsections = []
        for subsection_index, subsection in enumerate(
            raw_section.get("subsections") or ()
        ):
            subsection_id = str(subsection.get("id") or section_id)
            subsections.append(
                {
                    "id": subsection_id,
                    "title": subsection.get("title"),
                    "implicit": bool(subsection.get("implicit")),
                    "order": subsection_index,
                    "component_ids": [
                        row["id"]
                        for row in component_rows
                        if row["subsection_id"] == subsection_id
                    ],
                }
            )
        if not subsections:
            subsections.append(
                {
                    "id": section_id,
                    "title": raw_section.get("title"),
                    "implicit": True,
                    "order": 0,
                    "component_ids": [row["id"] for row in component_rows],
                }
            )
        sections.append(
            {
                "id": section_id,
                "title": raw_section.get("title"),
                "order": section_index,
                "subsections": subsections,
                "components": component_rows,
            }
        )
    return {
        "report": {
            "id": "report",
            "kind": "report",
            "title_source": "dt.project.title",
        },
        "sections": sections,
    }


def _resolved_tables(
    store: EvidenceStore,
    *,
    contract: dict[str, Any],
    data_catalogue: dict[str, Any] | None,
    components: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    # Rendering here is intentionally an implementation detail.  We retain only
    # table structures and cells; generated/deterministic paragraphs are dropped.
    expected_tree = parse_markdown(
        render_report(
            store,
            contract=contract,
            data_catalogue=data_catalogue,
        )
    )
    canonical_sections = [
        section
        for section in contract.get("structure", {}).get("sections", [])
        if section.get("id") != "front_matter"
    ]
    if len(canonical_sections) != len(expected_tree["sections"]):
        raise ValueError("deterministic report section count differs from contract")
    section_trees = {
        str(canonical["id"]): rendered
        for canonical, rendered in zip(canonical_sections, expected_tree["sections"])
    }
    table_artifacts_by_section: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for artifact in components:
        if artifact["type"] == "table":
            table_artifacts_by_section[str(artifact["section_id"])].append(artifact)

    output: dict[str, dict[str, Any]] = {}
    for section_id, table_artifacts in table_artifacts_by_section.items():
        observed_tables = section_trees.get(section_id, {}).get("tables", [])
        if len(observed_tables) != len(table_artifacts):
            raise ValueError(
                f"{section_id}: deterministic table count differs from contract "
                f"({len(observed_tables)} != {len(table_artifacts)})"
            )
        for artifact, rendered in zip(table_artifacts, observed_tables):
            table_id = _component_id(artifact)
            rows = deepcopy(rendered["rows"])
            typed_rows = [
                [_typed_cell(cell, store) for cell in row] for row in rows
            ]
            citation_targets = sorted(
                {
                    target
                    for row in typed_rows
                    for cell in row
                    for target in cell["citation_targets"]
                }
            )
            output[table_id] = {
                "id": table_id,
                "section_id": section_id,
                "parsed_section_id": section_trees[section_id]["id"],
                "subsection_id": artifact.get("subsection_id") or section_id,
                "headers": deepcopy(rendered["headers"]),
                "rows": rows,
                "typed_rows": typed_rows,
                "citation_obligations": {
                    "required_targets": citation_targets,
                    "allowed_targets": citation_targets,
                },
                "data_ids": deepcopy(artifact.get("data_ids") or []),
                "contains_calculations": any(
                    str(node_id).startswith("calc.")
                    for node_id in artifact.get("data_ids") or ()
                ),
            }
    return output


def _typed_cell(cell: str, store: EvidenceStore) -> dict[str, Any]:
    targets = [match.group(2) for match in LINK_PATTERN.finditer(str(cell))]
    quantity = parse_quantity(str(cell))
    state = None
    if len(targets) == 1:
        target = targets[0]
        node_id = target.removeprefix("missing.")
        state = _node_state(store.get(node_id))
    return {
        "surface": display_text(str(cell)),
        "citation_targets": targets,
        "quantity": (
            {"value": str(quantity[0]), "unit": quantity[1]}
            if quantity is not None
            else None
        ),
        "state": state,
    }


def _calculation_states(
    store: EvidenceStore, contract: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    definitions = {
        str(node["canonical_id"]): node
        for node in contract.get("generated_nodes", [])
        if node.get("canonical_id")
    }
    calculated = store.calculated()
    return {
        node_id: {
            **_node_state(node),
            "dependencies": list(
                definitions.get(node_id, {}).get("canonical_dependencies")
                or node.get("dependencies")
                or ()
            ),
            "expression": definitions.get(node_id, {}).get("expression"),
            "operation_id": node.get("operation_id"),
            "calculation_depth": definitions.get(node_id, {}).get(
                "calculation_depth"
            ),
        }
        for node_id, node in sorted(calculated.items())
    }


def _node_state(node: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(
        node.get("records")
        if node.get("kind") == "collection"
        else node.get("fields")
        if node.get("kind") == "record"
        else node.get("value")
    )
    if isinstance(value, Decimal):
        value = str(value)
    return {
        "id": node.get("id"),
        "kind": node.get("kind"),
        "status": node.get("status"),
        "value": value,
        "unit": node.get("unit"),
        **(
            {"missing_id": node["missing_id"]}
            if node.get("missing_id")
            else {}
        ),
    }


def _resolved_obligations(
    store: EvidenceStore,
    *,
    contract: dict[str, Any],
    components: list[dict[str, Any]],
    obligation_specs: Mapping[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    calculation_dependencies = {
        str(calculation_id): [
            str(node_id)
            for node_id in definition.get("input_ids", {}).values()
        ]
        for calculation_id, definition in calculation_registry(contract).items()
    }
    llm_index_by_section: dict[str, int] = defaultdict(int)
    output = []
    for artifact in components:
        if artifact["type"] != "llm":
            continue
        section_id = str(artifact["section_id"])
        component_id = _component_id(artifact)
        index = llm_index_by_section[section_id]
        llm_index_by_section[section_id] += 1
        specs, source = _component_specs(
            artifact,
            store=store,
            obligation_specs=obligation_specs,
        )
        resolved = [
            _resolve_obligation(spec, store=store)
            for spec in specs
        ]
        dependency_ids = set(
            artifact.get("instruction_dependency_ids")
            or artifact.get("canonical_dependencies")
            or ()
        )
        allowed_ids = _dependency_closure(
            dependency_ids, calculation_dependencies
        )
        for node_id in list(allowed_ids):
            allowed_ids.update(_node_descendant_ids(store.get(node_id)))
        for obligation in resolved:
            allowed_ids.update(obligation.get("allowed_citation_ids") or ())
        output.append(
            {
                "component_id": component_id,
                "artifact_id": artifact["id"],
                "section_id": section_id,
                "parsed_section_id": _parser_section_id(
                    next(
                        section["title"]
                        for section in contract["structure"]["sections"]
                        if section["id"] == section_id
                    )
                ),
                "subsection_id": artifact.get("subsection_id") or section_id,
                "paragraph_index": index,
                "spec_source": source,
                "context_ids": sorted(dependency_ids),
                "obligations": resolved,
                "allowed_citation_ids": sorted(allowed_ids),
            }
        )
    return output


def _component_specs(
    artifact: dict[str, Any],
    *,
    store: EvidenceStore,
    obligation_specs: Mapping[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], str]:
    component_id = _component_id(artifact)
    keys = (
        str(artifact["id"]),
        f"{artifact['section_id']}.{component_id}",
        component_id,
    )
    for key in keys:
        if key in obligation_specs:
            return deepcopy(obligation_specs[key]), "sidecar"
    embedded = artifact.get("semantic_obligations")
    if isinstance(embedded, list):
        return deepcopy(embedded), "compiled_contract"
    contract_id = str(artifact.get("output_contract_id") or "")
    resolver = OUTPUT_CONTRACT_RESOLVERS.get(contract_id)
    if resolver is not None:
        return resolver(artifact, store), contract_id
    # Dependencies are context, not a checklist.  Requiring every prompt input
    # was the old evaluator's core mistake and rewarded table regurgitation.
    # Unknown/legacy schemas therefore get only a small section-specific anchor
    # set and remain auditable through ``spec_source``.
    return _anchor_specs(artifact, store), "conservative_anchor_fallback"


def _dependency_ids(artifact: dict[str, Any]) -> list[str]:
    return [
        str(item)
        for item in (
            artifact.get("instruction_dependency_ids")
            or artifact.get("canonical_dependencies")
            or ()
        )
    ]


def _claims(
    node_ids: Iterable[str], *, prefix: str = "claim"
) -> list[dict[str, Any]]:
    return [
        {
            "id": f"{prefix}.{index + 1}",
            "kind": "node_claim",
            "node_id": node_id,
            "require_value": str(node_id).startswith("calc."),
        }
        for index, node_id in enumerate(dict.fromkeys(node_ids))
    ]


def _interpretive_specs(
    artifact: dict[str, Any], store: EvidenceStore
) -> list[dict[str, Any]]:
    del store
    dependencies = _dependency_ids(artifact)
    required = [
        node_id
        for node_id in dependencies
        if node_id.startswith(("calc.", "req."))
        or any(
            token in node_id.casefold()
            for token in ("status", "qualification", "evidence_gap")
        )
    ]
    required.extend(_section_anchor_ids(artifact, dependencies))
    return _claims(required, prefix="interpretation")


def _evidence_requirement_specs(
    artifact: dict[str, Any], store: EvidenceStore
) -> list[dict[str, Any]]:
    dependencies = _dependency_ids(artifact)
    required = [node_id for node_id in dependencies if node_id.startswith("req.")]
    required.extend(
        node_id
        for node_id in dependencies
        if store.get(node_id).get("status") not in AVAILABLE_STATUSES
    )
    # Status calculations determine whether a gap exists and are useful
    # deterministic anchors for evidence-request prose.
    required.extend(
        node_id
        for node_id in dependencies
        if node_id.startswith("calc.")
        and any(token in node_id.casefold() for token in ("status", "gap", "missing"))
    )
    if not required:
        # The conclusion prompt deliberately refers to its preceding tables as
        # a whole.  These fixed cross-section anchors make its minimum content
        # deterministic without turning every gap row into mandatory prose.
        required.extend(
            node_id
            for node_id in (
                "calc.funding_reconciliation_status",
                "calc.maximum_risk_priority_score",
                "calc.kpi_priority_cutoff",
                "req.financial_model",
                "req.technical_design_maturity",
                "req.environmental_social_safeguards",
            )
            if store.get(node_id).get("status") != "unknown_id"
        )
    return _claims(required, prefix="evidence_requirement")


def _executive_specs(
    artifact: dict[str, Any], store: EvidenceStore
) -> list[dict[str, Any]]:
    dependencies = _dependency_ids(artifact)
    anchors = [
        node_id
        for node_id in dependencies
        if node_id.startswith("req.")
        or any(
            token in node_id.casefold()
            for token in (
                "funding_reconciliation_status",
                "cofinance_per_gcf",
                "financing_intensity",
                "cost_per_tco2e",
                "priority_risk",
                "highest_risk",
                "priority_kpi",
                "top_kpi",
                "evidence_gap",
            )
        )
    ]
    specs = _claims(anchors, prefix="executive_anchor")
    # If selector outputs and their source collections are both in context,
    # resolve the selected records as part of the executive obligation too.
    specs.extend(
        _dynamic_selected_set_specs(
            artifact, store, domain="risk", identity_only=True
        )
    )
    specs.extend(
        _dynamic_selected_set_specs(
            artifact, store, domain="kpi", identity_only=True
        )
    )
    return _dedupe_specs(specs)


def _risk_specs(
    artifact: dict[str, Any], store: EvidenceStore
) -> list[dict[str, Any]]:
    specs = _dynamic_selected_set_specs(artifact, store, domain="risk")
    if specs:
        return [
            *specs,
            *_claims(
                _available_contract_nuggets(
                    artifact,
                    store,
                    (
                        "calc.maximum_risk_priority_score",
                        "calc.maximum_priority_risk_count",
                        "calc.scored_risk_count",
                        "calc.incomplete_risk_count",
                    ),
                ),
                prefix="risk_priority",
            ),
        ]
    unavailable = _unavailable_selector_specs(artifact, store, domain="risk")
    if unavailable:
        return unavailable
    # Fail visibly in the gold rather than reverting to "mention every risk".
    # A redesigned risk component without a resolvable priority selector is not
    # deterministically evaluable.
    raise ValueError(
        f"{_component_id(artifact)}: risk-priority output contract has no "
        "resolvable selector and priority field"
    )


def _kpi_specs(
    artifact: dict[str, Any], store: EvidenceStore
) -> list[dict[str, Any]]:
    specs = _dynamic_selected_set_specs(artifact, store, domain="kpi")
    if specs:
        return [
            *specs,
            *_claims(
                _available_contract_nuggets(
                    artifact,
                    store,
                    (
                        "calc.kpi_priority_cutoff",
                        "calc.priority_kpi_count",
                        "calc.prioritized_kpi_count",
                        "calc.available_kpi_priority_count",
                        "calc.incomplete_kpi_priority_count",
                        "calc.mrv_ready_kpi_count",
                        "calc.kpi_compatible_target_delta_count",
                    ),
                ),
                prefix="kpi_priority",
            ),
        ]
    unavailable = _unavailable_selector_specs(artifact, store, domain="kpi")
    if unavailable:
        return unavailable
    raise ValueError(
        f"{_component_id(artifact)}: KPI-priority output contract has no "
        "resolvable selector and priority field"
    )


def _unavailable_selector_specs(
    artifact: dict[str, Any],
    store: EvidenceStore,
    *,
    domain: str,
) -> list[dict[str, Any]]:
    dependencies = _dependency_ids(artifact)
    preferred_selector = (
        "calc.maximum_priority_risks"
        if domain == "risk"
        else "calc.priority_kpis"
    )
    if preferred_selector not in dependencies:
        return []
    if store.get(preferred_selector).get("status") == "available":
        return []
    diagnostic_tokens = (
        ("incomplete_risk_count", "scored_risk_count")
        if domain == "risk"
        else (
            "priority_kpi_count",
            "prioritized_kpi_count",
            "available_kpi_priority_count",
            "incomplete_kpi_priority_count",
            "kpi_priority_cutoff",
        )
    )
    required = [preferred_selector]
    required.extend(
        node_id
        for node_id in dependencies
        if any(token in node_id for token in diagnostic_tokens)
    )
    return _claims(required, prefix=f"{domain}_selection_unavailable")


def _available_contract_nuggets(
    artifact: dict[str, Any],
    store: EvidenceStore,
    preferred_ids: tuple[str, ...],
) -> list[str]:
    dependencies = set(_dependency_ids(artifact))
    return [
        node_id
        for node_id in preferred_ids
        if node_id in dependencies
        and store.get(node_id).get("status") != "unknown_id"
    ]


def _dynamic_selected_set_specs(
    artifact: dict[str, Any],
    store: EvidenceStore,
    *,
    domain: str,
    identity_only: bool = False,
) -> list[dict[str, Any]]:
    dependencies = _dependency_ids(artifact)
    collection_id = _collection_dependency(dependencies, store, domain=domain)
    if collection_id is None:
        return []
    selector_id = _selector_dependency(
        dependencies,
        store,
        collection_id=collection_id,
        domain=domain,
    )
    collection = store.get(collection_id)
    records = _record_list(collection)
    priority_field = _priority_field(records, domain=domain)
    selected_record_ids: list[str] = []
    if selector_id is None and priority_field is not None:
        selected_record_ids = _select_records_by_priority(
            records,
            priority_field=priority_field,
            top_k=1 if domain == "risk" else 2,
        )
    if selector_id is None and not selected_record_ids:
        return []

    preferred_fields = (
        ("name",)
        if identity_only and domain == "risk"
        else ("indicator",)
        if identity_only
        else ("name", priority_field, "mitigation")
        if domain == "risk"
        else (
            "indicator",
            priority_field,
            "baseline",
            "final_target",
            "verification",
        )
    )
    required_fields = [
        field
        for field in preferred_fields
        if field and any(field in record.get("fields", {}) for record in records)
    ]
    spec: dict[str, Any] = {
        "id": f"{domain}_priority_selected_set",
        "kind": "selected_set",
        "collection_id": collection_id,
        "required_fields": required_fields,
        "require_selector_support": selector_id is not None,
    }
    if selector_id is not None:
        spec["selector_id"] = selector_id
    else:
        spec["selected_record_ids"] = selected_record_ids
        spec["selection_rule"] = {
            "priority_field": priority_field,
            "top_k": 1 if domain == "risk" else 2,
            "ties_at_cutoff": "include_all",
        }
    return [spec]


def _collection_dependency(
    dependencies: list[str],
    store: EvidenceStore,
    *,
    domain: str,
) -> str | None:
    preferred = (
        ("calc.scored_risks",)
        if domain == "risk"
        else ("calc.prioritized_kpis",)
    )
    for node_id in preferred:
        if _record_list(store.get(node_id)):
            return node_id
    for node_id in dependencies:
        node = store.get(node_id)
        if _record_list(node) and domain in node_id.casefold():
            return node_id
    return None


def _selector_dependency(
    dependencies: list[str],
    store: EvidenceStore,
    *,
    collection_id: str,
    domain: str,
) -> str | None:
    records = _record_list(store.get(collection_id))
    candidates = [
        node_id
        for node_id in dependencies
        if node_id.startswith("calc.")
        and domain in node_id.casefold()
        and any(
            token in node_id.casefold()
            for token in ("selected", "highest", "maximum", "priority", "top")
        )
    ]
    # Prefer explicit set/list names over scalar score or count nodes.
    preferred_selector = (
        "calc.maximum_priority_risks"
        if domain == "risk"
        else "calc.priority_kpis"
    )
    candidates.sort(
        key=lambda node_id: (
            node_id != preferred_selector,
            not any(
                token in node_id.casefold()
                for token in ("selected_set", "selected_ids", "highest_risks", "top_kpis")
            ),
            "count" in node_id.casefold(),
            node_id,
        )
    )
    for node_id in candidates:
        try:
            selected = _selected_record_ids(store.get(node_id), records=records)
        except ValueError:
            continue
        if selected:
            return node_id
    return None


def _record_list(node: dict[str, Any]) -> list[dict[str, Any]]:
    if node.get("kind") == "collection":
        return [
            item for item in node.get("records") or () if isinstance(item, dict)
        ]
    if node.get("kind") == "calculated" and isinstance(node.get("value"), list):
        return [item for item in node["value"] if isinstance(item, dict)]
    return []


def _priority_field(
    records: list[dict[str, Any]], *, domain: str
) -> str | None:
    candidates = (
        ("priority_score", "importance_score", "risk_score")
        if domain == "risk"
        else (
            "benchmark_reporting_priority",
            "benchmark_priority",
            "reporting_priority",
            "priority_score",
            "priority",
        )
    )
    for field in candidates:
        if records and all(field in record.get("fields", {}) for record in records):
            return field
    return None


def _select_records_by_priority(
    records: list[dict[str, Any]],
    *,
    priority_field: str,
    top_k: int,
) -> list[str]:
    scored = []
    for record in records:
        field = record.get("fields", {}).get(priority_field, {})
        if field.get("status") != "available":
            continue
        try:
            score = Decimal(str(field.get("value")))
        except Exception:
            continue
        scored.append((score, str(record["id"])))
    if not scored:
        return []
    scored.sort(key=lambda item: (-item[0], item[1]))
    cutoff_index = min(top_k, len(scored)) - 1
    cutoff = scored[cutoff_index][0]
    return [record_id for score, record_id in scored if score >= cutoff]


def _anchor_specs(
    artifact: dict[str, Any], store: EvidenceStore
) -> list[dict[str, Any]]:
    del store
    dependencies = _dependency_ids(artifact)
    selected = _section_anchor_ids(artifact, dependencies)
    # Calculated statuses and explicit evidence requirements are always stronger
    # anchors than arbitrary source operands.
    selected.extend(
        node_id
        for node_id in dependencies
        if node_id.startswith("req.")
        or (
            node_id.startswith("calc.")
            and "status" in node_id.casefold()
        )
    )
    return _claims(selected, prefix="anchor")


def _section_anchor_ids(
    artifact: dict[str, Any], dependencies: list[str]
) -> list[str]:
    section = str(artifact.get("section_id") or "").casefold()
    anchors_by_section = (
        (
            "project_identification",
            ("project.code", "project.title", "project.description", "entity_name"),
        ),
        (
            "promoter",
            ("entity_name", "implementation_agency", "delivery_mechanism", "governance"),
        ),
        (
            "climate",
            ("project.description", "ghg_accounting_qualification", "hazard", "climate_rationale"),
        ),
        (
            "technical",
            ("implementation_sequence", "implementation_years", "installed_capacity", "technical"),
        ),
        (
            "cost",
            ("total_cost_usd", "gcf_financing_usd", "cofinance_usd"),
        ),
        (
            "financ",
            ("funding_reconciliation_status", "cofinance_per_gcf", "total_cost_usd"),
        ),
        (
            "impact",
            ("ghg_reduction_tco2e", "beneficiaries", "installed_capacity"),
        ),
        (
            "safeguard",
            ("environmental_social", "gender", "stakeholder"),
        ),
        (
            "mrv",
            ("monitoring_reporting_process", "verification", "baseline"),
        ),
    )
    patterns = next(
        (values for key, values in anchors_by_section if key in section),
        (),
    )
    selected: list[str] = []
    for pattern in patterns:
        match = next(
            (
                node_id
                for node_id in dependencies
                if pattern in node_id.casefold() and node_id not in selected
            ),
            None,
        )
        if match is not None:
            selected.append(match)
    return selected[:4]


def _dedupe_specs(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    seen = set()
    for spec in specs:
        identity = (
            spec.get("kind"),
            spec.get("node_id"),
            spec.get("collection_id"),
            spec.get("selector_id"),
        )
        if identity not in seen:
            seen.add(identity)
            output.append(spec)
    return output


OUTPUT_CONTRACT_RESOLVERS = {
    "benchmark.risk_priority.v1": _risk_specs,
    "benchmark.kpi_priority.v1": _kpi_specs,
    "benchmark.executive_assessment.v1": _executive_specs,
    "benchmark.evidence_requirements.v1": _evidence_requirement_specs,
    "benchmark.interpretive_assessment.v1": _interpretive_specs,
}


def _resolve_obligation(
    spec: dict[str, Any], *, store: EvidenceStore
) -> dict[str, Any]:
    kind = str(spec.get("kind") or "node_claim")
    obligation_id = str(spec.get("id") or kind)
    if kind in {"node_claim", "qualification"}:
        node_id = str(spec.get("node_id") or "")
        if not node_id:
            raise ValueError(f"{obligation_id}: node obligation lacks node_id")
        node = store.get(node_id)
        required_targets = _required_target_group(node)
        return {
            "id": obligation_id,
            "kind": kind,
            "node_id": node_id,
            "required_target_groups": [required_targets],
            "allowed_citation_ids": sorted(
                target.removeprefix("missing.") for target in required_targets
            ),
            "expected_state": _node_state(node),
            "expected_labels": _expected_labels(node),
            "require_value": bool(spec.get("require_value", kind == "node_claim")),
        }
    if kind == "citation_any":
        node_ids = [str(item) for item in spec.get("node_ids") or ()]
        if not node_ids:
            raise ValueError(f"{obligation_id}: citation_any lacks node_ids")
        group = sorted(
            {
                target
                for node_id in node_ids
                for target in _required_target_group(store.get(node_id))
            }
        )
        return {
            "id": obligation_id,
            "kind": kind,
            "node_ids": node_ids,
            "required_target_groups": [group],
            "allowed_citation_ids": sorted(
                target.removeprefix("missing.") for target in group
            ),
            "require_value": False,
        }
    if kind == "selected_set":
        return _resolve_selected_set(spec, store=store)
    raise ValueError(f"{obligation_id}: unsupported semantic obligation {kind!r}")


def _resolve_selected_set(
    spec: dict[str, Any], *, store: EvidenceStore
) -> dict[str, Any]:
    obligation_id = str(spec.get("id") or "selected_set")
    collection_id = str(spec.get("collection_id") or "")
    if not collection_id:
        raise ValueError(f"{obligation_id}: selected_set lacks collection_id")
    collection = store.get(collection_id)
    records = _record_list(collection)
    universe = [str(record["id"]) for record in records]
    selected = [str(item) for item in spec.get("selected_record_ids") or ()]
    selector_id = spec.get("selector_id")
    if not selected:
        if not selector_id:
            raise ValueError(
                f"{obligation_id}: selected_set needs selector_id or selected_record_ids"
            )
        selected = _selected_record_ids(
            store.get(str(selector_id)), records=records
        )
    unknown = sorted(set(selected) - set(universe))
    if unknown:
        raise ValueError(
            f"{obligation_id}: selector resolved records outside {collection_id}: "
            + ", ".join(unknown)
        )
    required_fields = [str(item) for item in spec.get("required_fields") or ()]
    member_groups = []
    records_by_id = {str(record["id"]): record for record in records}
    for record_id in selected:
        if required_fields:
            groups = [
                _required_target_group(
                    records_by_id[record_id].get("fields", {}).get(field)
                    or store.get(f"{record_id}.{field}")
                )
                for field in required_fields
            ]
        else:
            groups = [[record_id]]
        member_groups.append(
            {"record_id": record_id, "required_target_groups": groups}
        )
    selector_groups: list[list[str]] = []
    if selector_id and spec.get("require_selector_support", True):
        selector_groups.append(_required_target_group(store.get(str(selector_id))))
    allowed_ids = set(_node_descendant_ids(collection))
    allowed_ids.add(collection_id)
    if selector_id:
        allowed_ids.add(str(selector_id))
    return {
        "id": obligation_id,
        "kind": "selected_set",
        "selector_id": selector_id,
        "collection_id": collection_id,
        "expected_record_ids": selected,
        "universe_record_ids": universe,
        "universe_members": [
            {
                "record_id": str(record["id"]),
                "citation_ids": sorted(
                    {
                        str(record["id"]),
                        *(
                            str(field["id"])
                            for field in record.get("fields", {}).values()
                            if field.get("id")
                        ),
                    }
                ),
            }
            for record in records
        ],
        "required_fields": required_fields,
        "members": member_groups,
        "support_groups": [
            {
                "id": "selector",
                "required_target_groups": selector_groups,
            },
            *[
                {
                    "id": member["record_id"],
                    "required_target_groups": member["required_target_groups"],
                }
                for member in member_groups
            ],
        ],
        "required_target_groups": [
            *selector_groups,
            *[
                group
                for member in member_groups
                for group in member["required_target_groups"]
            ],
        ],
        "allowed_citation_ids": sorted(allowed_ids),
        "require_value": False,
    }


def _selected_record_ids(
    selector: dict[str, Any], *, records: list[dict[str, Any]]
) -> list[str]:
    raw = selector.get("records")
    if raw is None:
        raw = selector.get("value")
    items = raw if isinstance(raw, list) else [raw]
    by_id = {str(record["id"]): record for record in records}
    selected: list[str] = []
    for item in items:
        if isinstance(item, dict) and item.get("id") in by_id:
            selected.append(str(item["id"]))
            continue
        if isinstance(item, str) and item in by_id:
            selected.append(item)
            continue
        matches = [
            record_id
            for record_id, record in by_id.items()
            if _record_matches_selector_value(record, item)
        ]
        if len(matches) == 1:
            selected.append(matches[0])
    selected = list(dict.fromkeys(selected))
    if selector.get("status") == "available" and items and not selected:
        raise ValueError(
            f"selector {selector.get('id')} did not resolve stable record identities"
        )
    return selected


def _record_matches_selector_value(record: dict[str, Any], value: Any) -> bool:
    candidate = str(value or "").strip().casefold()
    if not candidate:
        return False
    for field in record.get("fields", {}).values():
        field_value = str(field.get("value") or "").strip().casefold()
        if field_value and (field_value == candidate or field_value in candidate):
            return True
    return False


def _required_target_group(node: dict[str, Any]) -> list[str]:
    node_id = str(node.get("id") or "")
    if node.get("status") not in AVAILABLE_STATUSES:
        return [f"missing.{node_id}"]
    if node.get("kind") == "collection":
        return sorted({node_id, *_node_descendant_ids(node)})
    return [node_id]


def _expected_labels(node: dict[str, Any]) -> list[str]:
    rendered = display(node)
    matches = list(LINK_PATTERN.finditer(rendered))
    return [display_text(match.group(1)) for match in matches]


def _node_descendant_ids(node: dict[str, Any]) -> set[str]:
    output: set[str] = set()
    if node.get("kind") == "collection":
        for record in node.get("records") or ():
            output.add(str(record["id"]))
            output.update(_node_descendant_ids(record))
    elif node.get("kind") == "record":
        for field in node.get("fields", {}).values():
            output.add(str(field["id"]))
    elif node.get("kind") == "calculated" and isinstance(node.get("value"), list):
        for item in node["value"]:
            if isinstance(item, dict) and item.get("id"):
                output.add(str(item["id"]))
                output.update(_node_descendant_ids(item))
    return output


def _dependency_closure(
    roots: Iterable[str], dependencies: Mapping[str, list[str]]
) -> set[str]:
    output = {str(item) for item in roots}
    pending = list(output)
    while pending:
        current = pending.pop()
        for dependency in dependencies.get(current, []):
            if dependency not in output:
                output.add(dependency)
                pending.append(dependency)
    return output


def _build_dag(
    contract: dict[str, Any],
    structure: dict[str, Any],
    components: list[dict[str, Any]],
) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {
        "document.report": {"id": "document.report", "kind": "report"}
    }
    edges: list[dict[str, str]] = []
    artifact_by_id = {artifact["id"]: artifact for artifact in components}
    for section in structure["sections"]:
        section_node = f"section.{section['id']}"
        nodes[section_node] = {
            "id": section_node,
            "kind": "section",
            "label": section.get("title"),
        }
        edges.append(
            {"from": "document.report", "to": section_node, "kind": "contains"}
        )
        for subsection in section["subsections"]:
            subsection_node = f"subsection.{section['id']}.{subsection['id']}"
            nodes[subsection_node] = {
                "id": subsection_node,
                "kind": "subsection",
                "label": subsection.get("title"),
                "implicit": bool(subsection.get("implicit")),
            }
            edges.append(
                {"from": section_node, "to": subsection_node, "kind": "contains"}
            )
        for component in section["components"]:
            component_node = f"component.{component['id']}"
            nodes[component_node] = {
                "id": component_node,
                "kind": component["kind"],
                "label": component.get("title"),
            }
            subsection_node = (
                f"subsection.{section['id']}.{component['subsection_id']}"
            )
            if subsection_node not in nodes:
                nodes[subsection_node] = {
                    "id": subsection_node,
                    "kind": "subsection",
                    "label": component["subsection_id"],
                    "implicit": True,
                }
                edges.append(
                    {"from": section_node, "to": subsection_node, "kind": "contains"}
                )
            edges.append(
                {"from": subsection_node, "to": component_node, "kind": "contains"}
            )
            artifact = artifact_by_id[component["artifact_id"]]
            dependencies = (
                artifact.get("data_ids")
                if component["kind"] == "table"
                else artifact.get("instruction_dependency_ids")
                or artifact.get("canonical_dependencies")
                or ()
            )
            for dependency in dependencies:
                dependency = str(dependency)
                _ensure_data_node(nodes, dependency)
                edges.append(
                    {"from": dependency, "to": component_node, "kind": "supports"}
                )

    registry = calculation_registry(contract)
    for calculation_id, definition in registry.items():
        calculation_id = str(calculation_id)
        _ensure_data_node(nodes, calculation_id)
        nodes[calculation_id].update(
            label=definition.get("description"),
            expression=definition.get("expression"),
            operation_id=definition.get("operation_id"),
            calculation_depth=definition.get("calculation_depth"),
        )
        for dependency in definition.get("input_ids", {}).values():
            dependency = str(dependency)
            _ensure_data_node(nodes, dependency)
            edges.append(
                {"from": dependency, "to": calculation_id, "kind": "calculates"}
            )

    unique_edges = []
    seen_edges = set()
    for edge in edges:
        identity = (edge["from"], edge["to"], edge["kind"])
        if identity not in seen_edges:
            seen_edges.add(identity)
            unique_edges.append(edge)
    acyclic, topological_order = _topological_order(nodes, unique_edges)
    return {
        "nodes": [nodes[node_id] for node_id in sorted(nodes)],
        "edges": unique_edges,
        "acyclic": acyclic,
        "topological_order": topological_order,
    }


def _ensure_data_node(nodes: dict[str, dict[str, Any]], node_id: str) -> None:
    if node_id in nodes:
        return
    kind = (
        "calculation"
        if node_id.startswith("calc.")
        else "requirement"
        if node_id.startswith("req.")
        else "reference"
        if node_id.startswith("reference.")
        else "evidence"
    )
    nodes[node_id] = {"id": node_id, "kind": kind}


def _topological_order(
    nodes: Mapping[str, Any], edges: list[dict[str, str]]
) -> tuple[bool, list[str]]:
    indegree = {node_id: 0 for node_id in nodes}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        source, target = edge["from"], edge["to"]
        outgoing[source].append(target)
        indegree[target] += 1
    queue = deque(sorted(node_id for node_id, degree in indegree.items() if degree == 0))
    order = []
    while queue:
        node_id = queue.popleft()
        order.append(node_id)
        for target in sorted(outgoing[node_id]):
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    return len(order) == len(nodes), order


def _expected_title(store: EvidenceStore) -> str:
    node = store.get("dt.project.title")
    return str(node.get("value") or "") if node.get("status") == "available" else ""


def _table_missing_targets(tables: Mapping[str, dict[str, Any]]) -> Iterable[str]:
    for table in tables.values():
        for row in table.get("typed_rows", []):
            for cell in row:
                for target in cell.get("citation_targets") or ():
                    if str(target).startswith("missing."):
                        yield str(target)


def _obligation_missing_targets(
    obligations: list[dict[str, Any]],
) -> Iterable[str]:
    for component in obligations:
        for obligation in component.get("obligations", []):
            for group in obligation.get("required_target_groups", []):
                for target in group:
                    if str(target).startswith("missing."):
                        yield str(target)
