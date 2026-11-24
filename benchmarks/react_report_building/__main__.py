"""V2 corpus-maintenance and local diagnostic commands.

Study planning, execution, resume, status, and export live in ``benchrun``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .paths import NORMALIZED_ROOT
from .runtime.providers import create_provider
from .runtime.providers.fixtures import FixtureProvider
from .util import read_json, sha256_json
from .validation import validate_everything
from .v2.gold import (
    GoldAuthoringConfigurationError,
    GoldReviewValidationError,
    author_v2_gold,
    promote_reviewed_gold,
)
from .v2.oracle import DEFAULT_GOLD_ROOT, write_resolved_gold_population
from .v2.perturbations import (
    PILOT_PATH,
    POPULATION_CONDITIONS_PATH,
    TOPOLOGY_CATEGORIES,
    apply_mutation,
    build_project_conditions,
    prepare_perturbation_twin,
    write_pilot,
    write_population_conditions,
)
from .v2.preflight import preflight_study_population
from .v2.runner import run_report as run_v2_report
from .v2.runner import run_section as run_v2_section
from .v2.runner import run_sections as run_v2_sections


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="python -m benchmarks.react_report_building",
        description="Maintain and inspect the Climinvest V2 benchmark corpus.",
    )
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "generate-conditions-v2",
        help="write graph-derived masks and mutations for all 20 V2 projects",
    )
    commands.add_parser(
        "validate",
        help="validate every frozen V2 input without provider calls",
    )

    smoke_v2 = commands.add_parser(
        "smoke-v2",
        help="run one compiled-document V2 population instance",
    )
    smoke_v2.add_argument("--project", default="FP083")
    smoke_v2.add_argument("--scope", choices=["report", "section"], default="report")
    smoke_v2.add_argument("--section")
    smoke_v2.add_argument("--max-turns", type=int, default=3)
    smoke_v2.add_argument("--output", type=Path)
    smoke_v2.add_argument("--trace-output", type=Path)
    v2_condition = smoke_v2.add_mutually_exclusive_group()
    v2_condition.add_argument("--mask-category", choices=list(TOPOLOGY_CATEGORIES))
    v2_condition.add_argument(
        "--mutation-category", choices=list(TOPOLOGY_CATEGORIES)
    )
    add_provider_arguments(smoke_v2, required=False, include_fixture=True)

    preflight_v2 = commands.add_parser(
        "preflight-v2",
        help="validate the V2 population without provider calls",
    )
    preflight_v2.add_argument(
        "--projects",
        help="optional comma-separated authoritative subset; default is all 20",
    )
    preflight_v2.add_argument(
        "--allow-missing",
        action="store_true",
        help="permit explicit missing evidence (N/A remains contract-gated)",
    )
    preflight_v2.add_argument("--output", type=Path)

    executable_gold_v2 = commands.add_parser(
        "build-gold-v2",
        help=(
            "resolve V2 structure, tables, calculations, and semantic "
            "obligations without provider calls"
        ),
    )
    executable_gold_v2.add_argument(
        "--output-dir", type=Path, default=DEFAULT_GOLD_ROOT
    )
    executable_gold_v2.add_argument(
        "--include-conditions",
        action="store_true",
        help="also resolve every frozen missingness and mutation condition",
    )

    author_v2 = commands.add_parser(
        "author-gold-v2",
        help=(
            "optionally author prose QA drafts; these are not evaluation gold "
            "and are never required for benchmark execution"
        ),
    )
    add_provider_arguments(
        author_v2,
        required=False,
        include_fixture=True,
        provider_required=True,
    )
    author_v2.add_argument("--output-dir", type=Path, required=True)
    author_v2.add_argument(
        "--projects",
        help="optional comma-separated authoritative subset; default is all 20",
    )
    author_v2.add_argument(
        "--resume",
        action="store_true",
        help="reuse only identity-matched immutable component checkpoints",
    )

    promote_v2 = commands.add_parser(
        "promote-gold-v2",
        help="validate and immutably promote one manually reviewed V2 report",
    )
    promote_v2.add_argument("--output-dir", type=Path, required=True)
    promote_v2.add_argument("--project", required=True)
    promote_v2.add_argument("--reviewed-report", type=Path, required=True)
    promote_v2.add_argument("--reviewer", required=True)
    promote_v2.add_argument("--review-note", required=True)
    return root


def add_provider_arguments(
    command: argparse.ArgumentParser,
    *,
    required: bool = True,
    include_fixture: bool = False,
    provider_required: bool | None = None,
) -> None:
    choices = ["openai_responses", "anthropic_messages", "openai_compatible"]
    if include_fixture:
        choices.append("fixture")
    command.add_argument(
        "--provider",
        required=required if provider_required is None else provider_required,
        choices=choices,
    )
    command.add_argument("--model", required=required)
    command.add_argument("--endpoint")
    command.add_argument("--max-output-tokens", type=int, default=8000)
    command.add_argument(
        "--reasoning-effort",
        help="reasoning effort for providers that support it (OpenAI Responses)",
    )


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "generate-conditions-v2":
        manifest = write_population_conditions()
        pilot = write_pilot()
        result = {
            "valid": manifest["all_categories_supported"],
            "path": str(POPULATION_CONDITIONS_PATH),
            "pilot_path": str(PILOT_PATH),
            "pilot_mask_count": len(pilot["masks"]),
            "pilot_mutation_count": len(pilot["mutations"]),
            "project_count": manifest["project_count"],
            "mask_count": manifest["mask_count"],
            "mutation_count": manifest["mutation_count"],
            "unavailable_categories": manifest["unavailable_categories"],
        }
    elif args.command == "validate":
        result = validate_everything()
    elif args.command == "smoke-v2":
        return smoke_v2_command(args)
    elif args.command == "preflight-v2":
        return preflight_v2_command(args)
    elif args.command == "build-gold-v2":
        manifest = write_resolved_gold_population(
            args.output_dir,
            include_conditions=args.include_conditions,
        )
        result = {
            "valid": True,
            "output_dir": str(args.output_dir),
            "project_count": manifest["project_count"],
            "gold_count": manifest["gold_count"],
            "conditions_included": manifest["conditions_included"],
            "provider_calls": manifest["provider_calls"],
            "manifest_sha256": manifest["manifest_sha256"],
        }
    elif args.command == "author-gold-v2":
        return author_gold_v2_command(args)
    elif args.command == "promote-gold-v2":
        return promote_gold_v2_command(args)
    else:  # pragma: no cover - argparse enforces the command set
        raise AssertionError(args.command)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("valid", True) else 1


def author_gold_v2_command(args: argparse.Namespace) -> int:
    if args.provider != "fixture" and not args.model:
        print("--model is required for a real provider", file=sys.stderr)
        return 2
    if args.max_output_tokens <= 0:
        print("--max-output-tokens must be greater than zero", file=sys.stderr)
        return 2
    if args.reasoning_effort and args.provider != "openai_responses":
        print(
            "--reasoning-effort is supported only by openai_responses",
            file=sys.stderr,
        )
        return 2
    if args.model and args.provider == "fixture":
        print("--model is ignored for the fixture provider", file=sys.stderr)
    project_ids = None
    if args.projects is not None:
        project_ids = [item.strip().upper() for item in args.projects.split(",")]
    try:
        provider = provider_from_args(args)
    except (OSError, TypeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        manifest = author_v2_gold(
            provider,
            output_dir=args.output_dir,
            project_ids=project_ids,
            resume=args.resume,
            provider_config={
                "provider": args.provider,
                "model": provider.model,
                "endpoint": getattr(provider, "endpoint", args.endpoint),
                "max_output_tokens": getattr(
                    provider,
                    "max_output_tokens",
                    getattr(provider, "max_tokens", args.max_output_tokens),
                ),
                "reasoning_effort": getattr(provider, "reasoning_effort", None),
                "timeout_seconds": getattr(provider, "timeout_seconds", None),
            },
        )
    except GoldAuthoringConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:  # provider/runtime interruption; checkpoints persist
        print(f"gold authoring interrupted: {exc}", file=sys.stderr)
        return 1
    result = {
        "valid": manifest["valid"],
        "status": manifest["status"],
        "output_dir": str(args.output_dir),
        "project_count": manifest["project_count"],
        "generation_count": manifest["generation_count"],
        "expected_generation_count": manifest["expected_generation_count"],
        "provider_call_count": manifest["provider_call_count"],
        "provider_calls_this_invocation": manifest["invocations"][-1][
            "provider_calls"
        ],
        "reused_checkpoints_this_invocation": manifest["invocations"][-1][
            "reused_checkpoints"
        ],
        "usage": manifest.get("usage", {}),
        "latency_seconds": manifest.get("latency_seconds", 0.0),
        "manifest": str(args.output_dir / "manifest.json"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if manifest["valid"] else 1


def promote_gold_v2_command(args: argparse.Namespace) -> int:
    try:
        review = promote_reviewed_gold(
            args.output_dir,
            args.project,
            reviewed_report=args.reviewed_report,
            reviewer=args.reviewer,
            review_note=args.review_note,
        )
    except GoldReviewValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, TypeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    result = {
        "valid": True,
        "status": review["status"],
        "project_id": review["project_id"],
        "reviewed_report_sha256": review["reviewed_report_sha256"],
        "component_edit_count": len(review["component_edits"]),
        "review_manifest": str(
            args.output_dir
            / "projects"
            / review["project_id"].lower()
            / "review.json"
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def smoke_v2_command(args: argparse.Namespace) -> int:
    if args.provider and args.provider != "fixture" and not args.model:
        print("--model is required for a real provider", file=sys.stderr)
        return 2
    if args.model and not args.provider:
        print("--model requires --provider", file=sys.stderr)
        return 2
    provider = provider_from_args(args) if args.provider else FixtureProvider()
    project_id = args.project.strip().upper()
    twin_path = NORMALIZED_ROOT / f"{project_id.lower()}.json"
    if not twin_path.is_file():
        print(f"unknown normalized project {project_id}", file=sys.stderr)
        return 2
    twin = read_json(twin_path)
    masked_ids: set[str] | None = None
    selected_condition = None
    if args.mask_category or args.mutation_category:
        conditions = build_project_conditions(project_id, twin=twin)
        group = "masks" if args.mask_category else "mutations"
        category = args.mask_category or args.mutation_category
        selected_condition = next(
            item for item in conditions[group] if item["category"] == category
        )
        if args.mask_category:
            masked_ids = set(selected_condition["masked_ids"])
        else:
            twin = apply_mutation(
                prepare_perturbation_twin(project_id, twin),
                selected_condition,
            )
    if args.scope == "report":
        result = run_v2_report(
            twin,
            provider,
            max_turns=args.max_turns,
            masked_ids=masked_ids,
        )
        markdown = (result.get("terminal") or {}).get("markdown")
    elif args.section:
        result = run_v2_section(
            twin,
            provider,
            section_id=args.section,
            max_turns=args.max_turns,
            masked_ids=masked_ids,
        )
        markdown = (result.get("terminal") or {}).get("markdown")
    else:
        result = run_v2_sections(
            twin,
            provider,
            max_turns=args.max_turns,
            masked_ids=masked_ids,
        )
        markdown = result.get("markdown")
    if selected_condition:
        result["condition_id"] = selected_condition["condition_id"]
        result["condition_category"] = selected_condition["category"]
        result["condition_sha256"] = sha256_json(selected_condition)
        result["condition_contract_sha256"] = selected_condition.get(
            "contract_sha256"
        )
        result["condition_prepared_evidence_sha256"] = selected_condition.get(
            "prepared_evidence_sha256"
        )
    if args.trace_output:
        args.trace_output.parent.mkdir(parents=True, exist_ok=True)
        args.trace_output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if result.get("status") != "completed" or not markdown:
        print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown, encoding="utf-8")
        print(str(args.output))
    else:
        print(markdown, end="" if markdown.endswith("\n") else "\n")
    return 0


def preflight_v2_command(args: argparse.Namespace) -> int:
    project_ids = None
    if args.projects:
        project_ids = [
            item.strip().upper()
            for item in args.projects.split(",")
            if item.strip()
        ]
    try:
        result = preflight_study_population(
            project_ids=project_ids,
            require_all_available=not args.allow_missing,
        )
    except (OSError, TypeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(str(args.output))
    else:
        print(rendered, end="")
    return 0 if result["all_ready_for_provider_smoke"] else 1


def provider_from_args(args: argparse.Namespace):
    return create_provider(
        args.provider,
        model=args.model,
        endpoint=args.endpoint,
        max_output_tokens=args.max_output_tokens,
        reasoning_effort=args.reasoning_effort,
    )


if __name__ == "__main__":
    raise SystemExit(main())
