from __future__ import annotations

from typing import Any

from .alignment import prf


def score_missingness(
    candidate_tree: dict[str, Any], gold_tree: dict[str, Any]
) -> dict[str, Any]:
    candidate_occurrences = [
        item["target"]
        for item in candidate_tree["links"]
        if item["target"].startswith("missing.")
    ]
    gold_occurrences = [
        item["target"]
        for item in gold_tree["links"]
        if item["target"].startswith("missing.")
    ]
    candidate = set(candidate_occurrences)
    gold = set(gold_occurrences)
    result = prf(len(candidate & gold), len(candidate), len(gold))
    return {
        "score": result["f1"],
        **result,
        "expected_missing_targets": sorted(gold),
        "observed_missing_targets": sorted(candidate),
        "expected_occurrence_count": len(gold_occurrences),
        "observed_occurrence_count": len(candidate_occurrences),
    }
