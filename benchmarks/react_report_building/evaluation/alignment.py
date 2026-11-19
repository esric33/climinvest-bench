from __future__ import annotations

import re
from typing import Any


COMPONENT_ALIGNMENT_POLICY = "heading_type_sequence/v1"


def align_components(
    components: list[dict[str, Any]],
    section: dict[str, Any],
) -> dict[str, Any]:
    """Map expected components to observed blocks without repairing the report.

    Exact subsection headings and table headers anchor an order-preserving
    sequence alignment. Prose is matched by kind within that sequence, never
    by its claims/citations or the answer key. A standalone heading or an exact
    supplied table-title caption is an extra block, not analytical prose.
    """

    blocks = section.get("blocks", [])
    caption_titles = {
        _caption_text(str(item.get("title") or ""))
        for item in components
        if item.get("kind") == "table" and item.get("title")
    }

    def match_weight(component: dict[str, Any], block: dict[str, Any]) -> int:
        kind = "prose" if component.get("kind") == "llm" else component.get("kind")
        if kind != block.get("kind"):
            return 0
        if kind == "subsection":
            return 4 if component.get("heading") == block.get("heading") else 1
        if kind == "table":
            table = section.get("tables", [])[block["index"]]
            return 4 if component.get("headers") == table.get("headers") else 1
        if kind == "prose":
            paragraph = section.get("paragraphs", [])[block["index"]]["text"]
            if re.match(r"^\s*#{1,6}(?:\s|$)", paragraph):
                return 0
            if _caption_text(paragraph) in caption_titles:
                return 0
            return 1
        return 0

    weights = [[match_weight(item, block) for block in blocks] for item in components]
    rows = [[0] * (len(blocks) + 1) for _ in range(len(components) + 1)]
    for i in range(len(components) - 1, -1, -1):
        for j in range(len(blocks) - 1, -1, -1):
            rows[i][j] = max(rows[i + 1][j], rows[i][j + 1])
            if weights[i][j]:
                rows[i][j] = max(rows[i][j], weights[i][j] + rows[i + 1][j + 1])

    matches: list[int | None] = [None] * len(components)
    i = j = 0
    while i < len(components) and j < len(blocks):
        if weights[i][j] and rows[i][j] == weights[i][j] + rows[i + 1][j + 1]:
            matches[i] = j
            i += 1
            j += 1
        elif rows[i][j] == rows[i][j + 1]:
            j += 1
        else:
            i += 1
    matched = {index for index in matches if index is not None}
    return {
        "policy_version": COMPONENT_ALIGNMENT_POLICY,
        "component_block_indices": matches,
        "unmatched_observed_block_indices": [
            index for index in range(len(blocks)) if index not in matched
        ],
    }


def _caption_text(text: str) -> str:
    # Only exact metadata titles (optionally Markdown-emphasized) qualify.
    # Arbitrary short prose must not be discarded based on its quality.
    return text.strip().strip("*_").strip().removesuffix(":").strip()


TABLE_IDS_BY_SECTION = {
    "project_overview": ["project_overview.characteristics_table"],
    "scale_and_calculated_indicators": [
        "scale.calculation_table",
        "scale.reference_table",
        "scale.comparison_table",
    ],
    "selected_performance_indicators": ["kpis.table"],
    "priority_risks": ["risks.table"],
    "overall_evidence_summary": [],
}


def aligned_tables(
    tree: dict[str, Any],
    table_ids_by_section: dict[str, list[str]] | None = None,
) -> dict[str, dict[str, Any] | None]:
    output: dict[str, dict[str, Any] | None] = {}
    sections = {item["id"]: item for item in tree["sections"]}
    for section_id, table_ids in (
        table_ids_by_section or TABLE_IDS_BY_SECTION
    ).items():
        observed = sections.get(section_id, {}).get("tables", [])
        for index, table_id in enumerate(table_ids):
            output[table_id] = observed[index] if index < len(observed) else None
    return output


def lcs_length(left: list[str], right: list[str]) -> int:
    rows = [[0] * (len(right) + 1) for _ in range(len(left) + 1)]
    for i, left_item in enumerate(left, 1):
        for j, right_item in enumerate(right, 1):
            rows[i][j] = (
                rows[i - 1][j - 1] + 1
                if left_item == right_item
                else max(rows[i - 1][j], rows[i][j - 1])
            )
    return rows[-1][-1]


def prf(matches: int, predicted: int, expected: int) -> dict[str, float]:
    precision = matches / predicted if predicted else (1.0 if expected == 0 else 0.0)
    recall = matches / expected if expected else 1.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return {"precision": precision, "recall": recall, "f1": f1}
