from __future__ import annotations

from pathlib import Path
from typing import Any

from ..evaluation.aggregate import aggregate_scores
from ..evaluation.evaluate import evaluate_report
from ..evaluation.oracle import (
    oracle_section_contract,
    score_calculations_against_oracle,
    score_citations_against_oracle,
    score_missingness_against_oracle,
    score_tables_against_oracle,
    score_update_against_oracle,
)
from ..evaluation.report_tree import parse_markdown
from ..evaluation.structure import score_structure
from ..runtime.evidence_store import EvidenceStore
from .contract_registry import DEFAULT_CONTRACT_REGISTRY
from .document import section_contracts
from .gold import load_authored_gold
from .oracle import build_executable_gold, validate_executable_gold
from .registry import project_catalogue


def evaluate_v2_report(
    candidate_markdown: str,
    expected_markdown: str | None = None,
    *,
    store: EvidenceStore,
    record_id: str,
    contract: dict[str, Any] | None = None,
    executable_gold: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if executable_gold is not None:
        return _evaluate_against_executable_gold(
            candidate_markdown,
            executable_gold,
            record_id=record_id,
        )
    if expected_markdown is None:
        resolved_contract = contract
        if resolved_contract is None:
            resolved_contract = DEFAULT_CONTRACT_REGISTRY.resolve(
                project_id=store.project_id
            ).load()
        gold = build_executable_gold(
            store,
            contract=resolved_contract,
            data_catalogue=project_catalogue(
                project_id=store.project_id,
                contract=resolved_contract,
            ),
        )
        return _evaluate_against_executable_gold(
            candidate_markdown,
            gold,
            record_id=record_id,
        )
    parameters = _evaluation_parameters(store, contract=contract)
    return evaluate_report(
        candidate_markdown,
        expected_markdown,
        allowed_ids=parameters["allowed_ids"],
        record_id=record_id,
        evidence_by_id=parameters["evidence_by_id"],
        section_contract=parameters["section_contract"],
        table_ids_by_section=parameters["table_ids_by_section"],
        calculation_table_ids=parameters["calculation_table_ids"],
        expected_title=parameters["expected_title"],
    )


def evaluate_v2_update(
    candidate_markdown: str,
    expected_markdown: str | None,
    original_markdown: str,
    *,
    store: EvidenceStore,
    record_id: str,
    affected_section_ids: set[str],
    section_decisions: dict[str, str] | None = None,
    contract: dict[str, Any] | None = None,
    executable_gold: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate deterministic update correctness and all-and-only routing.

    ``affected_section_ids`` is private scorer truth.  Callers must never place
    it in a model prompt or ``Episode``.  Section decisions use the public
    ``retain``/``rewrite`` vocabulary, while the shared evaluator also accepts
    the terminal tool's legacy ``keep``/``replace`` spellings.
    """

    if executable_gold is not None or expected_markdown is None:
        resolved_contract = contract
        if resolved_contract is None:
            resolved_contract = DEFAULT_CONTRACT_REGISTRY.resolve(
                project_id=store.project_id
            ).load()
        gold = executable_gold or build_executable_gold(
            store,
            contract=resolved_contract,
            data_catalogue=project_catalogue(
                project_id=store.project_id,
                contract=resolved_contract,
            ),
        )
        result = _evaluate_against_executable_gold(
            candidate_markdown,
            gold,
            record_id=record_id,
        )
        result["update"] = score_update_against_oracle(
            parse_markdown(candidate_markdown),
            parse_markdown(original_markdown),
            gold,
            affected_section_ids=set(affected_section_ids),
            evaluated_components=result["components"],
            section_actions=section_decisions,
        )
        return result

    parameters = _evaluation_parameters(store, contract=contract)
    expected_ids = {
        section["id"] for section in parameters["section_contract"]
    }
    unknown = sorted(set(affected_section_ids) - expected_ids)
    if unknown:
        raise ValueError(
            "update scorer received affected sections outside the contract: "
            + ", ".join(unknown)
        )
    parsed_expected = parse_markdown(expected_markdown)
    parsed_sections = parsed_expected.get("sections", [])
    contracts = parameters["section_contract"]
    if len(parsed_sections) != len(contracts):
        raise ValueError(
            "update scorer expected report does not match the section contract"
        )
    id_map = {
        contract_section["id"]: parsed_section["id"]
        for contract_section, parsed_section in zip(contracts, parsed_sections)
    }
    parsed_affected = {id_map[section_id] for section_id in affected_section_ids}
    parsed_decisions = (
        {
            id_map.get(section_id, section_id): decision
            for section_id, decision in section_decisions.items()
        }
        if section_decisions is not None
        else None
    )
    result = evaluate_report(
        candidate_markdown,
        expected_markdown,
        allowed_ids=parameters["allowed_ids"],
        record_id=record_id,
        original_markdown=original_markdown,
        affected_section_ids=parsed_affected,
        section_actions=parsed_decisions,
        evidence_by_id=parameters["evidence_by_id"],
        section_contract=parameters["section_contract"],
        table_ids_by_section=parameters["table_ids_by_section"],
        calculation_table_ids=parameters["calculation_table_ids"],
        expected_title=parameters["expected_title"],
    )
    reverse_map = {parsed: contract for contract, parsed in id_map.items()}
    update = result.get("update")
    if isinstance(update, dict) and isinstance(update.get("per_section"), dict):
        update["per_section"] = {
            reverse_map.get(section_id, section_id): metrics
            for section_id, metrics in update["per_section"].items()
        }
    return result


def _evaluate_against_executable_gold(
    candidate_markdown: str,
    executable_gold: dict[str, Any],
    *,
    record_id: str,
) -> dict[str, Any]:
    errors = validate_executable_gold(executable_gold)
    if errors:
        raise ValueError("invalid executable gold: " + "; ".join(errors))
    candidate = parse_markdown(candidate_markdown)
    section_contract = oracle_section_contract(executable_gold)
    table_layout = executable_gold["evaluation_contract"].get(
        "parsed_table_ids_by_section"
    ) or executable_gold["evaluation_contract"]["table_ids_by_section"]
    components = {
        "structure": score_structure(
            candidate,
            section_contract=section_contract,
            table_ids_by_section=table_layout,
            expected_title=executable_gold["evaluation_contract"][
                "expected_title"
            ],
        ),
        "tables": score_tables_against_oracle(candidate, executable_gold),
        "citations": score_citations_against_oracle(candidate, executable_gold),
        "calculations": score_calculations_against_oracle(
            candidate, executable_gold
        ),
        "missingness": score_missingness_against_oracle(
            candidate, executable_gold
        ),
    }
    return {
        "schema_version": "react_report.score/v3-executable-gold",
        "score_policy_version": "react_report.executable_gold_scoring/v3-position-independent-preservation",
        "score_scope": "deterministic_structure_values_and_citation_obligations",
        "semantic_prose_quality_measured": False,
        "record_id": record_id,
        "gold_sha256": executable_gold["gold_sha256"],
        "primary_score": aggregate_scores(components),
        "components": components,
    }


def _evaluation_parameters(
    store: EvidenceStore,
    *,
    contract: dict[str, Any] | None,
) -> dict[str, Any]:
    resolved_contract = contract
    if resolved_contract is None:
        resolved_contract = DEFAULT_CONTRACT_REGISTRY.resolve(
            project_id=store.project_id
        ).load()
    contracts = section_contracts(resolved_contract)
    table_layout = {
        section["id"]: [
            component["id"]
            for component in section["required_components"]
            if component["kind"] == "table"
        ]
        for section in contracts
    }
    calculation_tables = [
        component["id"]
        for section in contracts
        for component in section["required_components"]
        if component["kind"] == "table"
        and any(node_id.startswith("calc.") for node_id in component["data_ids"])
    ]
    title = str(store.get("dt.project.title").get("value") or "")
    allowed = store.all_ids()
    return {
        "allowed_ids": allowed,
        "evidence_by_id": {
            node_id: store.get(node_id) for node_id in allowed
        },
        "section_contract": contracts,
        "table_ids_by_section": table_layout,
        "calculation_table_ids": calculation_tables,
        "expected_title": title,
    }


def evaluate_against_authored_gold(
    candidate_markdown: str,
    *,
    gold_root: Path,
    project_id: str,
    record_id: str,
    require_reviewed: bool = True,
) -> dict[str, Any]:
    """Evaluate against one hash-checked current-family authored gold report."""

    gold = load_authored_gold(
        gold_root,
        project_id,
        require_reviewed=require_reviewed,
    )
    return evaluate_v2_report(
        candidate_markdown,
        gold["report"],
        store=gold["store"],
        record_id=record_id,
        contract=gold["contract"],
    )
