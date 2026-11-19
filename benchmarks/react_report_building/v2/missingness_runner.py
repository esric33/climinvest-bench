"""Zero-provider readiness checks for stratified missing-evidence cases."""

from __future__ import annotations

from typing import Any

from ..runtime.calculator import Calculator
from ..runtime.evidence_store import EvidenceStore
from ..runtime.rendering import calculate_all
from ..util import sha256_json
from .document import section_contracts
from .registry import calculation_registry
from .rendering import render_section
from .runner import resolve_runtime_context
from .source_aliases import validate_mask_alias_closure


def preflight_missingness_case(
    twin: dict[str, Any],
    condition: dict[str, Any],
) -> dict[str, Any]:
    """Require declared missingness impact to equal observable report impact."""

    project_id = str(twin.get("project_id") or "").upper()
    errors: list[dict[str, str]] = []
    try:
        context = resolve_runtime_context(twin)
        if condition.get("kind") != "missingness":
            raise ValueError("condition is not a v2 missingness mask")
        if str(condition.get("project_id") or "").upper() != context.project_id:
            raise ValueError("condition belongs to a different project")
        if condition.get("contract_sha256") != sha256_json(context.contract):
            raise ValueError("condition contract hash is stale")
        if condition.get("prepared_evidence_sha256") != sha256_json(context.twin):
            raise ValueError("condition prepared-evidence hash is stale")
        validate_mask_alias_closure(context.twin, condition)
        masked_ids = set(condition.get("masked_ids") or ())
        if not masked_ids:
            raise ValueError("missingness condition has no masked IDs")
        base_store = _calculated_store(context, masked_ids=set())
        masked_store = _calculated_store(context, masked_ids=masked_ids)
        sections = section_contracts(context.contract)
        observed = {
            section["id"]
            for section in sections
            if render_section(
                section["id"],
                base_store,
                contract=context.contract,
                data_catalogue=context.catalogue,
            )
            != render_section(
                section["id"],
                masked_store,
                contract=context.contract,
                data_catalogue=context.catalogue,
            )
        }
        declared = set(condition.get("affected_section_ids") or ())
        if observed != declared:
            errors.append(
                {
                    "code": "mask_impact_mismatch",
                    "message": (
                        "graph-declared affected sections do not match "
                        "deterministic complete/masked rendering"
                    ),
                }
            )
    except (KeyError, TypeError, ValueError) as exc:
        errors.append({"code": "invalid_missingness_case", "message": str(exc)})
    return {
        "schema_version": "react_report.missingness_preflight/v2",
        "project_id": project_id,
        "condition_id": condition.get("condition_id"),
        "condition_sha256": sha256_json(condition),
        "ready_for_provider_smoke": not errors,
        "provider_calls": 0,
        "errors": errors,
    }


def _calculated_store(context: Any, *, masked_ids: set[str]) -> EvidenceStore:
    store = EvidenceStore(
        context.twin,
        context.reference,
        masked_ids=masked_ids,
    )
    calculate_all(
        Calculator(store, registry=calculation_registry(context.contract))
    )
    return store
