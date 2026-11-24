"""Immutable run metadata and portable JSON/Markdown exports."""

from __future__ import annotations

import json
import os
import tempfile
from collections import deque
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path
from typing import Any, Iterable

from .config import StudyConfig, parse_study_config, sanitized_config
from .metrics import (
    failed_provider_response_accounting,
    observed_provider_accounting,
    operational_provider_accounting,
    provider_turn_records,
    retry_diagnostics,
    retry_cycle_export_records,
    scheduler_attempt_records,
    work_model_identity,
)
from .plan import StudyPlan
from .storage import RunStore


MANIFEST_SCHEMA_VERSION = "benchrunner.run_manifest/v1"


class IncrementalRecordExporter:
    """Publish a committed prefix of small, immutable record JSONL shards.

    The atomic index commits each shard only after its data is durable. Readers
    read index.json once and consume shards 1..shard_count; an unindexed shard
    left by interruption is ignored and overwritten on retry. Full provider
    ledgers and episode bodies are never scanned by event-time publication.
    """

    def __init__(
        self, run_dir: Path, store: RunStore, *, batch_size: int = 32,
        execution_shard: dict[str, Any] | None = None,
    ) -> None:
        if isinstance(batch_size, bool) or not 1 <= batch_size <= 256:
            raise ValueError("record export batch_size must be between 1 and 256")
        self.root = Path(run_dir) / "exports" / "record-stream"
        self.store = store
        self.batch_size = batch_size
        self.execution_shard = execution_shard
        self._published: set[str] = set()
        self._pending: deque[str] = deque()
        self._queued: set[str] = set()
        self._shard_count = 0
        self._statuses: dict[str, int] = {}
        self._total = sum(item.kind == "react_record" for item in store.graph)
        self._reconciled = False

    def reconcile(self) -> None:
        """Recover a prior committed prefix, then discover missed completions once."""

        if self._reconciled:
            return
        index_path = self.root / "index.json"
        if index_path.exists():
            index = read_json_file(index_path)
            if index.get("graph_id") != self.store.graph.graph_id:
                raise ValueError("incremental record export belongs to another graph")
            count = int(index["shard_count"])
            restored: set[str] = set()
            statuses: dict[str, int] = {}
            for number in range(1, count + 1):
                for line in self._shard_path(number).read_text(encoding="utf-8").splitlines():
                    row = json.loads(line)
                    work_id = str(row["work_id"])
                    if work_id in restored:
                        raise ValueError("duplicate committed incremental record")
                    restored.add(work_id)
                    status = str(row["record"].get("status") or "unknown")
                    statuses[status] = statuses.get(status, 0) + 1
            if len(restored) != int(index["finalized_records"]):
                raise ValueError("incremental record export count differs from index")
            self._published = restored
            self._statuses = statuses
            self._shard_count = count
        # Read only reducer state, once per invocation. Missed completion events
        # (including a crash after DB commit) are recovered without duplicate rows.
        record_ids = [
            item.work_id for item in self.store.graph if item.kind == "react_record"
        ]
        for start in range(0, len(record_ids), 256):
            statuses = self.store.work_statuses(tuple(record_ids[start:start + 256]))
            for work_id, status in statuses.items():
                if status == "completed":
                    self.enqueue(work_id)
        self._reconciled = True

    def enqueue(self, work_id: str) -> None:
        if (
            work_id not in self._published
            and work_id not in self._queued
            and self.store.graph.get(work_id).kind == "react_record"
        ):
            self._pending.append(work_id)
            self._queued.add(work_id)

    @property
    def should_publish(self) -> bool:
        return bool(self._pending) and (
            not self._published or len(self._pending) >= self.batch_size
        )

    def publish(self, *, drain: bool = False) -> dict[str, Any]:
        self.reconcile()
        while self._pending:
            work_ids = list(islice(self._pending, self.batch_size))
            rows = []
            statuses = dict(self._statuses)
            for work_id in work_ids:
                state = self.store.get_state(work_id)
                record = (
                    state.result.get("record") if isinstance(state.result, dict) else None
                )
                if state.status != "completed" or not isinstance(record, dict):
                    raise ValueError("only committed reducer records can be exported")
                rows.append({"work_id": work_id, "record": record})
                status = str(record.get("status") or "unknown")
                statuses[status] = statuses.get(status, 0) + 1
            number = self._shard_count + 1
            atomic_write_jsonl(self._shard_path(number), rows)
            index = self._index(
                shard_count=number,
                finalized_records=len(self._published) + len(rows),
                statuses=statuses,
            )
            atomic_write_json(self.root / "index.json", index)
            self._shard_count = number
            self._statuses = statuses
            for work_id in work_ids:
                self._pending.popleft()
                self._queued.remove(work_id)
                self._published.add(work_id)
            if not drain:
                break
        if not self._shard_count:
            atomic_write_json(self.root / "index.json", self._index())
        return self._index()

    def _shard_path(self, number: int) -> Path:
        return self.root / f"records-{number:08d}.jsonl"

    def _index(
        self,
        *,
        shard_count: int | None = None,
        finalized_records: int | None = None,
        statuses: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        count = len(self._published) if finalized_records is None else finalized_records
        return {
            "schema_version": "benchrunner.incremental_records/v1",
            "graph_id": self.store.graph.graph_id,
            "shard_pattern": "records-{number:08d}.jsonl",
            "shard_count": self._shard_count if shard_count is None else shard_count,
            "max_records_per_shard": self.batch_size,
            "finalized_records": count,
            "planned_records": self._total,
            "collection_complete": count == self._total,
            "record_statuses": dict(sorted((self._statuses if statuses is None else statuses).items())),
            **_collection_scope(self.execution_shard, finalized_records=count),
        }


def initialize_run_directory(run_dir: Path, plan: StudyPlan) -> None:
    """Create or verify the immutable, credential-free run definition."""

    root = Path(run_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    for child in ("episodes", "records", "candidates", "exports"):
        (root / child).mkdir(exist_ok=True)

    config_payload = sanitized_config(plan.config)
    plan_payload = plan.to_dict()
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "study_id": plan.config.study_id,
        "study_mode": plan.config.mode,
        "inferential": plan.config.inferential,
        "adapter": plan.config.adapter,
        "plan_id": plan.plan_id,
        "graph_id": plan.graph.graph_id,
        "record_count": plan.record_count,
        "episode_count": plan.episode_count,
        "credential_storage": "environment_only",
    }
    _write_or_verify_json(root / "resolved-config.json", config_payload)
    _write_or_verify_json(root / "plan.json", plan_payload)
    if plan.execution_shard is not None:
        if plan.canonical_plan is None:
            raise ValueError("execution shard is missing its canonical parent plan")
        _write_or_verify_json(root / "canonical-plan.json", plan.canonical_plan.to_dict())
        _write_or_verify_json(root / "shard.json", plan.execution_shard)
        manifest["execution_shard"] = plan.execution_shard
    manifest_path = root / "manifest.json"
    if manifest_path.is_file():
        existing = read_json_file(manifest_path)
        immutable = (
            "schema_version",
            "study_id",
            "study_mode",
            "inferential",
            "adapter",
            "plan_id",
            "graph_id",
            "record_count",
            "episode_count",
            "credential_storage",
            "execution_shard",
        )
        if any(existing.get(key) != manifest.get(key) for key in immutable):
            raise ValueError("run directory belongs to a different immutable plan")
    else:
        atomic_write_json(manifest_path, manifest)


def load_run_config(run_dir: Path) -> StudyConfig:
    payload = read_json_file(Path(run_dir) / "resolved-config.json")
    payload.pop("inferential", None)
    return parse_study_config(payload)


def load_run_plan_payload(run_dir: Path) -> dict[str, Any]:
    return read_json_file(Path(run_dir) / "plan.json")


def write_episode_artifact(
    run_dir: Path,
    work_id: str,
    payload: dict[str, Any],
) -> str:
    relative = Path("episodes") / f"{work_id}.json"
    atomic_write_json(Path(run_dir) / relative, payload)
    return relative.as_posix()


def write_record_artifacts(
    run_dir: Path,
    work_id: str,
    record: dict[str, Any],
    markdown: str | None,
) -> tuple[str, str | None]:
    record_relative = Path("records") / f"{work_id}.json"
    atomic_write_json(Path(run_dir) / record_relative, record)
    candidate_relative: Path | None = None
    if markdown is not None:
        candidate_relative = Path("candidates") / f"{work_id}.md"
        atomic_write_text(Path(run_dir) / candidate_relative, markdown)
    return (
        record_relative.as_posix(),
        candidate_relative.as_posix() if candidate_relative else None,
    )


def export_run(run_dir: Path, store: RunStore) -> dict[str, Any]:
    """Export reducer records, failures, and one coherent store snapshot."""

    root = Path(run_dir)
    exports = root / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    # Materialize every export input from one SQLite snapshot. Scheduler writes
    # may continue after this block, but cannot produce a mixed-generation
    # export or change the accounting totals represented by these rows.
    with store.read_snapshot():
        store.verify_checkpoint_integrity()
        states = store.states()
        planned_records = sum(state.work.kind == "react_record" for state in states)
        materialized_episodes = sum(
            state.work.kind == "react_episode" and state.status == "completed"
            for state in states
        )
        for state in states:
            if state.work.kind == "react_record" and state.status == "completed" and state.result is not None:
                result = state.result
                record = result.get("record") if isinstance(result, dict) else None
                if isinstance(record, dict):
                    records.append(record)
            if state.status in {"failed", "blocked"}:
                failures.append(
                    {
                        "work_id": state.work.work_id,
                        "kind": state.work.kind,
                        "provider": state.work.provider,
                        "model": state.work.model,
                        **work_model_identity(state.work),
                        "status": state.status,
                        "attempt_count": state.attempt_count,
                        "error": state.error,
                    }
                )
        records.sort(key=lambda item: str(item.get("record_key") or ""))
        failures.sort(key=lambda item: item["work_id"])
        atomic_write_jsonl(exports / "records.jsonl", records)
        atomic_write_jsonl(exports / "failures.jsonl", failures)
        # Provider-turn and attempt ledgers can reach hundreds of thousands of
        # rows in the full study. Stream them from the same read snapshot rather
        # than holding the whole export in memory. A second compact-table pass
        # derives aggregates from the identical snapshot.
        atomic_write_jsonl(
            exports / "provider-turns.jsonl",
            provider_turn_records(store),
        )
        provider_accounting = observed_provider_accounting(
            provider_turn_records(store)
        )
        atomic_write_jsonl(
            exports / "attempts.jsonl",
            scheduler_attempt_records(store),
        )
        retry_cycle_count = len(store.retry_cycle_records())
        failed_response_accounting = failed_provider_response_accounting(
            scheduler_attempt_records(store)
        )
        operational_accounting = operational_provider_accounting(
            provider_turn_records(store),
            scheduler_attempt_records(store),
        )
        retry_diagnostic_summary = retry_diagnostics(
            scheduler_attempt_records(store),
            retry_cycle_count=retry_cycle_count,
        )
        atomic_write_jsonl(
            exports / "retry-cycles.jsonl",
            retry_cycle_export_records(store),
        )
        scheduler_summary = store.summary()
        store_schema_version = store.schema_version
        exporter_provenance = store.current_runner_provenance
    summary = {
        "schema_version": "benchrunner.run_export/v2",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "store_schema_version": store_schema_version,
        "exporter_provenance_schema_version": exporter_provenance["schema_version"],
        "exporter_implementation_sha256": exporter_provenance[
            "implementation_sha256"
        ],
        "scheduler": scheduler_summary,
        "scientific_records": len(records),
        "planned_records": planned_records,
        "collection_complete": len(records) == planned_records,
        "materialized_episodes": materialized_episodes,
        "analysis_eligible_records": sum(item.get("analysis_eligible") is True for item in records),
        "records_with_scientific_scores": sum(isinstance(item.get("score"), dict) for item in records),
        "record_scopes": _counts(str(item.get("scope") or "unknown") for item in records),
        "terminal_actions": {
            action: sum(
                int((((item.get("outcomes") or {}).get("terminal_actions") or {}).get(action) or {}).get("accepted") or 0)
                for item in records
            ) for action in ("create", "replace", "keep", "unknown")
        },
        "records_with_outcome_diagnostics": sum(isinstance(item.get("outcomes"), dict) for item in records),
        "infrastructure_failures": len(failures),
        "record_statuses": _counts(
            str(item.get("status") or "unknown") for item in records
        ),
        "observed_provider_accounting": provider_accounting,
        "failed_provider_response_accounting": failed_response_accounting,
        "operational_provider_accounting": operational_accounting,
        "retry_diagnostics": retry_diagnostic_summary,
    }
    if (root / "plan.json").is_file():
        summary.update(_collection_scope(
            read_json_file(root / "plan.json").get("execution_shard"),
            finalized_records=len(records),
        ))
    atomic_write_json(exports / "summary.json", summary)
    return summary


def _collection_scope(
    shard: dict[str, Any] | None, *, finalized_records: int,
) -> dict[str, Any]:
    if shard is None:
        return {}
    return {
        "collection_scope": "execution_shard",
        "parent_plan_id": shard["parent_plan_id"],
        "selected_projects": shard["selected_projects"],
        "canonical_planned_records": shard["canonical_record_count"],
        "canonical_collection_complete": (
            shard["is_complete_canonical_selection"]
            and finalized_records == shard["canonical_record_count"]
        ),
        "population_inference_requires_canonical_coverage": True,
    }


def atomic_write_json(path: Path, value: Any) -> None:
    rendered = json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"
    atomic_write_text(path, rendered)


def atomic_write_jsonl(path: Path, values: Iterable[Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            for value in values:
                stream.write(
                    json.dumps(
                        value,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                    + "\n"
                )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def atomic_write_text(path: Path, value: str) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def read_json_file(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _write_or_verify_json(path: Path, value: Any) -> None:
    if path.is_file():
        if json.loads(path.read_text(encoding="utf-8")) != value:
            raise ValueError(f"immutable run artifact differs: {path.name}")
        return
    atomic_write_json(path, value)


def _counts(values: Iterable[str]) -> dict[str, int]:
    output: dict[str, int] = {}
    for value in values:
        output[value] = output.get(value, 0) + 1
    return dict(sorted(output.items()))
