from __future__ import annotations

from typing import Any

from .aggregate import aggregate_scores
from .calculations import score_calculations
from .citations import score_citations
from .missingness import score_missingness
from .report_tree import parse_markdown
from .structure import score_structure
from .tables import score_tables
from .updates import score_update


def evaluate_report(
    candidate_markdown: str,
    expected_markdown: str,
    *,
    allowed_ids: set[str],
    record_id: str,
    original_markdown: str | None = None,
    affected_section_ids: set[str] | None = None,
    section_actions: dict[str, str] | None = None,
    evidence_by_id: dict[str, Any] | None = None,
    section_contract: list[dict[str, Any]] | None = None,
    table_ids_by_section: dict[str, list[str]] | None = None,
    calculation_table_ids: list[str] | None = None,
    expected_title: str = "Project Investment and Performance Profile",
) -> dict[str, Any]:
    candidate = parse_markdown(candidate_markdown)
    expected = parse_markdown(expected_markdown)
    components = {
        "structure": score_structure(
            candidate,
            section_contract=section_contract,
            table_ids_by_section=table_ids_by_section,
            expected_title=expected_title,
        ),
        "tables": score_tables(
            candidate,
            expected,
            table_ids_by_section=table_ids_by_section,
        ),
        "citations": score_citations(
            candidate, expected, allowed_ids=allowed_ids
        ),
        "calculations": score_calculations(
            candidate,
            expected,
            table_ids_by_section=table_ids_by_section,
            calculation_table_ids=calculation_table_ids,
        ),
        "missingness": score_missingness(candidate, expected),
    }
    result: dict[str, Any] = {
        "schema_version": "react_report.score/v2",
        "record_id": record_id,
        "primary_score": aggregate_scores(components),
        "components": components,
    }
    if original_markdown is not None and affected_section_ids is not None:
        result["update"] = score_update(
            candidate,
            expected,
            parse_markdown(original_markdown),
            affected_section_ids=affected_section_ids,
            section_actions=section_actions,
        )
    return result
