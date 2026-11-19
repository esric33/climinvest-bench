"""Neutral citation inventories derived only from model-visible T0 text."""

from __future__ import annotations

import re
from typing import Mapping

CITATION_CONTEXT_VERSION = "react_report.t0_citation_context/v1"
_CITATION = re.compile(r"\[[^\]\n]*\]\((?:missing\.)?((?:dt|reference|req|calc)\.[a-z0-9_.]+)\)")


def citation_targets(markdown: str) -> set[str]:
    return set(_CITATION.findall(markdown))


def citation_inventory(sections: Mapping[str, str], *, t0_sha256: str) -> dict:
    """No impact, freshness, validity, or T1 values enter this projection."""
    return {
        "schema_version": CITATION_CONTEXT_VERSION,
        "canonical_t0_sha256": t0_sha256,
        "sections": [
            {
                "section_id": section_id,
                "direct_evidence_ids": sorted(
                    value for value in citation_targets(markdown)
                    if not value.startswith("calc.")
                ),
                "calculation_ids": sorted(
                    value for value in citation_targets(markdown)
                    if value.startswith("calc.")
                ),
            }
            for section_id, markdown in sections.items()
        ],
    }


def visible_report_sections(markdown: str, sections: list[dict]) -> dict[str, str]:
    """Extract exact section bodies using the existing trimmed-boundary convention.

    Duplicate headings are not eligible for inherited proof. Unexpected headings
    remain in their containing body, so additions cannot inherit a shorter T0.
    The ordinary report validator still diagnoses all layout errors.
    """
    lines = markdown.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("## ")]
    result = {}
    for section in sections:
        matches = [i for i in starts if lines[i] == f"## {section['heading']}"]
        if len(matches) != 1:
            continue
        start = matches[0]
        end = next((i for i in starts if i > start), len(lines))
        result[str(section["id"])] = "\n".join(lines[start:end]).strip()
    return result
