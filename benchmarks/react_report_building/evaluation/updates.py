from __future__ import annotations

from typing import Any

from .report_tree import section_map


def score_update(
    candidate_tree: dict[str, Any],
    expected_tree: dict[str, Any],
    original_tree: dict[str, Any],
    *,
    affected_section_ids: set[str],
    section_actions: dict[str, str] | None = None,
) -> dict[str, Any]:
    candidate = section_map(candidate_tree)
    expected = section_map(expected_tree)
    original = section_map(original_tree)
    section_ids = set(expected) | set(original)
    affected_correct = 0
    unaffected_preserved = 0
    affected_total = 0
    unaffected_total = 0
    per_section: dict[str, dict[str, Any]] = {}
    for section_id in sorted(section_ids):
        candidate_section = candidate.get(section_id)
        expected_section = expected.get(section_id)
        original_section = original.get(section_id)
        candidate_text = _section_text(candidate_section)
        expected_text = _section_text(expected_section)
        original_text = _section_text(original_section)
        is_affected = section_id in affected_section_ids
        content_correct = (
            candidate_text == expected_text
            if is_affected
            else candidate_text == original_text
        )
        per_section[section_id] = {
            "affected": is_affected,
            "content_correct": content_correct,
            "changed_from_t0": candidate_text != original_text,
        }
        if is_affected:
            affected_total += 1
            affected_correct += candidate_text == expected_text
        else:
            unaffected_total += 1
            unaffected_preserved += candidate_text == original_text
    routing = None
    if section_actions is not None:
        normalized_actions = {
            section_id: _normalized_action(section_actions.get(section_id))
            for section_id in section_ids
        }
        true_replace = sum(
            normalized_actions.get(section_id) == "rewrite"
            for section_id in affected_section_ids
        )
        false_replace = sum(
            normalized_actions.get(section_id) == "rewrite"
            for section_id in section_ids - affected_section_ids
        )
        true_retain = sum(
            normalized_actions.get(section_id) == "retain"
            for section_id in section_ids - affected_section_ids
        )
        explicit = sum(
            action in {"retain", "rewrite"}
            for action in normalized_actions.values()
        )
        invalid_or_missing = sorted(
            section_id
            for section_id, action in normalized_actions.items()
            if action not in {"retain", "rewrite"}
        )
        affected_recall = (
            true_replace / len(affected_section_ids)
            if affected_section_ids
            else 1.0
        )
        unnecessary_rate = (
            false_replace / len(section_ids - affected_section_ids)
            if section_ids - affected_section_ids
            else 0.0
        )
        unaffected_retain_rate = (
            true_retain / len(section_ids - affected_section_ids)
            if section_ids - affected_section_ids
            else 1.0
        )
        routing = {
            "affected_section_recall": affected_recall,
            "unnecessary_regeneration_rate": unnecessary_rate,
            "unaffected_section_retain_rate": unaffected_retain_rate,
            "decision_coverage": explicit / len(section_ids) if section_ids else 1.0,
            "explicit_decision_count": explicit,
            "expected_decision_count": len(section_ids),
            "invalid_or_missing_section_ids": invalid_or_missing,
            "all_and_only_routing_correct": (
                explicit == len(section_ids)
                and affected_recall == 1.0
                and unnecessary_rate == 0.0
            ),
        }
    direct = affected_correct / affected_total if affected_total else 1.0
    preservation = (
        unaffected_preserved / unaffected_total if unaffected_total else 1.0
    )
    return {
        "score": (direct + preservation) / 2,
        "affected_section_correctness": direct,
        "unaffected_section_preservation": preservation,
        "affected_section_count": affected_total,
        "unaffected_section_count": unaffected_total,
        "all_affected_content_correct": affected_correct == affected_total,
        "all_unaffected_content_preserved": (
            unaffected_preserved == unaffected_total
        ),
        "all_and_only_content_correct": (
            affected_correct == affected_total
            and unaffected_preserved == unaffected_total
        ),
        "routing": routing,
        "per_section": per_section,
    }


def _section_text(section: dict[str, Any] | None) -> str | None:
    if section is None:
        return None
    return str(
        {
            "heading": section["heading"],
            "headings": section["headings"],
            "tables": section["tables"],
            "paragraphs": section["paragraphs"],
        }
    )


def _normalized_action(value: Any) -> str | None:
    if value in {"keep", "retain"}:
        return "retain"
    if value in {"replace", "rewrite"}:
        return "rewrite"
    return None
