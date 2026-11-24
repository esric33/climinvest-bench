from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from benchmarks.react_report_building.runtime.structured_output import (
    ACTION_JSON_SCHEMA,
    ACTION_OUTPUT_CONTRACTS,
)
from benchmarks.react_report_building.v2.citation_judge import (
    DEFAULT_PROMPT_PATH as DEFAULT_JUDGE_PROMPT_PATH,
    DEFAULT_QUESTION_BANK_PATH,
    CitationJudgeConfig,
    execute_citation_judge,
    plan_citation_judge,
)

from .artifacts import (
    atomic_write_json,
    export_run,
    load_run_config,
)
from .config import StudyConfigError, load_study_config
from .environment import EnvironmentLoadResult, load_local_environment
from .orchestration import (
    StudyRunError,
    execute_study,
    run_status,
    sqlite_journal_mode,
)
from .plan import StudyPlanError, build_study_plan
from .sharding import load_execution_plan, select_execution_shard, verify_shard_exports
from .providers.doctor import (
    AVAILABLE_CHECK_NAMES,
    CHECK_NAMES,
    NATIVE_AUTO_TOOL_CHECK,
    NATIVE_PARALLEL_TOOL_CHECK,
    STRUCTURED_ACTION_CHECK,
    run_responses_doctor,
)
from .providers.profiles import (
    PROVIDER_PROFILES,
    ProviderProfileError,
    resolve_provider_profile,
)
from .progress_api import serve_progress_api
from .readiness import evaluate_readiness, validate_paid_readiness
from .storage import RunStoreError
from .store_locator import open_run_store
from .work import WorkGraphError

BATCH_SCHEMA_VERSION = "benchrunner.responses_conformance_batch/v3"


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="benchrun",
        description="Reusable orchestration for Responses-compatible benchmarks.",
    )
    commands = root.add_subparsers(dest="command", required=True)

    doctor = commands.add_parser(
        "doctor",
        help="run serial Responses conformance checks (all three by default)",
    )
    doctor.add_argument(
        "--provider",
        "--target",
        dest="provider",
        required=True,
        choices=sorted(PROVIDER_PROFILES),
    )
    doctor.add_argument(
        "--models",
        required=True,
        help="comma-separated model IDs; probes run sequentially",
    )
    doctor.add_argument("--timeout-seconds", type=float, default=30.0)
    doctor.add_argument("--max-output-tokens", type=int, default=512)
    doctor.add_argument(
        "--checks",
        nargs="+",
        choices=AVAILABLE_CHECK_NAMES,
        metavar="CHECK",
        help=(
            "run only the named checks; default: all three. "
            "text_response checks only for a valid nonempty generation. "
            "Available: text_response, forced_function_call, and "
            "function_call_output_continuation, plus the opt-in "
            f"structured_action_response, {NATIVE_AUTO_TOOL_CHECK}, and "
            f"{NATIVE_PARALLEL_TOOL_CHECK}. "
            "The continuation check also requires forced_function_call; the "
            "native auto-tool check includes its own continuation request. "
            "The native parallel-tool check requires two independent native "
            "calls in one response. "
            "Independent selected checks still run after another check fails"
        ),
    )
    doctor.add_argument(
        "--output-contract",
        choices=sorted(ACTION_OUTPUT_CONTRACTS),
        default=ACTION_JSON_SCHEMA,
        help=(
            "wire contract for structured_action_response; standard JSON schema "
            "by default, a </think>-prefixed JSON regex for compatible vLLM "
            "models, or a GPT-OSS Harmony structural tag"
        ),
    )
    doctor.add_argument(
        "--reasoning-effort",
        choices=["none", "minimal", "low", "medium", "high", "xhigh", "max"],
        help="omit for compatible providers that do not expose this setting",
    )
    doctor.add_argument(
        "--output",
        type=Path,
        help="optional path for the redacted JSON diagnostic",
    )

    native_smoke = commands.add_parser(
        "native-smoke", help="qualify production native schemas without loading benchmark data",
    )
    native_smoke.add_argument("--config", type=Path, required=True)
    native_smoke.add_argument("--output-dir", type=Path, required=True)
    native_smoke.add_argument("--probe-max-output-tokens", type=int, default=2048,
                              help="explicit serving-gate output ceiling; production study cap is recorded separately")
    native_smoke.add_argument("--long-form", action="store_true",
                              help="append one bounded synthetic long-form terminal generation")
    native_smoke.add_argument("--production-settings", action="store_true",
                              help="use the study output allowance and retries; test short counting transport without context padding")
    native_smoke.add_argument("--long-form-max-output-tokens", type=int, default=8192,
                              help="separate output allowance for the optional long-form case")

    matrix = commands.add_parser("serving-matrix", help="shared Stage A: report/section context under required/auto tools")
    matrix.add_argument("--config", type=Path, required=True)
    matrix.add_argument("--endpoint-limits", type=Path, required=True)
    matrix.add_argument("--output-dir", type=Path, required=True)
    matrix.add_argument("--inspect-only", action="store_true", help="refresh public limits without model requests")
    matrix.add_argument("--required-context-window", type=int,
                        help="minimum accepted endpoint window; cannot weaken the study's window")
    matrix.add_argument("--probe-max-output-tokens", type=int, default=2048)
    matrix.add_argument("--require-both-policies", action="store_true",
                        help="exit successfully only if both policies pass; default gates the explicit study policy")

    validate = commands.add_parser(
        "validate",
        help="strictly bind a study config to the frozen benchmark without calls",
    )
    validate.add_argument("--config", type=Path, required=True)

    plan = commands.add_parser(
        "plan",
        help="expand a credential-free config into immutable records and work",
    )
    plan.add_argument("--config", type=Path, required=True)
    plan.add_argument("--output", type=Path)
    plan.add_argument("--shard-index", type=int, help="zero-based execution shard index")
    plan.add_argument("--shard-count", type=int, help="partition canonical projects without changing scientific identities")

    shards = commands.add_parser("verify-shards", help="verify canonical coverage and reject divergent duplicate records")
    shards.add_argument("--run-dir", type=Path, action="append", required=True)
    shards.add_argument("--require-complete", action="store_true")

    readiness = commands.add_parser(
        "readiness",
        help="audit every frozen cell and gate a target paid plan",
    )
    readiness.add_argument("--config", type=Path, required=True)
    readiness.add_argument("--target-config", type=Path)
    readiness.add_argument("--run-dir", type=Path, required=True)
    readiness.add_argument("--concurrency", type=int, default=10)

    run = commands.add_parser(
        "run",
        help="create or resume an immutable study run",
    )
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--run-dir", type=Path, required=True)
    run.add_argument("--shard-index", type=int)
    run.add_argument("--shard-count", type=int)
    run.add_argument("--smoke-b", action="store_true",
                     help="run one real instance per condition within the full study store; pause the remainder")
    run_readiness = run.add_mutually_exclusive_group()
    run_readiness.add_argument(
        "--readiness-report",
        type=Path,
        help="required for any non-fixture study and pinned to this plan",
    )
    run_readiness.add_argument(
        "--skip-readiness-gate",
        action="store_true",
        help=(
            "explicitly bypass the readiness-report requirement and repeated "
            "condition preflight; intended for cluster jobs whose committed "
            "source was already validated"
        ),
    )
    run.add_argument(
        "--no-progress",
        action="store_true",
        help="disable the interactive redraw-in-place status dashboard",
    )

    resume = commands.add_parser(
        "resume",
        help="resume from resolved config, SQLite state, and turn checkpoints",
    )
    resume.add_argument("--run-dir", type=Path, required=True)
    resume.add_argument("--continue-full", action="store_true",
                        help="explicitly continue the full study after Smoke B, reusing its stored outcomes")
    resume_readiness = resume.add_mutually_exclusive_group()
    resume_readiness.add_argument("--readiness-report", type=Path)
    resume_readiness.add_argument(
        "--skip-readiness-gate",
        action="store_true",
        help=(
            "explicitly bypass the readiness-report requirement and repeated "
            "condition preflight; intended for cluster jobs whose committed "
            "source was already validated"
        ),
    )
    resume.add_argument(
        "--retry-transient-http",
        action="store_true",
        help=(
            "after the current run is terminal, reopen only exhausted "
            "retryable provider failures: transient HTTP statuses such as "
            "503 and explicit failed-response envelopes"
        ),
    )
    resume.add_argument(
        "--no-progress",
        action="store_true",
        help="disable the interactive redraw-in-place status dashboard",
    )

    status = commands.add_parser("status", help="show persisted scheduler status")
    status.add_argument("--run-dir", type=Path, required=True)

    export = commands.add_parser(
        "export",
        help="rebuild portable JSONL exports from persisted run state",
    )
    export.add_argument("--run-dir", type=Path, required=True)

    judge = commands.add_parser(
        "judge",
        help="run or plan the uncalibrated secondary V2 citation judge",
    )
    judge.add_argument("--run-dir", type=Path, required=True)
    judge.add_argument("--output-dir", type=Path, required=True)
    judge.add_argument(
        "--endpoint",
        default="http://127.0.0.1:8000/v1",
        help="OpenAI-compatible judge endpoint (default: local vLLM)",
    )
    judge.add_argument("--judge-model", required=True)
    judge.add_argument(
        "--judge-model-revision",
        help="optional immutable model revision included in the judge identity",
    )
    judge.add_argument(
        "--candidate-model-alias",
        action="append",
        default=[],
        help="limit records to this candidate alias; repeat to select several",
    )
    judge.add_argument(
        "--question-bank",
        type=Path,
        default=DEFAULT_QUESTION_BANK_PATH,
    )
    judge.add_argument(
        "--prompt",
        type=Path,
        default=DEFAULT_JUDGE_PROMPT_PATH,
    )
    judge.add_argument("--concurrency", type=int, default=8)
    judge.add_argument("--components-per-job", type=int, default=8)
    judge.add_argument("--seed", type=int, default=7)
    judge.add_argument("--max-attempts", type=int, default=3)
    judge.add_argument("--timeout-seconds", type=float, default=900.0)
    judge.add_argument(
        "--api-key-env",
        help="optional environment variable containing the judge bearer token",
    )
    judge.add_argument(
        "--plan",
        "--dry-run",
        dest="plan_only",
        action="store_true",
        help="validate and print exact cardinalities without any judge call",
    )

    progress_api = commands.add_parser(
        "progress-api",
        help="serve sanitized PostgreSQL-backed benchmark progress",
    )
    progress_api.add_argument("--host", default="127.0.0.1")
    progress_api.add_argument("--port", type=int, default=8080)
    progress_api.add_argument(
        "--database-url-env",
        default="BENCHRUN_DATABASE_URL",
        help="environment variable holding the PostgreSQL URL",
    )
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        environment = load_local_environment()
    except (OSError, ValueError) as exc:
        return _configuration_failure(
            "environment.invalid",
            str(exc),
        )

    if args.command == "doctor":
        return doctor_command(args, environment)
    if args.command == "progress-api":
        return serve_progress_api(
            host=args.host,
            port=args.port,
            database_url_env=args.database_url_env,
        )
    try:
        if args.command == "serving-matrix":
            from .providers.serving_matrix import run_serving_matrix
            report = run_serving_matrix(load_study_config(args.config), args.output_dir,
                                        json.loads(args.endpoint_limits.read_text()),
                                        inspect_only=args.inspect_only,
                                        required_window=args.required_context_window,
                                        probe_output_cap=args.probe_max_output_tokens)
            _print_json(report)
            if args.inspect_only:
                return 0 if report.get("status") == "prepared_not_qualified" else 1
            status = report.get("matrix_status") if args.require_both_policies else report.get("status")
            return 0 if status == "passed" else 1
        if args.command == "native-smoke":
            from .providers.native_smoke import run_native_smoke
            report = run_native_smoke(load_study_config(args.config), args.output_dir,
                                      probe_max_output_tokens=args.probe_max_output_tokens,
                                      include_long_form=args.long_form,
                                      production_settings=args.production_settings,
                                      long_form_max_output_tokens=args.long_form_max_output_tokens)
            _print_json(report)
            return 0 if report.get("status") == "passed" else 1
        if args.command == "validate":
            config = load_study_config(args.config)
            plan = build_study_plan(config)
            _print_json(_plan_summary(plan))
            return 0
        if args.command == "plan":
            config = load_study_config(args.config)
            plan = select_execution_shard(build_study_plan(config),
                                          shard_index=args.shard_index,
                                          shard_count=args.shard_count)
            if args.output:
                atomic_write_json(args.output, plan.to_dict())
            _print_json(
                {
                    **_plan_summary(plan),
                    **({"output": str(args.output.resolve())} if args.output else {}),
                }
            )
            return 0
        if args.command == "verify-shards":
            _print_json(verify_shard_exports(args.run_dir, require_complete=args.require_complete))
            return 0
        if args.command == "readiness":
            config = load_study_config(args.config)
            target = (
                load_study_config(args.target_config)
                if args.target_config
                else None
            )
            report = evaluate_readiness(
                config,
                args.run_dir,
                target_config=target,
                concurrency=args.concurrency,
            )
            _print_readiness_result(report, run_dir=args.run_dir)
            return 0 if report["ready_for_paid_smoke"] else 1
        if args.command == "run":
            config = load_study_config(args.config)
            plan = build_study_plan(
                config,
                enforce_condition_readiness=not args.skip_readiness_gate,
            )
            plan = select_execution_shard(plan, shard_index=args.shard_index,
                                          shard_count=args.shard_count)
            if args.skip_readiness_gate:
                _warn_readiness_gate_skipped()
            else:
                _require_paid_gate(config, getattr(plan, "canonical_plan", None) or plan, args.readiness_report)
            result = execute_study(
                config,
                args.run_dir,
                plan=plan,
                progress_stream=(None if args.no_progress else sys.stderr),
                execution_stage="smoke_b" if args.smoke_b else None,
            )
            _print_execution_result(result)
            return 0 if _execution_succeeded(result) else 1
        if args.command == "resume":
            config = load_run_config(args.run_dir)
            if (args.run_dir / "shard.json").exists():
                plan = load_execution_plan(args.run_dir, config=config)
            else:
                plan = build_study_plan(
                    config,
                    enforce_condition_readiness=not args.skip_readiness_gate,
                )
            if args.skip_readiness_gate:
                _warn_readiness_gate_skipped()
            else:
                _require_paid_gate(config, getattr(plan, "canonical_plan", None) or plan, args.readiness_report)
            result = execute_study(
                config,
                args.run_dir,
                plan=plan,
                recover_disconnects=not (args.run_dir / "smoke-b-selection.json").exists(),
                recover_transient_http=args.retry_transient_http,
                progress_stream=(None if args.no_progress else sys.stderr),
                execution_stage="full" if args.continue_full else None,
            )
            _print_execution_result(result)
            return 0 if _execution_succeeded(result) else 1
        if args.command == "status":
            _print_json(run_status(args.run_dir))
            return 0
        if args.command == "export":
            with open_run_store(
                args.run_dir,
                journal_mode=sqlite_journal_mode(),
                require_existing=True,
            ) as store:
                result = export_run(args.run_dir, store)
            _print_json(result)
            return 0
        if args.command == "judge":
            config = CitationJudgeConfig(
                run_dir=args.run_dir,
                output_dir=args.output_dir,
                endpoint=args.endpoint,
                judge_model=args.judge_model,
                judge_model_revision=args.judge_model_revision,
                question_bank_path=args.question_bank,
                prompt_path=args.prompt,
                candidate_model_aliases=tuple(args.candidate_model_alias),
                concurrency=args.concurrency,
                components_per_job=args.components_per_job,
                seed=args.seed,
                max_attempts=args.max_attempts,
                timeout_seconds=args.timeout_seconds,
                api_key_env=args.api_key_env,
            )
            result = (
                plan_citation_judge(config)
                if args.plan_only
                else execute_citation_judge(config)
            )
            _print_json(result)
            return 0 if result.get("status") in {"planned", "completed"} else 1
    except (
        OSError,
        StudyConfigError,
        StudyPlanError,
        StudyRunError,
        RunStoreError,
        WorkGraphError,
        ValueError,
    ) as exc:
        return _configuration_failure("runner.preflight_failed", str(exc))
    raise AssertionError(args.command)  # pragma: no cover


def _execution_succeeded(result: dict[str, Any]) -> bool:
    """Require both scheduler completion and successful scientific records.

    Reducer work can complete normally while emitting a failed scientific
    record (for example, after a turn-limit or protocol failure).  Treating
    that state as a successful CLI invocation creates a false-green provider
    gate, so paid runs must also have no failed records or infrastructure
    failures in their coherent export snapshot.
    """

    scheduler = result.get("scheduler") or {}
    export = result.get("export") or {}
    record_statuses = export.get("record_statuses") or {}
    try:
        scientific_records = int(export.get("scientific_records") or 0)
        status_counts = {
            str(name): int(count)
            for name, count in record_statuses.items()
        }
    except (AttributeError, TypeError, ValueError):
        return False
    return (
        scheduler.get("status") == "completed"
        and scientific_records > 0
        and status_counts.get("completed", 0) == scientific_records
        and sum(status_counts.values()) == scientific_records
        and int(export.get("infrastructure_failures") or 0) == 0
    )


def _scientific_dataset_is_coherent(
    result: dict[str, Any],
    manifest: dict[str, Any],
) -> bool:
    """Accept complete exports even when the model outcome is unsuccessful.

    Cluster launchers use this narrower operational classification after the
    strict CLI gate returns nonzero. It proves that every planned scientific
    record and every scheduler work item is present; it does not require the
    model-level record statuses to be successful.
    """

    try:
        export = result["export"]
        scheduler = result["scheduler"]
        scheduler_counts = scheduler["counts"]
        export_scheduler = export["scheduler"]
        statuses = {
            str(name): int(count)
            for name, count in export["record_statuses"].items()
        }
        scientific_records = int(export["scientific_records"])
        expected_records = int(manifest["record_count"])
        infrastructure_failures = int(export["infrastructure_failures"])
        scheduled_total = int(scheduler_counts["total"])
        scheduled_completed = int(scheduler_counts["completed"])
        exported_total = int(export_scheduler["total"])
        exported_completed = int(export_scheduler["completed"])
    except (KeyError, AttributeError, TypeError, ValueError):
        return False
    allowed_record_statuses = {
        "completed",
        "failed",
        "protocol_failure",
        "turn_limit_exhausted",
    }
    incomplete_scheduler_states = (
        "blocked",
        "failed",
        "pending",
        "retry_wait",
        "running",
    )
    return (
        result.get("schema_version") == "benchrunner.study_execution/v1"
        and export.get("schema_version") == "benchrunner.run_export/v2"
        and manifest.get("schema_version") == "benchrunner.run_manifest/v1"
        and result.get("plan_id") == manifest.get("plan_id")
        and scheduler.get("graph_id") == manifest.get("graph_id")
        and scheduler.get("status") == "completed"
        and scientific_records > 0
        and scientific_records == expected_records
        and set(statuses).issubset(allowed_record_statuses)
        and all(count >= 0 for count in statuses.values())
        and sum(statuses.values()) == scientific_records
        and infrastructure_failures == 0
        and scheduled_total > 0
        and scheduled_completed == scheduled_total
        and exported_total == scheduled_total
        and exported_completed == scheduled_total
        and all(
            int(scheduler_counts.get(name) or 0) == 0
            and int(export_scheduler.get(name) or 0) == 0
            for name in incomplete_scheduler_states
        )
    )


def doctor_command(
    args: argparse.Namespace,
    environment: EnvironmentLoadResult,
) -> int:
    models = _parse_models(args.models)
    if not models:
        return _configuration_failure(
            "config.models_missing",
            "At least one non-empty model identifier is required.",
        )
    requested_checks = (
        CHECK_NAMES
        if args.checks is None
        else tuple(
            name for name in AVAILABLE_CHECK_NAMES if name in set(args.checks)
        )
    )
    if (
        "function_call_output_continuation" in requested_checks
        and "forced_function_call" not in requested_checks
    ):
        return _configuration_failure(
            "config.check_dependency_missing",
            "The continuation check requires the forced function-call check.",
        )
    full_conformance_requested = all(
        name in requested_checks for name in CHECK_NAMES
    )
    try:
        profile = resolve_provider_profile(args.provider)
    except ProviderProfileError as exc:
        return _configuration_failure("config.profile_invalid", str(exc))

    api_key = os.environ.get(profile.api_key_env)
    if not profile.credential_present or not api_key:
        return _configuration_failure(
            "credential.missing",
            f"{profile.api_key_env} is not configured.",
        )

    diagnostics = [
        run_responses_doctor(
            profile,
            api_key=api_key,
            model=model,
            timeout_seconds=args.timeout_seconds,
            max_output_tokens=args.max_output_tokens,
            reasoning_effort=args.reasoning_effort,
            checks=requested_checks,
            output_contract=args.output_contract,
        )
        for model in models
    ]
    passed = all(item.get("status") == "passed" for item in diagnostics)
    report: dict[str, Any] = {
        "schema_version": BATCH_SCHEMA_VERSION,
        "status": "passed" if passed else "failed",
        "provider": profile.profile_id,
        "protocol": profile.protocol,
        "models_requested": models,
        "check_selection": {
            "mode": "full" if full_conformance_requested else "selected",
            "requested": list(requested_checks),
            "full_conformance_requested": full_conformance_requested,
        },
        "sequential": True,
        "automatic_retries": 0,
        "environment": _environment_summary(environment),
        "diagnostics": diagnostics,
    }
    if STRUCTURED_ACTION_CHECK in requested_checks:
        report["check_selection"]["output_contract"] = args.output_contract
    _write_report(report, args.output)
    return 0 if passed else 1


def _parse_models(value: str) -> list[str]:
    models: list[str] = []
    seen: set[str] = set()
    for item in str(value or "").split(","):
        model = item.strip()
        if model and model not in seen:
            models.append(model)
            seen.add(model)
    return models


def _environment_summary(result: EnvironmentLoadResult) -> dict[str, Any]:
    return {
        "file": str(result.path),
        "file_found": result.file_found,
        "loaded_variables": list(result.loaded_keys),
        "preserved_variables": list(result.preserved_keys),
        "skipped_variables": list(result.skipped_keys),
    }


def _configuration_failure(code: str, message: str) -> int:
    print(
        json.dumps(
            {
                "status": "configuration_error",
                "failure": {"code": code, "message": message},
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    return 2


def _print_execution_result(result: dict[str, Any]) -> None:
    """Keep human terminal output bounded; preserve JSON when redirected."""

    try:
        interactive = bool(sys.stdout.isatty())
    except (AttributeError, OSError):
        interactive = False
    if not interactive:
        _print_json(result)
        return
    scheduler = result.get("scheduler") or {}
    counts = scheduler.get("counts") or {}
    exported = result.get("export") or {}
    accounting = exported.get("observed_provider_accounting") or {}
    diagnostics = exported.get("retry_diagnostics") or {}
    recovery = result.get("resume_recovery") or {}
    elapsed = float(scheduler.get("elapsed_seconds") or 0.0)
    completed = int(counts.get("completed") or 0)
    invocation = result.get("invocation_metrics") or {}
    invocation_completed = int(invocation.get("completed_work") or 0)
    throughput = (invocation_completed / elapsed * 60.0) if elapsed else 0.0
    width = max(20, _stream_columns(sys.stdout))
    lines = [
        f"benchrun: {scheduler.get('status', 'unknown')}",
        (
            f"work: {completed}/{counts.get('total', 0)} completed | "
            f"failed {counts.get('failed', 0)} | blocked {counts.get('blocked', 0)}"
        ),
        f"scientific records: {exported.get('scientific_records', 0)}",
        (
            f"tokens: {_compact_quantity(accounting.get('total_tokens', 0))} | "
            f"responses {accounting.get('response_turns', 0)} | "
            f"normalized {accounting.get('normalization_count', 0)}"
        ),
        (
            f"this run: {_compact_duration(elapsed)} | {throughput:.2f} work/min | "
            f"{_compact_quantity(invocation.get('provider_tokens', 0))} tokens"
        ),
        (
            f"disconnects: {diagnostics.get('provider_no_response_failures', 0)} | "
            f"resume cycles {diagnostics.get('retry_cycles', 0)} | "
            f"requeued {len(recovery.get('requeued_work_ids') or [])}"
        ),
        f"run: {result.get('run_dir', '')}",
    ]
    shard = result.get("execution_shard")
    if isinstance(shard, dict):
        lines[2] = (
            f"assigned records: {exported.get('scientific_records', 0)}/"
            f"{exported.get('planned_records', shard['selected_record_count'])} | "
            f"canonical target {shard['canonical_record_count']}"
        )
        index = shard.get("shard_index")
        selection = (
            f"index {index} of {shard['shard_count']} (zero based)"
            if index is not None else "explicit project selection"
        )
        lines.insert(1, f"execution shard: {selection}")
        lines.insert(4, "canonical collection: " + (
            "complete" if exported.get("canonical_collection_complete") is True
            else "incomplete; verify combined shard exports"
        ))
    print("\n".join(_truncate_line(line, width) for line in lines))


def _print_readiness_result(report: dict[str, Any], *, run_dir: Path) -> None:
    """Keep readiness output compact in a terminal; retain JSON for pipes."""

    try:
        interactive = bool(sys.stdout.isatty())
    except (AttributeError, OSError):
        interactive = False
    if not interactive:
        _print_json(report)
        return
    population = report.get("population_preflight") or {}
    missingness = report.get("missingness_semantics") or {}
    updates = report.get("update_semantics") or {}
    repository = report.get("repository_validation") or {}
    fixture = report.get("offline_fixture") or {}
    target = report.get("target_plan") or {}
    width = max(20, _stream_columns(sys.stdout))
    lines = [
        f"readiness: {report.get('status', 'unknown')}",
        (
            f"projects: {population.get('ready_project_count', 0)}/"
            f"{population.get('project_count', 0)} ready"
        ),
        (
            f"conditions: missing {missingness.get('ready', 0)}/"
            f"{missingness.get('total', 0)} | update {updates.get('ready', 0)}/"
            f"{updates.get('total', 0)}"
        ),
        (
            f"repository: {'passed' if repository.get('passed') else 'failed'} | "
            f"errors {repository.get('error_count', 0)}"
        ),
        (
            f"offline fixture: {fixture.get('status', 'unknown')} | "
            f"provider calls {report.get('provider_calls', 0)}"
        ),
        (
            f"target: {target.get('episode_count', 0)} episodes | "
            f"{target.get('record_count', 0)} records | paid gate "
            f"{'open' if report.get('ready_for_paid_smoke') else 'closed'}"
        ),
        f"report: {Path(run_dir).resolve() / 'readiness.json'}",
    ]
    print("\n".join(_truncate_line(line, width) for line in lines))


def _stream_columns(stream: Any, *, fallback: int = 80) -> int:
    try:
        return int(os.get_terminal_size(stream.fileno()).columns)
    except (AttributeError, OSError, ValueError):
        return int(fallback)


def _truncate_line(value: str, width: int) -> str:
    return value if len(value) <= width else value[: max(1, width - 1)] + "…"


def _compact_quantity(value: Any) -> str:
    number = float(value or 0)
    for suffix, divisor in (("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if abs(number) >= divisor:
            return f"{number / divisor:.2f}{suffix}"
    return str(int(number)) if number.is_integer() else f"{number:.2f}"


def _compact_duration(value: Any) -> str:
    total = max(0, int(round(float(value or 0))))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{seconds:02d}s"
    if minutes:
        return f"{minutes}m{seconds:02d}s"
    return f"{seconds}s"


def _write_report(report: dict[str, Any], output: Path | None) -> None:
    rendered = json.dumps(
        report,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    if output is None:
        print(rendered, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    print(str(output))


def _plan_summary(plan) -> dict[str, Any]:
    summary = {
        "status": "passed",
        "provider_calls": 0,
        "study_id": plan.config.study_id,
        "study_mode": plan.config.mode,
        "inferential": plan.config.inferential,
        "plan_id": plan.plan_id,
        "graph_id": plan.graph.graph_id,
        "record_count": plan.record_count,
        "episode_count": plan.episode_count,
        "work_count": len(plan.graph),
    }
    shard = getattr(plan, "execution_shard", None)
    if shard is not None:
        summary.update(
            collection_scope="execution_shard",
            parent_plan_id=shard["parent_plan_id"],
            parent_plan_sha256=shard["parent_plan_sha256"],
            canonical_graph_id=shard["parent_graph_id"],
            canonical_record_count=shard["canonical_record_count"],
            canonical_episode_count=shard["canonical_episode_count"],
            canonical_work_count=shard["canonical_work_count"],
            assigned_record_count=plan.record_count,
            assigned_episode_count=plan.episode_count,
            assigned_work_count=len(plan.graph),
            shard_index=shard["shard_index"],
            shard_index_base=0,
            shard_count=shard["shard_count"],
            selected_projects=shard["selected_projects"],
            canonical_design_inferential=plan.config.inferential,
            inferential=bool(plan.config.inferential and shard["is_complete_canonical_selection"]),
            population_inference_requires_canonical_coverage=True,
        )
    return summary


def _require_paid_gate(config, plan, path: Path | None) -> None:
    paid = any(model.provider != "fixture" for model in config.models)
    if not paid:
        return
    if path is None:
        raise StudyRunError(
            "non-fixture studies require --readiness-report from benchrun readiness"
        )
    validate_paid_readiness(path, target_plan=plan)


def _warn_readiness_gate_skipped() -> None:
    print(
        "warning: readiness gate and repeated condition preflight skipped by "
        "explicit --skip-readiness-gate",
        file=sys.stderr,
    )


def _print_json(value: Any) -> None:
    print(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
