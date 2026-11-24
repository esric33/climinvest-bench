from __future__ import annotations

"""Scoring against a typed executable gold, never reference prose."""

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .alignment import align_components, aligned_tables, lcs_length, prf
from .tables import (
    LINK_PATTERN,
    combine_metric_counts,
    display_text,
    parse_quantity,
    row_identity,
    score_aligned_cells,
    semantic_cell_score,
)
from .report_tree import section_map


def oracle_section_contract(gold: dict[str, Any]) -> list[dict[str, Any]]:
    """Project typed structure into the existing structural scorer contract."""

    output = []
    section_id_map = gold["evaluation_contract"].get("section_id_map", {})
    for section in gold["structure"]["sections"]:
        subsection_by_id = {
            item["id"]: item for item in section.get("subsections", [])
        }
        emitted_subsections: set[str] = set()
        required_components = []
        for component in section.get("components", []):
            subsection_id = component.get("subsection_id")
            subsection = subsection_by_id.get(subsection_id)
            if (
                subsection
                and not subsection.get("implicit")
                and subsection_id not in emitted_subsections
            ):
                required_components.append(
                    {"kind": "subsection", "heading": subsection.get("title")}
                )
                emitted_subsections.add(str(subsection_id))
            required_components.append(
                {
                    "id": component["id"],
                    "kind": component["kind"],
                    "title": component.get("title"),
                    **(
                        {"headers": component.get("headers", [])}
                        if component["kind"] == "table"
                        else {}
                    ),
                }
            )
        output.append(
            {
                "id": section_id_map.get(section["id"], section["id"]),
                "canonical_id": section["id"],
                "heading": section["title"],
                "required_components": required_components,
            }
        )
    return output


def score_tables_against_oracle(
    candidate_tree: dict[str, Any], gold: dict[str, Any]
) -> dict[str, Any]:
    table_layout = _parsed_table_layout(gold)
    candidate = aligned_tables(candidate_tree, table_layout)
    expected_tables = gold["resolved"]["tables"]
    details: dict[str, Any] = {}
    scores = []
    all_metrics = []
    for table_id in _ordered_table_ids(table_layout):
        expected = expected_tables[table_id]
        observed = candidate.get(table_id)
        observed_rows = observed["rows"] if observed is not None else []
        metrics = score_aligned_cells(expected["rows"], observed_rows)
        all_metrics.append(metrics)
        if observed is None:
            details[table_id] = {
                "score": 0.0,
                "missing": True,
                "cell_accuracy": metrics["table_surface_format_accuracy"],
                **metrics,
            }
            scores.append(0.0)
            continue
        headers_exact = observed["headers"] == expected["headers"]
        expected_keys = [row_identity(row) for row in expected["rows"] if row]
        observed_keys = [row_identity(row) for row in observed_rows if row]
        row_sequence = prf(
            lcs_length(expected_keys, observed_keys),
            len(observed_keys),
            len(expected_keys),
        )
        shape_exact = (
            len(observed_rows) == len(expected["rows"])
            and all(len(row) == len(expected["headers"]) for row in observed_rows)
        )
        score = (
            float(headers_exact) * 0.2
            + row_sequence["f1"] * 0.25
            + semantic_cell_score(metrics) * 0.45
            + float(shape_exact) * 0.1
        )
        details[table_id] = {
            "score": score,
            "headers_exact": headers_exact,
            "row_sequence": row_sequence,
            "cell_accuracy": metrics["table_surface_format_accuracy"],
            "shape_exact": shape_exact,
            **metrics,
        }
        scores.append(score)
    aggregate = combine_metric_counts(all_metrics)
    return {
        "score": sum(scores) / len(scores) if scores else 1.0,
        **aggregate,
        "tables": details,
    }


def score_calculations_against_oracle(
    candidate_tree: dict[str, Any], gold: dict[str, Any]
) -> dict[str, Any]:
    table_layout = _parsed_table_layout(gold)
    candidate = aligned_tables(candidate_tree, table_layout)
    expected_tables = gold["resolved"]["tables"]
    details: dict[str, float] = {}
    table_metrics: dict[str, Any] = {}
    all_metrics = []
    for table_id in gold["evaluation_contract"]["calculation_table_ids"]:
        expected = expected_tables[table_id]
        observed = candidate.get(table_id)
        metrics = score_aligned_cells(
            expected["rows"],
            observed["rows"] if observed else [],
            start_column=1,
        )
        all_metrics.append(metrics)
        details[table_id] = semantic_cell_score(metrics)
        table_metrics[table_id] = metrics
    aggregate = combine_metric_counts(all_metrics)
    return {
        "score": semantic_cell_score(aggregate),
        "correct_cells": aggregate["value_correct_cells"],
        "total_cells": aggregate["value_total_cells"],
        **aggregate,
        "tables": details,
        "table_metrics": table_metrics,
    }


def score_citations_against_oracle(
    candidate_tree: dict[str, Any], gold: dict[str, Any]
) -> dict[str, Any]:
    """Score exact table citations and local prose support obligations.

    Prose wording is never compared.  A paragraph may be freely paraphrased as
    long as it cites the required nugget/support groups and, for selected sets,
    identifies exactly the deterministically selected records.
    """

    table_result = _score_table_citations(candidate_tree, gold)
    prose_result = _score_prose_obligations(candidate_tree, gold)
    return {
        "score": table_result["score"] * 0.4 + prose_result["score"] * 0.6,
        "table_citations": table_result,
        "prose_obligations": prose_result,
        "coverage": prose_result["coverage"],
        "target_validity": prose_result["target_validity"],
        "invalid_targets": prose_result["invalid_targets"],
    }


def score_missingness_against_oracle(
    candidate_tree: dict[str, Any], gold: dict[str, Any]
) -> dict[str, Any]:
    expected_occurrences = list(
        gold["resolved"].get("required_missing_targets") or ()
    )
    observed_occurrences = [
        link["target"]
        for link in candidate_tree["links"]
        if str(link["target"]).startswith("missing.")
    ]
    expected, observed = set(expected_occurrences), set(observed_occurrences)
    result = prf(len(expected & observed), len(observed), len(expected))
    return {
        "score": result["f1"],
        **result,
        "expected_missing_targets": sorted(expected),
        "observed_missing_targets": sorted(observed),
        "expected_occurrence_count": len(expected_occurrences),
        "observed_occurrence_count": len(observed_occurrences),
    }


def score_update_against_oracle(
    candidate_tree: dict[str, Any],
    original_tree: dict[str, Any],
    gold: dict[str, Any],
    *,
    affected_section_ids: set[str],
    evaluated_components: dict[str, dict[str, Any]],
    section_actions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Score affected sections semantically and preserve unaffected T0 bytes.

    Affected prose is intentionally not compared with deterministic prose.
    Unaffected sections still have a strong all-and-only update invariant: their
    parsed content must be exactly the candidate's supplied T0 content.
    """

    candidate = section_map(candidate_tree)
    original = section_map(original_tree)
    section_ids = [section["id"] for section in gold["structure"]["sections"]]
    section_id_map = gold["evaluation_contract"].get("section_id_map", {})
    unknown = sorted(set(affected_section_ids) - set(section_ids))
    if unknown:
        raise ValueError(
            "update oracle received unknown affected sections: " + ", ".join(unknown)
        )
    table_to_section = {
        table_id: table["section_id"]
        for table_id, table in gold["resolved"]["tables"].items()
    }
    component_to_section = {
        component["component_id"]: component["section_id"]
        for component in gold.get("llm_obligations", [])
    }
    table_scores: dict[str, list[float]] = defaultdict(list)
    for table_id, detail in evaluated_components["tables"].get("tables", {}).items():
        table_scores[table_to_section[table_id]].append(float(detail["score"]))
    prose_scores: dict[str, list[float]] = defaultdict(list)
    prose_details = evaluated_components["citations"].get(
        "prose_obligations", {}
    ).get("components", {})
    for component_id, detail in prose_details.items():
        prose_scores[component_to_section[component_id]].append(float(detail["score"]))

    affected_values = []
    unaffected_values = []
    per_section: dict[str, dict[str, Any]] = {}
    for section_id in section_ids:
        is_affected = section_id in affected_section_ids
        parsed_section_id = section_id_map.get(section_id, section_id)
        candidate_section = candidate.get(parsed_section_id)
        original_section = original.get(parsed_section_id)
        changed = _section_text(candidate_section) != _section_text(original_section)
        if is_affected:
            parts = [*table_scores.get(section_id, []), *prose_scores.get(section_id, [])]
            semantic_score = (
                sum(parts) / len(parts)
                if parts
                else float(candidate_section is not None)
            )
            affected_values.append(semantic_score)
            content_correct = semantic_score == 1.0
            per_section[section_id] = {
                "affected": True,
                "content_correct": content_correct,
                "semantic_score": semantic_score,
                "changed_from_t0": changed,
            }
        else:
            preserved = _section_text(candidate_section) == _section_text(original_section)
            unaffected_values.append(float(preserved))
            per_section[section_id] = {
                "affected": False,
                "content_correct": preserved,
                "preserved_from_t0": preserved,
                "changed_from_t0": changed,
            }

    direct = (
        sum(affected_values) / len(affected_values) if affected_values else 1.0
    )
    preservation = (
        sum(unaffected_values) / len(unaffected_values) if unaffected_values else 1.0
    )
    routing = _score_routing(
        section_ids,
        affected_section_ids=affected_section_ids,
        section_actions=section_actions,
    )
    return {
        "score": (direct + preservation) / 2,
        "affected_section_correctness": direct,
        "unaffected_section_preservation": preservation,
        "affected_section_count": len(affected_values),
        "unaffected_section_count": len(unaffected_values),
        "all_affected_content_correct": all(value == 1.0 for value in affected_values),
        "all_unaffected_content_preserved": all(
            value == 1.0 for value in unaffected_values
        ),
        "all_and_only_content_correct": (
            all(value == 1.0 for value in affected_values)
            and all(value == 1.0 for value in unaffected_values)
        ),
        "routing": routing,
        "per_section": per_section,
    }


def _score_routing(
    section_ids: list[str],
    *,
    affected_section_ids: set[str],
    section_actions: dict[str, str] | None,
) -> dict[str, Any] | None:
    if section_actions is None:
        return None
    normalized = {
        section_id: _normalized_action(section_actions.get(section_id))
        for section_id in section_ids
    }
    unaffected = set(section_ids) - affected_section_ids
    true_rewrite = sum(normalized[item] == "rewrite" for item in affected_section_ids)
    false_rewrite = sum(normalized[item] == "rewrite" for item in unaffected)
    true_retain = sum(normalized[item] == "retain" for item in unaffected)
    explicit = sum(value in {"retain", "rewrite"} for value in normalized.values())
    recall = true_rewrite / len(affected_section_ids) if affected_section_ids else 1.0
    unnecessary = false_rewrite / len(unaffected) if unaffected else 0.0
    return {
        "affected_section_recall": recall,
        "unnecessary_regeneration_rate": unnecessary,
        "unaffected_section_retain_rate": (
            true_retain / len(unaffected) if unaffected else 1.0
        ),
        "decision_coverage": explicit / len(section_ids) if section_ids else 1.0,
        "explicit_decision_count": explicit,
        "expected_decision_count": len(section_ids),
        "invalid_or_missing_section_ids": sorted(
            section_id
            for section_id, value in normalized.items()
            if value not in {"retain", "rewrite"}
        ),
        "all_and_only_routing_correct": (
            explicit == len(section_ids) and recall == 1.0 and unnecessary == 0.0
        ),
    }


def _normalized_action(value: Any) -> str | None:
    if value in {"keep", "retain"}:
        return "retain"
    if value in {"replace", "rewrite"}:
        return "rewrite"
    return None


def _section_text(section: dict[str, Any] | None) -> str | None:
    if section is None:
        return None
    return str(
        {
            "heading": section["heading"],
            # Earlier edits move otherwise unchanged subsections. Their source
            # positions are parser metadata, not part of the preserved content.
            "headings": [
                {key: value for key, value in heading.items() if key != "line"}
                for heading in section["headings"]
            ],
            "tables": section["tables"],
            "paragraphs": section["paragraphs"],
        }
    )


def _score_table_citations(
    candidate_tree: dict[str, Any], gold: dict[str, Any]
) -> dict[str, Any]:
    table_layout = _parsed_table_layout(gold)
    candidate = aligned_tables(candidate_tree, table_layout)
    expected_tables = gold["resolved"]["tables"]
    expected_count = 0
    observed_count = 0
    matches = 0
    details = {}
    for table_id in _ordered_table_ids(table_layout):
        expected = expected_tables[table_id]
        observed = candidate.get(table_id)
        observed_rows = observed["rows"] if observed else []
        expected_by_key = {
            row_identity(row): row for row in expected["rows"] if row
        }
        observed_by_key = {
            row_identity(row): row for row in observed_rows if row
        }
        table_expected = table_observed = table_matches = 0
        for key, expected_row in expected_by_key.items():
            observed_row = observed_by_key.get(key, [])
            for index, expected_cell in enumerate(expected_row):
                expected_targets = _cell_targets(expected_cell)
                observed_targets = (
                    _cell_targets(observed_row[index])
                    if index < len(observed_row)
                    else []
                )
                table_expected += len(expected_targets)
                table_observed += len(observed_targets)
                table_matches += len(
                    set(expected_targets) & set(observed_targets)
                )
        result = prf(table_matches, table_observed, table_expected)
        details[table_id] = {**result, "score": result["f1"]}
        expected_count += table_expected
        observed_count += table_observed
        matches += table_matches
    aggregate = prf(matches, observed_count, expected_count)
    return {"score": aggregate["f1"], **aggregate, "tables": details}


def _score_prose_obligations(
    candidate_tree: dict[str, Any], gold: dict[str, Any]
) -> dict[str, Any]:
    sections = {section["id"]: section for section in candidate_tree["sections"]}
    aligned_paragraphs: dict[str, dict[str, Any]] = {}
    for section_contract in oracle_section_contract(gold):
        section = sections.get(section_contract["id"], {})
        required_components = section_contract["required_components"]
        alignment = align_components(required_components, section)
        for component, block_index in zip(
            required_components, alignment["component_block_indices"]
        ):
            if component["kind"] == "llm" and block_index is not None:
                block = section["blocks"][block_index]
                aligned_paragraphs[component["id"]] = section["paragraphs"][block["index"]]
    total_groups = matched_groups = 0
    total_value_claims = correct_value_claims = 0
    allowed_target_count = observed_target_count = 0
    invalid_targets: set[str] = set()
    selected_scores = []
    components = {}

    for component in gold.get("llm_obligations", []):
        paragraph = aligned_paragraphs.get(
            component["component_id"], {"text": "", "links": []}
        )
        links = paragraph.get("links", [])
        observed_targets = {str(link["target"]) for link in links}
        locally_allowed = set(component.get("allowed_citation_ids") or ())
        locally_allowed_missing = {f"missing.{item}" for item in locally_allowed}
        valid_targets = locally_allowed | locally_allowed_missing
        invalid = observed_targets - valid_targets
        invalid_targets.update(invalid)
        observed_target_count += len(observed_targets)
        allowed_target_count += len(observed_targets) - len(invalid)

        component_groups = component_matches = 0
        component_values = component_correct_values = 0
        component_selected = []
        for obligation in component.get("obligations", []):
            groups = obligation.get("required_target_groups") or []
            component_groups += len(groups)
            for group in groups:
                if observed_targets & set(group):
                    component_matches += 1
            if obligation.get("require_value"):
                component_values += 1
                if _value_obligation_correct(obligation, links):
                    component_correct_values += 1
            if obligation.get("kind") == "selected_set":
                selected = _selected_set_score(
                    obligation,
                    observed_targets,
                    [str(link["target"]) for link in links],
                )
                component_selected.append(selected)
                selected_scores.append(selected["score"])

        total_groups += component_groups
        matched_groups += component_matches
        total_value_claims += component_values
        correct_value_claims += component_correct_values
        coverage = (
            component_matches / component_groups if component_groups else 1.0
        )
        value_accuracy = (
            component_correct_values / component_values
            if component_values
            else 1.0
        )
        selection_score = (
            sum(item["score"] for item in component_selected)
            / len(component_selected)
            if component_selected
            else 1.0
        )
        validity = (
            (len(observed_targets) - len(invalid)) / len(observed_targets)
            if observed_targets
            else (1.0 if not component_groups else 0.0)
        )
        components[component["component_id"]] = {
            "score": (
                coverage * 0.55
                + value_accuracy * 0.15
                + selection_score * 0.2
                + validity * 0.1
            ),
            "required_group_coverage": coverage,
            "matched_group_count": component_matches,
            "required_group_count": component_groups,
            "value_accuracy": value_accuracy,
            "selected_sets": component_selected,
            "target_validity": validity,
            "invalid_targets": sorted(invalid),
            "paragraph_present": component["component_id"] in aligned_paragraphs,
        }

    coverage = matched_groups / total_groups if total_groups else 1.0
    value_accuracy = (
        correct_value_claims / total_value_claims if total_value_claims else 1.0
    )
    selection_score = (
        sum(selected_scores) / len(selected_scores) if selected_scores else 1.0
    )
    target_validity = (
        allowed_target_count / observed_target_count
        if observed_target_count
        else (1.0 if total_groups == 0 else 0.0)
    )
    score = (
        coverage * 0.55
        + value_accuracy * 0.15
        + selection_score * 0.2
        + target_validity * 0.1
    )
    return {
        "score": score,
        "coverage": {
            "precision": target_validity,
            "recall": coverage,
            "f1": (
                2 * target_validity * coverage / (target_validity + coverage)
                if target_validity + coverage
                else 0.0
            ),
        },
        "semantic_group_coverage": coverage,
        "matched_group_count": matched_groups,
        "required_group_count": total_groups,
        "value_accuracy": value_accuracy,
        "selected_set_score": selection_score,
        "target_validity": target_validity,
        "invalid_targets": sorted(invalid_targets),
        "components": components,
    }


def _value_obligation_correct(
    obligation: dict[str, Any], links: list[dict[str, Any]]
) -> bool:
    groups = obligation.get("required_target_groups") or []
    targets = {target for group in groups for target in group}
    matching = [link for link in links if link.get("target") in targets]
    if not matching:
        return False
    state = obligation.get("expected_state") or {}
    if state.get("status") != "available":
        return any(str(link.get("target", "")).startswith("missing.") for link in matching)
    value = state.get("value")
    if not isinstance(value, (int, float, Decimal)) or isinstance(value, bool):
        # Citation support is deterministic; unrestricted natural-language
        # equivalence for categorical/text values belongs to the judge metric.
        return True
    expected_quantities = [
        quantity
        for label in obligation.get("expected_labels") or ()
        if (quantity := parse_quantity(str(label))) is not None
    ]
    if not expected_quantities:
        try:
            expected_quantities = [
                (Decimal(str(value)), str(state.get("unit") or ""))
            ]
        except InvalidOperation:
            return True
    for link in matching:
        quantity = parse_quantity(str(link.get("text") or ""))
        if quantity is not None and any(
            quantity[0] == expected[0]
            and (not expected[1] or quantity[1] == expected[1])
            for expected in expected_quantities
        ):
            return True
    return False


def _selected_set_score(
    obligation: dict[str, Any],
    observed_targets: set[str],
    observed_target_sequence: list[str],
) -> dict[str, Any]:
    universe = set(obligation.get("universe_record_ids") or ())
    expected = set(obligation.get("expected_record_ids") or ())
    member_targets = {
        str(member["record_id"]): set(member.get("citation_ids") or ())
        for member in obligation.get("universe_members") or ()
    }
    observed = {
        record_id
        for record_id in universe
        if any(
            target in member_targets.get(record_id, set())
            or target == record_id
            or target == f"missing.{record_id}"
            or target.startswith(f"{record_id}.")
            or target.startswith(f"missing.{record_id}.")
            or target.removeprefix("missing.")
            in member_targets.get(record_id, set())
            for target in observed_targets
        )
    }
    result = prf(len(expected & observed), len(observed), len(expected))
    observed_order = []
    for target in observed_target_sequence:
        record_id = next(
            (
                candidate
                for candidate in obligation.get("universe_record_ids") or ()
                if target in member_targets.get(candidate, set())
                or target == candidate
                or target.startswith(f"{candidate}.")
                or target.removeprefix("missing.")
                in member_targets.get(candidate, set())
            ),
            None,
        )
        if record_id is not None and record_id not in observed_order:
            observed_order.append(record_id)
    expected_order = list(obligation.get("expected_record_ids") or ())
    order = prf(
        lcs_length(expected_order, observed_order),
        len(observed_order),
        len(expected_order),
    )
    return {
        **result,
        "score": result["f1"] * 0.8 + order["f1"] * 0.2,
        "order": order,
        "expected_record_ids": sorted(expected),
        "observed_record_ids": sorted(observed),
        "expected_record_order": expected_order,
        "observed_record_order": observed_order,
        "missing_record_ids": sorted(expected - observed),
        "extra_record_ids": sorted(observed - expected),
    }


def _cell_targets(cell: str) -> list[str]:
    return [match.group(2) for match in LINK_PATTERN.finditer(str(cell))]


def _ordered_table_ids(layout: Mapping[str, list[str]]) -> list[str]:
    return [table_id for table_ids in layout.values() for table_id in table_ids]


def _parsed_table_layout(gold: dict[str, Any]) -> dict[str, list[str]]:
    evaluation = gold["evaluation_contract"]
    return evaluation.get("parsed_table_ids_by_section") or evaluation[
        "table_ids_by_section"
    ]
