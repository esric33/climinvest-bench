from __future__ import annotations

from collections import Counter
from typing import Any

from .alignment import prf


def score_citations(
    candidate_tree: dict[str, Any],
    gold_tree: dict[str, Any],
    *,
    allowed_ids: set[str],
) -> dict[str, Any]:
    candidate_targets = [item["target"] for item in candidate_tree["links"]]
    gold_targets = [item["target"] for item in gold_tree["links"]]
    candidate_counter = Counter(candidate_targets)
    gold_counter = Counter(gold_targets)
    matches = sum(
        min(candidate_counter[target], count)
        for target, count in gold_counter.items()
    )
    coverage = prf(matches, len(candidate_targets), len(gold_targets))
    valid = sum(
        target in allowed_ids or target.startswith("missing.")
        for target in candidate_targets
    )
    validity = valid / len(candidate_targets) if candidate_targets else 0.0
    return {
        "score": coverage["f1"] * 0.7 + validity * 0.3,
        "coverage": coverage,
        "target_validity": validity,
        "invalid_targets": sorted(
            {target for target in candidate_targets if target not in allowed_ids and not target.startswith("missing.")}
        ),
    }

