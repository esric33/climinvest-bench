from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from ..runtime.episode import LEGACY_TERMINAL_PROTOCOL, SPLIT_TERMINAL_PROTOCOL, UNRESTRICTED_TURNS
from ..runtime.episode_factory import load_reference, make_episode, prompt
from ..runtime.accounting import aggregate_report_episodes
from ..runtime.calculator import Calculator
from ..runtime.controller import run_episode
from ..runtime.evidence_store import EvidenceStore
from ..runtime.providers.base import Provider
from ..runtime.rendering import calculate_all
from ..util import compact_json, sha256_json, sha256_text
from .contract_registry import DEFAULT_CONTRACT_REGISTRY, ContractBinding
from .citation_context import citation_inventory, citation_targets, visible_report_sections
from .document import (
    compose_report,
    report_output_contract,
    model_visible_output_contract,
    PROMPT_POLICY_VERSION,
    section_contracts,
    section_output_contract,
)
from .evidence import (
    evidence_bundle_metadata,
    load_enrichment,
    load_source_normalization,
    prepare_v2_reference,
    prepare_v2_twin,
)
from .output_validation import validate_report_markdown, validate_section_markdown
from .perturbations import (
    apply_mutation,
    public_mutation_event,
    public_mutation_twin,
)
from .preflight import preflight_project_contract
from .registry import (
    calculation_registry,
    project_catalogue,
)
from .rendering import render_report, render_section


@dataclass(frozen=True)
class RuntimeContext:
    project_id: str
    template_id: str
    binding: ContractBinding
    contract: dict[str, Any]
    twin: dict[str, Any]
    reference: dict[str, Any]
    catalogue: dict[str, Any]
    preflight: dict[str, Any]


class UpdateReadinessError(ValueError):
    """Raised before provider use when a v2 update case is not immutable-ready."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class UpdateCase:
    base_context: RuntimeContext
    updated_context: RuntimeContext
    canonical_t0: dict[str, Any]
    public_event: dict[str, Any]
    expected_t1_markdown: str
    expected_t1_sha256: str
    updated_store: EvidenceStore
    affected_section_ids: frozenset[str]
    canonical_section_proofs: dict[str, dict[str, Any]]


def run_report(
    twin: dict[str, Any],
    provider: Provider,
    *,
    max_turns: int = 4,
    turn_policy: str = UNRESTRICTED_TURNS,
    terminal_protocol_version: str = LEGACY_TERMINAL_PROTOCOL,
    masked_ids: set[str] | None = None,
) -> dict[str, Any]:
    context = resolve_runtime_context(twin)
    prompt_blocks = catalogue_prompt_blocks(
        "create_report",
        terminal_protocol_version=terminal_protocol_version,
        contract=context.contract,
        project_id=context.project_id,
        catalogue_payload=context.catalogue,
    )
    episode = _episode(
        episode_id=f"{twin['project_id'].lower()}.v2.report",
        episode_kind="report_create",
        context=context,
        provider_prompt=prompt(
            "v2_report_generation.md",
            project_id=context.project_id,
            report_contract=compact_json(
                model_visible_output_contract(report_output_contract(context.contract), context.catalogue)
            ),
            **prompt_blocks,
        ),
        max_turns=max_turns,
        turn_policy=turn_policy,
        terminal_protocol_version=terminal_protocol_version,
        masked_ids=masked_ids,
    )
    return _annotate_result(run_episode(episode, provider), context)


def run_sections(
    twin: dict[str, Any],
    provider: Provider,
    *,
    max_turns: int = 4,
    turn_policy: str = UNRESTRICTED_TURNS,
    terminal_protocol_version: str = LEGACY_TERMINAL_PROTOCOL,
    masked_ids: set[str] | None = None,
) -> dict[str, Any]:
    context = resolve_runtime_context(twin)
    episodes = []
    rendered: dict[str, str] = {}
    contracts = section_contracts(context.contract)
    for section in contracts:
        result = _run_section_with_context(
            context,
            provider,
            section_id=section["id"],
            max_turns=max_turns,
            turn_policy=turn_policy,
            terminal_protocol_version=terminal_protocol_version,
            masked_ids=masked_ids,
        )
        episodes.append(result)
        if result["status"] == "completed":
            rendered[section["id"]] = result["terminal"]["markdown"]
    status = "completed" if len(rendered) == len(contracts) else "failed"
    title_node = context.twin["nodes"]["dt.project.title"]
    title = str(title_node.get("value") or "Project Investment and Performance Profile")
    return {
        "status": status,
        "benchmark_version": context.contract.get("benchmark_version", "v2"),
        "episodes": episodes,
        "sections": rendered,
        "markdown": (
            compose_report(rendered, title=title, contract=context.contract)
            if status == "completed"
            else None
        ),
        "accounting": aggregate_report_episodes(episodes),
        "project_id": context.project_id,
        "template_id": context.template_id,
        "contract_id": context.binding.contract_id,
        "preflight": context.preflight,
    }


def run_section(
    twin: dict[str, Any],
    provider: Provider,
    *,
    section_id: str,
    max_turns: int = 4,
    turn_policy: str = UNRESTRICTED_TURNS,
    terminal_protocol_version: str = LEGACY_TERMINAL_PROTOCOL,
    masked_ids: set[str] | None = None,
) -> dict[str, Any]:
    context = resolve_runtime_context(twin)
    return _run_section_with_context(
        context,
        provider,
        section_id=section_id,
        max_turns=max_turns,
        turn_policy=turn_policy,
        terminal_protocol_version=terminal_protocol_version,
        masked_ids=masked_ids,
    )


def prepare_canonical_t0(
    twin: dict[str, Any],
    *,
    gold_root: Path | None = None,
    allow_deterministic_fallback: bool = True,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Build the validated, hash-pinned T0 fixture used by update tasks.

    The normal benchmark path uses the deterministic renderer; it is an update
    fixture, not reference prose for report-quality scoring.  ``gold_root`` is
    retained only as a backwards-compatible, explicitly requested override for
    manually reviewed fixtures.  A partial, stale, or corrupt override never
    falls back silently.
    """

    context = resolve_runtime_context(twin)
    return _prepare_canonical_t0_with_context(
        context,
        gold_root=gold_root,
        allow_deterministic_fallback=allow_deterministic_fallback,
        expected_sha256=expected_sha256,
    )


def preflight_update_case(
    twin: dict[str, Any],
    condition: dict[str, Any],
    *,
    canonical_t0: dict[str, Any] | None = None,
    gold_root: Path | None = None,
    allow_deterministic_fallback: bool = True,
    expected_t0_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate one complete update case without making a provider call."""

    project_id = str(twin.get("project_id") or "").strip().upper()
    try:
        case = _build_update_case(
            twin,
            condition,
            canonical_t0=canonical_t0,
            gold_root=gold_root,
            allow_deterministic_fallback=allow_deterministic_fallback,
            expected_t0_sha256=expected_t0_sha256,
        )
    except UpdateReadinessError as exc:
        return {
            "schema_version": "react_report.update_preflight/v2",
            "project_id": project_id,
            "ready_for_provider_smoke": False,
            "provider_calls": 0,
            "errors": [{"code": exc.code, "message": str(exc)}],
        }
    except (OSError, TypeError, ValueError) as exc:
        return {
            "schema_version": "react_report.update_preflight/v2",
            "project_id": project_id,
            "ready_for_provider_smoke": False,
            "provider_calls": 0,
            "errors": [
                {
                    "code": "invalid_update_case",
                    "message": str(exc),
                }
            ],
        }
    section_ids = [
        item["id"] for item in section_contracts(case.base_context.contract)
    ]
    return {
        "schema_version": "react_report.update_preflight/v2",
        "project_id": case.base_context.project_id,
        "template_id": case.base_context.template_id,
        "ready_for_provider_smoke": True,
        "provider_calls": 0,
        "errors": [],
        "section_count": len(section_ids),
        "section_ids": section_ids,
        "canonical_t0": _canonical_metadata(case.canonical_t0),
        "public_update_event_sha256": sha256_json(case.public_event),
        "expected_t1_sha256": case.expected_t1_sha256,
        "condition_id": condition.get("condition_id"),
        "condition_sha256": sha256_json(condition),
        "affected_section_count": len(case.affected_section_ids),
    }


def prepare_update_case(
    twin: dict[str, Any],
    condition: dict[str, Any],
    *,
    canonical_t0: dict[str, Any] | None = None,
    gold_root: Path | None = None,
    allow_deterministic_fallback: bool = True,
    expected_t0_sha256: str | None = None,
) -> UpdateCase:
    """Return the immutable, zero-provider update case for a scheduler."""

    return _build_update_case(
        twin,
        condition,
        canonical_t0=canonical_t0,
        gold_root=gold_root,
        allow_deterministic_fallback=allow_deterministic_fallback,
        expected_t0_sha256=expected_t0_sha256,
    )


def run_report_update(
    twin: dict[str, Any],
    condition: dict[str, Any],
    provider: Provider,
    *,
    canonical_t0: dict[str, Any] | None = None,
    gold_root: Path | None = None,
    allow_deterministic_fallback: bool = True,
    expected_t0_sha256: str | None = None,
    max_turns: int = 4,
    turn_policy: str = UNRESTRICTED_TURNS,
    terminal_protocol_version: str = LEGACY_TERMINAL_PROTOCOL,
) -> dict[str, Any]:
    """Update a complete canonical t0 report from a public mutation packet."""

    case = _build_update_case(
        twin,
        condition,
        canonical_t0=canonical_t0,
        gold_root=gold_root,
        allow_deterministic_fallback=allow_deterministic_fallback,
        expected_t0_sha256=expected_t0_sha256,
    )
    prompt_blocks = catalogue_prompt_blocks(
        "create_report",
        terminal_protocol_version=terminal_protocol_version,
        contract=case.updated_context.contract,
        project_id=case.updated_context.project_id,
        catalogue_payload=case.updated_context.catalogue,
    )
    episode = _episode(
        episode_id=(
            f"{case.updated_context.project_id.lower()}.v2.report_update."
            f"{case.public_event['update_id']}"
        ),
        episode_kind="report_update",
        context=case.updated_context,
        provider_prompt=prompt(
            "v2_report_update.md",
            project_id=case.updated_context.project_id,
            canonical_t0_sha256=case.canonical_t0["report_sha256"],
            update_event=compact_json(case.public_event),
            previous_report=case.canonical_t0["markdown"],
            report_contract=compact_json(
                model_visible_output_contract(report_output_contract(case.updated_context.contract), case.updated_context.catalogue)
            ),
            **prompt_blocks,
        ),
        max_turns=max_turns,
        turn_policy=turn_policy,
        terminal_protocol_version=terminal_protocol_version,
        masked_ids=None,
        original_markdown=case.canonical_t0["markdown"],
        update_event=case.public_event,
        canonical_report_case=(
            case if terminal_protocol_version == SPLIT_TERMINAL_PROTOCOL else None
        ),
    )
    if terminal_protocol_version == SPLIT_TERMINAL_PROTOCOL:
        episode.messages[-1]["content"] += _citation_context_prompt(
            _split_report_sections(
                case.canonical_t0["markdown"], contract=case.base_context.contract
            ),
            case.canonical_t0["report_sha256"],
        )
    result = _annotate_result(
        run_episode(episode, provider), case.updated_context
    )
    _annotate_update_result(result, case, condition=condition, scope="report")
    markdown = (result.get("terminal") or {}).get("markdown")
    if result.get("status") == "completed" and markdown:
        result["score"] = _score_update(
            case,
            markdown,
            record_id=(
                f"{case.updated_context.project_id.lower()}.v2.update.report."
                f"{case.public_event['update_id']}"
            ),
        )
    return result


def run_section_update(
    twin: dict[str, Any],
    condition: dict[str, Any],
    provider: Provider,
    *,
    section_id: str,
    canonical_t0: dict[str, Any] | None = None,
    gold_root: Path | None = None,
    allow_deterministic_fallback: bool = True,
    expected_t0_sha256: str | None = None,
    max_turns: int = 4,
    turn_policy: str = UNRESTRICTED_TURNS,
    terminal_protocol_version: str = LEGACY_TERMINAL_PROTOCOL,
) -> dict[str, Any]:
    """Run one independently schedulable section update.

    This entry point receives no routing oracle.  It validates the entire case,
    then gives the provider only this section's t0 text and the public mutation
    event.  A scheduler can therefore execute all fifteen calls concurrently.
    """

    case = _build_update_case(
        twin,
        condition,
        canonical_t0=canonical_t0,
        gold_root=gold_root,
        allow_deterministic_fallback=allow_deterministic_fallback,
        expected_t0_sha256=expected_t0_sha256,
    )
    result = _run_section_update_with_case(
        case,
        provider,
        section_id=section_id,
        max_turns=max_turns,
        turn_policy=turn_policy,
        terminal_protocol_version=terminal_protocol_version,
    )
    _annotate_update_result(result, case, condition=condition, scope="section")
    return result


def run_section_updates(
    twin: dict[str, Any],
    condition: dict[str, Any],
    provider: Provider,
    *,
    canonical_t0: dict[str, Any] | None = None,
    gold_root: Path | None = None,
    allow_deterministic_fallback: bool = True,
    expected_t0_sha256: str | None = None,
    max_turns: int = 4,
    turn_policy: str = UNRESTRICTED_TURNS,
    terminal_protocol_version: str = LEGACY_TERMINAL_PROTOCOL,
) -> dict[str, Any]:
    """Query all fifteen sections and compose explicit retain/rewrite results."""

    case = _build_update_case(
        twin,
        condition,
        canonical_t0=canonical_t0,
        gold_root=gold_root,
        allow_deterministic_fallback=allow_deterministic_fallback,
        expected_t0_sha256=expected_t0_sha256,
    )
    episodes: list[dict[str, Any]] = []
    for section in section_contracts(case.updated_context.contract):
        section_id = section["id"]
        result = _run_section_update_with_case(
            case,
            provider,
            section_id=section_id,
            max_turns=max_turns,
            turn_policy=turn_policy,
            terminal_protocol_version=terminal_protocol_version,
        )
        episodes.append(result)
    return _reduce_section_update_results(case, condition, episodes)


def reduce_section_update_results(
    twin: dict[str, Any],
    condition: dict[str, Any],
    section_results: list[dict[str, Any]],
    *,
    canonical_t0: dict[str, Any] | None = None,
    gold_root: Path | None = None,
    allow_deterministic_fallback: bool = True,
    expected_t0_sha256: str | None = None,
) -> dict[str, Any]:
    """Purely compose and score fifteen independently scheduled results."""

    case = prepare_update_case(
        twin,
        condition,
        canonical_t0=canonical_t0,
        gold_root=gold_root,
        allow_deterministic_fallback=allow_deterministic_fallback,
        expected_t0_sha256=expected_t0_sha256,
    )
    return _reduce_section_update_results(case, condition, section_results)


def _reduce_section_update_results(
    case: UpdateCase,
    condition: dict[str, Any],
    section_results: list[dict[str, Any]],
) -> dict[str, Any]:
    contracts = section_contracts(case.updated_context.contract)
    expected_ids = [section["id"] for section in contracts]
    by_section: dict[str, dict[str, Any]] = {}
    for result in section_results:
        section_id = result.get("section_id")
        if section_id not in expected_ids:
            raise ValueError(
                f"section-update result has unknown section_id {section_id!r}"
            )
        if section_id in by_section:
            raise ValueError(
                f"section-update results duplicate section {section_id!r}"
            )
        by_section[section_id] = result
    missing = [section_id for section_id in expected_ids if section_id not in by_section]
    if missing:
        raise ValueError(
            "section-update reduction requires all 15 results; missing "
            + ", ".join(missing)
        )
    episodes = [by_section[section_id] for section_id in expected_ids]
    rendered: dict[str, str] = {}
    decisions: dict[str, str] = {}
    tool_modes: dict[str, str] = {}
    for section_id, result in zip(expected_ids, episodes):
        terminal = result.get("terminal") or {}
        if result.get("status") != "completed":
            continue
        mode = terminal.get("mode")
        decision = _normalized_section_decision(mode)
        markdown = terminal.get("markdown")
        if decision is None or not isinstance(markdown, str):
            continue
        rendered[section_id] = markdown
        decisions[section_id] = decision
        tool_modes[section_id] = str(mode)
    status = (
        "completed"
        if list(rendered) == expected_ids and list(decisions) == expected_ids
        else "failed"
    )
    title = str(
        case.updated_store.get("dt.project.title").get("value")
        or "Project Investment and Performance Profile"
    )
    markdown = (
        compose_report(
            rendered,
            title=title,
            contract=case.updated_context.contract,
        )
        if status == "completed"
        else None
    )
    result = {
        "status": status,
        "benchmark_version": case.updated_context.contract.get(
            "benchmark_version", "v2"
        ),
        "episodes": episodes,
        "queried_section_ids": expected_ids,
        "sections": rendered,
        "section_decisions": decisions,
        "section_tool_modes": tool_modes,
        "markdown": markdown,
        "accounting": aggregate_report_episodes(episodes),
        "project_id": case.updated_context.project_id,
        "template_id": case.updated_context.template_id,
        "contract_id": case.updated_context.binding.contract_id,
        "preflight": case.updated_context.preflight,
    }
    _annotate_update_result(result, case, condition=condition, scope="section")
    if status == "completed" and markdown:
        result["score"] = _score_update(
            case,
            markdown,
            record_id=(
                f"{case.updated_context.project_id.lower()}.v2.update.section."
                f"{case.public_event['update_id']}"
            ),
            section_decisions=decisions,
        )
    return result


def _build_update_case(
    twin: dict[str, Any],
    condition: dict[str, Any],
    *,
    canonical_t0: dict[str, Any] | None,
    gold_root: Path | None,
    allow_deterministic_fallback: bool,
    expected_t0_sha256: str | None,
) -> UpdateCase:
    base_context = resolve_runtime_context(twin)
    contracts = section_contracts(base_context.contract)
    declared_count = (
        base_context.contract.get("template_family", {})
        .get("visible_section_count")
    )
    if not contracts:
        raise UpdateReadinessError(
            "section_contract_count",
            f"{base_context.project_id}: v2 update requires at least one section",
        )
    if declared_count is not None and len(contracts) != declared_count:
        raise UpdateReadinessError(
            "section_contract_count",
            f"{base_context.project_id}: compiled structure has {len(contracts)} "
            f"sections but declares {declared_count}",
        )
    if canonical_t0 is None:
        resolved_t0 = _prepare_canonical_t0_with_context(
            base_context,
            gold_root=gold_root,
            allow_deterministic_fallback=allow_deterministic_fallback,
            expected_sha256=expected_t0_sha256,
        )
    else:
        resolved_t0 = _validate_supplied_canonical_t0(
            canonical_t0,
            context=base_context,
            expected_sha256=expected_t0_sha256,
        )

    public_event = public_mutation_event(condition)
    if public_event["project_id"] != base_context.project_id:
        raise UpdateReadinessError(
            "mutation_project_mismatch",
            f"{base_context.project_id}: mutation event belongs to "
            f"{public_event['project_id']}",
        )
    try:
        applied_twin = apply_mutation(base_context.twin, condition)
        updated_twin = public_mutation_twin(applied_twin, public_event)
    except (TypeError, ValueError) as exc:
        raise UpdateReadinessError(
            "mutation_not_applicable",
            f"{base_context.project_id}: mutation cannot be applied: {exc}",
        ) from exc
    updated_preflight = preflight_project_contract(
        twin=updated_twin,
        reference=base_context.reference,
        contract=base_context.contract,
        evidence_metadata=evidence_bundle_metadata(base_context.project_id),
    )
    if updated_preflight["ready_for_provider_smoke"] is not True:
        codes = ", ".join(
            item["code"] for item in updated_preflight["errors"]
        )
        raise UpdateReadinessError(
            "updated_evidence_preflight_failed",
            f"{base_context.project_id}: updated evidence failed preflight: {codes}",
        )
    updated_context = replace(
        base_context,
        twin=updated_twin,
        preflight=updated_preflight,
    )

    base_store = _calculated_store(base_context)
    updated_store = _calculated_store(updated_context)
    section_ids = {item["id"] for item in contracts}
    affected = frozenset(condition.get("affected_section_ids") or [])
    if not affected:
        raise UpdateReadinessError(
            "empty_affected_section_set",
            f"{base_context.project_id}: mutation has no affected sections",
        )
    unknown_affected = sorted(set(affected) - section_ids)
    if unknown_affected:
        raise UpdateReadinessError(
            "unknown_affected_sections",
            f"{base_context.project_id}: mutation names sections outside its "
            f"contract: {', '.join(unknown_affected)}",
        )

    deterministic_t0_sections = {
        item["id"]: render_section(
            item["id"],
            base_store,
            contract=base_context.contract,
            data_catalogue=base_context.catalogue,
        )
        for item in contracts
    }
    deterministic_t1_sections = {
        item["id"]: render_section(
            item["id"],
            updated_store,
            contract=updated_context.contract,
            data_catalogue=updated_context.catalogue,
        )
        for item in contracts
    }
    observed_changes = frozenset(
        section_id
        for section_id in section_ids
        if deterministic_t0_sections[section_id]
        != deterministic_t1_sections[section_id]
    )
    if observed_changes != affected:
        raise UpdateReadinessError(
            "mutation_impact_mismatch",
            f"{base_context.project_id}: graph-declared affected sections do not "
            "match deterministic t0/t1 rendering",
        )

    original_sections = _split_report_sections(
        resolved_t0["markdown"],
        contract=base_context.contract,
    )
    canonical_section_proofs: dict[str, dict[str, Any]] = {}
    for item in contracts:
        section_id = item["id"]
        section_markdown = original_sections[section_id]
        section_validation = validate_section_markdown(
            section_markdown,
            section_output_contract(section_id, base_context.contract),
            allowed_ids=base_store.all_ids(),
        )
        if section_validation.get("valid") is not True:
            codes = ", ".join(
                sorted(
                    {
                        str(error.get("code") or "unknown")
                        for error in section_validation.get("errors", [])
                    }
                )
            )
            raise UpdateReadinessError(
                "canonical_t0_section_invalid",
                f"{base_context.project_id}: canonical t0 section "
                f"{section_id!r} fails validation: {codes}",
            )
        canonical_section_proofs[section_id] = {
            "schema_version": "react_report.retained_section_proof/v1",
            "section_id": section_id,
            "valid": True,
            "errors": [],
            "canonical_t0_sha256": resolved_t0["report_sha256"],
            "section_sha256": sha256_text(section_markdown),
            "contract_sha256": sha256_json(
                section_output_contract(section_id, base_context.contract)
            ),
            "validation_basis": "canonical_t0_prevalidated",
        }
    expected_sections = {
        item["id"]: (
            deterministic_t1_sections[item["id"]]
            if item["id"] in affected
            else original_sections[item["id"]]
        )
        for item in contracts
    }
    title = str(
        updated_store.get("dt.project.title").get("value")
        or "Project Investment and Performance Profile"
    )
    expected_t1 = compose_report(
        expected_sections,
        title=title,
        contract=updated_context.contract,
    )
    validation = validate_report_markdown(
        expected_t1,
        report_output_contract(updated_context.contract),
        expected_title=title,
        allowed_ids=updated_store.all_ids(),
    )
    if validation["valid"] is not True:
        codes = ", ".join(
            sorted({item["code"] for item in validation["errors"]})
        )
        raise UpdateReadinessError(
            "expected_t1_invalid",
            f"{base_context.project_id}: deterministic t1 fails the current "
            f"report contract: {codes}",
        )
    return UpdateCase(
        base_context=base_context,
        updated_context=updated_context,
        canonical_t0=resolved_t0,
        public_event=public_event,
        expected_t1_markdown=expected_t1,
        expected_t1_sha256=sha256_text(expected_t1),
        updated_store=updated_store,
        affected_section_ids=affected,
        canonical_section_proofs=canonical_section_proofs,
    )


def _prepare_canonical_t0_with_context(
    context: RuntimeContext,
    *,
    gold_root: Path | None,
    allow_deterministic_fallback: bool,
    expected_sha256: str | None,
) -> dict[str, Any]:
    report: str
    source: str
    source_path: str | None
    validation: dict[str, Any]
    reviewed_report = None
    reviewed_review = None
    if gold_root is not None:
        project_root = Path(gold_root) / "projects" / context.project_id.lower()
        reviewed_report = project_root / "reviewed.md"
        reviewed_review = project_root / "review.json"
        exists = (reviewed_report.is_file(), reviewed_review.is_file())
        if any(exists) and not all(exists):
            raise UpdateReadinessError(
                "partial_reviewed_t0",
                f"{context.project_id}: reviewed t0 is partial; both reviewed.md "
                "and review.json are required",
            )
    if reviewed_report is not None and reviewed_report.is_file():
        try:
            # Local import avoids the gold -> runner module dependency during
            # initial module loading.
            from .gold import load_authored_gold

            gold = load_authored_gold(
                Path(gold_root),
                context.project_id,
                require_reviewed=True,
            )
        except (OSError, TypeError, ValueError) as exc:
            raise UpdateReadinessError(
                "invalid_reviewed_t0",
                f"{context.project_id}: reviewed t0 failed immutable validation: "
                f"{exc}",
            ) from exc
        if sha256_json(gold["contract"]) != sha256_json(context.contract):
            raise UpdateReadinessError(
                "stale_reviewed_t0_contract",
                f"{context.project_id}: reviewed t0 contract differs from runtime",
            )
        if sha256_json(context.twin) != gold["authoring"].get(
            "prepared_twin_sha256"
        ):
            raise UpdateReadinessError(
                "stale_reviewed_t0_evidence",
                f"{context.project_id}: reviewed t0 evidence differs from runtime",
            )
        report = gold["report"]
        source = "reviewed_gold"
        source_path = gold["report_path"]
        validation = gold["validation"]
        store = gold["store"]
    else:
        if not allow_deterministic_fallback:
            raise UpdateReadinessError(
                "canonical_t0_unavailable",
                f"{context.project_id}: reviewed t0 is absent and deterministic "
                "fallback is disabled",
            )
        store = _calculated_store(context)
        report = render_report(
            store,
            contract=context.contract,
            data_catalogue=context.catalogue,
        )
        source = "deterministic_renderer"
        source_path = None
        title = str(store.get("dt.project.title").get("value") or "")
        validation = validate_report_markdown(
            report,
            report_output_contract(context.contract),
            expected_title=title,
            allowed_ids=store.all_ids(),
        )
    if validation.get("valid") is not True:
        codes = ", ".join(
            sorted({item["code"] for item in validation.get("errors", [])})
        )
        raise UpdateReadinessError(
            "canonical_t0_invalid",
            f"{context.project_id}: canonical t0 fails report validation: {codes}",
        )
    report_sha256 = sha256_text(report)
    if expected_sha256 is not None and report_sha256 != expected_sha256:
        raise UpdateReadinessError(
            "canonical_t0_hash_mismatch",
            f"{context.project_id}: canonical t0 hash differs from the pinned hash",
        )
    calculated_store_sha256 = sha256_json(
        {
            node_id: store.get(node_id)
            for node_id in sorted(store.all_ids())
        }
    )
    identity = {
        "project_id": context.project_id,
        "template_id": context.template_id,
        "benchmark_version": context.contract.get("benchmark_version", "v2"),
        "source": source,
        "report_sha256": report_sha256,
        "contract_sha256": sha256_json(context.contract),
        "prepared_twin_sha256": sha256_json(context.twin),
        "prepared_reference_sha256": sha256_json(context.reference),
        "prepared_evidence_sha256": sha256_json(
            {"twin": context.twin, "reference": context.reference}
        ),
        "calculated_store_sha256": calculated_store_sha256,
    }
    return {
        "schema_version": "react_report.canonical_t0/v2",
        **identity,
        "canonical_identity_sha256": sha256_json(identity),
        "frozen": True,
        "source_path": source_path,
        "markdown": report,
        "validation": validation,
    }


def _validate_supplied_canonical_t0(
    canonical_t0: dict[str, Any],
    *,
    context: RuntimeContext,
    expected_sha256: str | None,
) -> dict[str, Any]:
    if not isinstance(canonical_t0, dict):
        raise UpdateReadinessError(
            "invalid_canonical_t0", "canonical t0 must be an object"
        )
    report = canonical_t0.get("markdown")
    if not isinstance(report, str) or not report.strip():
        raise UpdateReadinessError(
            "invalid_canonical_t0", "canonical t0 has no report Markdown"
        )
    actual_sha256 = sha256_text(report)
    pinned_sha256 = canonical_t0.get("report_sha256")
    if pinned_sha256 != actual_sha256:
        raise UpdateReadinessError(
            "canonical_t0_hash_mismatch",
            f"{context.project_id}: supplied t0 Markdown differs from its hash",
        )
    if expected_sha256 is not None and actual_sha256 != expected_sha256:
        raise UpdateReadinessError(
            "canonical_t0_hash_mismatch",
            f"{context.project_id}: supplied t0 differs from the expected hash",
        )
    store = _calculated_store(context)
    calculated_store_sha256 = sha256_json(
        {
            node_id: store.get(node_id)
            for node_id in sorted(store.all_ids())
        }
    )
    expected_identity = {
        "project_id": context.project_id,
        "template_id": context.template_id,
        "benchmark_version": context.contract.get("benchmark_version", "v2"),
        "contract_sha256": sha256_json(context.contract),
        "prepared_twin_sha256": sha256_json(context.twin),
        "prepared_reference_sha256": sha256_json(context.reference),
        "prepared_evidence_sha256": sha256_json(
            {"twin": context.twin, "reference": context.reference}
        ),
        "calculated_store_sha256": calculated_store_sha256,
    }
    for key, expected in expected_identity.items():
        if canonical_t0.get(key) != expected:
            raise UpdateReadinessError(
                "stale_canonical_t0",
                f"{context.project_id}: supplied t0 has stale {key}",
            )
    source = canonical_t0.get("source")
    if source not in {"reviewed_gold", "deterministic_renderer"}:
        raise UpdateReadinessError(
            "invalid_canonical_t0_source",
            f"{context.project_id}: supplied t0 has an unknown source",
        )
    identity = {
        "project_id": context.project_id,
        "template_id": context.template_id,
        "benchmark_version": expected_identity["benchmark_version"],
        "source": source,
        "report_sha256": actual_sha256,
        "contract_sha256": expected_identity["contract_sha256"],
        "prepared_twin_sha256": expected_identity["prepared_twin_sha256"],
        "prepared_reference_sha256": expected_identity[
            "prepared_reference_sha256"
        ],
        "prepared_evidence_sha256": expected_identity[
            "prepared_evidence_sha256"
        ],
        "calculated_store_sha256": calculated_store_sha256,
    }
    if canonical_t0.get("canonical_identity_sha256") != sha256_json(identity):
        raise UpdateReadinessError(
            "canonical_t0_identity_mismatch",
            f"{context.project_id}: supplied t0 identity hash differs",
        )
    if canonical_t0.get("frozen") is not True:
        raise UpdateReadinessError(
            "unfrozen_canonical_t0",
            f"{context.project_id}: supplied t0 is not marked frozen",
        )
    title = str(context.twin["nodes"]["dt.project.title"].get("value") or "")
    validation = validate_report_markdown(
        report,
        report_output_contract(context.contract),
        expected_title=title,
        allowed_ids=store.all_ids(),
    )
    if validation["valid"] is not True:
        codes = ", ".join(
            sorted({item["code"] for item in validation["errors"]})
        )
        raise UpdateReadinessError(
            "canonical_t0_invalid",
            f"{context.project_id}: supplied t0 fails report validation: {codes}",
        )
    return {**canonical_t0, "validation": validation}


def _calculated_store(context: RuntimeContext) -> EvidenceStore:
    store = EvidenceStore(context.twin, context.reference)
    result = calculate_all(
        Calculator(store, registry=calculation_registry(context.contract))
    )
    invalid = [
        item["id"]
        for item in result["results"]
        if item.get("status")
        not in {"available", "not_applicable_dependency"}
    ]
    if invalid:
        raise UpdateReadinessError(
            "unresolved_update_calculations",
            f"{context.project_id}: unresolved update calculations: "
            + ", ".join(invalid),
        )
    return store


def _split_report_sections(
    markdown: str,
    *,
    contract: dict[str, Any],
) -> dict[str, str]:
    lines = markdown.splitlines()
    contracts = section_contracts(contract)
    starts: list[tuple[int, dict[str, Any]]] = []
    for section in contracts:
        heading = f"## {section['heading']}"
        matches = [index for index, line in enumerate(lines) if line == heading]
        if len(matches) != 1:
            raise UpdateReadinessError(
                "canonical_t0_section_identity",
                f"canonical t0 requires exactly one {heading!r} heading",
            )
        starts.append((matches[0], section))
    if [index for index, _ in starts] != sorted(index for index, _ in starts):
        raise UpdateReadinessError(
            "canonical_t0_section_order",
            "canonical t0 section order differs from the compiled contract",
        )
    output: dict[str, str] = {}
    for position, (start, section) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        output[section["id"]] = "\n".join(lines[start:end]).strip()
    return output


def _run_section_update_with_case(
    case: UpdateCase,
    provider: Provider,
    *,
    section_id: str,
    max_turns: int,
    turn_policy: str,
    terminal_protocol_version: str,
) -> dict[str, Any]:
    output_contract = section_output_contract(
        section_id, case.updated_context.contract
    )
    originals = _split_report_sections(
        case.canonical_t0["markdown"],
        contract=case.base_context.contract,
    )
    prompt_blocks = catalogue_prompt_blocks(
        "replace_section" if terminal_protocol_version == SPLIT_TERMINAL_PROTOCOL else "create_section",
        terminal_protocol_version=terminal_protocol_version,
        contract=case.updated_context.contract,
        project_id=case.updated_context.project_id,
        catalogue_payload=case.updated_context.catalogue,
    )
    episode = _episode(
        episode_id=(
            f"{case.updated_context.project_id.lower()}.v2.section_update."
            f"{case.public_event['update_id']}.{section_id}"
        ),
        episode_kind="section_update",
        context=case.updated_context,
        provider_prompt=prompt(
            "v2_section_update.md",
            section_heading=output_contract["section"]["heading"],
            section_id=section_id,
            project_id=case.updated_context.project_id,
            canonical_t0_sha256=case.canonical_t0["report_sha256"],
            update_event=compact_json(case.public_event),
            original_section=originals[section_id],
            section_contract=compact_json(model_visible_output_contract(output_contract, case.updated_context.catalogue)),
            **prompt_blocks,
        ),
        max_turns=max_turns,
        turn_policy=turn_policy,
        terminal_protocol_version=terminal_protocol_version,
        masked_ids=None,
        section_id=section_id,
        output_contract=output_contract,
        original_markdown=originals[section_id],
        update_event=case.public_event,
        retained_section_proof=case.canonical_section_proofs[section_id],
    )
    if terminal_protocol_version == SPLIT_TERMINAL_PROTOCOL:
        episode.messages[-1]["content"] += _citation_context_prompt(
            {section_id: originals[section_id]}, case.canonical_t0["report_sha256"],
        )
    return _annotate_result(
        run_episode(episode, provider), case.updated_context
    )


def _score_update(
    case: UpdateCase,
    candidate_markdown: str,
    *,
    record_id: str,
    section_decisions: dict[str, str] | None = None,
) -> dict[str, Any]:
    # Local import avoids evaluation -> gold -> runner at module import time.
    from .evaluation import evaluate_v2_update
    from .oracle import build_executable_gold

    executable_gold = build_executable_gold(
        case.updated_store,
        contract=case.updated_context.contract,
        data_catalogue=case.updated_context.catalogue,
        condition_id=str(case.public_event["update_id"]),
    )

    return evaluate_v2_update(
        candidate_markdown,
        None,
        case.canonical_t0["markdown"],
        store=case.updated_store,
        record_id=record_id,
        affected_section_ids=set(case.affected_section_ids),
        section_decisions=section_decisions,
        contract=case.updated_context.contract,
        executable_gold=executable_gold,
    )


def _annotate_update_result(
    result: dict[str, Any],
    case: UpdateCase,
    *,
    condition: dict[str, Any],
    scope: str,
) -> None:
    result.update(
        task="update",
        scope=scope,
        update_id=case.public_event["update_id"],
        public_update_event_sha256=sha256_json(case.public_event),
        condition_id=condition.get("condition_id"),
        condition_sha256=sha256_json(condition),
        canonical_t0=_canonical_metadata(case.canonical_t0),
        expected_t1_sha256=case.expected_t1_sha256,
    )


def _canonical_metadata(canonical_t0: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in canonical_t0.items()
        if key not in {"markdown", "validation"}
    }


def _normalized_section_decision(mode: Any) -> str | None:
    if mode in {"keep", "retain"}:
        return "retain"
    if mode in {"replace", "rewrite"}:
        return "rewrite"
    return None


def _run_section_with_context(
    context: RuntimeContext,
    provider: Provider,
    *,
    section_id: str,
    max_turns: int,
    turn_policy: str,
    terminal_protocol_version: str,
    masked_ids: set[str] | None,
) -> dict[str, Any]:
    output_contract = section_output_contract(section_id, context.contract)
    prompt_blocks = catalogue_prompt_blocks(
        "create_section",
        terminal_protocol_version=terminal_protocol_version,
        contract=context.contract,
        project_id=context.project_id,
        catalogue_payload=context.catalogue,
    )
    episode = _episode(
        episode_id=f"{context.project_id.lower()}.v2.section.{section_id}",
        episode_kind="section_create",
        context=context,
        provider_prompt=prompt(
            "v2_section_generation.md",
            section_heading=output_contract["section"]["heading"],
            section_id=section_id,
            project_id=context.project_id,
            section_contract=compact_json(model_visible_output_contract(output_contract, context.catalogue)),
            **prompt_blocks,
        ),
        max_turns=max_turns,
        turn_policy=turn_policy,
        terminal_protocol_version=terminal_protocol_version,
        masked_ids=masked_ids,
        section_id=section_id,
        output_contract=output_contract,
    )
    return _annotate_result(run_episode(episode, provider), context)


def _episode(
    *,
    episode_id: str,
    episode_kind: str,
    context: RuntimeContext,
    provider_prompt: str,
    max_turns: int,
    turn_policy: str,
    terminal_protocol_version: str,
    masked_ids: set[str] | None,
    section_id: str | None = None,
    output_contract: dict[str, Any] | None = None,
    original_markdown: str | None = None,
    update_event: dict[str, Any] | None = None,
    retained_section_proof: dict[str, Any] | None = None,
    canonical_report_case: UpdateCase | None = None,
):
    contract = context.contract
    data_catalogue = context.catalogue
    return make_episode(
        episode_id=episode_id,
        episode_kind=episode_kind,
        twin=context.twin,
        user_prompt=provider_prompt,
        max_turns=max_turns,
        turn_policy=turn_policy,
        terminal_protocol_version=terminal_protocol_version,
        masked_ids=masked_ids,
        section_id=section_id,
        original_markdown=original_markdown,
        update_event=update_event,
        retained_section_proof=retained_section_proof,
        system_prompt_name="v2_react_system.md",
        calculation_registry=calculation_registry(contract),
        benchmark_version=contract.get("benchmark_version", "v2"),
        report_renderer=lambda store: render_report(
            store,
            contract=contract,
            data_catalogue=data_catalogue,
        ),
        report_output_validator=(
            _report_validator(report_output_contract(contract), canonical_case=canonical_report_case)
            if episode_kind in {"report_create", "report_update", "oracle_report"}
            else None
        ),
        section_renderer=lambda selected_section_id, store: render_section(
            selected_section_id,
            store,
            contract=contract,
            data_catalogue=data_catalogue,
        ),
        section_output_validator=(
            _section_validator(output_contract) if output_contract is not None else None
        ),
        reference=context.reference,
    )


def resolve_runtime_context(twin: dict[str, Any]) -> RuntimeContext:
    """Resolve and preflight one all-population instance without provider calls."""

    project_id = str(twin.get("project_id") or "").upper()
    binding = _require_registered_project(twin)
    contract = binding.load()
    source = load_source_normalization(project_id)
    enrichment = load_enrichment(project_id)
    prepared_twin = prepare_v2_twin(
        twin,
        source_normalization=source,
        enrichment=enrichment,
    )
    reference = prepare_v2_reference(
        load_reference(),
        project_id=project_id,
        enrichment=enrichment,
    )
    preflight = preflight_project_contract(
        twin=prepared_twin,
        reference=reference,
        contract=contract,
        evidence_metadata=evidence_bundle_metadata(project_id),
    )
    if preflight["ready_for_provider_smoke"] is not True:
        codes = ", ".join(item["code"] for item in preflight["errors"])
        raise ValueError(
            f"{project_id}: v2 preflight failed before provider use: {codes}"
        )
    return RuntimeContext(
        project_id=project_id,
        template_id=binding.contract_id,
        binding=binding,
        contract=contract,
        twin=prepared_twin,
        reference=reference,
        catalogue=project_catalogue(
            contract=contract,
            project_id=project_id,
        ),
        preflight=preflight,
    )


def _require_registered_project(twin: dict[str, Any]) -> ContractBinding:
    return DEFAULT_CONTRACT_REGISTRY.resolve(
        project_id=str(twin.get("project_id") or "")
    )


def _section_validator(contract: dict[str, Any]):
    def validate(markdown: str, store) -> dict[str, Any]:
        return validate_section_markdown(
            markdown,
            contract,
            allowed_ids=store.all_ids(),
        )

    return validate


def _citation_context_prompt(sections: dict[str, str], t0_sha256: str) -> str:
    return (
        "\n\nCANONICAL T0 CITATION CONTEXT:\n"
        + compact_json(citation_inventory(sections, t0_sha256=t0_sha256))
        + "\nThis inventory is extracted from the supplied T0 text. It does not "
        "identify which evidence changed. Determine current relevance from the "
        "public update and tools; refresh calculations for text you rewrite.\n"
    )


def _report_validator(contract: dict[str, Any], *, canonical_case: UpdateCase | None = None):
    frozen_sections: dict[str, str] = {}
    if canonical_case is not None:
        t0 = canonical_case.canonical_t0
        if sha256_text(t0["markdown"]) != t0["report_sha256"]:
            raise UpdateReadinessError("canonical_t0_hash_mismatch", "T0 proof hash mismatch")
        frozen_sections = visible_report_sections(t0["markdown"], contract["sections"])
        for section in contract["sections"]:
            section_id = str(section["id"])
            proof = canonical_case.canonical_section_proofs.get(section_id, {})
            if (
                proof.get("schema_version") != "react_report.retained_section_proof/v1"
                or proof.get("valid") is not True
                or proof.get("section_id") != section_id
                or proof.get("canonical_t0_sha256") != t0["report_sha256"]
                or proof.get("section_sha256") != sha256_text(frozen_sections.get(section_id, ""))
                or proof.get("contract_sha256") != sha256_json(
                    section_output_contract(section_id, canonical_case.base_context.contract)
                )
            ):
                raise UpdateReadinessError("canonical_t0_proof_mismatch", "T0 section proof mismatch")

    def validate(markdown: str, store) -> dict[str, Any]:
        title = str(store.get("dt.project.title").get("value") or "")
        current_ids = store.all_ids()
        observed = visible_report_sections(markdown, contract["sections"])
        inherited = {
            section_id: current_ids | citation_targets(original)
            for section_id, original in frozen_sections.items()
            if observed.get(section_id) == original
        }
        result = validate_report_markdown(
            markdown,
            contract,
            expected_title=title,
            allowed_ids=current_ids,
            section_allowed_ids=inherited,
        )
        if canonical_case is not None:
            result["citation_validation_policy"] = "react_report.update_citations/v2-frozen-t0"
            result["inherited_section_ids"] = sorted(inherited)
            result["canonical_t0_sha256"] = canonical_case.canonical_t0["report_sha256"]
        return result

    return validate


def catalogue_prompt_blocks(
    terminal_tool: str,
    *,
    terminal_protocol_version: str = LEGACY_TERMINAL_PROTOCOL,
    contract: dict[str, Any] | None = None,
    project_id: str | None = None,
    catalogue_payload: dict[str, Any] | None = None,
) -> dict[str, str]:
    payload = catalogue_payload or project_catalogue(
        contract=contract,
        project_id=project_id,
    )
    tool_names = ("get_data", "calculate", terminal_tool)
    tools = {name: payload["tools"][name] for name in tool_names if name in payload["tools"]}
    if terminal_tool == "create_section" and terminal_protocol_version == SPLIT_TERMINAL_PROTOCOL:
        tools["create_section"] = {"terminal": True, "arguments": {"section_id": "requested section ID", "markdown": "complete section Markdown"}}
    if terminal_tool == "replace_section":
        tools["replace_section"] = {
            "terminal": True,
            "arguments": {"section_id": "requested section ID", "markdown": "complete replacement section Markdown"},
        }
        tools["keep_section"] = {"terminal": True, "arguments": {"section_id": "requested section ID"}}
    return {
        # Catalogue membership describes what can be requested, not its
        # condition-specific availability. A masked item may still carry a
        # baseline status in the static catalogue; only tool results may
        # establish its current status.
        "evidence_catalogue": compact_json({
            node_id: {key: value for key, value in definition.items() if key != "status"}
            for node_id, definition in payload["data"].items()
        }),
        "calculation_catalogue": compact_json(
            {
                "calculations": {
                    calculation_id: _calculation_prompt_definition(definition)
                    for calculation_id, definition in payload[
                        "calculations"
                    ].items()
                },
            }
        ),
        "tool_catalogue": compact_json(tools),
    }


def _calculation_prompt_definition(
    definition: dict[str, Any],
) -> dict[str, Any]:
    """Render the semantic calculation contract without call boilerplate."""

    output: dict[str, Any] = {
        "description": definition.get("description"),
        "unit": definition.get("unit"),
        "depends_on": list(dict.fromkeys(definition.get("input_ids", {}).values())),
    }
    operation_id = definition.get("operation_id")
    if operation_id == "expression":
        output["expression"] = definition.get("expression")
    else:
        output["operation"] = operation_id
        if definition.get("parameters"):
            output["parameters"] = definition["parameters"]
    return {
        key: value
        for key, value in output.items()
        if value not in (None, [], {})
    }


def _annotate_result(
    result: dict[str, Any],
    context: RuntimeContext,
) -> dict[str, Any]:
    result["contract_id"] = context.binding.contract_id
    result["template_id"] = context.template_id
    result["preflight"] = context.preflight
    result["prompt_policy"] = PROMPT_POLICY_VERSION
    return result
