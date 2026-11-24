from __future__ import annotations

from typing import Any

from ..domain.catalogue import SECTION_CONTRACT
from .alignment import TABLE_IDS_BY_SECTION, lcs_length, prf


def score_structure(
    tree: dict[str, Any],
    *,
    section_contract: list[dict[str, Any]] | None = None,
    table_ids_by_section: dict[str, list[str]] | None = None,
    expected_title: str = "Project Investment and Performance Profile",
) -> dict[str, Any]:
    contracts = section_contract or SECTION_CONTRACT
    table_layout = table_ids_by_section or TABLE_IDS_BY_SECTION
    expected = [item["id"] for item in contracts]
    observed = [item["id"] for item in tree["sections"]]
    sequence = prf(lcs_length(expected, observed), len(observed), len(expected))
    expected_tables = sum(len(items) for items in table_layout.values())
    observed_tables = sum(len(item["tables"]) for item in tree["sections"])
    matched_tables = 0
    section_by_id = {item["id"]: item for item in tree["sections"]}
    for section_id, table_ids in table_layout.items():
        matched_tables += min(
            len(table_ids), len(section_by_id.get(section_id, {}).get("tables", []))
        )
    table_presence = prf(matched_tables, observed_tables, expected_tables)
    expected_block_tokens = []
    observed_block_tokens = []
    for contract in contracts:
        expected_tokens = [
            _contract_block_token(item)
            for item in contract.get(
                "required_blocks",
                contract.get("required_components", []),
            )
        ]
        section = section_by_id.get(contract["id"], {})
        observed_tokens = [
            _block_token(item) for item in section.get("blocks", [])
        ]
        expected_block_tokens.extend(
            f"{contract['id']}:{token}" for token in expected_tokens
        )
        observed_block_tokens.extend(
            f"{contract['id']}:{token}" for token in observed_tokens
        )
    block_sequence = prf(
        lcs_length(expected_block_tokens, observed_block_tokens),
        len(observed_block_tokens),
        len(expected_block_tokens),
    )
    title_correct = tree.get("title") == expected_title
    score = (
        float(title_correct) * 0.05
        + sequence["f1"] * 0.45
        + block_sequence["f1"] * 0.35
        + table_presence["f1"] * 0.15
    )
    return {
        "score": score,
        "title_correct": title_correct,
        "expected_sections": expected,
        "observed_sections": observed,
        "section_sequence": sequence,
        "block_sequence": block_sequence,
        "expected_block_tokens": expected_block_tokens,
        "observed_block_tokens": observed_block_tokens,
        "table_presence": table_presence,
    }


def _block_token(block: dict[str, Any]) -> str:
    if block.get("kind") == "subsection":
        return f"subsection:{block.get('heading') or ''}"
    return str(block.get("kind") or "")


def _contract_block_token(block: dict[str, Any]) -> str:
    if block.get("kind") == "llm":
        return "prose"
    return _block_token(block)
