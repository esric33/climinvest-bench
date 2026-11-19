from __future__ import annotations

import re
from html import unescape
from decimal import Decimal, InvalidOperation
from typing import Any

from .alignment import aligned_tables, lcs_length, prf


LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
QUANTITY_PATTERN = re.compile(
    r"^(?:(?P<prefix>US\$|\$|€|£)\s*)?"
    r"(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"\s*(?P<suffix>.*)$"
)


def visible(value: str) -> str:
    return display_text(value).casefold()


def row_identity(row: list[str]) -> str:
    """Return a stable row key, preserving duplicate visible record names."""

    if not row:
        return ""
    match = LINK_PATTERN.search(str(row[0]))
    if match is not None:
        return f"citation:{match.group(2)}"
    return f"visible:{visible(row[0])}"


def display_text(value: str) -> str:
    """Return normalized visible cell text while preserving surface casing."""

    return unescape(" ".join(LINK_PATTERN.sub(r"\1", str(value)).split()))


def parse_quantity(value: str) -> tuple[Decimal, str] | None:
    """Parse one complete numeric quantity without converting units or scale."""

    match = QUANTITY_PATTERN.fullmatch(display_text(value))
    if match is None:
        return None
    try:
        number = Decimal(match.group("number").replace(",", ""))
    except InvalidOperation:
        return None
    unit_parts = [
        part.strip()
        for part in (match.group("prefix") or "", match.group("suffix") or "")
        if part.strip()
    ]
    return number, " ".join(unit_parts)


def score_aligned_cells(
    expected_rows: list[list[str]],
    observed_rows: list[list[str]],
    *,
    start_column: int = 0,
) -> dict[str, Any]:
    """Compare cell values, units, and rendered surfaces independently."""

    expected_by_key = {row_identity(row): row for row in expected_rows if row}
    observed_by_key = {row_identity(row): row for row in observed_rows if row}
    counts = {
        "value_correct_cells": 0,
        "value_total_cells": 0,
        "unit_correct_cells": 0,
        "unit_total_cells": 0,
        "surface_correct_cells": 0,
        "surface_total_cells": 0,
    }
    for key, expected_row in expected_by_key.items():
        observed_row = observed_by_key.get(key)
        for index in range(start_column, len(expected_row)):
            expected_cell = expected_row[index]
            observed_cell = (
                observed_row[index]
                if observed_row is not None and index < len(observed_row)
                else None
            )
            expected_surface = display_text(expected_cell)
            observed_surface = (
                display_text(observed_cell) if observed_cell is not None else None
            )
            expected_quantity = parse_quantity(expected_cell)
            observed_quantity = (
                parse_quantity(observed_cell) if observed_cell is not None else None
            )

            counts["value_total_cells"] += 1
            counts["surface_total_cells"] += 1
            if expected_quantity is None:
                value_correct = (
                    observed_cell is not None
                    and visible(observed_cell) == visible(expected_cell)
                )
            else:
                counts["unit_total_cells"] += 1
                value_correct = (
                    observed_quantity is not None
                    and observed_quantity[0] == expected_quantity[0]
                )
                if (
                    observed_quantity is not None
                    and observed_quantity[1] == expected_quantity[1]
                ):
                    counts["unit_correct_cells"] += 1
            if value_correct:
                counts["value_correct_cells"] += 1
            if observed_surface == expected_surface:
                counts["surface_correct_cells"] += 1
    return with_metric_accuracies(counts)


def with_metric_accuracies(counts: dict[str, int]) -> dict[str, Any]:
    output: dict[str, Any] = dict(counts)
    output["table_value_accuracy"] = _accuracy(
        counts["value_correct_cells"], counts["value_total_cells"]
    )
    output["table_unit_accuracy"] = _accuracy(
        counts["unit_correct_cells"], counts["unit_total_cells"]
    )
    output["table_surface_format_accuracy"] = _accuracy(
        counts["surface_correct_cells"], counts["surface_total_cells"]
    )
    return output


def combine_metric_counts(metrics: list[dict[str, Any]]) -> dict[str, Any]:
    count_keys = (
        "value_correct_cells",
        "value_total_cells",
        "unit_correct_cells",
        "unit_total_cells",
        "surface_correct_cells",
        "surface_total_cells",
    )
    return with_metric_accuracies(
        {
            key: sum(int(metric[key]) for metric in metrics)
            for key in count_keys
        }
    )


def semantic_cell_score(metrics: dict[str, Any]) -> float:
    value_score = float(metrics["table_value_accuracy"])
    if int(metrics["unit_total_cells"]) == 0:
        return value_score
    return (value_score + float(metrics["table_unit_accuracy"])) / 2


def _accuracy(correct: int, total: int) -> float:
    return correct / total if total else 1.0


def score_tables(
    candidate_tree: dict[str, Any],
    gold_tree: dict[str, Any],
    *,
    table_ids_by_section: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    candidate = aligned_tables(candidate_tree, table_ids_by_section)
    gold = aligned_tables(gold_tree, table_ids_by_section)
    details = {}
    scores = []
    all_metrics = []
    for table_id, expected in gold.items():
        if expected is None:
            continue
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
        expected_keys = [row_identity(row) for row in expected["rows"]]
        observed_keys = [row_identity(row) for row in observed["rows"]]
        row_sequence = prf(
            lcs_length(expected_keys, observed_keys),
            len(observed_keys),
            len(expected_keys),
        )
        shape_exact = (
            len(observed["rows"]) == len(expected["rows"])
            and all(
                len(row) == len(expected["headers"]) for row in observed["rows"]
            )
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
    aggregate_metrics = combine_metric_counts(all_metrics)
    return {
        "score": sum(scores) / len(scores) if scores else 1.0,
        **aggregate_metrics,
        "tables": details,
    }
