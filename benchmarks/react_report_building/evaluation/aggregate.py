from __future__ import annotations

from typing import Any


DEFAULT_WEIGHTS = {
    "structure": 0.20,
    "tables": 0.25,
    "citations": 0.20,
    "calculations": 0.25,
    "missingness": 0.10,
}


def aggregate_scores(
    components: dict[str, dict[str, Any]],
    *,
    weights: dict[str, float] | None = None,
) -> float:
    selected = weights or DEFAULT_WEIGHTS
    denominator = sum(selected.values())
    return (
        sum(float(components[name]["score"]) * weight for name, weight in selected.items())
        / denominator
    )

