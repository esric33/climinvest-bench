"""Offline 2026-10-09 manuscript metrics over frozen reports and executable gold.

This module performs no evidence generation, LLM calls, or file writes. It uses
the repository's Markdown parser, alignment, literal citation and value checks;
its entry point never invokes the v2 evaluator's source-equivalence wrapper.
The caller must fingerprint these dependencies alongside this file.

K uses the declared calculation source, including scalar fields of calculated
collections, and never infers source identity from equal numeric values. It
uses frozen ``require_value`` obligations rather than inventing new obligations
from interpretation instructions. Available list-valued prose obligations are
reported separately: their selector/content requirements are assessed by C/R.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from benchmarks.react_report_building.evaluation.alignment import (
    align_components,
    aligned_tables,
)
from benchmarks.react_report_building.evaluation.oracle import (
    _section_text,
    oracle_section_contract,
    score_calculations_against_oracle,
    score_citations_against_oracle,
    score_missingness_against_oracle,
    score_tables_against_oracle,
    score_update_against_oracle,
)
from benchmarks.react_report_building.evaluation.report_tree import (
    parse_markdown,
    section_map,
)
from benchmarks.react_report_building.evaluation.structure import score_structure
from benchmarks.react_report_building.evaluation.tables import (
    LINK_PATTERN,
    parse_quantity,
    semantic_cell_score,
    visible,
    with_metric_accuracies,
)


POLICY_VERSION = "react_report.paper_rescore/2026-10-09-equal-weights-calc-occurrences-change-rate-v1"
DEPENDENCY_PATHS = (
    "benchmarks/react_report_building/evaluation/alignment.py",
    "benchmarks/react_report_building/evaluation/oracle.py",
    "benchmarks/react_report_building/evaluation/report_tree.py",
    "benchmarks/react_report_building/evaluation/structure.py",
    "benchmarks/react_report_building/evaluation/tables.py",
)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 1.0


def _table_layout(gold: dict[str, Any]) -> dict[str, list[str]]:
    contract = gold["evaluation_contract"]
    return contract.get("parsed_table_ids_by_section") or contract["table_ids_by_section"]


def _prose_paragraphs(tree: dict[str, Any], gold: dict[str, Any]) -> dict[str, Any]:
    sections = section_map(tree)
    output = {}
    for contract in oracle_section_contract(gold):
        section = sections.get(contract["id"], {})
        components = contract["required_components"]
        indices = align_components(components, section)["component_block_indices"]
        for component, block_index in zip(components, indices):
            if component["kind"] == "llm" and block_index is not None:
                block = section["blocks"][block_index]
                output[component["id"]] = section["paragraphs"][block["index"]]
    return output


def _calculation_id(target: str) -> str | None:
    node_id = str(target).removeprefix("missing.")
    return node_id if node_id.startswith("calc.") else None


def _occurrence_result(
    *, calculation_id: str, component_id: str, location: str,
    expected: str, observed: str | None,
    expected_target: str, observed_target: str | None,
) -> dict[str, Any]:
    expected_quantity = parse_quantity(expected)
    observed_quantity = parse_quantity(observed) if observed is not None else None
    target_matches = observed_target == expected_target
    numeric = expected_quantity is not None
    value_correct = target_matches and observed is not None and (
        observed_quantity is not None and observed_quantity[0] == expected_quantity[0]
        if numeric else visible(observed) == visible(expected)
    )
    unit_correct = bool(
        target_matches and numeric and observed_quantity is not None
        and observed_quantity[1] == expected_quantity[1]
    )
    return {
        "calculation_id": calculation_id, "component_id": component_id,
        "location": location, "expected": expected, "observed": observed,
        "expected_target": expected_target, "observed_target": observed_target,
        "numeric": numeric, "value_correct": bool(value_correct),
        "unit_correct": unit_correct if numeric else None,
    }


def _score_calculation_occurrences(tree: dict[str, Any], gold: dict[str, Any]) -> dict[str, Any]:
    """Match calculation IDs within each component, consuming each use once."""
    tables = aligned_tables(tree, _table_layout(gold))
    occurrences = []
    excluded = []
    for component_id, expected_table in gold["resolved"]["tables"].items():
        queues: dict[str, deque[tuple[str, str]]] = defaultdict(deque)
        observed_table = tables.get(component_id)
        for row in (observed_table or {}).get("rows", []):
            for cell in row[1:]:  # Identity/label cells never contribute to K.
                for match in LINK_PATTERN.finditer(str(cell)):
                    calc_id = _calculation_id(match.group(2))
                    if calc_id:
                        queues[calc_id].append((str(cell), match.group(2)))
        for row_index, row in enumerate(expected_table["rows"]):
            for column_index, cell in enumerate(row[1:], 1):
                links = [m for m in LINK_PATTERN.finditer(str(cell)) if _calculation_id(m.group(2))]
                if not links:
                    continue
                if len(links) != 1:
                    raise ValueError(f"Ambiguous calculation sources at {component_id}/{row_index}/{column_index}")
                target = links[0].group(2)
                calc_id = _calculation_id(target)
                matched = queues[calc_id].popleft() if queues[calc_id] else None
                occurrences.append(_occurrence_result(
                    calculation_id=calc_id, component_id=component_id,
                    location=f"table:{row_index}:{column_index}", expected=str(cell),
                    observed=matched[0] if matched else None, expected_target=target,
                    observed_target=matched[1] if matched else None,
                ))

    paragraphs = _prose_paragraphs(tree, gold)
    for component in gold.get("llm_obligations", []):
        component_id = component["component_id"]
        queues: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
        for link in paragraphs.get(component_id, {}).get("links", []):
            calc_id = _calculation_id(link["target"])
            if calc_id:
                queues[calc_id].append(link)
        for obligation in component.get("obligations", []):
            calc_id = _calculation_id(obligation.get("node_id", ""))
            if not obligation.get("require_value") or not calc_id:
                continue
            state = obligation.get("expected_state") or {}
            if state.get("status") == "available" and isinstance(state.get("value"), (list, dict)):
                excluded.append({"component_id": component_id, "obligation_id": obligation["id"],
                                 "calculation_id": calc_id, "reason": "available_nonscalar_result"})
                continue
            labels = obligation.get("expected_labels") or []
            if len(labels) != 1:
                raise ValueError(f"Expected one resolved scalar label for {component_id}/{obligation['id']}, got {labels!r}")
            targets = [str(t) for group in obligation.get("required_target_groups", []) for t in group]
            if len(targets) != 1 or _calculation_id(targets[0]) != calc_id:
                raise ValueError(f"Ambiguous required calculation target for {component_id}/{obligation['id']}")
            matched = queues[calc_id].popleft() if queues[calc_id] else None
            occurrences.append(_occurrence_result(
                calculation_id=calc_id, component_id=component_id,
                location=f"prose:{obligation['id']}", expected=str(labels[0]),
                observed=str(matched.get("text", "")) if matched else None,
                expected_target=targets[0], observed_target=matched["target"] if matched else None,
            ))
    counts = {
        "value_correct_cells": sum(item["value_correct"] for item in occurrences),
        "value_total_cells": len(occurrences),
        "unit_correct_cells": sum(bool(item["unit_correct"]) for item in occurrences),
        "unit_total_cells": sum(item["numeric"] for item in occurrences),
        "surface_correct_cells": sum(item["observed"] is not None and visible(item["observed"]) == visible(item["expected"]) for item in occurrences),
        "surface_total_cells": len(occurrences),
    }
    metrics = with_metric_accuracies(counts)
    return {"score": semantic_cell_score(metrics), **metrics,
            "occurrence_count": len(occurrences),
            "table_occurrence_count": sum(item["location"].startswith("table:") for item in occurrences),
            "prose_occurrence_count": sum(item["location"].startswith("prose:") for item in occurrences),
            "occurrences": occurrences, "excluded_prose_obligations": excluded}


def _score_changes(tree: dict[str, Any], baseline_tree: dict[str, Any], gold: dict[str, Any], affected: set[str]) -> dict[str, Any]:
    ids = [section["id"] for section in gold["structure"]["sections"]]
    if not affected <= set(ids):
        raise ValueError(f"Unknown affected sections: {sorted(affected - set(ids))}")
    id_map = gold["evaluation_contract"].get("section_id_map", {})
    candidate, baseline = section_map(tree), section_map(baseline_tree)
    values = {}
    for section_id in ids:
        parsed_id = id_map.get(section_id, section_id)
        old, new = baseline.get(parsed_id), candidate.get(parsed_id)
        if old is None:
            raise ValueError(f"Canonical baseline lacks required section {section_id}")
        present = new is not None
        changed = present and _section_text(new) != _section_text(old)
        preserved = present and _section_text(new) == _section_text(old)
        values[section_id] = {"affected": section_id in affected,
                              "present": present, "changed_from_t0": bool(changed),
                              "preserved_from_t0": bool(preserved)}
    return {
        "affected_section_change_rate": _mean([float(x["changed_from_t0"]) for x in values.values() if x["affected"]]),
        "unaffected_section_preservation": _mean([float(x["preserved_from_t0"]) for x in values.values() if not x["affected"]]),
        "affected_section_count": len(affected), "unaffected_section_count": len(ids) - len(affected),
        "per_section": values,
    }


def rescore_report(candidate_markdown: str, gold: dict[str, Any], *, canonical_markdown: str | None = None, affected_section_ids: set[str] | None = None) -> dict[str, Any]:
    """Recalculate deterministic metrics; semantic verdicts stay with caller.

    ``gold`` is frozen, condition-specific executable gold. A/P are returned
    under ``update`` only when both maintenance arguments are supplied. This
    function scores content, not submission acceptance; the caller applies
    the study's report-failure penalties after retaining these diagnostics.
    """
    if (canonical_markdown is None) != (affected_section_ids is None):
        raise ValueError("Supply both canonical_markdown and affected_section_ids for maintenance")
    tree = parse_markdown(candidate_markdown)
    structure = score_structure(tree, section_contract=oracle_section_contract(gold),
                                table_ids_by_section=_table_layout(gold),
                                expected_title=gold["evaluation_contract"]["expected_title"])
    tables = score_tables_against_oracle(tree, gold)
    citations = score_citations_against_oracle(tree, gold)
    legacy_calculations = score_calculations_against_oracle(tree, gold)
    missingness = score_missingness_against_oracle(tree, gold)
    historical_scores = {"structure": structure["score"], "tables": tables["score"],
                         "citations": citations["score"], "calculations": legacy_calculations["score"],
                         "missingness": missingness["score"]}
    if canonical_markdown is not None:
        old_update = score_update_against_oracle(
            tree, parse_markdown(canonical_markdown), gold,
            affected_section_ids=set(affected_section_ids),
            evaluated_components={"tables": tables, "citations": citations},
        )
        historical_scores["affected_section_correctness"] = old_update["affected_section_correctness"]
        historical_scores["unaffected_section_preservation"] = old_update["unaffected_section_preservation"]
    structure["score"] = _mean([float(structure["title_correct"]), structure["section_sequence"]["f1"],
                                structure["block_sequence"]["f1"], structure["table_presence"]["f1"]])
    for table in tables["tables"].values():
        if not table.get("missing"):
            table["score"] = _mean([float(table["headers_exact"]), table["row_sequence"]["f1"],
                                    semantic_cell_score(table), float(table["shape_exact"])])
    tables["score"] = _mean([table["score"] for table in tables["tables"].values()])
    prose = citations["prose_obligations"]
    selections = []
    for component in prose["components"].values():
        for selection in component["selected_sets"]:
            selection["score"] = (selection["f1"] + selection["order"]["f1"]) / 2
            selections.append(selection["score"])
        component["score"] = _mean([component["required_group_coverage"], component["value_accuracy"],
                                     _mean([item["score"] for item in component["selected_sets"]]), component["target_validity"]])
    prose["selected_set_score"] = _mean(selections)
    prose["score"] = _mean([prose["semantic_group_coverage"], prose["value_accuracy"],
                            prose["selected_set_score"], prose["target_validity"]])
    citations["score"] = (citations["table_citations"]["score"] + prose["score"]) / 2
    components = {"structure": structure, "tables": tables, "calculations": _score_calculation_occurrences(tree, gold),
                  "citations": citations, "missingness": missingness}
    result = {"score_policy_version": POLICY_VERSION, "gold_sha256": gold.get("gold_sha256"), "components": components,
              "details": {"source_equivalence": False, "semantic_judge_calls": 0,
                          "equal_weights": True, "calculation_prose_scope": "frozen_require_value_scalar_results",
                          "historical_helper_scores": historical_scores,
                          "failure_penalties_applied": False}}
    if canonical_markdown is not None:
        result["update"] = _score_changes(tree, parse_markdown(canonical_markdown), gold, set(affected_section_ids))
    return result
