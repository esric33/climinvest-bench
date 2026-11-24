"""High-level construction and resumption of one persisted study run."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, TextIO

from .adapters import ReactReportV2Executor
from .artifacts import (
    IncrementalRecordExporter,
    atomic_write_json,
    export_run,
    initialize_run_directory,
    read_json_file,
)
from .config import StudyConfig, sanitized_config
from .plan import StudyPlan, build_study_plan
from .providers.profiles import resolve_provider_profile
from .progress import LiveRunProgress
from .progress_api import format_run_progress
from .retry import RetryPolicy
from .scheduler import ConcurrencyLimits, Scheduler
from .sampling import smoke_b_selection
from .sharding import load_execution_plan
from .storage import RunStore
from .store_locator import open_run_store


class StudyRunError(RuntimeError):
    """Raised before dispatch when a persisted study cannot run safely."""


def credential_preflight(config: StudyConfig) -> dict[str, Any]:
    """Check required environment variables without returning their values."""

    required_profiles = sorted(
        {model.provider for model in config.models if model.provider != "fixture"}
    )
    profiles: list[dict[str, Any]] = []
    for profile_id in required_profiles:
        resolved = resolve_provider_profile(profile_id)
        profiles.append(
            {
                "profile_id": profile_id,
                "protocol": resolved.protocol,
                "responses_endpoint": resolved.responses_endpoint,
                "api_key_env": resolved.api_key_env,
                "credential_present": resolved.credential_present,
            }
        )
    return {
        "ready": all(item["credential_present"] for item in profiles),
        "profiles": profiles,
    }


def execute_study(
    config: StudyConfig,
    run_dir: Path,
    *,
    plan: StudyPlan | None = None,
    recover_disconnects: bool = False,
    recover_transient_http: bool = False,
    progress_stream: TextIO | None = None,
    execution_stage: str | None = None,
) -> dict[str, Any]:
    """Create or resume a study and export all currently terminal records."""

    root = Path(run_dir).resolve()
    resolved_plan = plan or (
        load_execution_plan(root, config=config)
        if (root / "shard.json").is_file()
        else build_study_plan(config)
    )
    if sanitized_config(config) != sanitized_config(resolved_plan.config):
        raise StudyRunError("execution config differs from the immutable plan")
    selection_path = root / "smoke-b-selection.json"
    if execution_stage not in {None, "smoke_b", "full"}:
        raise StudyRunError("unknown execution stage")
    # A plain resume remains bounded until the user explicitly continues full.
    if execution_stage is None and selection_path.exists():
        execution_stage = "smoke_b"
    selection = smoke_b_selection(resolved_plan) if (
        execution_stage == "smoke_b" or selection_path.exists()) else None
    if selection_path.exists() and read_json_file(selection_path) != selection:
        raise StudyRunError("persisted Smoke B sample differs from the full study plan")
    if execution_stage == "smoke_b" and (recover_disconnects or recover_transient_http):
        raise StudyRunError("Smoke B retains terminal failures; resume without recovery flags")
    credentials = credential_preflight(config)
    if credentials["ready"] is not True:
        missing = ", ".join(
            item["api_key_env"]
            for item in credentials["profiles"]
            if not item["credential_present"]
        )
        raise StudyRunError(f"missing provider credentials: {missing}")

    initialize_run_directory(root, resolved_plan)
    if execution_stage == "smoke_b" and not selection_path.exists():
        atomic_write_json(selection_path, selection)
    events = _EventJournal(root / "events.jsonl")
    limits = concurrency_limits_for(config)
    retry = RetryPolicy(
        max_attempts=config.retry.max_attempts,
        base_delay_seconds=config.retry.base_delay_seconds,
        max_delay_seconds=config.retry.max_delay_seconds,
        max_total_delay_seconds=config.retry.max_total_delay_seconds,
    )
    with open_run_store(
        root,
        resolved_plan.graph,
        journal_mode=sqlite_journal_mode(),
    ) as store:
        recovery = (
            store.requeue_terminal_provider_failures(
                include_transient_http=recover_transient_http,
            )
            if recover_disconnects or recover_transient_http
            else {
                "requeued_work_ids": [],
                "unblocked_work_ids": [],
                "retry_cycles": {},
            }
        )
        if recovery["requeued_work_ids"] or recovery["unblocked_work_ids"]:
            events(
                {
                    "event": "resume_recovery",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "requeued_work_ids": recovery["requeued_work_ids"],
                    "unblocked_work_ids": recovery["unblocked_work_ids"],
                    "retry_cycles": recovery["retry_cycles"],
                }
            )
        initial_activity = store.progress_snapshot()
        progress_registry = _ProgressRegistryPublisher(
            store,
            _progress_identity(config, resolved_plan, store),
            artifact_path=root / "progress.json",
            refresh_seconds=progress_publish_seconds(),
            record_exporter=IncrementalRecordExporter(
                root, store, execution_shard=resolved_plan.execution_shard,
            ),
        )
        progress = (
            LiveRunProgress(
                store,
                stream=progress_stream,
                baseline=initial_activity,
            )
            if progress_stream is not None
            else None
        )

        def handle_event(event: Mapping[str, Any]) -> None:
            events(event)
            progress_registry.on_event(event)
            if progress is not None:
                progress.on_event(event)

        executor = ReactReportV2Executor(config, store, root)
        scheduler = Scheduler(
            store,
            resolved_plan.graph,
            executor,
            limits=limits,
            retry_policy=retry,
            lease_seconds=config.scheduler.lease_seconds,
            on_event=handle_event,
            execution_work_ids=(tuple(selection["selected_work_ids"])
                                if execution_stage == "smoke_b" else None),
        )
        if progress is not None:
            progress.start()
        progress_registry.start()
        try:
            summary = scheduler.run().to_dict()
            exported = export_run(root, store)
            final_activity = store.progress_snapshot()
        except BaseException:
            progress_registry.stop(state="failed", finished=True)
            raise
        else:
            terminal_counts = summary.get("counts") or {}
            final_state = "paused" if execution_stage == "smoke_b" else (
                "completed_with_failures" if int(terminal_counts.get("failed") or 0)
                or int(terminal_counts.get("blocked") or 0)
                or int(exported.get("infrastructure_failures") or 0) else "completed")
            progress_registry.stop(
                state=final_state,
                finished=execution_stage != "smoke_b",
            )
        finally:
            if progress is not None:
                progress.stop(clear=True)
    result = {
        "schema_version": "benchrunner.study_execution/v1",
        "plan_id": resolved_plan.plan_id,
        "run_dir": str(root),
        "credentials": credentials,
        "resume_recovery": recovery,
        "invocation_metrics": _invocation_metrics(
            initial_activity,
            final_activity,
            elapsed_seconds=float(summary.get("elapsed_seconds") or 0.0),
        ),
        "scheduler": summary,
        "export": exported,
        "progress_registry": progress_registry.report(),
        "execution_stage": execution_stage or "full",
        **({"smoke_b_selection": selection} if selection else {}),
        **({"execution_shard": resolved_plan.execution_shard} if resolved_plan.execution_shard else {}),
    }
    atomic_write_json(root / "last-run.json", result)
    if execution_stage == "smoke_b":
        atomic_write_json(root / "smoke-b-result.json", result)
    return result


def concurrency_limits_for(config: StudyConfig) -> ConcurrencyLimits:
    """Resolve alias-keyed study limits onto shared backend model resources."""

    model_limits: dict[tuple[str, str], int] = {}
    for model in config.models:
        limit = config.scheduler.model_limits.get(model.alias)
        if limit is not None:
            model_limits[(model.provider, model.model)] = limit
    return ConcurrencyLimits(
        max_workers=config.scheduler.concurrency,
        provider_limits=config.scheduler.provider_limits,
        model_limits=model_limits,
    )


def _invocation_metrics(
    initial: Mapping[str, Any],
    final: Mapping[str, Any],
    *,
    elapsed_seconds: float,
) -> dict[str, Any]:
    initial_counts = initial.get("scheduler") or {}
    final_counts = final.get("scheduler") or {}
    initial_accounting = initial.get("observed_provider_accounting") or {}
    final_accounting = final.get("observed_provider_accounting") or {}

    def delta(before: Mapping[str, Any], after: Mapping[str, Any], key: str) -> int:
        return max(0, int(after.get(key) or 0) - int(before.get(key) or 0))

    return {
        "elapsed_seconds": max(0.0, float(elapsed_seconds)),
        "completed_work": delta(initial_counts, final_counts, "completed"),
        "provider_tokens": delta(
            initial_accounting,
            final_accounting,
            "total_tokens",
        ),
        "successful_provider_responses": delta(
            initial_accounting,
            final_accounting,
            "response_turns",
        ),
    }


def run_status(run_dir: Path) -> dict[str, Any]:
    root = Path(run_dir).resolve()
    with open_run_store(
        root,
        journal_mode=sqlite_journal_mode(),
        require_existing=True,
    ) as store:
        return {
            "schema_version": "benchrunner.run_status/v1",
            "run_dir": str(root),
            "storage_backend": store.backend,
            "run_id": store.run_id,
            "graph_id": store.graph.graph_id,
            "counts": store.summary(),
            **({"execution_shard": read_json_file(root / "shard.json")} if (root / "shard.json").is_file() else {}),
        }


class _EventJournal:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def __call__(self, event: Mapping[str, Any]) -> None:
        rendered = json.dumps(
            dict(event),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ) + "\n"
        with self._lock:
            descriptor = os.open(
                self.path,
                os.O_APPEND | os.O_CREAT | os.O_WRONLY,
                0o600,
            )
            try:
                os.write(descriptor, rendered.encode("utf-8"))
            finally:
                os.close(descriptor)


def sqlite_journal_mode() -> str:
    """Choose WAL locally and allow batch launchers to request NFS-safe DELETE."""

    return os.environ.get("BENCHRUN_SQLITE_JOURNAL_MODE", "wal")


def progress_publish_seconds() -> float:
    raw = str(os.environ.get("BENCHRUN_PROGRESS_PUBLISH_SECONDS") or "15")
    try:
        value = float(raw)
    except ValueError as exc:
        raise StudyRunError(
            "BENCHRUN_PROGRESS_PUBLISH_SECONDS must be a number"
        ) from exc
    if not 1 <= value <= 300:
        raise StudyRunError(
            "BENCHRUN_PROGRESS_PUBLISH_SECONDS must be between 1 and 300"
        )
    return value


def _progress_identity(
    config: StudyConfig,
    plan: StudyPlan,
    store: RunStore,
) -> dict[str, Any]:
    model_aliases = sorted({model.alias for model in config.models})
    model_ids = sorted({model.model for model in config.models})
    providers = sorted({model.provider for model in config.models})
    return {
        "backend": os.environ.get("BENCHRUN_EXECUTION_BACKEND") or "local",
        "cluster_profile": os.environ.get("BENCHRUN_CLUSTER_PROFILE") or "local",
        "model_alias": ",".join(model_aliases),
        "study_id": config.study_id,
        "plan_id": plan.plan_id,
        "run_label": os.environ.get("BENCHRUN_RUN_LABEL") or config.study_id,
        "artifact_ref": os.environ.get("BENCHRUN_ARTIFACT_REF"),
        "metadata": {
            "graph_id": plan.graph.graph_id,
            "model_id": model_ids[0] if len(model_ids) == 1 else model_ids,
            "provider": providers[0] if len(providers) == 1 else providers,
            "study_mode": config.mode,
            "source_revision": os.environ.get("BENCHRUN_SOURCE_REVISION"),
            "target": os.environ.get("BENCHRUN_TARGET"),
            **({"execution_shard": plan.execution_shard} if plan.execution_shard else {}),
        },
        "storage_backend": store.backend,
    }


class _ProgressRegistryPublisher:
    """Publish liveness and aggregate progress without failing a study run."""

    def __init__(
        self,
        store: RunStore,
        identity: Mapping[str, Any],
        *,
        artifact_path: Path,
        refresh_seconds: float,
        record_exporter: IncrementalRecordExporter | None = None,
    ) -> None:
        self.store = store
        self.identity = dict(identity)
        self.artifact_path = Path(artifact_path)
        self.refresh_seconds = float(refresh_seconds)
        self.record_exporter = record_exporter
        self._record_export: dict[str, Any] | None = None
        self.started_at = time.time()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_publish_at = 0.0
        self._publish_count = 0
        self._artifact_publish_count = 0
        self._registry_publish_count = 0
        self._error_count = 0
        self._last_error_type: str | None = None

    @property
    def enabled(self) -> bool:
        return True

    @property
    def registry_enabled(self) -> bool:
        return self.store.backend == "postgresql"

    def start(self) -> None:
        if not self.enabled:
            return
        self._publish(state="running")
        self._thread = threading.Thread(
            target=self._refresh_loop,
            name="benchrun-progress-registry",
            daemon=True,
        )
        self._thread.start()

    def on_event(self, event: Mapping[str, Any] | None = None) -> None:
        record_ready = False
        if self.record_exporter is not None and event is not None:
            with self._lock:
                if event.get("event") == "work_completed":
                    self.record_exporter.enqueue(str(event["work_id"]))
                record_ready = self.record_exporter.should_publish
        if (
            self.enabled
            and (record_ready or time.monotonic() - self._last_publish_at >= self.refresh_seconds)
        ):
            self._publish(state="running")

    def stop(self, *, state: str, finished: bool) -> None:
        if not self.enabled:
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.refresh_seconds * 2))
        self._publish(state=state, finished=finished)

    def report(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "registry_enabled": self.registry_enabled,
            "publish_count": self._publish_count,
            "artifact_publish_count": self._artifact_publish_count,
            "registry_publish_count": self._registry_publish_count,
            "error_count": self._error_count,
            "last_error_type": self._last_error_type,
            "record_export": self._record_export,
        }

    def _refresh_loop(self) -> None:
        while not self._stop.wait(self.refresh_seconds):
            self._publish(state="running")

    def _publish(self, *, state: str, finished: bool = False) -> None:
        with self._lock:
            try:
                finished_at = time.time() if finished else None
                if self.record_exporter is not None:
                    self._record_export = self.record_exporter.publish(drain=finished)
                snapshot = self.store.progress_snapshot()
                if self._record_export is not None:
                    snapshot["record_export"] = self._record_export
                atomic_write_json(
                    self.artifact_path,
                    _artifact_progress_payload(
                        self.identity,
                        snapshot,
                        state=state,
                        started_at=self.started_at,
                        finished_at=finished_at,
                    ),
                )
                self._artifact_publish_count += 1
                if self.registry_enabled:
                    published = self.store.publish_progress(
                        self.identity,
                        state=state,
                        started_at=self.started_at,
                        finished_at=finished_at,
                        snapshot=snapshot,
                    )
                    if published:
                        self._registry_publish_count += 1
                self._publish_count += 1
                self._last_error_type = None
            except Exception as exc:
                self._error_count += 1
                self._last_error_type = type(exc).__name__
            finally:
                self._last_publish_at = time.monotonic()


def _artifact_progress_payload(
    identity: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    *,
    state: str,
    started_at: float,
    finished_at: float | None,
) -> dict[str, Any]:
    """Publish the same bounded public contract read through the progress API."""
    now = datetime.now(timezone.utc)
    run_id = str(
        os.environ.get("BENCHRUN_RUN_ID")
        or identity.get("run_label")
        or "local"
    )
    scheduler = snapshot.get("scheduler") or {}
    episodes = snapshot.get("episodes") or {}
    records = snapshot.get("records") or {}
    accounting = snapshot.get("observed_provider_accounting") or {}
    row = {
        "run_id": run_id,
        **{key: identity.get(key) for key in (
            "backend", "cluster_profile", "model_alias", "study_id", "plan_id", "run_label", "artifact_ref",
        )},
        "state": state,
        **{key: scheduler.get(key) for key in (
            "total", "pending", "retry_wait", "running", "completed", "failed", "blocked",
        )},
        "episodes_total": episodes.get("total"),
        "episodes_completed": episodes.get("materialized"),
        "records_total": records.get("total"),
        "records_completed": records.get("evaluated"),
        "provider_turns": accounting.get("response_turns"),
        **{key: accounting.get(key) for key in (
            "input_tokens", "output_tokens", "reasoning_tokens", "cached_input_tokens",
        )},
        "metadata_json": identity.get("metadata"),
        "started_at": datetime.fromtimestamp(started_at, timezone.utc),
        "updated_at": now,
        "finished_at": datetime.fromtimestamp(finished_at, timezone.utc) if finished_at is not None else None,
    }
    payload = format_run_progress(row, observed_at=now)
    # Local readers use this additive summary for incremental artifact export.
    # Never copy error bodies, raw records, or filesystem paths into telemetry.
    export = snapshot.get("record_export")
    if isinstance(export, Mapping):
        summary: dict[str, Any] = {}
        for key in ("finalized_records", "planned_records", "canonical_planned_records", "shard_count"):
            value = export.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                summary[key] = value
        for key in ("collection_complete", "canonical_collection_complete", "population_inference_requires_canonical_coverage"):
            if isinstance(export.get(key), bool):
                summary[key] = export[key]
        payload["record_export"] = summary
    return payload
