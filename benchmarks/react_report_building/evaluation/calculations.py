from __future__ import annotations

from typing import Any

from .alignment import aligned_tables
from .tables import (
    combine_metric_counts,
    score_aligned_cells,
    semantic_cell_score,
)


CALC_TABLE_IDS = ["scale.calculation_table", "scale.comparison_table", "risks.table"]


def score_calculations(
    candidate_tree: dict[str, Any],
    gold_tree: dict[str, Any],
    *,
    table_ids_by_section: dict[str, list[str]] | None = None,
    calculation_table_ids: list[str] | None = None,
) -> dict[str, Any]:
    candidate = aligned_tables(candidate_tree, table_ids_by_section)
    gold = aligned_tables(gold_tree, table_ids_by_section)
    details = {}
    table_metrics = {}
    all_metrics = []
    for table_id in calculation_table_ids or CALC_TABLE_IDS:
        expected = gold.get(table_id)
        if expected is None:
            continue
        observed = candidate.get(table_id)
        metrics = score_aligned_cells(
            expected["rows"],
            observed["rows"] if observed else [],
            start_column=1,
        )
        all_metrics.append(metrics)
        details[table_id] = semantic_cell_score(metrics)
        table_metrics[table_id] = metrics
    aggregate_metrics = combine_metric_counts(all_metrics)
    return {
        "score": semantic_cell_score(aggregate_metrics),
        "correct_cells": aggregate_metrics["value_correct_cells"],
        "total_cells": aggregate_metrics["value_total_cells"],
        **aggregate_metrics,
        "tables": details,
        "table_metrics": table_metrics,
    }
