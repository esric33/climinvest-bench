from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from ..paths import NORMALIZED_ROOT, REFERENCE_ROOT
from ..evaluation.report_tree import parse_markdown
from ..runtime.calculator import Calculator
from ..runtime.evidence_store import EvidenceStore
from ..runtime.providers.base import Provider
from ..runtime.rendering import calculate_all
from ..util import (
    compact_json,
    read_json,
    sha256_json,
    sha256_text,
    write_json,
    write_text,
)
from .contract import load_compiled_contract
from .document import report_output_contract, section_contracts
from .evidence import (
    load_enrichment,
    load_source_normalization,
    prepare_v2_reference,
    prepare_v2_twin,
)
from .output_validation import validate_report_markdown
from .registry import calculation_registry
from .rendering import render_report
from .runner import resolve_runtime_context
from .study_design import (
    POPULATION_PATH,
    project_specialisation_assignments,
)


CANONICAL_CITATION = re.compile(
    r"\[([^\]]*)\]\(((?:missing\.)?(?:dt|calc|req|reference)\.[A-Za-z0-9_.-]+)\)"
)

GOLD_RUN_SCHEMA = "react_report.gold_population_authoring/v5"
GOLD_PROJECT_SCHEMA = "react_report.gold_authoring/v5"
GOLD_COMPONENT_SCHEMA = "react_report.gold_component/v5"
GOLD_REVIEW_SCHEMA = "react_report.gold_review/v5"
GOLD_SYSTEM_PROMPT = (
    "Write exactly one compact, neutral report paragraph from the supplied "
    "instructions and resolved evidence. Use only supplied evidence. Cite every "
    "required scalar and calculation ID at least once as [visible text](node_id); "
    "an available collection must be covered by at least one available canonical "
    "root, record, or field citation, not only a missing optional child. "
    "Use a separate citation for both endpoints of every range. For a supplied "
    "missing or not-applicable item, preserve that status and cite it through "
    "missing.node_id, for example [not applicable](missing.node_id). Never use "
    "the missing namespace for an available item, and never turn N/A into zero. "
    "Use non-empty citation labels, preserve every scope and qualification, and "
    "do not introduce facts, dates, rankings, advice, or causal claims that the "
    "packet does not support. Use human-readable rounding with no more than two "
    "decimals unless more precision is material. Return only the paragraph, with "
    "no heading, table, list, preamble, or code fence."
)


class GoldAuthoringConfigurationError(ValueError):
    """Raised before provider use for an unsafe or incompatible gold run."""


class GoldReviewValidationError(ValueError):
    """Raised when a proposed reviewed report does not satisfy the gold gate."""


@dataclass
class GoldComponentEpisode:
    episode_id: str
    project_id: str
    component_id: str
    episode_kind: str = "gold_component"
    template_id: str | None = None
    section_id: str | None = None
    required_ids: tuple[str, ...] = ()
    not_applicable_ids: tuple[str, ...] = ()
    allowed_tools: frozenset[str] = field(default_factory=frozenset)
    turns: list[dict[str, Any]] = field(default_factory=list)


def author_v2_gold(
    provider: Provider,
    *,
    output_dir: Path,
    project_ids: list[str] | None = None,
    resume: bool = False,
    provider_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Author current-contract oracle drafts for the selected v2 population.

    The default selection is the authoritative twenty-project population. Each
    prompt-controlled component is called exactly once and immediately persisted
    as an immutable checkpoint. ``resume=True`` reuses only checkpoints whose
    provider, contract, evidence, and prompt identities still match exactly.
    """

    root = Path(output_dir)
    manifest_path = root / "manifest.json"
    try:
        selected = _selected_project_ids(project_ids)
        existing_entries = list(root.iterdir()) if root.is_dir() else []
        if existing_entries and not resume:
            raise ValueError(
                f"gold output directory is not empty; use a fresh directory or "
                f"--resume: {root}"
            )
        if resume and not manifest_path.is_file():
            raise ValueError(
                f"cannot resume without an existing gold manifest: {manifest_path}"
            )

        provider_identity = _provider_identity(provider, provider_config)
        plans = [_build_project_plan(project_id) for project_id in selected]
        identity = _run_identity(selected, provider_identity, plans)
        fingerprint = sha256_json(identity)
        now = _utc_now()

        if resume:
            manifest = read_json(manifest_path)
            if manifest.get("schema_version") != GOLD_RUN_SCHEMA:
                raise ValueError("cannot resume an unexpected gold-manifest schema")
            if (
                manifest.get("identity") != identity
                or manifest.get("run_fingerprint") != fingerprint
                or manifest.get("run_fingerprint")
                != sha256_json(manifest.get("identity"))
            ):
                raise ValueError(
                    "cannot resume: provider, selection, contract, evidence, or "
                    "prompt identity differs from the existing run"
                )
            _validate_resume_manifest_shape(manifest, plans)
            _preflight_resume_artifacts(
                root,
                manifest,
                plans=plans,
                provider_identity=provider_identity,
            )
        else:
            root.mkdir(parents=True, exist_ok=True)
            manifest = {
                "schema_version": GOLD_RUN_SCHEMA,
                "run_fingerprint": fingerprint,
                "identity": identity,
                "created_at": now,
                "updated_at": now,
                "status": "in_progress",
                "valid": False,
                "project_count": len(plans),
                "expected_generation_count": sum(
                    len(plan["components"]) for plan in plans
                ),
                "generation_count": 0,
                "provider_call_count": 0,
                "projects": [_pending_project_summary(plan) for plan in plans],
                "invocations": [],
            }
    except GoldAuthoringConfigurationError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise GoldAuthoringConfigurationError(str(exc)) from exc

    invocation = {
        "started_at": now,
        "finished_at": None,
        "resume": resume,
        "provider_calls": 0,
        "reused_checkpoints": 0,
        "status": "in_progress",
    }
    manifest.setdefault("invocations", []).append(invocation)
    manifest["status"] = "in_progress"
    manifest["updated_at"] = now
    write_json(manifest_path, manifest)

    summaries: list[dict[str, Any]] = []
    try:
        for project_index, plan in enumerate(plans):
            summary = _author_project(
                provider,
                provider_identity=provider_identity,
                root=root,
                plan=plan,
                resume=resume,
                invocation=invocation,
                checkpoint_callback=lambda completed, index=project_index: (
                    _record_checkpoint_progress(
                        manifest,
                        manifest_path,
                        project_index=index,
                        completed=completed,
                        invocation=invocation,
                    )
                ),
            )
            summaries.append(summary)
            manifest["projects"][project_index] = summary
            _refresh_run_totals(manifest)
            write_json(manifest_path, manifest)
    except Exception as exc:
        invocation["status"] = "interrupted"
        invocation["finished_at"] = _utc_now()
        manifest["status"] = "interrupted"
        manifest["valid"] = False
        manifest["last_error"] = f"{type(exc).__name__}: {exc}"
        manifest["updated_at"] = invocation["finished_at"]
        _refresh_run_totals(manifest)
        write_json(manifest_path, manifest)
        raise

    invocation["status"] = "completed"
    invocation["finished_at"] = _utc_now()
    manifest["projects"] = summaries
    _refresh_run_totals(manifest)
    manifest["valid"] = all(item.get("valid") is True for item in summaries)
    manifest["status"] = (
        "completed" if manifest["valid"] else "completed_with_qa_failures"
    )
    manifest["updated_at"] = invocation["finished_at"]
    manifest.pop("last_error", None)
    write_json(manifest_path, manifest)
    return manifest


def load_authored_gold(
    output_dir: Path,
    project_id: str,
    *,
    require_reviewed: bool = True,
) -> dict[str, Any]:
    """Load one current, validated authored report without legacy fallback.

    Reviewed gold is the safe default. An approved review requires an immutable
    ``review.json`` sidecar whose hashes bind the generated and reviewed reports.
    ``require_reviewed=False`` is intended for draft QA and fixture tests.
    """

    root = Path(output_dir)
    manifest = read_json(root / "manifest.json")
    if manifest.get("schema_version") != GOLD_RUN_SCHEMA:
        raise ValueError("unexpected authored-gold manifest schema")
    if manifest.get("run_fingerprint") != sha256_json(manifest.get("identity")):
        raise ValueError("authored-gold run fingerprint differs")
    population_identity = manifest.get("identity", {}).get(
        "population_manifest", {}
    )
    if population_identity.get("sha256") != sha256_text(
        POPULATION_PATH.read_text(encoding="utf-8")
    ):
        raise ValueError("authored-gold population manifest is stale")
    _validate_terminal_manifest(manifest)
    project = str(project_id or "").strip().upper()
    project_root = root / "projects" / project.lower()
    authoring = read_json(project_root / "authoring.json")
    if authoring.get("schema_version") != GOLD_PROJECT_SCHEMA:
        raise ValueError(f"{project}: unexpected gold-authoring schema")
    if authoring.get("project_id") != project:
        raise ValueError(f"{project}: authored-gold project identity differs")
    if project not in manifest.get("identity", {}).get("project_ids", []):
        raise ValueError(f"{project}: project is absent from the gold-run identity")
    manifest_summary = next(
        (
            item
            for item in manifest.get("projects", [])
            if item.get("project_id") == project
        ),
        None,
    )
    if not isinstance(manifest_summary, dict):
        raise ValueError(f"{project}: project is absent from the gold-run summary")
    if manifest_summary.get("authoring_sha256") != sha256_json(authoring):
        raise ValueError(f"{project}: stale project authoring hash differs")
    if manifest_summary.get("report_sha256") != authoring.get("report_sha256"):
        raise ValueError(f"{project}: stale project report identity differs")
    if not require_reviewed and authoring.get("valid") is not True:
        raise ValueError(f"{project}: generated gold is not valid")

    context, store, identity, plan = _current_project_identity(project)
    for key in (
        "benchmark_version",
        "template_id",
        "contract_sha256",
        "prepared_evidence_sha256",
        "prepared_twin_sha256",
        "prepared_reference_sha256",
        "calculated_store_sha256",
        "catalogue_sha256",
        "calculation_registry_sha256",
        "source_normalization_sha256",
        "enrichment_sha256",
    ):
        if authoring.get(key) != identity.get(key):
            raise ValueError(f"{project}: authored gold has stale {key}")

    _validate_manifest_project_identity(
        manifest,
        authoring,
        plan=plan,
        project=project,
    )
    checkpoint_records = _validate_project_checkpoints(
        project_root,
        authoring,
        project=project,
        plan=plan,
        provider_identity=manifest["identity"]["provider"],
    )

    if require_reviewed:
        review_path = project_root / "review.json"
        report_path = project_root / "reviewed.md"
        if not review_path.is_file() or not report_path.is_file():
            raise ValueError(f"{project}: reviewed gold has not been approved")
        review = read_json(review_path)
        if review.get("schema_version") != GOLD_REVIEW_SCHEMA:
            raise ValueError(f"{project}: unexpected gold-review schema")
        if review.get("project_id") != project:
            raise ValueError(f"{project}: gold review project identity differs")
        _validate_review_attestation(review, project=project)
        if review.get("authoring_sha256") != sha256_json(authoring):
            raise ValueError(f"{project}: gold review authoring hash differs")
        if review.get("contract_sha256") != identity["contract_sha256"]:
            raise ValueError(f"{project}: gold review contract hash differs")
        if (
            review.get("prepared_evidence_sha256")
            != identity["prepared_evidence_sha256"]
        ):
            raise ValueError(f"{project}: gold review evidence hash differs")
        if review.get("status") != "approved":
            raise ValueError(f"{project}: gold review is not approved")
        generated_path = project_root / "generated.md"
        generated = generated_path.read_text(encoding="utf-8")
        if generated != _render_generated_from_checkpoints(plan, checkpoint_records):
            raise ValueError(
                f"{project}: generated report differs from component checkpoints"
            )
        if authoring.get("report_sha256") != sha256_text(generated):
            raise ValueError(f"{project}: generated gold hash differs")
        if review.get("generated_report_sha256") != sha256_text(
            generated
        ):
            raise ValueError(f"{project}: reviewed gold source hash differs")
        report = report_path.read_text(encoding="utf-8")
        if review.get("reviewed_report_sha256") != sha256_text(report):
            raise ValueError(f"{project}: reviewed gold hash differs")
    else:
        review = None
        report_path = project_root / "generated.md"
        report = report_path.read_text(encoding="utf-8")
        if report != _render_generated_from_checkpoints(plan, checkpoint_records):
            raise ValueError(
                f"{project}: generated report differs from component checkpoints"
            )
        if authoring.get("report_sha256") != sha256_text(report):
            raise ValueError(f"{project}: generated gold hash differs")

    generated_source = generated if review is not None else report
    _validate_authoring_aggregates(
        authoring,
        plan=plan,
        records=checkpoint_records,
        generated=generated_source,
        project_root=project_root,
    )
    if manifest_summary != _project_summary_from_authoring(authoring):
        raise ValueError(f"{project}: project summary provenance differs")

    validation = validate_report_markdown(
        report,
        report_output_contract(context.contract),
        expected_title=str(store.get("dt.project.title").get("value") or ""),
        allowed_ids=store.all_ids(),
    )
    if not validation["valid"]:
        raise ValueError(
            f"{project}: authored report fails current contract validation: "
            + ", ".join(sorted({item["code"] for item in validation["errors"]}))
        )
    component_citation_qa = _report_component_citation_qa(report, plan)
    if not component_citation_qa["passed"]:
        raise ValueError(
            f"{project}: authored report fails status-aware citation validation: "
            + ", ".join(component_citation_qa["failing_component_ids"])
        )
    if review is not None and review.get("citation_qa") != component_citation_qa:
        raise ValueError(f"{project}: reviewed citation QA provenance differs")
    if review is not None and review.get("validation") != validation:
        raise ValueError(f"{project}: reviewed contract validation provenance differs")
    if review is not None and review.get("component_edits") != (
        _review_component_edits(generated, report, context.contract)
    ):
        raise ValueError(f"{project}: reviewed component-edit provenance differs")
    canonical = render_report(
        store,
        contract=context.contract,
        data_catalogue=context.catalogue,
    )
    if _table_raws(report) != _table_raws(canonical):
        raise ValueError(f"{project}: authored gold changes deterministic tables")
    return {
        "project_id": project,
        "report": report,
        "report_path": str(report_path),
        "authoring": authoring,
        "review": review,
        "validation": validation,
        "citation_qa": component_citation_qa,
        "contract": context.contract,
        "store": store,
    }


def promote_reviewed_gold(
    output_dir: Path,
    project_id: str,
    *,
    reviewed_report: Path,
    reviewer: str,
    review_note: str,
) -> dict[str, Any]:
    """Promote one human-edited report through a zero-provider validation gate."""

    project = str(project_id or "").strip().upper()
    reviewer_name = str(reviewer or "").strip()
    note = str(review_note or "").strip()
    if not reviewer_name:
        raise ValueError("reviewer must be non-empty")
    if not note:
        raise ValueError("review_note must be non-empty")
    source_path = Path(reviewed_report)
    if not source_path.is_file():
        raise ValueError(f"reviewed report does not exist: {source_path}")

    root = Path(output_dir)
    manifest = read_json(root / "manifest.json")
    if manifest.get("schema_version") != GOLD_RUN_SCHEMA:
        raise ValueError("unexpected authored-gold manifest schema")
    if manifest.get("run_fingerprint") != sha256_json(manifest.get("identity")):
        raise ValueError("authored-gold run fingerprint differs")
    if manifest.get("identity", {}).get("population_manifest", {}).get(
        "sha256"
    ) != sha256_text(POPULATION_PATH.read_text(encoding="utf-8")):
        raise ValueError("authored-gold population manifest is stale")
    _validate_terminal_manifest(manifest)
    project_root = root / "projects" / project.lower()
    authoring = read_json(project_root / "authoring.json")
    if authoring.get("schema_version") != GOLD_PROJECT_SCHEMA:
        raise ValueError(f"{project}: unexpected gold-authoring schema")
    if authoring.get("project_id") != project:
        raise ValueError(f"{project}: authored-gold project identity differs")
    manifest_summary = next(
        (
            item
            for item in manifest.get("projects", [])
            if item.get("project_id") == project
        ),
        None,
    )
    if not isinstance(manifest_summary, dict):
        raise ValueError(f"{project}: project is absent from the gold-run summary")
    if manifest_summary.get("authoring_sha256") != sha256_json(authoring):
        raise ValueError(f"{project}: stale project authoring hash differs")
    if manifest_summary.get("report_sha256") != authoring.get("report_sha256"):
        raise ValueError(f"{project}: stale project report identity differs")

    context, store, identity, plan = _current_project_identity(project)
    for key in (
        "benchmark_version",
        "template_id",
        "contract_sha256",
        "prepared_evidence_sha256",
        "prepared_twin_sha256",
        "prepared_reference_sha256",
        "calculated_store_sha256",
        "catalogue_sha256",
        "calculation_registry_sha256",
        "source_normalization_sha256",
        "enrichment_sha256",
    ):
        if authoring.get(key) != identity.get(key):
            raise ValueError(f"{project}: authored gold has stale {key}")

    _validate_manifest_project_identity(
        manifest,
        authoring,
        plan=plan,
        project=project,
    )
    checkpoint_records = _validate_project_checkpoints(
        project_root,
        authoring,
        project=project,
        plan=plan,
        provider_identity=manifest["identity"]["provider"],
    )

    generated_path = project_root / "generated.md"
    if not generated_path.is_file():
        raise ValueError(f"{project}: no complete generated draft exists to review")
    generated = generated_path.read_text(encoding="utf-8")
    if generated != _render_generated_from_checkpoints(plan, checkpoint_records):
        raise ValueError(
            f"{project}: generated report differs from component checkpoints"
        )
    if authoring.get("report_sha256") != sha256_text(generated):
        raise ValueError(f"{project}: generated draft hash differs")
    _validate_authoring_aggregates(
        authoring,
        plan=plan,
        records=checkpoint_records,
        generated=generated,
        project_root=project_root,
    )
    if manifest_summary != _project_summary_from_authoring(authoring):
        raise ValueError(f"{project}: project summary provenance differs")
    reviewed = source_path.read_text(encoding="utf-8")
    validation = validate_report_markdown(
        reviewed,
        report_output_contract(context.contract),
        expected_title=str(store.get("dt.project.title").get("value") or ""),
        allowed_ids=store.all_ids(),
    )
    if not validation["valid"]:
        raise GoldReviewValidationError(
            f"{project}: reviewed report fails current contract validation: "
            + ", ".join(sorted({item["code"] for item in validation["errors"]}))
        )
    component_citation_qa = _report_component_citation_qa(reviewed, plan)
    if not component_citation_qa["passed"]:
        raise GoldReviewValidationError(
            f"{project}: reviewed report fails status-aware citation validation: "
            + ", ".join(component_citation_qa["failing_component_ids"])
        )
    canonical = render_report(
        store,
        contract=context.contract,
        data_catalogue=context.catalogue,
    )
    if _table_raws(reviewed) != _table_raws(canonical):
        raise GoldReviewValidationError(
            f"{project}: reviewed report changes deterministic tables"
        )

    reviewed_path = project_root / "reviewed.md"
    review_path = project_root / "review.json"
    review = {
        "schema_version": GOLD_REVIEW_SCHEMA,
        "project_id": project,
        "status": "approved",
        "reviewer": reviewer_name,
        "review_note": note,
        "reviewed_at": _utc_now(),
        "authoring_sha256": sha256_json(authoring),
        "contract_sha256": identity["contract_sha256"],
        "prepared_evidence_sha256": identity["prepared_evidence_sha256"],
        "generated_report_sha256": sha256_text(generated),
        "reviewed_report_sha256": sha256_text(reviewed),
        "component_edits": _review_component_edits(
            generated,
            reviewed,
            context.contract,
        ),
        "validation": validation,
        "citation_qa": component_citation_qa,
    }
    _preflight_immutable_text(reviewed_path, reviewed)
    _preflight_immutable_json(review_path, review)
    _write_immutable_text(reviewed_path, reviewed)
    _write_immutable_json(review_path, review)
    return review


def _selected_project_ids(project_ids: list[str] | None) -> list[str]:
    population_order = list(project_specialisation_assignments())
    if project_ids is None:
        return population_order
    requested = [str(item or "").strip().upper() for item in project_ids]
    if not requested or any(not item for item in requested):
        raise ValueError("project selection must contain non-empty project IDs")
    if len(set(requested)) != len(requested):
        raise ValueError("project selection contains duplicate IDs")
    unknown = sorted(set(requested) - set(population_order))
    if unknown:
        raise ValueError(
            "projects outside the authoritative population: " + ", ".join(unknown)
        )
    requested_set = set(requested)
    return [item for item in population_order if item in requested_set]


def _provider_identity(
    provider: Provider,
    explicit: dict[str, Any] | None,
) -> dict[str, Any]:
    identity = {
        "provider": str(getattr(provider, "name", "")),
        "model": str(getattr(provider, "model", "")),
        "endpoint": getattr(provider, "endpoint", None),
        "max_output_tokens": getattr(
            provider,
            "max_output_tokens",
            getattr(provider, "max_tokens", None),
        ),
        "reasoning_effort": getattr(provider, "reasoning_effort", None),
        "timeout_seconds": getattr(provider, "timeout_seconds", None),
    }
    allowed = set(identity)
    unknown = sorted(set(explicit or {}) - allowed)
    if unknown:
        raise ValueError(
            "gold provider configuration contains unsupported fields: "
            + ", ".join(unknown)
        )
    for key, value in (explicit or {}).items():
        actual = identity[key]
        if actual is not None and value != actual:
            raise ValueError(
                f"gold provider configuration conflicts with effective {key}"
            )
        if actual is None:
            identity[key] = value
    if not identity["provider"] or not identity["model"]:
        raise ValueError("gold provider must expose non-empty name and model")
    endpoint = identity.get("endpoint")
    if endpoint is not None:
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise ValueError("gold provider endpoint must be a non-empty string")
        parsed = urlsplit(endpoint)
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError("gold provider endpoint contains unsafe credentials")
        sensitive_fragments = (
            "key",
            "token",
            "secret",
            "signature",
            "authorization",
            "credential",
        )
        if any(
            any(fragment in key.lower() for fragment in sensitive_fragments)
            for key, _ in parse_qsl(parsed.query, keep_blank_values=True)
        ):
            raise ValueError(
                "gold provider endpoint contains a sensitive query parameter"
            )
    return identity


def _build_project_plan(project_id: str) -> dict[str, Any]:
    twin = read_json(NORMALIZED_ROOT / f"{project_id.lower()}.json")
    context = resolve_runtime_context(twin)
    store = EvidenceStore(context.twin, context.reference)
    calculation_result = calculate_all(
        Calculator(store, registry=calculation_registry(context.contract))
    )
    invalid = [
        item["id"]
        for item in calculation_result["results"]
        if item.get("status") not in {"available", "not_applicable_dependency"}
    ]
    if invalid:
        raise ValueError(
            f"{project_id}: cannot author gold with unresolved calculations: "
            + ", ".join(invalid)
        )

    contract_sha256 = sha256_json(context.contract)
    prepared_twin_sha256 = sha256_json(context.twin)
    prepared_reference_sha256 = sha256_json(context.reference)
    prepared_evidence_sha256 = sha256_json(
        {"twin": context.twin, "reference": context.reference}
    )
    source = load_source_normalization(project_id)
    enrichment = load_enrichment(project_id)
    components = []
    registry = calculation_registry(context.contract)
    calculated_store_sha256 = sha256_json(
        {
            node_id: store.get(node_id)
            for node_id in sorted(store.all_ids())
        }
    )
    for section in section_contracts(context.contract):
        for component in section["required_components"]:
            if component["kind"] != "llm":
                continue
            packet = _component_prompt_packet(
                context=context,
                store=store,
                registry=registry,
                section=section,
                component=component,
            )
            messages = [
                {"role": "system", "content": GOLD_SYSTEM_PROMPT},
                {"role": "user", "content": _render_prompt_packet(packet)},
            ]
            components.append(
                {
                    "component_id": component["id"],
                    "section_id": section["id"],
                    "instructions": component["instructions"],
                    "required_ids": list(component["required_ids"]),
                    "prompt_packet": packet,
                    "messages": messages,
                    "prompt_sha256": sha256_json(messages),
                }
            )
    if len(components) != 15:
        raise ValueError(
            f"{project_id}: expected 15 current-contract llm components, got "
            f"{len(components)}"
        )
    component_ids = [item["component_id"] for item in components]
    if len(set(component_ids)) != len(component_ids):
        raise ValueError(f"{project_id}: component IDs must be unique")
    return {
        "project_id": project_id,
        "template_id": context.template_id,
        "benchmark_version": context.contract["benchmark_version"],
        "contract": context.contract,
        "contract_sha256": contract_sha256,
        "template_sha256": context.contract["template_sha256"],
        "prepared_evidence_sha256": prepared_evidence_sha256,
        "prepared_twin_sha256": prepared_twin_sha256,
        "prepared_reference_sha256": prepared_reference_sha256,
        "calculated_store_sha256": calculated_store_sha256,
        "catalogue_sha256": sha256_json(context.catalogue),
        "calculation_registry_sha256": sha256_json(registry),
        "source_normalization_sha256": sha256_json(source),
        "enrichment_sha256": sha256_json(enrichment),
        "context": context,
        "store": store,
        "components": components,
    }


def _component_prompt_packet(
    *,
    context: Any,
    store: EvidenceStore,
    registry: dict[str, dict[str, Any]],
    section: dict[str, Any],
    component: dict[str, Any],
) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    calculations: dict[str, Any] = {}
    for node_id in component["required_ids"]:
        resolved = store.get(node_id)
        if node_id.startswith("calc."):
            definition = registry[node_id]
            calculations[node_id] = {
                "description": definition.get("description"),
                "unit": definition.get("unit"),
                "expression": definition.get("expression"),
                "dependencies": list(definition.get("input_ids", {}).values()),
                "resolved": resolved,
            }
        else:
            evidence[node_id] = {
                "description": context.catalogue.get("data", {})
                .get(node_id, {})
                .get("description"),
                "resolved": resolved,
            }
    return {
        "schema_version": "react_report.gold_prompt_packet/v5",
        "project_id": context.project_id,
        "template_id": context.template_id,
        "benchmark_version": context.contract["benchmark_version"],
        "section_id": section["id"],
        "component_id": component["id"],
        "instructions": component["instructions"],
        "required_citation_ids": list(component["required_ids"]),
        "usable_evidence": evidence,
        "derivable_calculations": calculations,
    }


def _render_prompt_packet(packet: dict[str, Any]) -> str:
    return (
        f"PROJECT AND COMPONENT:\n"
        f"{compact_json({key: packet[key] for key in ('project_id', 'template_id', 'section_id', 'component_id')})}\n\n"
        f"INSTRUCTIONS:\n{packet['instructions']}\n\n"
        f"REQUIRED CITATION IDS:\n{compact_json(packet['required_citation_ids'])}\n\n"
        f"USABLE EVIDENCE:\n{compact_json(packet['usable_evidence'])}\n\n"
        f"DERIVABLE CALCULATIONS:\n{compact_json(packet['derivable_calculations'])}"
    )


def _run_identity(
    project_ids: list[str],
    provider_identity: dict[str, Any],
    plans: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "benchmark_versions": sorted(
            {plan["benchmark_version"] for plan in plans}
        ),
        "population_manifest": {
            "path": "v2/data/study/twenty-project-study-population.json",
            "sha256": sha256_text(POPULATION_PATH.read_text(encoding="utf-8")),
        },
        "project_ids": project_ids,
        "provider": provider_identity,
        "generation": {
            "recipe": "llm",
            "calls_per_component": 1,
            "agent_tools": [],
            "component_schema": GOLD_COMPONENT_SCHEMA,
            "citation_qa_contract": (
                "required_ids_status_and_collection_coverage/v3"
            ),
            "system_prompt_sha256": sha256_text(GOLD_SYSTEM_PROMPT),
        },
        "projects": [_project_run_identity(plan) for plan in plans],
    }


def _project_run_identity(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": plan["project_id"],
        "template_id": plan["template_id"],
        "contract_sha256": plan["contract_sha256"],
        "template_sha256": plan["template_sha256"],
        "prepared_evidence_sha256": plan["prepared_evidence_sha256"],
        "prepared_twin_sha256": plan["prepared_twin_sha256"],
        "prepared_reference_sha256": plan["prepared_reference_sha256"],
        "calculated_store_sha256": plan["calculated_store_sha256"],
        "catalogue_sha256": plan["catalogue_sha256"],
        "calculation_registry_sha256": plan[
            "calculation_registry_sha256"
        ],
        "source_normalization_sha256": plan[
            "source_normalization_sha256"
        ],
        "enrichment_sha256": plan["enrichment_sha256"],
        "component_prompt_sha256": {
            item["component_id"]: item["prompt_sha256"]
            for item in plan["components"]
        },
    }


def _gold_component_identity(
    plan: dict[str, Any],
    component: dict[str, Any],
    provider_identity: dict[str, Any],
) -> dict[str, Any]:
    return {
        "project_id": plan["project_id"],
        "template_id": plan["template_id"],
        "benchmark_version": plan["benchmark_version"],
        "contract_sha256": plan["contract_sha256"],
        "prepared_evidence_sha256": plan["prepared_evidence_sha256"],
        "provider": provider_identity,
        "section_id": component["section_id"],
        "component_id": component["component_id"],
        "required_ids": component["required_ids"],
        "prompt_sha256": component["prompt_sha256"],
        "citation_qa_contract": "required_ids_status_and_collection_coverage/v3",
    }


def _author_project(
    provider: Provider,
    *,
    provider_identity: dict[str, Any],
    root: Path,
    plan: dict[str, Any],
    resume: bool,
    invocation: dict[str, Any],
    checkpoint_callback: Any,
) -> dict[str, Any]:
    project_id = plan["project_id"]
    project_root = root / "projects" / project_id.lower()
    checkpoint_root = project_root / "components"
    records: dict[str, dict[str, Any]] = {}

    expected_names = {
        f"{item['component_id']}.json" for item in plan["components"]
    }
    if checkpoint_root.is_dir():
        extras = sorted(
            path.name
            for path in checkpoint_root.iterdir()
            if not path.is_file() or path.name not in expected_names
        )
        if extras:
            raise ValueError(
                f"{project_id}: unexpected component checkpoints: "
                + ", ".join(extras)
            )

    for component in plan["components"]:
        component_id = component["component_id"]
        checkpoint_path = checkpoint_root / f"{component_id}.json"
        component_identity = _gold_component_identity(
            plan,
            component,
            provider_identity,
        )
        identity_sha256 = sha256_json(component_identity)
        if checkpoint_path.is_file():
            if not resume:
                raise ValueError(
                    f"{project_id}/{component_id}: checkpoint already exists"
                )
            record = read_json(checkpoint_path)
            _validate_checkpoint_against_component(
                record,
                plan,
                component,
                provider_identity,
                checkpoint_path=checkpoint_path,
                project=project_id,
            )
            invocation["reused_checkpoints"] += 1
        else:
            episode = GoldComponentEpisode(
                episode_id=(
                    f"{project_id.lower()}.v2.gold.{plan['template_id']}."
                    f"{component_id}"
                ),
                project_id=project_id,
                template_id=plan["template_id"],
                section_id=component["section_id"],
                component_id=component_id,
                required_ids=tuple(component["required_ids"]),
                not_applicable_ids=tuple(
                    _not_applicable_required_ids(component["prompt_packet"])
                ),
            )
            invocation["provider_calls"] += 1
            response = provider.complete(component["messages"], episode=episode)
            record = {
                "schema_version": GOLD_COMPONENT_SCHEMA,
                "identity": component_identity,
                "identity_sha256": identity_sha256,
                "created_at": _utc_now(),
                "status": "generated",
                "request": {
                    "messages": component["messages"],
                    "messages_sha256": component["prompt_sha256"],
                    "prompt_packet": component["prompt_packet"],
                    "prompt_packet_sha256": sha256_json(
                        component["prompt_packet"]
                    ),
                },
                "response": {
                    "provider_request_id": response.provider_request_id,
                    "raw_output": response.text,
                    "raw_output_sha256": sha256_text(str(response.text or "")),
                    "metadata": _safe_response_metadata(response.raw_response),
                    "usage": response.usage,
                    "latency_seconds": response.latency_seconds,
                    "protocol_error": response.protocol_error,
                    "tool_call_count": len(response.tool_calls or []),
                },
            }
            response_error = _response_completion_error(response)
            try:
                if response_error is not None:
                    raise ValueError(response_error)
                generated_output = _clean_paragraph(response.text)
            except ValueError as exc:
                record["status"] = "invalid_output"
                record["output_error"] = str(exc)
                record["generated_output"] = None
                record["generated_output_sha256"] = None
                record["citation_qa"] = None
            else:
                record["generated_output"] = generated_output
                record["generated_output_sha256"] = sha256_text(generated_output)
                record["citation_qa"] = _component_citation_qa(
                    generated_output,
                    component["required_ids"],
                    component["prompt_packet"],
                )
            _write_immutable_json(checkpoint_path, record)
        records[component_id] = record
        checkpoint_callback(_checkpoint_progress(records))

    clean_records = {
        component_id: record
        for component_id, record in records.items()
        if record.get("status") == "generated"
        and isinstance(record.get("generated_output"), str)
    }
    output_failures = sorted(set(records) - set(clean_records))
    report = render_report(
        plan["store"],
        {
            component_id: (
                record["generated_output"]
                if component_id in clean_records
                else _invalid_component_placeholder(component_id)
            )
            for component_id, record in records.items()
        },
        contract=plan["contract"],
        data_catalogue=plan["context"].catalogue,
    )
    report_validation = _generated_report_validation(plan, records, report)

    failing_citations = sorted(
        component_id
        for component_id, record in records.items()
        if not isinstance(record.get("citation_qa"), dict)
        or record["citation_qa"].get("passed") is not True
    )
    valid = not output_failures and not failing_citations and report_validation["valid"]
    usage = _aggregate_usage(records.values())
    authoring = {
        "schema_version": GOLD_PROJECT_SCHEMA,
        "benchmark_version": plan["benchmark_version"],
        "project_id": project_id,
        "template_id": plan["template_id"],
        "contract_id": plan["template_id"],
        "contract_sha256": plan["contract_sha256"],
        "template_sha256": plan["template_sha256"],
        "compiler_pin": plan["contract"].get("compiler_pin"),
        "prepared_evidence_sha256": plan["prepared_evidence_sha256"],
        "prepared_twin_sha256": plan["prepared_twin_sha256"],
        "prepared_reference_sha256": plan["prepared_reference_sha256"],
        "calculated_store_sha256": plan["calculated_store_sha256"],
        "catalogue_sha256": plan["catalogue_sha256"],
        "calculation_registry_sha256": plan["calculation_registry_sha256"],
        "source_normalization_sha256": plan["source_normalization_sha256"],
        "enrichment_sha256": plan["enrichment_sha256"],
        "provider": provider_identity,
        "generation_recipe": "llm",
        "expected_generation_count": len(plan["components"]),
        "generation_count": len(records),
        "valid": valid,
        "status": "generated" if valid else "generated_with_qa_failures",
        "citation_qa": {
            "passing_component_count": len(records) - len(failing_citations),
            "failing_component_ids": failing_citations,
        },
        "output_failures": output_failures,
        "report_validation": report_validation,
        "report_sha256": sha256_text(report),
        "usage": usage,
        "latency_seconds": sum(
            float(record.get("response", {}).get("latency_seconds") or 0.0)
            for record in records.values()
        ),
        "review": _pending_review_metadata(),
        "components": {
            component_id: _component_summary(record, project_root)
            for component_id, record in records.items()
        },
    }
    _write_immutable_text(project_root / "generated.md", report)
    _write_immutable_json(project_root / "authoring.json", authoring)
    return {
        "project_id": project_id,
        "template_id": plan["template_id"],
        "valid": valid,
        "status": authoring["status"],
        "expected_generation_count": len(plan["components"]),
        "generation_count": len(records),
        "citation_failure_count": len(failing_citations),
        "output_failure_count": len(output_failures),
        "report_validation_valid": report_validation["valid"],
        "authoring_sha256": sha256_json(authoring),
        "report_sha256": authoring["report_sha256"],
        "usage": usage,
        "latency_seconds": authoring["latency_seconds"],
        "authoring_path": str(
            (Path("projects") / project_id.lower() / "authoring.json")
        ),
        "generated_report_path": (
            str(Path("projects") / project_id.lower() / "generated.md")
        ),
    }


def _validate_resume_manifest_shape(
    manifest: dict[str, Any],
    plans: list[dict[str, Any]],
) -> None:
    expected_ids = [plan["project_id"] for plan in plans]
    summaries = manifest.get("projects")
    if not isinstance(summaries, list) or [
        item.get("project_id") if isinstance(item, dict) else None
        for item in summaries
    ] != expected_ids:
        raise ValueError("cannot resume: gold-run project summaries differ")
    if manifest.get("project_count") != len(plans):
        raise ValueError("cannot resume: gold-run project count differs")
    expected_generation_count = sum(
        len(plan["components"]) for plan in plans
    )
    if manifest.get("expected_generation_count") != expected_generation_count:
        raise ValueError("cannot resume: expected generation count differs")
    if not isinstance(manifest.get("invocations"), list):
        raise ValueError("cannot resume: gold-run invocation history is invalid")


def _preflight_resume_artifacts(
    root: Path,
    manifest: dict[str, Any],
    *,
    plans: list[dict[str, Any]],
    provider_identity: dict[str, Any],
) -> None:
    projects_root = root / "projects"
    if projects_root.exists() and not projects_root.is_dir():
        raise ValueError("cannot resume: projects artifact path is not a directory")
    summaries = {
        item["project_id"]: item for item in manifest.get("projects", [])
    }
    for plan in plans:
        project = plan["project_id"]
        project_root = root / "projects" / project.lower()
        if not project_root.exists():
            continue
        if not project_root.is_dir():
            raise ValueError(f"{project}: project artifact path is not a directory")
        component_root = project_root / "components"
        expected_components = {
            item["component_id"]: item for item in plan["components"]
        }
        expected_names = {
            f"{component_id}.json" for component_id in expected_components
        }
        actual_names: set[str] = set()
        records: dict[str, dict[str, Any]] = {}
        if component_root.exists():
            if not component_root.is_dir():
                raise ValueError(
                    f"{project}: component artifact path is not a directory"
                )
            component_entries = list(component_root.iterdir())
            non_files = sorted(
                path.name for path in component_entries if not path.is_file()
            )
            if non_files:
                raise ValueError(
                    f"{project}: non-file component artifacts: "
                    + ", ".join(non_files)
                )
            actual_names = {path.name for path in component_entries}
            extras = sorted(actual_names - expected_names)
            if extras:
                raise ValueError(
                    f"{project}: unexpected component checkpoints: "
                    + ", ".join(extras)
                )
            for component_id, component in expected_components.items():
                checkpoint_path = component_root / f"{component_id}.json"
                if not checkpoint_path.is_file():
                    continue
                checkpoint = read_json(checkpoint_path)
                _validate_checkpoint_against_component(
                    checkpoint,
                    plan,
                    component,
                    provider_identity,
                    checkpoint_path=checkpoint_path,
                    project=project,
                )
                records[component_id] = checkpoint

        authoring_path = project_root / "authoring.json"
        generated_path = project_root / "generated.md"
        authoring: dict[str, Any] | None = None
        if (authoring_path.is_file() or generated_path.is_file()) and (
            actual_names != expected_names
        ):
            raise ValueError(
                f"{project}: finalized artifacts require all 15 checkpoints"
            )

        if authoring_path.is_file():
            authoring = read_json(authoring_path)
            if authoring.get("schema_version") != GOLD_PROJECT_SCHEMA:
                raise ValueError(f"{project}: unexpected gold-authoring schema")
            if authoring.get("project_id") != project:
                raise ValueError(f"{project}: authored-gold project identity differs")
            _validate_manifest_project_identity(
                manifest,
                authoring,
                plan=plan,
                project=project,
            )
            for key in (
                "benchmark_version",
                "template_id",
                "contract_sha256",
                "prepared_evidence_sha256",
                "prepared_twin_sha256",
                "prepared_reference_sha256",
                "calculated_store_sha256",
                "catalogue_sha256",
                "calculation_registry_sha256",
                "source_normalization_sha256",
                "enrichment_sha256",
            ):
                if authoring.get(key) != plan.get(key):
                    raise ValueError(f"{project}: authored gold has stale {key}")
            summary = summaries[project]
            if summary.get("authoring_sha256") not in {
                None,
                sha256_json(authoring),
            }:
                raise ValueError(f"{project}: stale project authoring hash differs")
            if summary.get("report_sha256") not in {
                None,
                authoring.get("report_sha256"),
            }:
                raise ValueError(f"{project}: stale project report identity differs")
            records = _validate_project_checkpoints(
                project_root,
                authoring,
                project=project,
                plan=plan,
                provider_identity=provider_identity,
            )

        if generated_path.is_file():
            generated = generated_path.read_text(encoding="utf-8")
            recomposed = _render_generated_from_checkpoints(plan, records)
            if recomposed is None or generated != recomposed:
                raise ValueError(
                    f"{project}: generated report differs from component checkpoints"
                )
            if authoring is not None and authoring.get(
                "report_sha256"
            ) != sha256_text(generated):
                raise ValueError(f"{project}: generated gold hash differs")
            if authoring is not None:
                _validate_authoring_aggregates(
                    authoring,
                    plan=plan,
                    records=records,
                    generated=generated,
                    project_root=project_root,
                )
                if summary.get("authoring_sha256") is not None and summary != (
                    _project_summary_from_authoring(authoring)
                ):
                    raise ValueError(
                        f"{project}: project summary provenance differs"
                    )
        elif authoring is not None and authoring.get("report_sha256") is not None:
            raise ValueError(f"{project}: generated report artifact is absent")


def _render_generated_from_checkpoints(
    plan: dict[str, Any],
    records: dict[str, dict[str, Any]],
) -> str | None:
    component_ids = {
        item["component_id"] for item in plan["components"]
    }
    if set(records) != component_ids:
        return None
    return render_report(
        plan["store"],
        {
            component_id: (
                records[component_id]["generated_output"]
                if records[component_id].get("status") == "generated"
                and isinstance(
                    records[component_id].get("generated_output"), str
                )
                else _invalid_component_placeholder(component_id)
            )
            for component_id in component_ids
        },
        contract=plan["contract"],
        data_catalogue=plan["context"].catalogue,
    )


def _generated_report_validation(
    plan: dict[str, Any],
    records: dict[str, dict[str, Any]],
    report: str,
) -> dict[str, Any]:
    validation = validate_report_markdown(
        report,
        report_output_contract(plan["contract"]),
        expected_title=str(
            plan["store"].get("dt.project.title").get("value") or ""
        ),
        allowed_ids=plan["store"].all_ids(),
    )
    output_failures = sorted(
        component_id
        for component_id, record in records.items()
        if record.get("status") != "generated"
        or not isinstance(record.get("generated_output"), str)
    )
    if not output_failures:
        return validation
    return {
        **validation,
        "valid": False,
        "errors": list(validation.get("errors") or [])
        + [
            {
                "code": "invalid_component_output",
                "component_id": component_id,
                "message": str(records[component_id].get("output_error") or ""),
            }
            for component_id in output_failures
        ],
    }


def _invalid_component_placeholder(component_id: str) -> str:
    return (
        "Manual repair required: the provider did not return a complete valid "
        f"paragraph for component {component_id}."
    )


def _pending_review_metadata() -> dict[str, Any]:
    return {
        "status": "pending_manual_review",
        "generated_report": "generated.md",
        "reviewed_report": "reviewed.md",
        "review_manifest": "review.json",
        "policy": (
            "Component checkpoints and generated.md are immutable provenance. "
            "Human-reviewed gold is a separate reviewed.md plus an approved, "
            "hash-bound review.json sidecar."
        ),
    }


def _pending_project_summary(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": plan["project_id"],
        "template_id": plan["template_id"],
        "valid": False,
        "status": "pending",
        "expected_generation_count": len(plan["components"]),
        "generation_count": 0,
        "usage": {},
        "latency_seconds": 0.0,
    }


def _checkpoint_progress(
    records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "generation_count": len(records),
        "usage": _aggregate_usage(records.values()),
        "latency_seconds": sum(
            float(record.get("response", {}).get("latency_seconds") or 0.0)
            for record in records.values()
        ),
    }


def _record_checkpoint_progress(
    manifest: dict[str, Any],
    manifest_path: Path,
    *,
    project_index: int,
    completed: dict[str, Any],
    invocation: dict[str, Any],
) -> None:
    summary = manifest["projects"][project_index]
    summary.update(completed)
    summary["status"] = "in_progress"
    manifest["invocations"][-1] = invocation
    manifest["updated_at"] = _utc_now()
    _refresh_run_totals(manifest)
    write_json(manifest_path, manifest)


def _refresh_run_totals(manifest: dict[str, Any]) -> None:
    projects = manifest.get("projects", [])
    manifest["generation_count"] = sum(
        int(item.get("generation_count") or 0) for item in projects
    )
    manifest["provider_call_count"] = sum(
        int(item.get("provider_calls") or 0)
        for item in manifest.get("invocations", [])
    )
    usage: dict[str, int] = {}
    for item in projects:
        for key, value in (item.get("usage") or {}).items():
            usage[key] = usage.get(key, 0) + int(value or 0)
    manifest["usage"] = usage
    manifest["latency_seconds"] = sum(
        float(item.get("latency_seconds") or 0.0) for item in projects
    )


def _aggregate_usage(records: Any) -> dict[str, int]:
    totals: dict[str, int] = {}
    for record in records:
        for key, value in (record.get("response", {}).get("usage") or {}).items():
            totals[str(key)] = totals.get(str(key), 0) + int(value or 0)
    return totals


def _component_summary(
    record: dict[str, Any],
    project_root: Path,
) -> dict[str, Any]:
    identity = record["identity"]
    component_id = identity["component_id"]
    return {
        "component_id": component_id,
        "section_id": identity["section_id"],
        "status": record["status"],
        "checkpoint": str(Path("components") / f"{component_id}.json"),
        "checkpoint_sha256": sha256_json(record),
        "required_ids": identity["required_ids"],
        "generated_output": record.get("generated_output"),
        "generated_output_sha256": record.get("generated_output_sha256"),
        "citation_qa": record.get("citation_qa"),
        "usage": record.get("response", {}).get("usage") or {},
        "latency_seconds": record.get("response", {}).get("latency_seconds"),
        "provider_request_id": record.get("response", {}).get(
            "provider_request_id"
        ),
    }


def _validate_authoring_aggregates(
    authoring: dict[str, Any],
    *,
    plan: dict[str, Any],
    records: dict[str, dict[str, Any]],
    generated: str,
    project_root: Path,
) -> None:
    project = plan["project_id"]
    output_failures = sorted(
        component_id
        for component_id, record in records.items()
        if record.get("status") != "generated"
        or not isinstance(record.get("generated_output"), str)
    )
    failing_citations = sorted(
        component_id
        for component_id, record in records.items()
        if not isinstance(record.get("citation_qa"), dict)
        or record["citation_qa"].get("passed") is not True
    )
    report_validation = _generated_report_validation(plan, records, generated)
    valid = (
        not output_failures
        and not failing_citations
        and report_validation["valid"]
    )
    expected = {
        "contract_id": plan["template_id"],
        "template_sha256": plan["template_sha256"],
        "compiler_pin": plan["contract"].get("compiler_pin"),
        "generation_recipe": "llm",
        "expected_generation_count": len(plan["components"]),
        "generation_count": len(records),
        "valid": valid,
        "status": "generated" if valid else "generated_with_qa_failures",
        "citation_qa": {
            "passing_component_count": len(records) - len(failing_citations),
            "failing_component_ids": failing_citations,
        },
        "output_failures": output_failures,
        "report_validation": report_validation,
        "report_sha256": sha256_text(generated),
        "usage": _aggregate_usage(records.values()),
        "latency_seconds": sum(
            float(record.get("response", {}).get("latency_seconds") or 0.0)
            for record in records.values()
        ),
        "review": _pending_review_metadata(),
        "components": {
            component_id: _component_summary(record, project_root)
            for component_id, record in records.items()
        },
    }
    for key, value in expected.items():
        if authoring.get(key) != value:
            raise ValueError(f"{project}: authored-gold aggregate {key} differs")


def _project_summary_from_authoring(
    authoring: dict[str, Any],
) -> dict[str, Any]:
    project = authoring["project_id"]
    return {
        "project_id": project,
        "template_id": authoring["template_id"],
        "valid": authoring["valid"],
        "status": authoring["status"],
        "expected_generation_count": authoring["expected_generation_count"],
        "generation_count": authoring["generation_count"],
        "citation_failure_count": len(
            authoring["citation_qa"]["failing_component_ids"]
        ),
        "output_failure_count": len(authoring["output_failures"]),
        "report_validation_valid": authoring["report_validation"]["valid"],
        "authoring_sha256": sha256_json(authoring),
        "report_sha256": authoring["report_sha256"],
        "usage": authoring["usage"],
        "latency_seconds": authoring["latency_seconds"],
        "authoring_path": str(
            Path("projects") / project.lower() / "authoring.json"
        ),
        "generated_report_path": str(
            Path("projects") / project.lower() / "generated.md"
        ),
    }


def _validate_terminal_manifest(manifest: dict[str, Any]) -> None:
    identity = manifest.get("identity")
    summaries = manifest.get("projects")
    if not isinstance(identity, dict) or not isinstance(summaries, list):
        raise ValueError("authored-gold terminal manifest is malformed")
    project_ids = identity.get("project_ids")
    if not isinstance(project_ids, list) or [
        item.get("project_id") if isinstance(item, dict) else None
        for item in summaries
    ] != project_ids:
        raise ValueError("authored-gold project summaries are duplicated or reordered")
    identity_projects = identity.get("projects")
    if not isinstance(identity_projects, list) or [
        item.get("project_id") if isinstance(item, dict) else None
        for item in identity_projects
    ] != project_ids:
        raise ValueError("authored-gold project identities are duplicated or reordered")
    if manifest.get("project_count") != len(project_ids):
        raise ValueError("authored-gold project count differs")
    expected_generation_count = sum(
        len(item.get("component_prompt_sha256", {}))
        for item in identity_projects
    )
    if manifest.get("expected_generation_count") != expected_generation_count:
        raise ValueError("authored-gold expected generation count differs")
    generation_count = sum(
        int(item.get("generation_count") or 0) for item in summaries
    )
    if manifest.get("generation_count") != generation_count:
        raise ValueError("authored-gold generation count differs")
    usage: dict[str, int] = {}
    for summary in summaries:
        for key, value in (summary.get("usage") or {}).items():
            usage[str(key)] = usage.get(str(key), 0) + int(value or 0)
    if manifest.get("usage", {}) != usage:
        raise ValueError("authored-gold usage aggregate differs")
    latency = sum(
        float(item.get("latency_seconds") or 0.0) for item in summaries
    )
    if manifest.get("latency_seconds", 0.0) != latency:
        raise ValueError("authored-gold latency aggregate differs")
    invocations = manifest.get("invocations")
    if not isinstance(invocations, list) or not invocations:
        raise ValueError("authored-gold invocation history is absent")
    for invocation in invocations:
        if not isinstance(invocation, dict) or invocation.get("status") not in {
            "completed",
            "interrupted",
        }:
            raise ValueError("authored-gold invocation history is nonterminal")
        if not invocation.get("started_at") or not invocation.get("finished_at"):
            raise ValueError("authored-gold invocation timestamps are incomplete")
        for key in ("provider_calls", "reused_checkpoints"):
            value = invocation.get(key)
            if not isinstance(value, int) or value < 0:
                raise ValueError("authored-gold invocation counts are invalid")
    provider_calls = sum(item["provider_calls"] for item in invocations)
    if manifest.get("provider_call_count") != provider_calls:
        raise ValueError("authored-gold provider-attempt count differs")
    expected_valid = all(item.get("valid") is True for item in summaries)
    expected_status = (
        "completed" if expected_valid else "completed_with_qa_failures"
    )
    if manifest.get("valid") is not expected_valid:
        raise ValueError("authored-gold terminal validity differs")
    if manifest.get("status") != expected_status:
        raise ValueError("authored-gold terminal status differs")


def _validate_component_checkpoint(
    record: dict[str, Any],
    *,
    identity_sha256: str,
    checkpoint_path: Path,
) -> None:
    if record.get("schema_version") != GOLD_COMPONENT_SCHEMA:
        raise ValueError(f"unexpected checkpoint schema: {checkpoint_path}")
    identity = record.get("identity")
    if not isinstance(identity, dict):
        raise ValueError(f"checkpoint identity is absent: {checkpoint_path}")
    if record.get("identity_sha256") != sha256_json(identity):
        raise ValueError(f"altered checkpoint identity: {checkpoint_path}")
    if record.get("identity_sha256") != identity_sha256:
        raise ValueError(f"stale or mismatched checkpoint: {checkpoint_path}")
    if record.get("status") not in {"generated", "invalid_output"}:
        raise ValueError(f"nonterminal checkpoint status: {checkpoint_path}")
    raw = str(record.get("response", {}).get("raw_output") or "")
    if record.get("response", {}).get("raw_output_sha256") != sha256_text(raw):
        raise ValueError(f"altered raw checkpoint output: {checkpoint_path}")
    generated = record.get("generated_output")
    expected_generated_hash = (
        sha256_text(generated) if isinstance(generated, str) else None
    )
    if record.get("generated_output_sha256") != expected_generated_hash:
        raise ValueError(f"altered generated checkpoint output: {checkpoint_path}")


def _validate_project_checkpoints(
    project_root: Path,
    authoring: dict[str, Any],
    *,
    project: str,
    plan: dict[str, Any],
    provider_identity: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    component_root = project_root / "components"
    component_summaries = authoring.get("components")
    expected_components = {
        item["component_id"]: item for item in plan["components"]
    }
    if not isinstance(component_summaries, dict) or set(component_summaries) != set(
        expected_components
    ):
        raise ValueError(f"{project}: authored gold lacks 15 component checkpoints")
    if not component_root.is_dir():
        raise ValueError(f"{project}: component checkpoint directory is absent")
    expected_names = {
        f"{component_id}.json" for component_id in expected_components
    }
    component_entries = list(component_root.iterdir())
    if any(not path.is_file() for path in component_entries):
        raise ValueError(f"{project}: non-file component artifacts are not allowed")
    actual_names = {path.name for path in component_entries}
    if actual_names != expected_names:
        raise ValueError(f"{project}: component checkpoint file set differs")
    records: dict[str, dict[str, Any]] = {}
    for component_id, summary in component_summaries.items():
        component = expected_components[component_id]
        expected_relative = Path("components") / f"{component_id}.json"
        if summary.get("checkpoint") != str(expected_relative):
            raise ValueError(f"{project}: unsafe or mismatched checkpoint path")
        checkpoint_path = component_root / f"{component_id}.json"
        checkpoint = read_json(checkpoint_path)
        _validate_checkpoint_against_component(
            checkpoint,
            plan,
            component,
            provider_identity,
            checkpoint_path=checkpoint_path,
            project=project,
        )
        if summary.get("checkpoint_sha256") != sha256_json(checkpoint):
            raise ValueError(f"{project}: component checkpoint hash differs")
        if summary.get("component_id") != component_id:
            raise ValueError(f"{project}: component checkpoint ID differs")
        if summary.get("section_id") != component["section_id"]:
            raise ValueError(f"{project}: component checkpoint section differs")
        if summary.get("required_ids") != component["required_ids"]:
            raise ValueError(f"{project}: component required-ID set differs")
        if summary.get("generated_output_sha256") != checkpoint.get(
            "generated_output_sha256"
        ):
            raise ValueError(f"{project}: component output hash differs")
        records[component_id] = checkpoint
    return records


def _validate_checkpoint_against_component(
    checkpoint: dict[str, Any],
    plan: dict[str, Any],
    component: dict[str, Any],
    provider_identity: dict[str, Any],
    *,
    checkpoint_path: Path,
    project: str,
) -> None:
    expected_identity = _gold_component_identity(
        plan,
        component,
        provider_identity,
    )
    if checkpoint.get("identity") != expected_identity:
        raise ValueError(f"{project}: stale component checkpoint identity")
    _validate_component_checkpoint(
        checkpoint,
        identity_sha256=sha256_json(expected_identity),
        checkpoint_path=checkpoint_path,
    )
    request = checkpoint.get("request")
    if not isinstance(request, dict):
        raise ValueError(f"{project}: component request provenance is absent")
    if request.get("messages") != component["messages"]:
        raise ValueError(f"{project}: component messages differ")
    if request.get("messages_sha256") != component["prompt_sha256"]:
        raise ValueError(f"{project}: component message hash differs")
    if request.get("prompt_packet") != component["prompt_packet"]:
        raise ValueError(f"{project}: component prompt packet differs")
    if request.get("prompt_packet_sha256") != sha256_json(
        component["prompt_packet"]
    ):
        raise ValueError(f"{project}: component prompt-packet hash differs")
    response = checkpoint.get("response")
    if not isinstance(response, dict):
        raise ValueError(f"{project}: component response provenance is absent")
    completion_error = _completion_error(
        protocol_error=response.get("protocol_error"),
        tool_call_count=response.get("tool_call_count"),
        metadata=response.get("metadata"),
    )
    generated = checkpoint.get("generated_output")
    if checkpoint.get("status") == "generated":
        if completion_error is not None:
            raise ValueError(f"{project}: completed component response is invalid")
        if generated != _clean_paragraph(
            str(response.get("raw_output") or "")
        ):
            raise ValueError(f"{project}: cleaned component output differs")
        expected_qa = _component_citation_qa(
            generated,
            component["required_ids"],
            component["prompt_packet"],
        )
        if checkpoint.get("citation_qa") != expected_qa:
            raise ValueError(f"{project}: component citation QA differs")
    else:
        if generated is not None or checkpoint.get("citation_qa") is not None:
            raise ValueError(f"{project}: invalid component has generated content")
        expected_error = completion_error
        if expected_error is None:
            try:
                _clean_paragraph(str(response.get("raw_output") or ""))
            except ValueError as exc:
                expected_error = str(exc)
        if not expected_error or checkpoint.get("output_error") != expected_error:
            raise ValueError(f"{project}: invalid component error provenance differs")


def _validate_manifest_project_identity(
    manifest: dict[str, Any],
    authoring: dict[str, Any],
    *,
    plan: dict[str, Any],
    project: str,
) -> None:
    run_identity = manifest.get("identity")
    if not isinstance(run_identity, dict):
        raise ValueError("authored-gold run identity is absent")
    if project not in run_identity.get("project_ids", []):
        raise ValueError(f"{project}: project is absent from the gold-run identity")
    matches = [
        item
        for item in run_identity.get("projects", [])
        if isinstance(item, dict) and item.get("project_id") == project
    ]
    if len(matches) != 1 or matches[0] != _project_run_identity(plan):
        raise ValueError(f"{project}: current project run identity differs")
    provider_identity = run_identity.get("provider")
    if not isinstance(provider_identity, dict):
        raise ValueError("authored-gold provider identity is absent")
    if authoring.get("provider") != provider_identity:
        raise ValueError(f"{project}: authored-gold provider identity differs")


def _safe_response_metadata(raw_response: Any) -> dict[str, Any] | None:
    if not isinstance(raw_response, dict):
        return None
    keys = (
        "id",
        "object",
        "status",
        "incomplete_details",
        "stop_reason",
        "model",
        "created_at",
        "fixture",
        "turn",
    )
    metadata = {key: raw_response[key] for key in keys if key in raw_response}
    choices = raw_response.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        metadata["finish_reason"] = choices[0].get("finish_reason")
    return metadata


def _response_completion_error(response: Any) -> str | None:
    return _completion_error(
        protocol_error=response.protocol_error,
        tool_call_count=len(response.tool_calls or []),
        metadata=_safe_response_metadata(response.raw_response),
    )


def _completion_error(
    *,
    protocol_error: Any,
    tool_call_count: Any,
    metadata: Any,
) -> str | None:
    if protocol_error:
        return f"provider protocol error: {protocol_error}"
    if not isinstance(tool_call_count, int) or tool_call_count < 0:
        return "provider response has invalid tool-call metadata"
    if tool_call_count:
        return "tool calls are not allowed during oracle gold generation"
    if not isinstance(metadata, dict):
        return None
    status = str(metadata.get("status") or "").strip().lower()
    if status and status not in {"completed", "complete", "succeeded", "success"}:
        return (
            f"provider response status is {status!r}; incomplete_details="
            f"{metadata.get('incomplete_details')!r}"
        )
    if metadata.get("incomplete_details"):
        return (
            "provider response is incomplete: "
            f"{metadata['incomplete_details']!r}"
        )
    finish_reason = str(metadata.get("finish_reason") or "").strip().lower()
    if finish_reason and finish_reason not in {
        "stop",
        "end_turn",
        "stop_sequence",
        "completed",
    }:
        return f"provider response finish reason is {finish_reason!r}"
    stop_reason = str(metadata.get("stop_reason") or "").strip().lower()
    if stop_reason and stop_reason not in {"end_turn", "stop_sequence", "stop"}:
        return f"provider response stop reason is {stop_reason!r}"
    return None


def _component_citation_qa(
    text: str,
    required_ids: list[str],
    prompt_packet: dict[str, Any],
) -> dict[str, Any]:
    result = gold_citation_qa(text, required_ids)
    not_applicable_ids = _not_applicable_required_ids(prompt_packet)
    resolved_statuses = _resolved_node_statuses(prompt_packet)
    matches = list(CANONICAL_CITATION.finditer(text))
    improper = [
        node_id
        for node_id in not_applicable_ids
        if not any(
            match.group(2) == f"missing.{node_id}"
            or match.group(2).startswith(f"missing.{node_id}.")
            for match in matches
        )
    ]
    missing_namespace_for_available = sorted(
        {
            match.group(2).removeprefix("missing.")
            for match in matches
            if match.group(2).startswith("missing.")
            and resolved_statuses.get(
                match.group(2).removeprefix("missing.")
            )
            == "available"
        }
    )
    canonical_namespace_for_unavailable = sorted(
        {
            match.group(2)
            for match in matches
            if not match.group(2).startswith("missing.")
            and resolved_statuses.get(match.group(2))
            in {"missing", "not_applicable", "not_applicable_dependency"}
        }
    )
    resolved_required = {
        **{
            node_id: item.get("resolved", {})
            for node_id, item in prompt_packet.get("usable_evidence", {}).items()
        },
        **{
            node_id: item.get("resolved", {})
            for node_id, item in prompt_packet.get(
                "derivable_calculations", {}
            ).items()
        },
    }
    collections_without_available_citations = sorted(
        required_id
        for required_id in required_ids
        if resolved_required.get(required_id, {}).get("kind") == "collection"
        and resolved_statuses.get(required_id) == "available"
        and not any(
            not match.group(2).startswith("missing.")
            and (
                match.group(2) == required_id
                or match.group(2).startswith(required_id + ".")
            )
            and resolved_statuses.get(match.group(2)) == "available"
            for match in matches
        )
    )
    result["not_applicable_ids"] = not_applicable_ids
    result["improper_not_applicable_citation_ids"] = improper
    result["missing_namespace_for_available_ids"] = (
        missing_namespace_for_available
    )
    result["canonical_namespace_for_unavailable_ids"] = (
        canonical_namespace_for_unavailable
    )
    result["collections_without_available_citations"] = (
        collections_without_available_citations
    )
    result["passed"] = result["passed"] and not any(
        (
            improper,
            missing_namespace_for_available,
            canonical_namespace_for_unavailable,
            collections_without_available_citations,
        )
    )
    return result


def _resolved_node_statuses(prompt_packet: dict[str, Any]) -> dict[str, str]:
    statuses: dict[str, str] = {}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            node_id = value.get("id")
            status = value.get("status")
            if isinstance(node_id, str):
                if isinstance(status, str):
                    statuses[node_id] = status
                elif value.get("kind") == "collection":
                    statuses[node_id] = (
                        "available" if value.get("records") else "missing"
                    )
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for item in prompt_packet.get("usable_evidence", {}).values():
        visit(item.get("resolved"))
    for item in prompt_packet.get("derivable_calculations", {}).values():
        visit(item.get("resolved"))
    return statuses


def _not_applicable_required_ids(
    prompt_packet: dict[str, Any],
) -> list[str]:
    resolved = {
        **{
            node_id: item.get("resolved", {})
            for node_id, item in prompt_packet.get("usable_evidence", {}).items()
        },
        **{
            node_id: item.get("resolved", {})
            for node_id, item in prompt_packet.get(
                "derivable_calculations", {}
            ).items()
        },
    }
    return [
        node_id
        for node_id in prompt_packet.get("required_citation_ids", [])
        if resolved.get(node_id, {}).get("status")
        in {"not_applicable", "not_applicable_dependency"}
    ]


def _table_raws(markdown: str) -> list[tuple[str, tuple[str, ...]]]:
    tree = parse_markdown(markdown)
    return [
        (
            str(section.get("heading") or ""),
            tuple(str(table.get("raw") or "") for table in section.get("tables", [])),
        )
        for section in tree.get("sections", [])
    ]


def _report_component_citation_qa(
    markdown: str,
    plan: dict[str, Any],
) -> dict[str, Any]:
    parsed_sections = parse_markdown(markdown).get("sections", [])
    contract_sections = section_contracts(plan["contract"])
    components = {
        item["component_id"]: item for item in plan["components"]
    }
    if len(parsed_sections) != len(contract_sections):
        raise ValueError(
            f"{plan['project_id']}: cannot map report sections for citation QA"
        )
    results: dict[str, dict[str, Any]] = {}
    for section, parsed in zip(contract_sections, parsed_sections):
        llm_components = [
            item
            for item in section["required_components"]
            if item["kind"] == "llm"
        ]
        if len(llm_components) != 1:
            raise ValueError(
                f"{plan['project_id']}: section {section['id']} must have one "
                "llm component"
            )
        component_id = llm_components[0]["id"]
        component = components[component_id]
        paragraph = "\n\n".join(
            str(item.get("text") or "")
            for item in parsed.get("paragraphs", [])
        )
        results[component_id] = _component_citation_qa(
            paragraph,
            component["required_ids"],
            component["prompt_packet"],
        )
    failing = sorted(
        component_id
        for component_id, result in results.items()
        if result.get("passed") is not True
    )
    return {
        "passed": not failing,
        "failing_component_ids": failing,
        "components": results,
    }


def _review_component_edits(
    generated: str,
    reviewed: str,
    contract: dict[str, Any],
) -> list[dict[str, Any]]:
    generated_sections = parse_markdown(generated).get("sections", [])
    reviewed_sections = parse_markdown(reviewed).get("sections", [])
    edits = []
    for section_contract, before, after in zip(
        section_contracts(contract),
        generated_sections,
        reviewed_sections,
    ):
        component = next(
            item
            for item in section_contract["required_components"]
            if item["kind"] == "llm"
        )
        before_text = "\n\n".join(
            str(item.get("text") or "") for item in before.get("paragraphs", [])
        )
        after_text = "\n\n".join(
            str(item.get("text") or "") for item in after.get("paragraphs", [])
        )
        if before_text != after_text:
            edits.append(
                {
                    "section_id": section_contract["id"],
                    "component_id": component["id"],
                    "generated_text_sha256": sha256_text(before_text),
                    "reviewed_text_sha256": sha256_text(after_text),
                }
            )
    return edits


def _validate_review_attestation(
    review: dict[str, Any],
    *,
    project: str,
) -> None:
    expected_keys = {
        "schema_version",
        "project_id",
        "status",
        "reviewer",
        "review_note",
        "reviewed_at",
        "authoring_sha256",
        "contract_sha256",
        "prepared_evidence_sha256",
        "generated_report_sha256",
        "reviewed_report_sha256",
        "component_edits",
        "validation",
        "citation_qa",
    }
    if set(review) != expected_keys:
        raise ValueError(f"{project}: gold review fields differ from schema")
    reviewer = review.get("reviewer")
    note = review.get("review_note")
    if not isinstance(reviewer, str) or not reviewer.strip() or reviewer != reviewer.strip():
        raise ValueError(f"{project}: gold review has an invalid reviewer")
    if not isinstance(note, str) or not note.strip() or note != note.strip():
        raise ValueError(f"{project}: gold review has an invalid review note")
    reviewed_at = review.get("reviewed_at")
    if not isinstance(reviewed_at, str):
        raise ValueError(f"{project}: gold review timestamp is absent")
    try:
        timestamp = datetime.fromisoformat(reviewed_at)
    except ValueError as exc:
        raise ValueError(f"{project}: gold review timestamp is invalid") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"{project}: gold review timestamp lacks a timezone")


def _preflight_immutable_json(path: Path, value: dict[str, Any]) -> None:
    if path.exists() and not path.is_file():
        raise ValueError(f"immutable artifact path is not a file: {path}")
    if path.is_file() and sha256_json(read_json(path)) != sha256_json(value):
        raise ValueError(f"refusing to overwrite immutable artifact: {path}")


def _preflight_immutable_text(path: Path, value: str) -> None:
    if path.exists() and not path.is_file():
        raise ValueError(f"immutable artifact path is not a file: {path}")
    if path.is_file() and path.read_text(encoding="utf-8") != value:
        raise ValueError(f"refusing to overwrite immutable artifact: {path}")


def _write_immutable_json(path: Path, value: dict[str, Any]) -> None:
    _preflight_immutable_json(path, value)
    if path.is_file():
        return
    write_json(path, value)


def _write_immutable_text(path: Path, value: str) -> None:
    _preflight_immutable_text(path, value)
    if path.is_file():
        return
    write_text(path, value)


def _current_project_identity(
    project_id: str,
) -> tuple[Any, EvidenceStore, dict[str, Any], dict[str, Any]]:
    plan = _build_project_plan(project_id)
    identity = {
        "benchmark_version": plan["benchmark_version"],
        "template_id": plan["template_id"],
        "contract_sha256": plan["contract_sha256"],
        "prepared_evidence_sha256": plan["prepared_evidence_sha256"],
        "prepared_twin_sha256": plan["prepared_twin_sha256"],
        "prepared_reference_sha256": plan["prepared_reference_sha256"],
        "calculated_store_sha256": plan["calculated_store_sha256"],
        "catalogue_sha256": plan["catalogue_sha256"],
        "calculation_registry_sha256": plan[
            "calculation_registry_sha256"
        ],
        "source_normalization_sha256": plan["source_normalization_sha256"],
        "enrichment_sha256": plan["enrichment_sha256"],
    }
    return plan["context"], plan["store"], identity, plan


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def author_fp083_gold(
    provider: Provider,
    *,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Author each neutral llm component once from its compiled prompt packet."""

    twin = prepare_v2_twin(read_json(NORMALIZED_ROOT / "fp083.json"))
    reference = prepare_v2_reference(
        read_json(REFERENCE_ROOT / "climatefund20-v1.json")
    )
    store = EvidenceStore(twin, reference)
    calculation_result = calculate_all(
        Calculator(store, registry=calculation_registry())
    )
    unavailable = [
        item["id"]
        for item in calculation_result["results"]
        if item.get("status") != "available"
    ]
    if unavailable:
        raise ValueError(
            "cannot author complete v2 gold with unavailable calculations: "
            + ", ".join(unavailable)
        )

    generated = {}
    records = {}
    for section in section_contracts():
        for component in section["required_components"]:
            if component["kind"] != "llm":
                continue
            component_id = component["id"]
            evidence = {
                node_id: store.get(node_id)
                for node_id in component["required_ids"]
            }
            episode = GoldComponentEpisode(
                episode_id=f"fp083.v2.gold.{component_id}",
                project_id="FP083",
                component_id=component_id,
            )
            response = provider.complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "Write one compact, neutral report paragraph from the "
                            "supplied resolved evidence. Use only that evidence and "
                            "never claim that an available supplied item is absent. "
                            "Cite claims as [visible text](node_id), use non-empty "
                            "citation labels, and cite both endpoints of every range "
                            "separately. Cite every required scalar or calculation ID "
                            "at least once; a collection may be covered through its "
                            "canonical child record or field IDs. Use human-readable "
                            "rounding with no more than two decimals unless additional "
                            "precision is material. Preserve genuine missing states, "
                            "synthesize record collections instead of repeating every "
                            "field, and return only the paragraph."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"INSTRUCTIONS:\n{component['instructions']}\n\n"
                            f"REQUIRED IDS:\n{compact_json(component['required_ids'])}\n\n"
                            f"RESOLVED EVIDENCE AND CALCULATIONS:\n"
                            f"{compact_json(evidence)}"
                        ),
                    },
                ],
                episode=episode,
            )
            paragraph = _clean_paragraph(response.text)
            required_ids = component["required_ids"]
            citation_qa = gold_citation_qa(
                paragraph,
                required_ids,
            )
            generated[component_id] = paragraph
            records[component_id] = {
                "component_id": component_id,
                "section_id": section["id"],
                "directive": "llm",
                "prompt_field": "instructions",
                "instructions": component["instructions"],
                "evidence_ids": required_ids,
                "required_ids": required_ids,
                "required_evidence_ids": [
                    node_id
                    for node_id in required_ids
                    if not node_id.startswith("calc.")
                ],
                "required_calculation_ids": [
                    node_id
                    for node_id in required_ids
                    if node_id.startswith("calc.")
                ],
                "provider": provider.name,
                "model": provider.model,
                "raw_output": response.text,
                "generated_output": paragraph,
                "final_output": paragraph,
                "reviewed_output": None,
                "review_status": "pending_manual_review",
                "manual_edits": [],
                "citation_qa": citation_qa,
                "usage": response.usage,
                "latency_seconds": response.latency_seconds,
                "provider_request_id": response.provider_request_id,
            }

    contract = load_compiled_contract()
    report = render_report(store, generated)
    failing_citations = [
        component_id
        for component_id, record in records.items()
        if not record["citation_qa"]["passed"]
    ]
    authoring = {
        "schema_version": "react_report.gold_authoring/v2",
        "benchmark_version": contract["benchmark_version"],
        "project_id": "FP083",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "template_sha256": contract["template_sha256"],
        "provider": provider.name,
        "model": provider.model,
        "generation_recipe": "llm",
        "generation_count": len(records),
        "citation_qa": {
            "passing_component_count": len(records) - len(failing_citations),
            "failing_component_ids": failing_citations,
        },
        "review": {
            "status": "pending_manual_review",
            "policy": (
                "Raw and generated outputs are immutable provenance. Reviewers may "
                "repair prose and citations in the reviewed report while recording "
                "component-level edits; model usage and latency remain attributed "
                "to the original generation."
            ),
            "generated_report": "fp083.generated.md",
            "reviewed_report": "fp083.md",
        },
        "components": records,
    }
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        write_text(output_dir / "fp083.generated.md", report)
        write_text(output_dir / "fp083.md", report)
        write_json(output_dir / "fp083.authoring.json", authoring)
    return {"report": report, "authoring": authoring}


def _clean_paragraph(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("v2 gold author returned an empty component")
    if re.search(r"^\s*(?:```|~~~)", text, re.M):
        raise ValueError("v2 llm gold component must not contain code fences")
    if re.search(r"^#{1,6}\s", text, re.M) or re.search(r"^\s*\|", text, re.M):
        raise ValueError("v2 llm gold component must not contain headings or tables")
    if re.search(r"^\s*(?:-{3,}|\*{3,}|_{3,}|={3,})\s*$", text, re.M):
        raise ValueError("v2 llm gold component must not contain thematic breaks")
    if re.search(r"^\s*(?:[-+*]\s+|\d+[.)]\s+|>\s*)", text, re.M):
        raise ValueError(
            "v2 llm gold component must not contain lists or block quotes"
        )
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
    if len(paragraphs) != 1:
        raise ValueError("v2 llm gold component must contain exactly one paragraph")
    return " ".join(paragraphs[0].splitlines()).strip()


def gold_citation_qa(
    text: str,
    required_ids: list[str],
) -> dict[str, Any]:
    """Record deterministic citation defects without rejecting repairable gold."""

    matches = list(CANONICAL_CITATION.finditer(text))
    citations = [
        {
            "label": match.group(1),
            "target": match.group(2),
            "canonical_target": match.group(2).removeprefix("missing."),
        }
        for match in matches
    ]
    cited_ids = [item["canonical_target"] for item in citations]

    def covered(required_id: str) -> bool:
        return any(
            cited_id == required_id or cited_id.startswith(required_id + ".")
            for cited_id in cited_ids
        )

    def allowed(cited_id: str) -> bool:
        return any(
            cited_id == required_id or cited_id.startswith(required_id + ".")
            for required_id in required_ids
        )

    empty_label_ids = [
        item["target"] for item in citations if not item["label"].strip()
    ]
    invalid_citation_ids = sorted(
        {cited_id for cited_id in cited_ids if not allowed(cited_id)}
    )
    missing_required_ids = [
        required_id for required_id in required_ids if not covered(required_id)
    ]
    malformed_link_count = max(0, text.count("](") - len(matches))
    passed = not any(
        (
            empty_label_ids,
            invalid_citation_ids,
            missing_required_ids,
            malformed_link_count,
        )
    )
    return {
        "passed": passed,
        "citation_count": len(citations),
        "cited_ids": cited_ids,
        "missing_required_ids": missing_required_ids,
        "invalid_citation_ids": invalid_citation_ids,
        "empty_label_ids": empty_label_ids,
        "malformed_link_count": malformed_link_count,
    }
