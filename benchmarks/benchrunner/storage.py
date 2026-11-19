"""Transactional scheduler state with crash-safe leases and checkpoints."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping
from urllib.parse import urlsplit

from benchmarks.react_report_building.runtime.provider_cost import (
    add_provider_cost,
    empty_provider_cost_summary,
    normalize_provider_cost,
    provider_cost_from_usage,
)

from .retry import (
    RETRYABLE_FAILED_RESPONSE_CODES,
    RETRYABLE_HTTP_STATUSES,
    failed_response_accounting_from_error,
)
from .work import WorkGraph, WorkSpec, canonical_json


STORE_SCHEMA_VERSION = "benchrunner.run_store/v2"
LEGACY_STORE_SCHEMA_VERSIONS = frozenset({"benchrunner.run_store/v1"})
RUNNER_PROVENANCE_SCHEMA_VERSION = "benchrunner.runner_provenance/v1"
PROVIDER_TURN_METRIC_SCHEMA_VERSION = "benchrunner.provider_turn_metrics/v3"
PROVIDER_TURN_METRIC_BACKFILL_KEY = "provider_turn_metrics_v3_backfill"
TERMINAL_STATUSES = frozenset({"completed", "failed", "blocked"})
ACTIVE_STATUSES = frozenset({"pending", "retry_wait", "running"})
POSTGRES_SCHEMA_LOCK_ID = 782742166591601
POSTGRES_SCHEMA_VERSION = "benchrunner.postgres_store/v1"
_POSTGRES_RUN_ID = re.compile(r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")
_PUBLIC_PROGRESS_METADATA_KEYS = frozenset(
    {
        "experiment",
        "graph_id",
        "model_id",
        "provider",
        "source_revision",
        "study_mode",
        "target",
    }
)

_POSTGRES_SCHEMA_STATEMENTS = (
    "CREATE SCHEMA IF NOT EXISTS benchrunner",
    """
    CREATE TABLE IF NOT EXISTS benchrunner.schema_info(
        singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK(singleton),
        schema_version TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS benchrunner.benchrunner_runs(
        run_id TEXT PRIMARY KEY
            DEFAULT current_setting('benchrunner.run_id'),
        graph_id TEXT,
        created_at DOUBLE PRECISION NOT NULL,
        updated_at DOUBLE PRECISION NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS benchrunner.metadata(
        run_id TEXT NOT NULL
            DEFAULT current_setting('benchrunner.run_id')
            REFERENCES benchrunner.benchrunner_runs(run_id) ON DELETE CASCADE,
        key TEXT NOT NULL,
        value_json TEXT NOT NULL,
        PRIMARY KEY(run_id, key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS benchrunner.work_items(
        run_id TEXT NOT NULL
            DEFAULT current_setting('benchrunner.run_id')
            REFERENCES benchrunner.benchrunner_runs(run_id) ON DELETE CASCADE,
        work_id TEXT NOT NULL,
        spec_json TEXT NOT NULL,
        kind TEXT NOT NULL,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        priority INTEGER NOT NULL,
        status TEXT NOT NULL CHECK(status IN (
            'pending', 'retry_wait', 'running',
            'completed', 'failed', 'blocked'
        )),
        attempt_count INTEGER NOT NULL,
        retry_delay_seconds DOUBLE PRECISION NOT NULL,
        available_at DOUBLE PRECISION NOT NULL,
        lease_owner TEXT,
        lease_expires_at DOUBLE PRECISION,
        claimed_at DOUBLE PRECISION,
        finished_at DOUBLE PRECISION,
        result_json TEXT,
        error_json TEXT,
        timing_json TEXT,
        created_at DOUBLE PRECISION NOT NULL,
        updated_at DOUBLE PRECISION NOT NULL,
        PRIMARY KEY(run_id, work_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS benchrunner.dependencies(
        run_id TEXT NOT NULL
            DEFAULT current_setting('benchrunner.run_id')
            REFERENCES benchrunner.benchrunner_runs(run_id) ON DELETE CASCADE,
        work_id TEXT NOT NULL,
        dependency_id TEXT NOT NULL,
        PRIMARY KEY(run_id, work_id, dependency_id),
        FOREIGN KEY(run_id, work_id)
            REFERENCES benchrunner.work_items(run_id, work_id),
        FOREIGN KEY(run_id, dependency_id)
            REFERENCES benchrunner.work_items(run_id, work_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS benchrunner.attempts(
        run_id TEXT NOT NULL
            DEFAULT current_setting('benchrunner.run_id')
            REFERENCES benchrunner.benchrunner_runs(run_id) ON DELETE CASCADE,
        work_id TEXT NOT NULL,
        attempt INTEGER NOT NULL,
        owner TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN (
            'running', 'completed', 'retry_wait', 'failed', 'interrupted'
        )),
        started_at DOUBLE PRECISION NOT NULL,
        finished_at DOUBLE PRECISION,
        error_json TEXT,
        timing_json TEXT,
        retry_delay_seconds DOUBLE PRECISION NOT NULL DEFAULT 0,
        producer_implementation_sha256 TEXT,
        PRIMARY KEY(run_id, work_id, attempt),
        FOREIGN KEY(run_id, work_id)
            REFERENCES benchrunner.work_items(run_id, work_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS benchrunner.checkpoints(
        run_id TEXT NOT NULL
            DEFAULT current_setting('benchrunner.run_id')
            REFERENCES benchrunner.benchrunner_runs(run_id) ON DELETE CASCADE,
        work_id TEXT NOT NULL,
        name TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL,
        created_at DOUBLE PRECISION NOT NULL,
        updated_at DOUBLE PRECISION NOT NULL,
        producer_implementation_sha256 TEXT,
        PRIMARY KEY(run_id, work_id, name),
        FOREIGN KEY(run_id, work_id)
            REFERENCES benchrunner.work_items(run_id, work_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS benchrunner.retry_cycles(
        run_id TEXT NOT NULL
            DEFAULT current_setting('benchrunner.run_id')
            REFERENCES benchrunner.benchrunner_runs(run_id) ON DELETE CASCADE,
        work_id TEXT NOT NULL,
        cycle INTEGER NOT NULL,
        attempt_base INTEGER NOT NULL,
        reason_json TEXT NOT NULL,
        created_at DOUBLE PRECISION NOT NULL,
        PRIMARY KEY(run_id, work_id, cycle),
        FOREIGN KEY(run_id, work_id)
            REFERENCES benchrunner.work_items(run_id, work_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS benchrunner.provider_turn_metrics(
        run_id TEXT NOT NULL
            DEFAULT current_setting('benchrunner.run_id')
            REFERENCES benchrunner.benchrunner_runs(run_id) ON DELETE CASCADE,
        work_id TEXT NOT NULL,
        name TEXT NOT NULL,
        input_tokens BIGINT NOT NULL,
        output_tokens BIGINT NOT NULL,
        reasoning_tokens BIGINT NOT NULL,
        cached_input_tokens BIGINT NOT NULL,
        latency_seconds DOUBLE PRECISION NOT NULL,
        normalization_count BIGINT NOT NULL DEFAULT 0,
        normalization_rule_counts_json TEXT NOT NULL DEFAULT '{}',
        request_context_json TEXT NOT NULL DEFAULT '{}',
        provider_cost_json TEXT NOT NULL DEFAULT '{}',
        PRIMARY KEY(run_id, work_id, name),
        FOREIGN KEY(run_id, work_id, name)
            REFERENCES benchrunner.checkpoints(run_id, work_id, name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS benchrunner.runner_provenance(
        implementation_sha256 TEXT PRIMARY KEY,
        provenance_json TEXT NOT NULL,
        first_seen_at DOUBLE PRECISION NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS work_status_available
    ON benchrunner.work_items(run_id, status, available_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS work_dispatch_key
    ON benchrunner.work_items(run_id, provider, model, status)
    """,
    """
    CREATE INDEX IF NOT EXISTS work_kind_status
    ON benchrunner.work_items(run_id, kind, status)
    """,
    """
    CREATE INDEX IF NOT EXISTS work_finished_at
    ON benchrunner.work_items(run_id, finished_at)
    WHERE finished_at IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS provider_metrics_run
    ON benchrunner.provider_turn_metrics(run_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS public.benchrunner_run_progress(
        run_id TEXT PRIMARY KEY
            REFERENCES benchrunner.benchrunner_runs(run_id) ON DELETE CASCADE,
        backend TEXT NOT NULL,
        cluster_profile TEXT,
        model_alias TEXT,
        study_id TEXT,
        plan_id TEXT,
        run_label TEXT,
        state TEXT NOT NULL,
        total BIGINT NOT NULL DEFAULT 0,
        pending BIGINT NOT NULL DEFAULT 0,
        retry_wait BIGINT NOT NULL DEFAULT 0,
        running BIGINT NOT NULL DEFAULT 0,
        completed BIGINT NOT NULL DEFAULT 0,
        failed BIGINT NOT NULL DEFAULT 0,
        blocked BIGINT NOT NULL DEFAULT 0,
        episodes_total BIGINT NOT NULL DEFAULT 0,
        episodes_completed BIGINT NOT NULL DEFAULT 0,
        records_total BIGINT NOT NULL DEFAULT 0,
        records_completed BIGINT NOT NULL DEFAULT 0,
        provider_turns BIGINT NOT NULL DEFAULT 0,
        input_tokens BIGINT NOT NULL DEFAULT 0,
        output_tokens BIGINT NOT NULL DEFAULT 0,
        reasoning_tokens BIGINT NOT NULL DEFAULT 0,
        cached_input_tokens BIGINT NOT NULL DEFAULT 0,
        started_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL,
        finished_at TIMESTAMPTZ,
        artifact_ref TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        CHECK(total >= 0 AND pending >= 0 AND retry_wait >= 0
              AND running >= 0 AND completed >= 0 AND failed >= 0
              AND blocked >= 0),
        CHECK(total = pending + retry_wait + running + completed + failed + blocked),
        CHECK(episodes_total >= 0 AND episodes_completed >= 0),
        CHECK(episodes_completed <= episodes_total),
        CHECK(records_total >= 0 AND records_completed >= 0),
        CHECK(records_completed <= records_total),
        CHECK(provider_turns >= 0 AND input_tokens >= 0 AND output_tokens >= 0
              AND reasoning_tokens >= 0 AND cached_input_tokens >= 0)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS benchrunner_run_progress_updated
    ON public.benchrunner_run_progress(updated_at DESC, run_id)
    """,
)

_POSTGRES_RUN_SCOPED_TABLES = (
    "benchrunner_runs",
    "metadata",
    "work_items",
    "dependencies",
    "attempts",
    "checkpoints",
    "retry_cycles",
    "provider_turn_metrics",
)


class _PostgresCursorAdapter:
    """Expose the small sqlite-style cursor surface used by :class:`RunStore`."""

    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    def execute(
        self,
        statement: str,
        parameters: Any = None,
    ) -> "_PostgresCursorAdapter":
        rendered = _postgres_parameter_sql(
            statement,
            escape_percent=parameters is not None,
        )
        if parameters is None:
            self._cursor.execute(rendered)
        else:
            self._cursor.execute(rendered, parameters)
        return self

    def executemany(
        self,
        statement: str,
        parameters: Any,
    ) -> "_PostgresCursorAdapter":
        self._cursor.executemany(
            _postgres_parameter_sql(statement, escape_percent=True),
            parameters,
        )
        return self

    def fetchone(self) -> Any:
        return self._cursor.fetchone()

    def fetchall(self) -> Any:
        return self._cursor.fetchall()

    def fetchmany(self, size: int | None = None) -> Any:
        return self._cursor.fetchmany(size) if size is not None else self._cursor.fetchmany()

    @property
    def rowcount(self) -> int:
        return int(self._cursor.rowcount)

    def close(self) -> None:
        self._cursor.close()


class _PostgresConnectionAdapter:
    """Adapt psycopg's DB-API spelling without weakening SQL isolation."""

    def __init__(self, connection: Any, idle_transaction_status: Any) -> None:
        self.raw_connection = connection
        self._idle_transaction_status = idle_transaction_status

    @property
    def in_transaction(self) -> bool:
        return (
            self.raw_connection.info.transaction_status
            != self._idle_transaction_status
        )

    def cursor(self) -> _PostgresCursorAdapter:
        return _PostgresCursorAdapter(self.raw_connection.cursor())

    def execute(
        self,
        statement: str,
        parameters: Any = None,
    ) -> _PostgresCursorAdapter:
        return self.cursor().execute(statement, parameters)

    def close(self) -> None:
        self.raw_connection.close()


def _postgres_parameter_sql(
    statement: str,
    *,
    escape_percent: bool = True,
) -> str:
    """Convert DB-API qmarks outside SQL literals to psycopg placeholders.

    RunStore owns every statement supplied here.  A small scanner is used rather
    than a regular-expression rewrite so question marks inside quoted SQL remain
    data, not bind parameters. PostgreSQL-only DDL is executed directly and does
    not pass through this adapter.
    """

    output: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(statement):
        character = statement[index]
        if quote is not None:
            output.append(
                "%%" if character == "%" and escape_percent else character
            )
            if character == quote:
                if index + 1 < len(statement) and statement[index + 1] == quote:
                    output.append(statement[index + 1])
                    index += 1
                else:
                    quote = None
        elif character in {"'", '"'}:
            quote = character
            output.append(character)
        elif character == "?":
            output.append("%s")
        elif character == "%" and escape_percent:
            output.append("%%")
        else:
            output.append(character)
        index += 1
    if quote is not None:
        raise RunStoreError("run-store SQL contains an unterminated quoted literal")
    return "".join(output)


class RunStoreError(RuntimeError):
    """Raised when persisted scheduler state violates its run contract."""


def _validated_postgres_run_id(value: str | None) -> str:
    run_id = str(value or "").strip()
    if len(run_id) > 63 or _POSTGRES_RUN_ID.fullmatch(run_id) is None:
        raise RunStoreError(
            "PostgreSQL run ID must be a lowercase DNS label of at most "
            "63 characters"
        )
    return run_id


def _connect_postgres(
    database_url: str,
    *,
    run_id: str,
) -> _PostgresConnectionAdapter:
    """Open one scoped psycopg connection without persisting its credentials."""

    if not database_url.strip():
        raise RunStoreError("PostgreSQL database_url must be non-empty")
    try:
        import psycopg  # type: ignore[import-not-found]
        from psycopg.pq import TransactionStatus  # type: ignore[import-not-found]
        from psycopg.rows import dict_row  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on installation
        raise RunStoreError(
            "PostgreSQL support requires the psycopg dependency"
        ) from exc
    connection: Any | None = None
    try:
        connection = psycopg.connect(
            database_url,
            autocommit=True,
            connect_timeout=10,
            application_name="benchrunner",
            row_factory=dict_row,
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('benchrunner.run_id', %s, false)",
                (run_id,),
            )
    except Exception as exc:
        # libpq errors may echo a DSN, username, host, or password.  The type is
        # useful for operators without copying exception text into run logs.
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
        raise RunStoreError(
            "could not connect to PostgreSQL "
            f"({type(exc).__name__})"
        ) from None
    return _PostgresConnectionAdapter(connection, TransactionStatus.IDLE)


@dataclass(frozen=True, slots=True)
class WorkClaim:
    work: WorkSpec
    owner: str
    attempt: int
    retry_cycle: int
    cycle_attempt: int
    claimed_at: float
    lease_expires_at: float
    queue_seconds: float
    retry_delay_seconds: float


@dataclass(frozen=True, slots=True)
class WorkState:
    work: WorkSpec
    status: str
    attempt_count: int
    available_at: float
    lease_owner: str | None
    lease_expires_at: float | None
    retry_delay_seconds: float
    result: Any = None
    error: Mapping[str, Any] | None = None
    timing: Mapping[str, Any] | None = None


class RunStore:
    """Transactional source of truth for one immutable :class:`WorkGraph`.

    SQLite remains the local default. Supplying ``database_url`` and ``run_id``
    selects PostgreSQL while preserving the same scheduler/checkpoint contract.
    One connection is serialized with an in-process lock in either backend;
    PostgreSQL additionally scopes every run table with forced row-level
    security. Expiring work leases make process interruption recoverable.
    """

    def __init__(
        self,
        path: Path | str,
        graph: WorkGraph | None = None,
        *,
        journal_mode: str = "wal",
        database_url: str | None = None,
        run_id: str | None = None,
    ) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._backend = "postgresql" if database_url is not None else "sqlite"
        self._run_id: str | None = None
        if self._backend == "postgresql":
            self._run_id = _validated_postgres_run_id(run_id)
            self._connection = _connect_postgres(
                str(database_url or ""),
                run_id=self._run_id,
            )
        else:
            if run_id is not None:
                raise RunStoreError("run_id requires a PostgreSQL database_url")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            requested_journal_mode = str(journal_mode).strip().lower()
            if requested_journal_mode not in {"delete", "wal"}:
                raise RunStoreError(
                    "SQLite journal mode must be either 'delete' or 'wal'"
                )
            self._connection = sqlite3.connect(
                str(self.path),
                isolation_level=None,
                check_same_thread=False,
                timeout=30.0,
            )
            self._connection.row_factory = sqlite3.Row
        self._runner_provenance = _runner_implementation_provenance()
        try:
            with self._lock:
                if self._backend == "sqlite":
                    self._connection.execute("PRAGMA foreign_keys = ON")
                    row = self._connection.execute(
                        f"PRAGMA journal_mode = {requested_journal_mode}"
                    ).fetchone()
                    actual_journal_mode = str(row[0]).lower() if row else ""
                    if actual_journal_mode != requested_journal_mode:
                        raise RunStoreError(
                            "could not activate requested SQLite journal mode "
                            f"{requested_journal_mode!r}; got {actual_journal_mode!r}"
                        )
                    self._connection.execute("PRAGMA synchronous = FULL")
                self._create_schema()
                if self._backend == "postgresql":
                    self._register_postgres_run()
            # Checkpoint bodies are the replay and accounting source of truth.
            # Validate them before migrating, backfilling, or exposing the store.
            self.verify_checkpoint_integrity()
            self._migrate_and_backfill_provider_turn_metrics()
            self._record_runner_provenance()
            if graph is not None:
                self.initialize(graph)
        except BaseException:
            self._connection.close()
            raise

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "RunStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def run_id(self) -> str | None:
        return self._run_id

    @property
    def journal_mode(self) -> str:
        if self._backend == "postgresql":
            return "postgresql"
        with self._lock:
            row = self._connection.execute("PRAGMA journal_mode").fetchone()
        return str(row[0]).lower()

    @property
    def graph(self) -> WorkGraph:
        value = self._metadata("graph")
        if value is None:
            raise RunStoreError("run store has not been initialized")
        return WorkGraph.from_dict(value)

    @property
    def schema_version(self) -> str:
        value = self._metadata("schema_version")
        return STORE_SCHEMA_VERSION if value is None else str(value)

    @property
    def current_runner_provenance(self) -> dict[str, Any]:
        """Return the implementation fingerprint of this store opener."""

        return json.loads(canonical_json(self._runner_provenance))

    @contextmanager
    def read_snapshot(self) -> Iterator[None]:
        """Hold one coherent read snapshot across several store calls.

        The in-process lock prevents this connection from being used by a
        scheduler writer while the snapshot is active. SQLite WAL and
        PostgreSQL repeatable-read both let other run connections continue
        without changing the snapshot observed here.
        """

        with self._lock:
            if self._connection.in_transaction:
                raise RunStoreError("cannot nest a run-store read snapshot")
            cursor = self._connection.cursor()
            cursor.execute(
                "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY"
                if self._backend == "postgresql"
                else "BEGIN"
            )
            try:
                # A read establishes the backend snapshot immediately, rather
                # than waiting for whichever helper happens to query first.
                cursor.execute("SELECT 1 FROM metadata LIMIT 1").fetchone()
                yield
            except BaseException:
                cursor.execute("ROLLBACK")
                raise
            else:
                cursor.execute("COMMIT")
            finally:
                cursor.close()

    def initialize(self, graph: WorkGraph, *, now: float | None = None) -> None:
        """Bind this database to exactly one graph, idempotently."""

        timestamp = _time(now)
        graph_json = canonical_json(graph.to_dict())
        with self._transaction() as cursor:
            if self._backend == "postgresql":
                cursor.execute(
                    """
                    SELECT run_id FROM benchrunner_runs
                    WHERE run_id = current_setting('benchrunner.run_id')
                    FOR UPDATE
                    """
                ).fetchone()
            existing = cursor.execute(
                "SELECT value_json FROM metadata WHERE key = 'graph'"
            ).fetchone()
            if existing is not None:
                persisted = str(existing["value_json"])
                if persisted != graph_json:
                    raise RunStoreError(
                        "run store graph differs from the requested graph"
                    )
                if self._backend == "postgresql":
                    cursor.execute(
                        """
                        UPDATE benchrunner_runs
                        SET graph_id = ?, updated_at = ?
                        WHERE run_id = current_setting('benchrunner.run_id')
                        """,
                        (graph.graph_id, timestamp),
                    )
                return
            cursor.executemany(
                "INSERT INTO metadata(key, value_json) VALUES (?, ?)",
                (
                    ("schema_version", canonical_json(STORE_SCHEMA_VERSION)),
                    ("graph_id", canonical_json(graph.graph_id)),
                    ("graph", graph_json),
                    ("created_at", canonical_json(timestamp)),
                ),
            )
            for item in graph:
                cursor.execute(
                    """
                    INSERT INTO work_items(
                        work_id, spec_json, kind, provider, model, priority,
                        status, attempt_count, retry_delay_seconds,
                        available_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, 0, ?, ?, ?)
                    """,
                    (
                        item.work_id,
                        canonical_json(item.to_dict()),
                        item.kind,
                        item.provider,
                        item.model,
                        item.priority,
                        timestamp,
                        timestamp,
                        timestamp,
                    ),
                )
            for item in graph:
                cursor.executemany(
                    "INSERT INTO dependencies(work_id, dependency_id) VALUES (?, ?)",
                    ((item.work_id, dependency) for dependency in item.dependencies),
                )
            if self._backend == "postgresql":
                cursor.execute(
                    """
                    UPDATE benchrunner_runs
                    SET graph_id = ?, updated_at = ?
                    WHERE run_id = current_setting('benchrunner.run_id')
                    """,
                    (graph.graph_id, timestamp),
                )

    def list_ready(
        self,
        *,
        now: float | None = None,
        limit: int | None = None,
        work_ids: tuple[str, ...] | None = None,
    ) -> tuple[WorkSpec, ...]:
        timestamp = _time(now)
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit < 1
        ):
            raise RunStoreError("ready-work limit must be a positive integer")
        if work_ids is not None and not work_ids:
            return ()
        selection_clause = (
            "" if work_ids is None else
            "AND item.work_id IN (" + ",".join("?" for _ in work_ids) + ")"
        )
        limit_clause = "" if limit is None else "LIMIT ?"
        parameters: tuple[Any, ...] = (
            (timestamp,) + (() if work_ids is None else tuple(work_ids))
            + (() if limit is None else (limit,))
        )
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT item.spec_json
                FROM work_items AS item
                WHERE item.status IN ('pending', 'retry_wait')
                  AND item.available_at <= ?
                  {selection_clause}
                  AND NOT EXISTS (
                    SELECT 1
                    FROM dependencies AS dependency
                    JOIN work_items AS parent
                      ON parent.work_id = dependency.dependency_id
                    WHERE dependency.work_id = item.work_id
                      AND parent.status != 'completed'
                  )
                ORDER BY item.priority DESC, item.work_id ASC
                {limit_clause}
                """,
                parameters,
            ).fetchall()
        return tuple(_decode_spec(row["spec_json"]) for row in rows)

    def work_statuses(self, work_ids: tuple[str, ...]) -> dict[str, str]:
        """Read bounded scheduling state without loading result/response bodies."""

        if not work_ids:
            return {}
        with self._lock:
            rows = self._connection.execute(
                "SELECT work_id, status FROM work_items WHERE work_id IN ("
                + ",".join("?" for _ in work_ids) + ")",
                tuple(work_ids),
            ).fetchall()
        return {str(row["work_id"]): str(row["status"]) for row in rows}

    def claim(
        self,
        work_id: str,
        *,
        owner: str,
        lease_seconds: float,
        now: float | None = None,
    ) -> WorkClaim | None:
        owner_name = str(owner or "").strip()
        if not owner_name:
            raise RunStoreError("lease owner must be non-empty")
        if lease_seconds <= 0:
            raise RunStoreError("lease_seconds must be greater than zero")
        timestamp = _time(now)
        expires = timestamp + float(lease_seconds)
        with self._transaction() as cursor:
            row = cursor.execute(
                (
                    "SELECT * FROM work_items WHERE work_id = ? FOR UPDATE"
                    if self._backend == "postgresql"
                    else "SELECT * FROM work_items WHERE work_id = ?"
                ),
                (work_id,),
            ).fetchone()
            if row is None:
                raise RunStoreError(f"unknown work ID {work_id!r}")
            if row["status"] not in {"pending", "retry_wait"}:
                return None
            if float(row["available_at"]) > timestamp:
                return None
            blocked_dependency = cursor.execute(
                """
                SELECT 1
                FROM dependencies AS dependency
                JOIN work_items AS parent
                  ON parent.work_id = dependency.dependency_id
                WHERE dependency.work_id = ?
                  AND parent.status != 'completed'
                LIMIT 1
                """,
                (work_id,),
            ).fetchone()
            if blocked_dependency is not None:
                return None

            attempt = int(row["attempt_count"]) + 1
            cycle_row = cursor.execute(
                """
                SELECT cycle, attempt_base
                FROM retry_cycles
                WHERE work_id = ?
                ORDER BY cycle DESC
                LIMIT 1
                """,
                (work_id,),
            ).fetchone()
            retry_cycle = int(cycle_row["cycle"]) if cycle_row is not None else 0
            attempt_base = (
                int(cycle_row["attempt_base"]) if cycle_row is not None else 0
            )
            cycle_attempt = attempt - attempt_base
            if cycle_attempt < 1:
                raise RunStoreError(
                    f"invalid retry-cycle attempt for work {work_id!r}"
                )
            cursor.execute(
                """
                UPDATE work_items
                SET status = 'running', attempt_count = ?, lease_owner = ?,
                    lease_expires_at = ?, claimed_at = ?, updated_at = ?,
                    error_json = NULL
                WHERE work_id = ?
                """,
                (attempt, owner_name, expires, timestamp, timestamp, work_id),
            )
            cursor.execute(
                """
                INSERT INTO attempts(
                    work_id, attempt, owner, status, started_at,
                    producer_implementation_sha256
                ) VALUES (?, ?, ?, 'running', ?, ?)
                """,
                (
                    work_id,
                    attempt,
                    owner_name,
                    timestamp,
                    self._runner_provenance["implementation_sha256"],
                ),
            )
            return WorkClaim(
                work=_decode_spec(row["spec_json"]),
                owner=owner_name,
                attempt=attempt,
                retry_cycle=retry_cycle,
                cycle_attempt=cycle_attempt,
                claimed_at=timestamp,
                lease_expires_at=expires,
                queue_seconds=max(0.0, timestamp - float(row["available_at"])),
                retry_delay_seconds=float(row["retry_delay_seconds"]),
            )

    def renew_lease(
        self,
        work_id: str,
        *,
        owner: str,
        lease_seconds: float,
        now: float | None = None,
    ) -> float:
        if lease_seconds <= 0:
            raise RunStoreError("lease_seconds must be greater than zero")
        timestamp = _time(now)
        expires = timestamp + float(lease_seconds)
        with self._transaction() as cursor:
            updated = cursor.execute(
                """
                UPDATE work_items
                SET lease_expires_at = ?, updated_at = ?
                WHERE work_id = ? AND status = 'running' AND lease_owner = ?
                """,
                (expires, timestamp, work_id, owner),
            ).rowcount
            if updated != 1:
                raise RunStoreError(
                    f"cannot renew {work_id!r}: active lease is not owned by {owner!r}"
                )
        return expires

    def complete(
        self,
        work_id: str,
        *,
        owner: str,
        result: Any,
        timing: Mapping[str, Any] | None = None,
        now: float | None = None,
    ) -> None:
        result_json = canonical_json(result)
        timing_json = canonical_json(timing or {})
        timestamp = _time(now)
        with self._transaction() as cursor:
            row = self._require_owned_lease(cursor, work_id, owner)
            cursor.execute(
                """
                UPDATE work_items
                SET status = 'completed', result_json = ?, timing_json = ?,
                    error_json = NULL, lease_owner = NULL,
                    lease_expires_at = NULL, finished_at = ?, updated_at = ?
                WHERE work_id = ?
                """,
                (result_json, timing_json, timestamp, timestamp, work_id),
            )
            cursor.execute(
                """
                UPDATE attempts
                SET status = 'completed', finished_at = ?, timing_json = ?
                WHERE work_id = ? AND attempt = ?
                """,
                (timestamp, timing_json, work_id, int(row["attempt_count"])),
            )

    def fail_attempt(
        self,
        work_id: str,
        *,
        owner: str,
        error: Mapping[str, Any],
        retry_at: float | None = None,
        retry_delay_seconds: float = 0.0,
        timing: Mapping[str, Any] | None = None,
        now: float | None = None,
    ) -> str:
        error_json = canonical_json(error)
        timing_json = canonical_json(timing or {})
        timestamp = _time(now)
        if retry_delay_seconds < 0:
            raise RunStoreError("retry delay cannot be negative")
        if retry_at is not None and retry_at < timestamp:
            retry_at = timestamp
        status = "retry_wait" if retry_at is not None else "failed"
        available_at = float(retry_at) if retry_at is not None else timestamp
        with self._transaction() as cursor:
            row = self._require_owned_lease(cursor, work_id, owner)
            cursor.execute(
                """
                UPDATE work_items
                SET status = ?, error_json = ?, timing_json = ?,
                    available_at = ?, retry_delay_seconds = retry_delay_seconds + ?,
                    lease_owner = NULL, lease_expires_at = NULL,
                    finished_at = CASE WHEN ? = 'failed' THEN ? ELSE NULL END,
                    updated_at = ?
                WHERE work_id = ?
                """,
                (
                    status,
                    error_json,
                    timing_json,
                    available_at,
                    float(retry_delay_seconds),
                    status,
                    timestamp,
                    timestamp,
                    work_id,
                ),
            )
            cursor.execute(
                """
                UPDATE attempts
                SET status = ?, finished_at = ?, error_json = ?,
                    timing_json = ?, retry_delay_seconds = ?
                WHERE work_id = ? AND attempt = ?
                """,
                (
                    "retry_wait" if retry_at is not None else "failed",
                    timestamp,
                    error_json,
                    timing_json,
                    float(retry_delay_seconds),
                    work_id,
                    int(row["attempt_count"]),
                ),
            )
        return status

    def recover_expired_leases(self, *, now: float | None = None,
                               work_ids: tuple[str, ...] | None = None) -> tuple[str, ...]:
        """Return expired running work to pending without losing checkpoints."""

        timestamp = _time(now)
        recovered: list[str] = []
        error = canonical_json(
            {
                "code": "scheduler.lease_expired",
                "message": "The previous worker lease expired before completion.",
                "retryable": True,
            }
        )
        selection, parameters = _work_selection_sql(work_ids)
        with self._transaction() as cursor:
            rows = cursor.execute(
                f"""
                SELECT work_id, attempt_count
                FROM work_items
                WHERE status = 'running' AND lease_expires_at <= ?
                  {selection}
                ORDER BY work_id
                """,
                (timestamp, *parameters),
            ).fetchall()
            for row in rows:
                work_id = str(row["work_id"])
                attempt = int(row["attempt_count"])
                cursor.execute(
                    """
                    UPDATE attempts
                    SET status = 'interrupted', finished_at = ?, error_json = ?
                    WHERE work_id = ? AND attempt = ? AND status = 'running'
                    """,
                    (timestamp, error, work_id, attempt),
                )
                cursor.execute(
                    """
                    UPDATE work_items
                    SET status = 'pending', available_at = ?, lease_owner = NULL,
                        lease_expires_at = NULL, error_json = ?, updated_at = ?
                    WHERE work_id = ?
                    """,
                    (timestamp, error, timestamp, work_id),
                )
                recovered.append(work_id)
        return tuple(recovered)

    def block_failed_dependents(self, *, now: float | None = None,
                                work_ids: tuple[str, ...] | None = None) -> tuple[str, ...]:
        """Transitively mark work blocked when a dependency cannot complete."""

        timestamp = _time(now)
        blocked: list[str] = []
        selection, parameters = _work_selection_sql(work_ids, column="item.work_id")
        with self._transaction() as cursor:
            while True:
                rows = cursor.execute(
                    f"""
                    SELECT DISTINCT item.work_id
                    FROM work_items AS item
                    JOIN dependencies AS dependency
                      ON dependency.work_id = item.work_id
                    JOIN work_items AS parent
                      ON parent.work_id = dependency.dependency_id
                    WHERE item.status IN ('pending', 'retry_wait')
                      AND parent.status IN ('failed', 'blocked')
                      {selection}
                    ORDER BY item.work_id
                    """, parameters,
                ).fetchall()
                if not rows:
                    break
                for row in rows:
                    work_id = str(row["work_id"])
                    error = canonical_json(
                        {
                            "code": "dependency.failed",
                            "message": "A required dependency did not complete.",
                            "retryable": False,
                        }
                    )
                    cursor.execute(
                        """
                        UPDATE work_items
                        SET status = 'blocked', error_json = ?, finished_at = ?,
                            lease_owner = NULL, lease_expires_at = NULL,
                            updated_at = ?
                        WHERE work_id = ?
                        """,
                        (error, timestamp, timestamp, work_id),
                    )
                    blocked.append(work_id)
        return tuple(blocked)

    def requeue_terminal_provider_disconnects(
        self,
        *,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Requeue only terminal pre-response provider disconnect failures.

        Existing provider-turn checkpoints and attempt rows are immutable and
        retained.  Each requeued episode starts a fresh bounded retry cycle,
        while its globally numbered attempt history remains monotonic.
        Dependency blocks are lifted only when no failed or blocked parent
        remains, so unrelated permanent failures cannot be retried by resume.
        """

        return self.requeue_terminal_provider_failures(now=now)

    def requeue_terminal_provider_failures(
        self,
        *,
        include_transient_http: bool = False,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Requeue explicitly recoverable terminal provider failures.

        The default is the historical resume policy: only retryable provider
        disconnects without an HTTP response are reopened. Callers must opt in
        to exhausted transient HTTP failures and retryable failed-response
        envelopes. That broader recovery is allowed only after the current run
        is terminal, preventing a second scheduler from racing a still-active
        invocation.

        Completed work, provider-turn checkpoints, and attempt rows remain
        immutable. Each requeued episode starts a fresh bounded retry cycle;
        dependency blocks are lifted only when every failed parent has been
        recovered.
        """

        timestamp = _time(now)
        requeued: list[str] = []
        unblocked: list[str] = []
        cycles: dict[str, int] = {}
        with self._transaction() as cursor:
            if include_transient_http:
                active = cursor.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM work_items
                    WHERE status IN ('pending', 'retry_wait', 'running')
                    """
                ).fetchone()
                active_count = int(active["count"] or 0)
                if active_count:
                    raise RunStoreError(
                        "cannot retry exhausted transient provider failures "
                        "while "
                        f"the run still has {active_count} active work items; "
                        "wait for the current invocation to finish or resume "
                        "it normally first"
                    )
            rows = cursor.execute(
                """
                SELECT work_id, attempt_count, error_json
                FROM work_items
                WHERE status = 'failed' AND kind = 'react_episode'
                ORDER BY work_id
                """
            ).fetchall()
            for row in rows:
                error = _optional_json(row["error_json"])
                if is_pre_response_disconnect(error):
                    reason_code = "resume.provider_disconnect"
                    reason_message = (
                        "A terminal pre-response provider disconnect was "
                        "requeued by an explicit resume invocation."
                    )
                    reason_metadata: dict[str, Any] = {}
                elif include_transient_http and is_retryable_http_failure(error):
                    metadata = error.get("metadata") or {}
                    http_status = int(metadata["http_status"])
                    reason_code = "resume.transient_http"
                    reason_message = (
                        f"An exhausted retryable HTTP {http_status} provider "
                        "failure was requeued by an explicit resume invocation."
                    )
                    reason_metadata = {"http_status": http_status}
                elif (
                    include_transient_http
                    and is_retryable_failed_response(error)
                ):
                    metadata = error.get("metadata") or {}
                    provider_error_code = str(metadata["provider_error_code"])
                    reason_code = "resume.transient_failed_response"
                    reason_message = (
                        "An exhausted retryable failed provider response was "
                        "requeued by an explicit resume invocation."
                    )
                    reason_metadata = {
                        "provider_error_code": provider_error_code
                    }
                else:
                    continue
                work_id = str(row["work_id"])
                prior = cursor.execute(
                    """
                    SELECT MAX(cycle) AS cycle
                    FROM retry_cycles WHERE work_id = ?
                    """,
                    (work_id,),
                ).fetchone()
                cycle = int(prior["cycle"] or 0) + 1
                reason = canonical_json(
                    {
                        "code": reason_code,
                        "message": reason_message,
                        **reason_metadata,
                        "resume_implementation_sha256": self._runner_provenance[
                            "implementation_sha256"
                        ],
                    }
                )
                cursor.execute(
                    """
                    INSERT INTO retry_cycles(
                        work_id, cycle, attempt_base, reason_json, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        work_id,
                        cycle,
                        int(row["attempt_count"]),
                        reason,
                        timestamp,
                    ),
                )
                cursor.execute(
                    """
                    UPDATE work_items
                    SET status = 'pending', available_at = ?,
                        retry_delay_seconds = 0, lease_owner = NULL,
                        lease_expires_at = NULL, claimed_at = NULL,
                        finished_at = NULL, error_json = NULL,
                        timing_json = NULL, updated_at = ?
                    WHERE work_id = ?
                    """,
                    (timestamp, timestamp, work_id),
                )
                requeued.append(work_id)
                cycles[work_id] = cycle

            while True:
                rows = cursor.execute(
                    """
                    SELECT item.work_id, item.error_json
                    FROM work_items AS item
                    WHERE item.status = 'blocked'
                      AND NOT EXISTS (
                        SELECT 1
                        FROM dependencies AS dependency
                        JOIN work_items AS parent
                          ON parent.work_id = dependency.dependency_id
                        WHERE dependency.work_id = item.work_id
                          AND parent.status IN ('failed', 'blocked')
                      )
                    ORDER BY item.work_id
                    """
                ).fetchall()
                eligible = [
                    str(row["work_id"])
                    for row in rows
                    if _is_dependency_failure(_optional_json(row["error_json"]))
                ]
                if not eligible:
                    break
                for work_id in eligible:
                    cursor.execute(
                        """
                        UPDATE work_items
                        SET status = 'pending', available_at = ?,
                            retry_delay_seconds = 0, lease_owner = NULL,
                            lease_expires_at = NULL, claimed_at = NULL,
                            finished_at = NULL, error_json = NULL,
                            timing_json = NULL, updated_at = ?
                        WHERE work_id = ?
                        """,
                        (timestamp, timestamp, work_id),
                    )
                    unblocked.append(work_id)

        return {
            "requeued_work_ids": requeued,
            "unblocked_work_ids": unblocked,
            "retry_cycles": cycles,
        }

    def save_checkpoint(
        self,
        work_id: str,
        name: str,
        payload: Any,
        *,
        owner: str | None = None,
        replace: bool = False,
        now: float | None = None,
    ) -> None:
        checkpoint_name = str(name or "").strip()
        if not checkpoint_name:
            raise RunStoreError("checkpoint name must be non-empty")
        payload_json = canonical_json(payload)
        payload_sha256 = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        timestamp = _time(now)
        with self._transaction() as cursor:
            row = cursor.execute(
                (
                    """
                    SELECT status, lease_owner FROM work_items
                    WHERE work_id = ? FOR UPDATE
                    """
                    if self._backend == "postgresql"
                    else "SELECT status, lease_owner FROM work_items WHERE work_id = ?"
                ),
                (work_id,),
            ).fetchone()
            if row is None:
                raise RunStoreError(f"unknown work ID {work_id!r}")
            if row["status"] in TERMINAL_STATUSES:
                raise RunStoreError(
                    f"cannot checkpoint terminal work {work_id!r}"
                )
            if owner is not None and (
                row["status"] != "running" or row["lease_owner"] != owner
            ):
                raise RunStoreError(
                    f"cannot checkpoint {work_id!r}: lease is not owned by {owner!r}"
                )
            existing = cursor.execute(
                """
                SELECT payload_json, payload_sha256 FROM checkpoints
                WHERE work_id = ? AND name = ?
                """,
                (work_id, checkpoint_name),
            ).fetchone()
            if existing is not None:
                _verify_checkpoint_sha(
                    work_id=work_id,
                    name=checkpoint_name,
                    payload_json=str(existing["payload_json"]),
                    payload_sha256=str(existing["payload_sha256"]),
                )
                if str(existing["payload_json"]) == payload_json:
                    _write_provider_turn_metric(
                        cursor,
                        work_id,
                        checkpoint_name,
                        payload,
                        replace=False,
                        postgresql=self._backend == "postgresql",
                    )
                    return
                if not replace:
                    raise RunStoreError(
                        f"checkpoint {work_id}/{checkpoint_name} is immutable"
                    )
                cursor.execute(
                    """
                    UPDATE checkpoints
                    SET payload_json = ?, payload_sha256 = ?, updated_at = ?,
                        producer_implementation_sha256 = ?
                    WHERE work_id = ? AND name = ?
                    """,
                    (
                        payload_json,
                        payload_sha256,
                        timestamp,
                        self._runner_provenance["implementation_sha256"],
                        work_id,
                        checkpoint_name,
                    ),
                )
                _write_provider_turn_metric(
                    cursor,
                    work_id,
                    checkpoint_name,
                    payload,
                    replace=True,
                    postgresql=self._backend == "postgresql",
                )
                return
            cursor.execute(
                """
                INSERT INTO checkpoints(
                    work_id, name, payload_json, payload_sha256,
                    created_at, updated_at, producer_implementation_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    work_id,
                    checkpoint_name,
                    payload_json,
                    payload_sha256,
                    timestamp,
                    timestamp,
                    self._runner_provenance["implementation_sha256"],
                ),
            )
            _write_provider_turn_metric(
                cursor,
                work_id,
                checkpoint_name,
                payload,
                replace=False,
                postgresql=self._backend == "postgresql",
            )

    def load_checkpoint(self, work_id: str, name: str) -> Any | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT payload_json, payload_sha256 FROM checkpoints
                WHERE work_id = ? AND name = ?
                """,
                (work_id, name),
            ).fetchone()
        if row is None:
            return None
        return _decode_verified_checkpoint(
            work_id=work_id,
            name=name,
            payload_json=str(row["payload_json"]),
            payload_sha256=str(row["payload_sha256"]),
        )

    def checkpoint_names(self, work_id: str) -> tuple[str, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT name FROM checkpoints WHERE work_id = ? ORDER BY name",
                (work_id,),
            ).fetchall()
        return tuple(str(row["name"]) for row in rows)

    def checkpoint_records(self) -> tuple[dict[str, Any], ...]:
        """Return immutable checkpoint metadata and decoded payloads."""

        with self._lock:
            rows = self._connection.execute(
                """
                SELECT work_id, name, payload_json, payload_sha256,
                       created_at, updated_at,
                       producer_implementation_sha256
                FROM checkpoints
                ORDER BY work_id, name
                """
            ).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            work_id = str(row["work_id"])
            name = str(row["name"])
            payload_json = str(row["payload_json"])
            payload_sha256 = str(row["payload_sha256"])
            output.append(
                {
                    "work_id": work_id,
                    "name": name,
                    "payload": _decode_verified_checkpoint(
                        work_id=work_id,
                        name=name,
                        payload_json=payload_json,
                        payload_sha256=payload_sha256,
                    ),
                    "payload_sha256": payload_sha256,
                    "producer_implementation_sha256": (
                        str(row["producer_implementation_sha256"])
                        if row["producer_implementation_sha256"] is not None
                        else None
                    ),
                    "created_at": float(row["created_at"]),
                    "updated_at": float(row["updated_at"]),
                }
            )
        return tuple(output)

    def verify_checkpoint_integrity(
        self,
        *,
        provider_turns_only: bool = False,
    ) -> int:
        """Verify persisted checkpoint bodies against their canonical hashes."""

        where = "WHERE name LIKE 'provider-turn-%'" if provider_turns_only else ""
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT work_id, name, payload_json, payload_sha256
                FROM checkpoints
                {where}
                ORDER BY work_id, name
                """
            ).fetchall()
        for row in rows:
            _verify_checkpoint_sha(
                work_id=str(row["work_id"]),
                name=str(row["name"]),
                payload_json=str(row["payload_json"]),
                payload_sha256=str(row["payload_sha256"]),
            )
        return len(rows)

    def provider_turn_metric_records(self) -> tuple[dict[str, Any], ...]:
        """Return the compact successful-response ledger without raw bodies."""

        return tuple(self.iter_provider_turn_metric_records())

    def iter_provider_turn_metric_records(
        self,
        *,
        batch_size: int = 1000,
    ) -> Iterator[dict[str, Any]]:
        if batch_size < 1:
            raise RunStoreError("provider metric batch size must be positive")

        with self._lock:
            cursor = self._connection.execute(
                """
                SELECT metric.work_id, metric.name,
                       checkpoint.payload_json, checkpoint.payload_sha256,
                       checkpoint.created_at AS checkpoint_created_at,
                       checkpoint.updated_at AS checkpoint_updated_at,
                       checkpoint.producer_implementation_sha256,
                       metric.input_tokens, metric.output_tokens,
                       metric.reasoning_tokens, metric.cached_input_tokens,
                       metric.latency_seconds, metric.normalization_count,
                       metric.normalization_rule_counts_json,
                       metric.request_context_json,
                       metric.provider_cost_json
                FROM provider_turn_metrics AS metric
                JOIN checkpoints AS checkpoint
                  ON checkpoint.work_id = metric.work_id
                 AND checkpoint.name = metric.name
                ORDER BY metric.work_id, metric.name
                """
            )
            try:
                while True:
                    rows = cursor.fetchmany(batch_size)
                    if not rows:
                        break
                    for row in rows:
                        value = dict(row)
                        _verify_checkpoint_sha(
                            work_id=str(value["work_id"]),
                            name=str(value["name"]),
                            payload_json=str(value.pop("payload_json")),
                            payload_sha256=str(value["payload_sha256"]),
                        )
                        try:
                            value["normalization_rule_counts"] = json.loads(
                                value.pop("normalization_rule_counts_json")
                            )
                        except json.JSONDecodeError as exc:
                            raise RunStoreError(
                                "provider-turn compact metric has invalid "
                                f"normalization rule counts: "
                                f"{value['work_id']}/{value['name']}"
                            ) from exc
                        try:
                            value["request_context"] = json.loads(
                                value.pop("request_context_json")
                            )
                        except json.JSONDecodeError as exc:
                            raise RunStoreError(
                                "provider-turn compact metric has invalid "
                                f"request context: "
                                f"{value['work_id']}/{value['name']}"
                            ) from exc
                        try:
                            value["provider_cost"] = normalize_provider_cost(
                                json.loads(value.pop("provider_cost_json"))
                            )
                        except (json.JSONDecodeError, TypeError, ValueError) as exc:
                            raise RunStoreError(
                                "provider-turn compact metric has invalid "
                                f"provider cost: {value['work_id']}/{value['name']}"
                            ) from exc
                        yield value
            finally:
                cursor.close()

    def provider_turn_checkpoint_count(self) -> int:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT COUNT(*) AS count FROM checkpoints
                WHERE name LIKE 'provider-turn-%'
                """
            ).fetchone()
        return int(row["count"])

    def get_state(self, work_id: str) -> WorkState:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM work_items WHERE work_id = ?", (work_id,)
            ).fetchone()
        if row is None:
            raise RunStoreError(f"unknown work ID {work_id!r}")
        return _decode_state(row)

    def states(self) -> tuple[WorkState, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM work_items ORDER BY work_id"
            ).fetchall()
        return tuple(_decode_state(row) for row in rows)

    def attempts(self, work_id: str) -> tuple[dict[str, Any], ...]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM attempts WHERE work_id = ? ORDER BY attempt
                """,
                (work_id,),
            ).fetchall()
        return tuple(
            {
                key: (
                    json.loads(row[key])
                    if key.endswith("_json") and row[key] is not None
                    else row[key]
                )
                for key in row.keys()
            }
            for row in rows
        )

    def attempt_records(self) -> tuple[dict[str, Any], ...]:
        """Return every scheduler attempt without provider payloads."""

        return tuple(self.iter_attempt_records())

    def iter_attempt_records(
        self,
        *,
        batch_size: int = 1000,
    ) -> Iterator[dict[str, Any]]:
        if batch_size < 1:
            raise RunStoreError("attempt batch size must be positive")

        with self._lock:
            cursor = self._connection.execute(
                "SELECT * FROM attempts ORDER BY work_id, attempt"
            )
            try:
                while True:
                    rows = cursor.fetchmany(batch_size)
                    if not rows:
                        break
                    for row in rows:
                        yield _decode_json_columns(row)
            finally:
                cursor.close()

    def retry_cycle_records(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT work_id, cycle, attempt_base, reason_json, created_at
                FROM retry_cycles ORDER BY work_id, cycle
                """
            ).fetchall()
        return tuple(_decode_json_columns(row) for row in rows)

    def summary(self, *, work_ids: tuple[str, ...] | None = None) -> dict[str, int]:
        selection, parameters = _work_selection_sql(work_ids)
        with self._lock:
            rows = self._connection.execute(
                f"SELECT status, COUNT(*) AS count FROM work_items WHERE 1=1 {selection} GROUP BY status",
                parameters,
            ).fetchall()
        output = {
            status: 0
            for status in (
                "pending",
                "retry_wait",
                "running",
                "completed",
                "failed",
                "blocked",
            )
        }
        output.update({str(row["status"]): int(row["count"]) for row in rows})
        output["total"] = sum(value for key, value in output.items() if key != "total")
        return output

    def progress_snapshot(self) -> dict[str, Any]:
        """Return lightweight metrics without loading raw checkpoint bodies."""

        with self.read_snapshot():
            # All pre-existing checkpoints are verified when the store opens;
            # newly saved checkpoints and their compact metrics share one
            # transaction.  Rehashing every raw response on each one-second
            # dashboard refresh would turn progress reporting into O(history).
            counts = self.summary()
            kind_rows = self._connection.execute(
                """
                SELECT kind, status, COUNT(*) AS count
                FROM work_items GROUP BY kind, status
                """
            ).fetchall()
            metric = self._connection.execute(
                """
                SELECT COUNT(*) AS response_turns,
                       COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens,
                       COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens,
                       COALESCE(SUM(cached_input_tokens), 0) AS cached_input_tokens,
                       COALESCE(SUM(normalization_count), 0) AS normalization_count,
                       COALESCE(SUM(latency_seconds), 0) AS latency_seconds
                FROM provider_turn_metrics
                """
            ).fetchone()
            cost_rows = self._connection.execute(
                "SELECT provider_cost_json FROM provider_turn_metrics"
            ).fetchall()
            error_rows = self._connection.execute(
                "SELECT error_json FROM attempts WHERE error_json IS NOT NULL"
            ).fetchall()
            cycle_row = self._connection.execute(
                "SELECT COUNT(*) AS count FROM retry_cycles"
            ).fetchone()
        by_kind: dict[str, dict[str, int]] = {}
        for row in kind_rows:
            by_kind.setdefault(str(row["kind"]), {})[str(row["status"])] = int(
                row["count"]
            )
        episode_counts = by_kind.get("react_episode", {})
        record_counts = by_kind.get("react_record", {})
        disconnects = 0
        for row in error_rows:
            error = _optional_json(row["error_json"])
            if is_pre_response_disconnect(error):
                disconnects += 1
        input_tokens = int(metric["input_tokens"])
        output_tokens = int(metric["output_tokens"])
        provider_cost = empty_provider_cost_summary()
        for row in cost_rows:
            try:
                add_provider_cost(
                    provider_cost,
                    json.loads(str(row["provider_cost_json"])),
                )
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise RunStoreError(
                    "provider-turn compact metric has invalid provider cost"
                ) from exc
        return {
            "scheduler": counts,
            "episodes": {
                "materialized": int(episode_counts.get("completed", 0)),
                "total": sum(episode_counts.values()),
            },
            "records": {
                "evaluated": int(record_counts.get("completed", 0)),
                "total": sum(record_counts.values()),
            },
            "observed_provider_accounting": {
                "response_turns": int(metric["response_turns"]),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "reasoning_tokens": int(metric["reasoning_tokens"]),
                "cached_input_tokens": int(metric["cached_input_tokens"]),
                "normalization_count": int(metric["normalization_count"]),
                "total_tokens": input_tokens + output_tokens,
                "successful_response_latency_seconds": float(
                    metric["latency_seconds"]
                ),
                "provider_cost": provider_cost,
            },
            "retry_diagnostics": {
                "provider_no_response_failures": disconnects,
                "retry_cycles": int(cycle_row["count"]),
            },
        }

    def publish_progress(
        self,
        identity: Mapping[str, Any],
        *,
        state: str = "running",
        started_at: Any = None,
        finished_at: Any = None,
        snapshot: Mapping[str, Any] | None = None,
    ) -> bool:
        """Upsert a sanitized, rebuildable progress row for cluster tooling.

        ``backend`` in ``identity`` is the execution backend (for example,
        ``openshift`` or ``slurm``), not this store's PostgreSQL backend.
        SQLite stores have no shared registry and deliberately return ``False``.
        """

        if self._backend != "postgresql":
            return False
        if not isinstance(identity, Mapping):
            raise RunStoreError("progress identity must be a mapping")
        execution_backend = _progress_identity_text(
            identity.get("backend", identity.get("execution_backend")),
            field="backend",
            required=True,
        )
        run_state = _progress_identity_text(
            state,
            field="state",
            required=True,
        )
        assert run_state is not None
        run_state = run_state.lower()

        progress = self.progress_snapshot() if snapshot is None else snapshot
        if not isinstance(progress, Mapping):
            raise RunStoreError("progress snapshot must be a mapping")
        scheduler = progress["scheduler"]
        episodes = progress["episodes"]
        records = progress["records"]
        accounting = progress["observed_provider_accounting"]
        with self._lock:
            row = self._connection.execute(
                """
                SELECT created_at FROM benchrunner_runs
                WHERE run_id = current_setting('benchrunner.run_id')
                """
            ).fetchone()
        if row is None:
            raise RunStoreError("PostgreSQL run registration is missing")
        default_started_at = datetime.fromtimestamp(
            float(row["created_at"]),
            tz=timezone.utc,
        )
        published_started_at = _progress_timestamp(
            started_at,
            field="started_at",
            default=default_started_at,
        )
        published_finished_at = (
            None
            if finished_at is None
            else _progress_timestamp(finished_at, field="finished_at")
        )
        updated_at = datetime.now(timezone.utc)

        metadata = _public_progress_metadata(identity)
        graph_id = self._metadata("graph_id")
        if graph_id is not None:
            metadata["graph_id"] = str(graph_id)
        artifact_ref = _safe_artifact_ref(identity.get("artifact_ref"))
        values = (
            self._run_id,
            execution_backend,
            _progress_identity_text(
                identity.get("cluster_profile"),
                field="cluster_profile",
            ),
            _progress_identity_text(
                identity.get("model_alias"),
                field="model_alias",
            ),
            _progress_identity_text(identity.get("study_id"), field="study_id"),
            _progress_identity_text(identity.get("plan_id"), field="plan_id"),
            _progress_identity_text(identity.get("run_label"), field="run_label"),
            run_state,
            int(scheduler["total"]),
            int(scheduler["pending"]),
            int(scheduler["retry_wait"]),
            int(scheduler["running"]),
            int(scheduler["completed"]),
            int(scheduler["failed"]),
            int(scheduler["blocked"]),
            int(episodes["total"]),
            int(episodes["materialized"]),
            int(records["total"]),
            int(records["evaluated"]),
            int(accounting["response_turns"]),
            int(accounting["input_tokens"]),
            int(accounting["output_tokens"]),
            int(accounting["reasoning_tokens"]),
            int(accounting["cached_input_tokens"]),
            published_started_at,
            updated_at,
            published_finished_at,
            artifact_ref,
            canonical_json(metadata),
        )
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO public.benchrunner_run_progress AS progress (
                    run_id, backend, cluster_profile, model_alias, study_id,
                    plan_id, run_label, state, total, pending, retry_wait,
                    running, completed, failed, blocked, episodes_total,
                    episodes_completed, records_total, records_completed,
                    provider_turns, input_tokens, output_tokens,
                    reasoning_tokens, cached_input_tokens, started_at,
                    updated_at, finished_at, artifact_ref, metadata_json
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(run_id) DO UPDATE SET
                    backend = excluded.backend,
                    cluster_profile = excluded.cluster_profile,
                    model_alias = excluded.model_alias,
                    study_id = excluded.study_id,
                    plan_id = excluded.plan_id,
                    run_label = excluded.run_label,
                    state = excluded.state,
                    total = excluded.total,
                    pending = excluded.pending,
                    retry_wait = excluded.retry_wait,
                    running = excluded.running,
                    completed = excluded.completed,
                    failed = excluded.failed,
                    blocked = excluded.blocked,
                    episodes_total = excluded.episodes_total,
                    episodes_completed = excluded.episodes_completed,
                    records_total = excluded.records_total,
                    records_completed = excluded.records_completed,
                    provider_turns = excluded.provider_turns,
                    input_tokens = excluded.input_tokens,
                    output_tokens = excluded.output_tokens,
                    reasoning_tokens = excluded.reasoning_tokens,
                    cached_input_tokens = excluded.cached_input_tokens,
                    started_at = LEAST(
                        progress.started_at,
                        excluded.started_at
                    ),
                    updated_at = excluded.updated_at,
                    finished_at = excluded.finished_at,
                    artifact_ref = excluded.artifact_ref,
                    metadata_json = excluded.metadata_json
                """,
                values,
            )
        return True

    def next_available_at(self) -> float | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT MIN(available_at) AS value
                FROM work_items WHERE status = 'retry_wait'
                """
            ).fetchone()
        return None if row is None or row["value"] is None else float(row["value"])

    def next_wakeup_at(self, *, work_ids: tuple[str, ...] | None = None) -> float | None:
        """Return the next retry time or lease expiry relevant to recovery."""

        selection, parameters = _work_selection_sql(work_ids)
        with self._lock:
            row = self._connection.execute(
                f"""
                SELECT MIN(value) AS value
                FROM (
                    SELECT available_at AS value
                    FROM work_items WHERE status = 'retry_wait' {selection}
                    UNION ALL
                    SELECT lease_expires_at AS value
                    FROM work_items
                    WHERE status = 'running' AND lease_expires_at IS NOT NULL
                      {selection}
                ) AS wakeups
                """, (*parameters, *parameters),
            ).fetchone()
        return None if row is None or row["value"] is None else float(row["value"])

    def is_terminal(self, *, work_ids: tuple[str, ...] | None = None) -> bool:
        summary = self.summary(work_ids=work_ids)
        return summary["total"] == sum(summary[item] for item in TERMINAL_STATUSES)

    def _metadata(self, key: str) -> Any | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT value_json FROM metadata WHERE key = ?", (key,)
            ).fetchone()
        return None if row is None else json.loads(row["value_json"])

    def _record_runner_provenance(self) -> None:
        with self._transaction() as cursor:
            cursor.execute(
                (
                    """
                    INSERT INTO runner_provenance(
                        implementation_sha256, provenance_json, first_seen_at
                    ) VALUES (?, ?, ?)
                    ON CONFLICT(implementation_sha256) DO NOTHING
                    """
                    if self._backend == "postgresql"
                    else """
                    INSERT OR IGNORE INTO runner_provenance(
                        implementation_sha256, provenance_json, first_seen_at
                    ) VALUES (?, ?, ?)
                    """
                ),
                (
                    self._runner_provenance["implementation_sha256"],
                    canonical_json(self._runner_provenance),
                    time.time(),
                ),
            )

    def _migrate_and_backfill_provider_turn_metrics(self) -> None:
        """Atomically backfill the compact ledger, then publish its schema."""

        with self._transaction() as cursor:
            schema_row = cursor.execute(
                "SELECT value_json FROM metadata WHERE key = 'schema_version'"
            ).fetchone()
            try:
                current = (
                    None
                    if schema_row is None
                    else json.loads(str(schema_row["value_json"]))
                )
            except (TypeError, json.JSONDecodeError) as exc:
                raise RunStoreError("run store has invalid schema metadata") from exc
            if (
                current is not None
                and current != STORE_SCHEMA_VERSION
                and current not in LEGACY_STORE_SCHEMA_VERSIONS
            ):
                raise RunStoreError(
                    f"unsupported run-store schema version: {current!r}"
                )
            marker = cursor.execute(
                """
                SELECT value_json FROM metadata
                WHERE key = ?
                """,
                (PROVIDER_TURN_METRIC_BACKFILL_KEY,),
            ).fetchone()
            try:
                marker_value = (
                    None
                    if marker is None
                    else json.loads(str(marker["value_json"]))
                )
            except (TypeError, json.JSONDecodeError):
                marker_value = None
            full_backfill = not (
                isinstance(marker_value, dict)
                and marker_value.get("completed") is True
                and marker_value.get("schema_version")
                == PROVIDER_TURN_METRIC_SCHEMA_VERSION
            )
            rows = cursor.execute(
                """
                SELECT checkpoint.work_id, checkpoint.name,
                       checkpoint.payload_json, checkpoint.payload_sha256,
                       metric.work_id AS metric_work_id
                FROM checkpoints AS checkpoint
                LEFT JOIN provider_turn_metrics AS metric
                  ON metric.work_id = checkpoint.work_id
                 AND metric.name = checkpoint.name
                WHERE checkpoint.name LIKE 'provider-turn-%'
                  AND (metric.work_id IS NULL OR ?)
                ORDER BY checkpoint.work_id, checkpoint.name
                """,
                (
                    full_backfill
                    if self._backend == "postgresql"
                    else int(full_backfill),
                ),
            ).fetchall()
            for row in rows:
                work_id = str(row["work_id"])
                name = str(row["name"])
                _write_provider_turn_metric(
                    cursor,
                    work_id,
                    name,
                    _decode_verified_checkpoint(
                        work_id=work_id,
                        name=name,
                        payload_json=str(row["payload_json"]),
                        payload_sha256=str(row["payload_sha256"]),
                    ),
                    replace=row["metric_work_id"] is not None,
                    postgresql=self._backend == "postgresql",
                )
            cursor.execute(
                (
                    """
                    INSERT INTO metadata(key, value_json)
                    VALUES (?, ?)
                    ON CONFLICT(run_id, key)
                    DO UPDATE SET value_json = excluded.value_json
                    """
                    if self._backend == "postgresql"
                    else """
                    INSERT INTO metadata(key, value_json)
                    VALUES (?, ?)
                    ON CONFLICT(key)
                    DO UPDATE SET value_json = excluded.value_json
                    """
                ),
                (
                    PROVIDER_TURN_METRIC_BACKFILL_KEY,
                    canonical_json(
                        {
                            "schema_version": PROVIDER_TURN_METRIC_SCHEMA_VERSION,
                            "completed": True,
                        }
                    ),
                ),
            )
            if current in LEGACY_STORE_SCHEMA_VERSIONS:
                cursor.execute(
                    (
                        """
                        INSERT INTO metadata(key, value_json)
                        VALUES ('schema_migration_v1_to_v2', ?)
                        ON CONFLICT(run_id, key) DO NOTHING
                        """
                        if self._backend == "postgresql"
                        else """
                        INSERT OR IGNORE INTO metadata(key, value_json)
                        VALUES ('schema_migration_v1_to_v2', ?)
                        """
                    ),
                    (
                        canonical_json(
                            {
                                "from": str(current),
                                "to": STORE_SCHEMA_VERSION,
                                "migrated_at": time.time(),
                            }
                        ),
                    ),
                )
                # This must remain the last migration statement: readers must
                # never observe v2 metadata unless its compact-ledger backfill
                # committed in the same transaction.
                cursor.execute(
                    """
                    UPDATE metadata SET value_json = ?
                    WHERE key = 'schema_version'
                    """,
                    (canonical_json(STORE_SCHEMA_VERSION),),
                )

    def _require_owned_lease(
        self,
        cursor: Any,
        work_id: str,
        owner: str,
    ) -> Any:
        row = cursor.execute(
            (
                "SELECT * FROM work_items WHERE work_id = ? FOR UPDATE"
                if self._backend == "postgresql"
                else "SELECT * FROM work_items WHERE work_id = ?"
            ),
            (work_id,),
        ).fetchone()
        if row is None:
            raise RunStoreError(f"unknown work ID {work_id!r}")
        if row["status"] != "running" or row["lease_owner"] != owner:
            raise RunStoreError(
                f"cannot finalize {work_id!r}: active lease is not owned by {owner!r}"
            )
        return row

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        with self._lock:
            cursor = self._connection.cursor()
            cursor.execute(
                "BEGIN" if self._backend == "postgresql" else "BEGIN IMMEDIATE"
            )
            try:
                yield cursor
            except BaseException:
                cursor.execute("ROLLBACK")
                raise
            else:
                if self._backend == "postgresql":
                    cursor.execute(
                        """
                        UPDATE benchrunner_runs SET updated_at = ?
                        WHERE run_id = current_setting('benchrunner.run_id')
                        """,
                        (time.time(),),
                    )
                cursor.execute("COMMIT")
            finally:
                cursor.close()

    def _create_postgres_schema(self) -> None:
        """Install and validate the shared PostgreSQL schema atomically."""

        connection = self._connection.raw_connection
        with connection.transaction():
            with connection.cursor() as cursor:
                # Every run process starts independently.  Serialize schema
                # installation so CREATE POLICY and the version sentinel cannot
                # race when a fresh database receives several jobs at once.
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(%s)",
                    (POSTGRES_SCHEMA_LOCK_ID,),
                )
                encoding = cursor.execute("SHOW server_encoding").fetchone()
                if (
                    encoding is None
                    or str(encoding["server_encoding"]).upper() != "UTF8"
                ):
                    raise RunStoreError(
                        "PostgreSQL run storage requires UTF8 server encoding"
                    )
                for statement in _POSTGRES_SCHEMA_STATEMENTS[:2]:
                    cursor.execute(statement)
                row = cursor.execute(
                    """
                    SELECT schema_version
                    FROM benchrunner.schema_info
                    WHERE singleton = TRUE
                    """
                ).fetchone()
                actual = None if row is None else str(row["schema_version"])
                if actual is not None and actual != POSTGRES_SCHEMA_VERSION:
                    raise RunStoreError(
                        "unsupported PostgreSQL run-store schema version: "
                        f"{actual!r}"
                    )
                if actual is None:
                    for statement in _POSTGRES_SCHEMA_STATEMENTS[2:]:
                        cursor.execute(statement)
                    for table in _POSTGRES_RUN_SCOPED_TABLES:
                        cursor.execute(
                            f"""
                            CREATE POLICY benchrunner_run_scope
                            ON benchrunner.{table}
                            USING (
                                run_id = current_setting('benchrunner.run_id')
                            )
                            WITH CHECK (
                                run_id = current_setting('benchrunner.run_id')
                            )
                            """
                        )
                        cursor.execute(
                            f"ALTER TABLE benchrunner.{table} "
                            "ENABLE ROW LEVEL SECURITY"
                        )
                        cursor.execute(
                            f"ALTER TABLE benchrunner.{table} "
                            "FORCE ROW LEVEL SECURITY"
                        )
                    # Publish the version only after every table, constraint,
                    # index, and policy has been installed in this transaction.
                    cursor.execute(
                        """
                        INSERT INTO benchrunner.schema_info(
                            singleton, schema_version
                        ) VALUES (TRUE, %s)
                        """,
                        (POSTGRES_SCHEMA_VERSION,),
                    )
                for table in _POSTGRES_RUN_SCOPED_TABLES:
                    isolation = cursor.execute(
                        """
                        SELECT relation.relrowsecurity AS enabled,
                               relation.relforcerowsecurity AS forced,
                               EXISTS (
                                   SELECT 1 FROM pg_catalog.pg_policies AS policy
                                   WHERE policy.schemaname = 'benchrunner'
                                     AND policy.tablename = relation.relname
                                     AND policy.policyname =
                                         'benchrunner_run_scope'
                               ) AS has_policy
                        FROM pg_catalog.pg_class AS relation
                        JOIN pg_catalog.pg_namespace AS namespace
                          ON namespace.oid = relation.relnamespace
                        WHERE namespace.nspname = 'benchrunner'
                          AND relation.relname = %s
                        """,
                        (table,),
                    ).fetchone()
                    if isolation is None or not all(
                        bool(isolation[field])
                        for field in ("enabled", "forced", "has_policy")
                    ):
                        raise RunStoreError(
                            "PostgreSQL run isolation is incomplete for table "
                            f"benchrunner.{table}"
                        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('search_path', %s, false)",
                ("benchrunner,public",),
            )

    def _register_postgres_run(self) -> None:
        """Create this connection's RLS root row if the run is new."""

        timestamp = time.time()
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO benchrunner_runs(created_at, updated_at)
                VALUES (?, ?)
                ON CONFLICT(run_id) DO NOTHING
                """,
                (timestamp, timestamp),
            )

    def _create_schema(self) -> None:
        if self._backend == "postgresql":
            self._create_postgres_schema()
            return
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata(
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS work_items(
                work_id TEXT PRIMARY KEY,
                spec_json TEXT NOT NULL,
                kind TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                priority INTEGER NOT NULL,
                status TEXT NOT NULL CHECK(status IN (
                    'pending', 'retry_wait', 'running',
                    'completed', 'failed', 'blocked'
                )),
                attempt_count INTEGER NOT NULL,
                retry_delay_seconds REAL NOT NULL,
                available_at REAL NOT NULL,
                lease_owner TEXT,
                lease_expires_at REAL,
                claimed_at REAL,
                finished_at REAL,
                result_json TEXT,
                error_json TEXT,
                timing_json TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS dependencies(
                work_id TEXT NOT NULL REFERENCES work_items(work_id),
                dependency_id TEXT NOT NULL REFERENCES work_items(work_id),
                PRIMARY KEY(work_id, dependency_id)
            );

            CREATE TABLE IF NOT EXISTS attempts(
                work_id TEXT NOT NULL REFERENCES work_items(work_id),
                attempt INTEGER NOT NULL,
                owner TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN (
                    'running', 'completed', 'retry_wait', 'failed', 'interrupted'
                )),
                started_at REAL NOT NULL,
                finished_at REAL,
                error_json TEXT,
                timing_json TEXT,
                retry_delay_seconds REAL NOT NULL DEFAULT 0,
                producer_implementation_sha256 TEXT,
                PRIMARY KEY(work_id, attempt)
            );

            CREATE TABLE IF NOT EXISTS checkpoints(
                work_id TEXT NOT NULL REFERENCES work_items(work_id),
                name TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                producer_implementation_sha256 TEXT,
                PRIMARY KEY(work_id, name)
            );

            CREATE TABLE IF NOT EXISTS retry_cycles(
                work_id TEXT NOT NULL REFERENCES work_items(work_id),
                cycle INTEGER NOT NULL,
                attempt_base INTEGER NOT NULL,
                reason_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY(work_id, cycle)
            );

            CREATE TABLE IF NOT EXISTS provider_turn_metrics(
                work_id TEXT NOT NULL,
                name TEXT NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                reasoning_tokens INTEGER NOT NULL,
                cached_input_tokens INTEGER NOT NULL,
                latency_seconds REAL NOT NULL,
                normalization_count INTEGER NOT NULL DEFAULT 0,
                normalization_rule_counts_json TEXT NOT NULL DEFAULT '{}',
                request_context_json TEXT NOT NULL DEFAULT '{}',
                provider_cost_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY(work_id, name),
                FOREIGN KEY(work_id, name)
                  REFERENCES checkpoints(work_id, name)
            );

            CREATE TABLE IF NOT EXISTS runner_provenance(
                implementation_sha256 TEXT PRIMARY KEY,
                provenance_json TEXT NOT NULL,
                first_seen_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS work_status_available
            ON work_items(status, available_at);

            CREATE INDEX IF NOT EXISTS work_dispatch_key
            ON work_items(provider, model, status);
            """
        )
        columns = {
            str(row["name"])
            for row in self._connection.execute(
                "PRAGMA table_info(provider_turn_metrics)"
            ).fetchall()
        }
        if "normalization_count" not in columns:
            self._connection.execute(
                """
                ALTER TABLE provider_turn_metrics
                ADD COLUMN normalization_count INTEGER NOT NULL DEFAULT 0
                """
            )
        if "normalization_rule_counts_json" not in columns:
            self._connection.execute(
                """
                ALTER TABLE provider_turn_metrics
                ADD COLUMN normalization_rule_counts_json TEXT NOT NULL DEFAULT '{}'
                """
            )
        if "request_context_json" not in columns:
            self._connection.execute(
                """
                ALTER TABLE provider_turn_metrics
                ADD COLUMN request_context_json TEXT NOT NULL DEFAULT '{}'
                """
            )
        if "provider_cost_json" not in columns:
            self._connection.execute(
                """
                ALTER TABLE provider_turn_metrics
                ADD COLUMN provider_cost_json TEXT NOT NULL DEFAULT '{}'
                """
            )
        attempt_columns = {
            str(row["name"])
            for row in self._connection.execute(
                "PRAGMA table_info(attempts)"
            ).fetchall()
        }
        if "producer_implementation_sha256" not in attempt_columns:
            self._connection.execute(
                """
                ALTER TABLE attempts
                ADD COLUMN producer_implementation_sha256 TEXT
                """
            )
        checkpoint_columns = {
            str(row["name"])
            for row in self._connection.execute(
                "PRAGMA table_info(checkpoints)"
            ).fetchall()
        }
        if "producer_implementation_sha256" not in checkpoint_columns:
            self._connection.execute(
                """
                ALTER TABLE checkpoints
                ADD COLUMN producer_implementation_sha256 TEXT
                """
            )


def _progress_identity_text(
    value: Any,
    *,
    field: str,
    required: bool = False,
) -> str | None:
    if value is None:
        if required:
            raise RunStoreError(f"progress identity {field} must be non-empty")
        return None
    text = str(value).strip()
    if not text:
        if required:
            raise RunStoreError(f"progress identity {field} must be non-empty")
        return None
    if len(text) > 255 or any(ord(character) < 32 for character in text):
        raise RunStoreError(f"progress identity {field} is invalid")
    return text


def _progress_timestamp(
    value: Any,
    *,
    field: str,
    default: datetime | None = None,
) -> datetime:
    if value is None:
        if default is None:
            raise RunStoreError(f"progress timestamp {field} is required")
        result = default
    elif isinstance(value, datetime):
        result = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            result = datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as exc:
            raise RunStoreError(f"progress timestamp {field} is invalid") from exc
    elif isinstance(value, str):
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            result = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise RunStoreError(f"progress timestamp {field} is invalid") from exc
    else:
        raise RunStoreError(f"progress timestamp {field} is invalid")
    if result.tzinfo is None:
        raise RunStoreError(f"progress timestamp {field} must include a timezone")
    return result.astimezone(timezone.utc)


def _public_progress_metadata(identity: Mapping[str, Any]) -> dict[str, Any]:
    raw_metadata = identity.get("metadata", identity.get("metadata_json"))
    if isinstance(raw_metadata, str):
        try:
            raw_metadata = json.loads(raw_metadata)
        except json.JSONDecodeError:
            raw_metadata = None
    candidates = dict(raw_metadata) if isinstance(raw_metadata, Mapping) else {}
    for key in _PUBLIC_PROGRESS_METADATA_KEYS:
        if key in identity:
            candidates[key] = identity[key]
    return {
        key: candidates[key]
        for key in sorted(_PUBLIC_PROGRESS_METADATA_KEYS)
        if key in candidates and _is_public_progress_value(candidates[key])
    }


def _is_public_progress_value(value: Any) -> bool:
    if value is None or isinstance(value, (bool, int, str)):
        return True
    if isinstance(value, float):
        return value == value and value not in {float("inf"), float("-inf")}
    if isinstance(value, list):
        return all(_is_public_progress_value(item) for item in value)
    return False


def _safe_artifact_ref(value: Any) -> str | None:
    text = _progress_identity_text(value, field="artifact_ref")
    if text is None:
        return None
    parsed = urlsplit(text)
    if (
        parsed.username
        or parsed.password
        or parsed.query
        or parsed.scheme.lower() in {"postgres", "postgresql"}
    ):
        return None
    return text


def _work_selection_sql(
    work_ids: tuple[str, ...] | None, *, column: str = "work_id",
) -> tuple[str, tuple[str, ...]]:
    if column not in {"work_id", "item.work_id"}:
        raise ValueError("unsupported work selection column")
    if work_ids is None:
        return "", ()
    if not work_ids:
        return "AND 0=1", ()
    return f"AND {column} IN ({','.join('?' for _ in work_ids)})", tuple(work_ids)


def _time(value: float | None) -> float:
    timestamp = time.time() if value is None else float(value)
    if timestamp < 0:
        raise RunStoreError("timestamps cannot be negative")
    return timestamp


def _decode_spec(value: str) -> WorkSpec:
    return WorkSpec.from_dict(json.loads(value))


def _optional_json(value: str | None) -> Any:
    return None if value is None else json.loads(value)


def _decode_json_columns(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: (
            json.loads(row[key])
            if key.endswith("_json") and row[key] is not None
            else row[key]
        )
        for key in row.keys()
    }


def is_pre_response_disconnect(error: Any) -> bool:
    """Return whether an error is strictly a retryable no-response disconnect."""

    if not isinstance(error, dict):
        return False
    metadata = error.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    return (
        error.get("code") == "provider.request_failed"
        and error.get("retryable") is True
        and "http_status" not in metadata
        and metadata.get("response_received") is not True
    )


def is_retryable_failed_response(error: Any) -> bool:
    """Return whether an exhausted parsed failed response can be retried."""

    if not isinstance(error, dict):
        return False
    metadata = error.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    decision = error.get("retry_decision")
    provider_error_code = metadata.get("provider_error_code")
    transport = metadata.get("transport")
    try:
        accounting = failed_response_accounting_from_error(error)
    except (TypeError, ValueError, OverflowError):
        return False
    return (
        error.get("code") == "provider.request_failed"
        and error.get("retryable") is True
        and isinstance(transport, str)
        and bool(transport.strip())
        and "http_status" not in metadata
        and metadata.get("response_received") is True
        and isinstance(provider_error_code, str)
        and provider_error_code in RETRYABLE_FAILED_RESPONSE_CODES
        and accounting is not None
        and decision in {None, "attempt_limit", "delay_budget"}
    )


def is_retryable_http_failure(error: Any) -> bool:
    """Return whether an exhausted provider HTTP failure can be retried later."""

    if not isinstance(error, dict):
        return False
    metadata = error.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    status = metadata.get("http_status")
    transport = metadata.get("transport")
    decision = error.get("retry_decision")
    return (
        error.get("code") == "provider.request_failed"
        and error.get("retryable") is True
        and isinstance(transport, str)
        and bool(transport.strip())
        and isinstance(status, int)
        and not isinstance(status, bool)
        and status in RETRYABLE_HTTP_STATUSES
        and decision in {None, "attempt_limit", "delay_budget"}
    )


def _verify_checkpoint_sha(
    *,
    work_id: str,
    name: str,
    payload_json: str,
    payload_sha256: str,
) -> None:
    actual = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    if actual != payload_sha256:
        raise RunStoreError(
            f"checkpoint payload hash mismatch: {work_id}/{name}"
        )


def _decode_verified_checkpoint(
    *,
    work_id: str,
    name: str,
    payload_json: str,
    payload_sha256: str,
) -> Any:
    _verify_checkpoint_sha(
        work_id=work_id,
        name=name,
        payload_json=payload_json,
        payload_sha256=payload_sha256,
    )
    try:
        return json.loads(payload_json)
    except json.JSONDecodeError as exc:
        raise RunStoreError(
            f"checkpoint payload is invalid JSON: {work_id}/{name}"
        ) from exc


def _runner_implementation_provenance() -> dict[str, Any]:
    benchmarks_root = Path(__file__).resolve().parents[1]
    source_roots = (
        benchmarks_root / "benchrunner",
        benchmarks_root / "react_report_building",
    )
    sources = []
    paths = sorted(
        path
        for source_root in source_roots
        for path in source_root.rglob("*.py")
        if "tests" not in path.relative_to(source_root).parts
    )
    for path in paths:
        relative = path.relative_to(benchmarks_root).as_posix()
        sources.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    fingerprint_payload = {
        "schema_version": RUNNER_PROVENANCE_SCHEMA_VERSION,
        "sources": sources,
    }
    return {
        **fingerprint_payload,
        "implementation_sha256": hashlib.sha256(
            canonical_json(fingerprint_payload).encode("utf-8")
        ).hexdigest(),
    }


def _is_dependency_failure(error: Any) -> bool:
    return isinstance(error, dict) and error.get("code") == "dependency.failed"


def _write_provider_turn_metric(
    cursor: Any,
    work_id: str,
    name: str,
    payload: Any,
    *,
    replace: bool,
    postgresql: bool = False,
) -> None:
    metric = _provider_turn_metric(payload)
    if metric is None and name.startswith("provider-turn-"):
        raise RunStoreError(
            f"provider-turn checkpoint has invalid compact metrics: {work_id}/{name}"
        )
    if replace:
        cursor.execute(
            "DELETE FROM provider_turn_metrics WHERE work_id = ? AND name = ?",
            (work_id, name),
        )
    if metric is None:
        return
    cursor.execute(
        (
            """
            INSERT INTO provider_turn_metrics(
                work_id, name, input_tokens, output_tokens, reasoning_tokens,
                cached_input_tokens, latency_seconds, normalization_count,
                normalization_rule_counts_json, request_context_json,
                provider_cost_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, work_id, name) DO NOTHING
            """
            if postgresql
            else """
            INSERT OR IGNORE INTO provider_turn_metrics(
                work_id, name, input_tokens, output_tokens, reasoning_tokens,
                cached_input_tokens, latency_seconds, normalization_count,
                normalization_rule_counts_json, request_context_json,
                provider_cost_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
        ),
        (
            work_id,
            name,
            metric["input_tokens"],
            metric["output_tokens"],
            metric["reasoning_tokens"],
            metric["cached_input_tokens"],
            metric["latency_seconds"],
            metric["normalization_count"],
            canonical_json(metric["normalization_rule_counts"]),
            canonical_json(metric["request_context"]),
            canonical_json(metric["provider_cost"]),
        ),
    )


def _provider_turn_metric(payload: Any) -> dict[str, Any] | None:
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version")
        != "benchrunner.provider_turn_checkpoint/v1"
        or not isinstance(payload.get("provider_turn"), dict)
    ):
        return None
    turn = payload["provider_turn"]
    usage = turn.get("usage")
    if not isinstance(usage, dict):
        return None
    try:
        values = {
            field: int(usage.get(field) or 0)
            for field in (
                "input_tokens",
                "output_tokens",
                "reasoning_tokens",
                "cached_input_tokens",
            )
        }
        latency = float(turn.get("latency_seconds") or 0.0)
    except (TypeError, ValueError):
        return None
    if any(value < 0 for value in values.values()) or latency < 0:
        return None
    normalizations = turn.get("normalizations") or []
    if not isinstance(normalizations, list):
        return None
    rule_counts: dict[str, int] = {}
    for normalization in normalizations:
        if not isinstance(normalization, dict):
            return None
        rule = str(normalization.get("kind") or "").strip()
        if not rule:
            return None
        rule_counts[rule] = rule_counts.get(rule, 0) + 1
    request_context = _sanitized_request_context(turn.get("request_context"))
    if request_context is None:
        return None
    try:
        if "provider_cost" in turn:
            provider_cost = normalize_provider_cost(turn.get("provider_cost"))
        else:
            provider_cost = provider_cost_from_usage(usage)
    except (TypeError, ValueError):
        return None
    return {
        **values,
        "latency_seconds": latency,
        "normalization_count": len(normalizations),
        "normalization_rule_counts": dict(sorted(rule_counts.items())),
        "request_context": request_context,
        "provider_cost": provider_cost,
    }


def _sanitized_request_context(value: Any) -> dict[str, Any] | None:
    """Retain bounded size, budget and terminal-policy provenance in the ledger."""

    if value is None or value == {}:
        return {}
    if not isinstance(value, dict):
        return None
    schema_version = value.get("schema_version")
    if schema_version not in {
        "react_report.request_context/v1",
        "react_report.request_context/v2",
        "react_report.request_context/v3",
    }:
        return None
    if value.get("measurement") != "serialized_characters_not_tokens":
        return None
    action_protocol = value.get("action_protocol")
    if not isinstance(action_protocol, str) or not action_protocol:
        return None
    integer_fields = (
        "replayed_turn_count",
        "input_item_count",
        "serialized_input_characters",
        "tool_definition_characters",
        "protocol_instruction_characters",
    )
    integers: dict[str, int] = {}
    for field in integer_fields:
        raw = value.get(field)
        if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
            return None
        integers[field] = raw
    raw_categories = value.get("categories")
    if not isinstance(raw_categories, dict):
        return None
    categories: dict[str, dict[str, int]] = {}
    for raw_name, raw_bucket in raw_categories.items():
        name = str(raw_name).strip()
        if not name or not isinstance(raw_bucket, dict):
            return None
        item_count = raw_bucket.get("items")
        characters = raw_bucket.get("serialized_characters")
        if (
            not isinstance(item_count, int)
            or isinstance(item_count, bool)
            or item_count < 0
            or not isinstance(characters, int)
            or isinstance(characters, bool)
            or characters < 0
        ):
            return None
        categories[name] = {
            "items": item_count,
            "serialized_characters": characters,
        }
    result = {
        "schema_version": schema_version,
        "measurement": "serialized_characters_not_tokens",
        "action_protocol": action_protocol,
        **integers,
        "categories": dict(sorted(categories.items())),
    }
    if "request_payload_sha256" in value:
        digest = value["request_payload_sha256"]
        if not isinstance(digest, str) or re.fullmatch(r"[a-f0-9]{64}", digest) is None:
            return None
        result["request_payload_sha256"] = digest
    if "generation_seed" in value:
        seed = value["generation_seed"]
        if type(seed) is not int or not 0 <= seed <= 2_147_483_647:
            return None
        result["generation_seed"] = seed
    if schema_version == "react_report.request_context/v3":
        instruction_characters = value.get(
            "top_level_instruction_characters"
        )
        if (
            not isinstance(instruction_characters, int)
            or isinstance(instruction_characters, bool)
            or instruction_characters < 0
            or value.get("instructions_transport")
            != "responses.instructions"
        ):
            return None
        result["top_level_instruction_characters"] = instruction_characters
        result["instructions_transport"] = "responses.instructions"
    if schema_version == "react_report.request_context/v2":
        action_output_contract = value.get("action_output_contract")
        constraint = value.get("structured_constraint")
        if (
            not isinstance(action_output_contract, str)
            or not action_output_contract
            or not isinstance(constraint, dict)
        ):
            return None
        expected_strings = (
            "contract",
            "schema_version",
            "kind",
            "request_field",
            "sha256",
        )
        strings: dict[str, str] = {}
        for field in expected_strings:
            raw = constraint.get(field)
            if not isinstance(raw, str) or not raw:
                return None
            strings[field] = raw
        serialized_characters = constraint.get("serialized_characters")
        if (
            not isinstance(serialized_characters, int)
            or isinstance(serialized_characters, bool)
            or serialized_characters < 0
            or strings["contract"] != action_output_contract
        ):
            return None
        result["action_output_contract"] = action_output_contract
        result["structured_constraint"] = {
            **strings,
            "serialized_characters": serialized_characters,
        }
    if "context_budget" in value:
        from math import isfinite
        from benchmarks.react_report_building.runtime.context_budget import ContextBudget

        raw = value["context_budget"]
        if not isinstance(raw, dict):
            return None
        probe_limits = raw.get("probe_limits")
        if probe_limits is not None and not isinstance(probe_limits, dict):
            return None
        try:
            policy = ContextBudget(
                raw.get("context_window_tokens"), raw.get("context_safety_margin_tokens"),
                raw.get("input_token_count_mode"), raw.get("input_token_counter_id"),
                context_probe_max_requests=(probe_limits or {}).get("max_requests"),
                context_probe_max_cost_usd=(probe_limits or {}).get("max_cost_usd"),
            ).provenance()
        except (TypeError, ValueError):
            return None
        # Preserve historical v2 receipts: their accepted probe output was one
        # token. New v3 policies explicitly reserve/account up to eight.
        if raw.get("schema_version") == "react_report.context_budget/v2" and policy["input_token_count_mode"] == "openrouter_probe_on_clamp":
            policy["schema_version"] = "react_report.context_budget/v2"
            policy["probe_limits"].pop("requested_output_tokens", None)
            policy["probe_limits"].pop("max_observed_output_tokens", None)
        if raw.get("schema_version") == "react_report.context_budget/v3" and policy["input_token_count_mode"] == "openrouter_probe_on_clamp":
            policy["schema_version"] = "react_report.context_budget/v3"
            policy["probe_limits"].update(requested_output_tokens=1, max_observed_output_tokens=8)
        if any(raw.get(key) != expected for key, expected in policy.items()):
            return None
        budget = dict(policy)
        for field in ("requested_max_output_tokens", "request_payload_bytes", "input_tokens", "effective_max_output_tokens"):
            number = raw.get(field)
            if number is None and field in {"input_tokens", "effective_max_output_tokens"}:
                budget[field] = None
            elif not isinstance(number, int) or isinstance(number, bool) or number < 0:
                return None
            else:
                budget[field] = number
        for field in ("requested_payload_sha256", "effective_payload_sha256"):
            digest = raw.get(field)
            if digest is None and field == "effective_payload_sha256":
                continue
            if not isinstance(digest, str) or re.fullmatch(r"[a-f0-9]{64}", digest) is None:
                return None
            budget[field] = digest
        mode = policy["input_token_count_mode"]
        conditional_probe = mode == "openrouter_probe_on_clamp"
        kind = raw.get("count_kind")
        if conditional_probe:
            triggered = raw.get("probe_triggered")
            estimate = raw.get("estimated_input_tokens")
            if (
                not isinstance(triggered, bool)
                or not isinstance(estimate, int) or isinstance(estimate, bool) or estimate < 0
                or not isinstance(kind, str) or kind not in {"estimate", "exact"}
                or (not triggered and kind != "estimate")
            ):
                return None
            budget.update(probe_triggered=triggered, estimated_input_tokens=estimate)
        elif kind != ("estimate" if mode == "conservative_bytes" else "exact"):
            return None
        budget["count_kind"] = kind
        if "estimate_assumption" in raw:
            assumption = (
                "one token per UTF-8 byte of the complete JSON request; "
                "server template expansion is covered only by the configured margin; "
                "not a tokenizer count or a guaranteed model-specific bound"
            )
            if raw["estimate_assumption"] != assumption:
                return None
            budget["estimate_assumption"] = assumption
        if "output_was_clamped" in raw:
            if not isinstance(raw["output_was_clamped"], bool):
                return None
            budget["output_was_clamped"] = raw["output_was_clamped"]
        if "preflight" in raw:
            preflight = raw["preflight"]
            if not isinstance(preflight, dict):
                return None
            expected_kind = {
                "openai_responses": "openai_input_tokens",
                "responses_probe": "self_hosted_responses_probe",
                "vllm_responses": "self_hosted_responses_count",
                "openrouter_probe_on_clamp": "openrouter_responses_probe",
            }.get(mode)
            if expected_kind is None or preflight.get("kind") != expected_kind:
                return None
            if conditional_probe and not triggered:
                return None
            generation_requested = expected_kind in {"self_hosted_responses_probe", "openrouter_responses_probe"}
            if preflight.get("generation_requested") is not generation_requested:
                return None
            count = preflight.get("request_count")
            latency = preflight.get("latency_seconds", 0 if count == 0 else None)
            digest = preflight.get("request_payload_sha256")
            if (
                not isinstance(count, int) or isinstance(count, bool)
                or count not in (set(range(21)) if "attempts" in preflight else {0, 1} if conditional_probe else {1})
                or not isinstance(latency, (int, float)) or isinstance(latency, bool)
                or not isfinite(latency) or latency < 0
                or (count == 0 and latency != 0)
                or (digest is None and count != 0)
                or (digest is not None and (not isinstance(digest, str) or re.fullmatch(r"[a-f0-9]{64}", digest) is None))
            ):
                return None
            clean_preflight = {
                "kind": expected_kind, "generation_requested": generation_requested,
                "request_count": count, "latency_seconds": latency,
            }
            if digest is not None:
                clean_preflight["request_payload_sha256"] = digest
            if generation_requested:
                requested_probe_output = policy.get("probe_limits", {}).get("requested_output_tokens", 1)
                if preflight.get("max_output_tokens") != requested_probe_output:
                    return None
                clean_preflight["max_output_tokens"] = requested_probe_output
            if "http_status" in preflight:
                status = preflight["http_status"]
                if count == 0 or isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
                    return None
                clean_preflight["http_status"] = status
            if "usage" in preflight:
                usage = preflight["usage"]
                if not generation_requested or not isinstance(usage, dict):
                    return None
                clean_usage = {}
                for field in ("input_tokens", "output_tokens", "reasoning_tokens", "cached_input_tokens"):
                    number = usage.get(field)
                    if number is not None and (not isinstance(number, int) or isinstance(number, bool) or number < 0):
                        return None
                    if count == 0 and number not in {None, 0}:
                        return None
                    clean_usage[field] = number
                clean_preflight["usage"] = clean_usage
            if "usage_warnings" in preflight:
                usage = clean_preflight.get("usage", {})
                if (preflight["usage_warnings"] != ["reasoning_tokens_exceed_output_tokens"]
                    or mode != "openrouter_probe_on_clamp"
                    or not isinstance(usage.get("reasoning_tokens"), int)
                    or not isinstance(usage.get("output_tokens"), int)
                    or usage["reasoning_tokens"] <= usage["output_tokens"]):
                    return None
                clean_preflight["usage_warnings"] = list(preflight["usage_warnings"])
            if "actions_executed" in preflight:
                if type(preflight["actions_executed"]) is not int or preflight["actions_executed"] != 0:
                    return None
                clean_preflight["actions_executed"] = 0
            if mode == "vllm_responses":
                if (preflight.get("input_payload_altered") is not False
                    or type(preflight.get("input_token_delta")) is not int or preflight["input_token_delta"] != 0):
                    return None
                clean_preflight.update(input_payload_altered=False, input_token_delta=0)
                details = preflight.get("counting")
                if details is not None:
                    from benchmarks.benchrunner.providers.vllm_input_tokens import SCHEMA_VERSION, SUPPORTED_VERSIONS
                    expected_counting = {
                        "schema_version": SCHEMA_VERSION, "method": "vllm_responses_renderer",
                        "request_payload_sha256": digest, "generation_requested": False,
                        "actions_executed": 0, "input_payload_altered": False,
                        "input_token_delta": 0, "render_only_overrides": {"max_output_tokens": 1},
                    }
                    if (not isinstance(details, dict)
                        or any(type(details.get(k)) is not type(v) or details[k] != v for k, v in expected_counting.items())
                        or type(details["render_only_overrides"].get("max_output_tokens")) is not int):
                        return None
                    version, renderer = details.get("vllm_version"), details.get("renderer_source_sha256")
                    if not isinstance(version, str) or version.split("+", 1)[0] not in SUPPORTED_VERSIONS:
                        return None
                    if not isinstance(renderer, str) or re.fullmatch(r"[a-f0-9]{64}", renderer) is None:
                        return None
                    model = details.get("model")
                    if not isinstance(model, str) or not model or len(model) > 200:
                        return None
                    clean_preflight["counting"] = {**expected_counting, "model": model, "vllm_version": version, "renderer_source_sha256": renderer}
            if "observed_output_tokens" in preflight:
                observed = preflight["observed_output_tokens"]
                ceiling = policy.get("probe_limits", {}).get("max_observed_output_tokens", 1)
                if (not generation_requested or isinstance(observed, bool) or not isinstance(observed, int) or observed < 0
                    or preflight.get("requested_output_tokens") != requested_probe_output
                    or preflight.get("max_observed_output_tokens") != ceiling
                    or preflight.get("output_cap_overrun") is not (observed > requested_probe_output)
                    or preflight.get("usage", {}).get("output_tokens") != observed):
                    return None
                clean_preflight.update(requested_output_tokens=requested_probe_output, observed_output_tokens=observed,
                                       max_observed_output_tokens=ceiling, output_cap_overrun=observed > requested_probe_output)
            if "provider_cost" in preflight:
                try:
                    cost = normalize_provider_cost(preflight["provider_cost"])
                except (TypeError, ValueError):
                    return None
                if count == 0 and cost:
                    return None
                clean_preflight["provider_cost"] = cost
            if "openrouter_metadata" in preflight:
                from benchmarks.benchrunner.providers.profiles import sanitize_openrouter_metadata

                if mode != "openrouter_probe_on_clamp" or count == 0:
                    return None
                metadata = sanitize_openrouter_metadata(preflight["openrouter_metadata"])
                if metadata is not None:
                    clean_preflight["openrouter_metadata"] = metadata
            if "failure_code" in preflight:
                code = preflight["failure_code"]
                if not isinstance(code, str) or code not in {
                    "invalid_probe_budget", "invalid_probe_receipt", "incompatible_probe_budget",
                    "corrupt_probe_budget", "probe_budget_storage_error", "probe_price_cap_breached",
                    "probe_request_limit", "probe_cost_limit", "unknown_probe_reservation",
                    "conflicting_probe_settlement", "probe_cost_accounting_unsupported",
                    "openrouter_count_probe_failed",
                }:
                    return None
                clean_preflight["failure_code"] = code
            if "budget_reservation" in preflight:
                from decimal import Decimal
                from benchmarks.react_report_building.runtime.provider_cost import canonical_decimal_string

                reservation = preflight["budget_reservation"]
                if not conditional_probe or not isinstance(reservation, dict):
                    return None
                token = reservation.get("reservation_id")
                item = reservation.get("reservation")
                state = reservation.get("budget")
                if (
                    not isinstance(token, str) or re.fullmatch(r"[a-f0-9]{32}", token) is None
                    or not isinstance(item, dict) or not isinstance(state, dict)
                    or state.get("schema_version") != "benchrunner.context_probe_budget/v1"
                ):
                    return None
                clean_item: dict[str, Any] = {}
                clean_state: dict[str, Any] = {"schema_version": "benchrunner.context_probe_budget/v1"}
                for source, target, field in (
                    (item, clean_item, "request_payload_sha256"),
                    (state, clean_state, "treatment_sha256"),
                ):
                    digest = source.get(field)
                    if not isinstance(digest, str) or re.fullmatch(r"[a-f0-9]{64}", digest) is None:
                        return None
                    target[field] = digest
                if not isinstance(item.get("state"), str) or item["state"] not in {"reserved", "unknown", "known", "overrun", "unsupported_cost"}:
                    return None
                clean_item["state"] = item["state"]
                for source, target, fields in (
                    (item, clean_item, ("worst_case_cost_usd", "observed_cost_usd", "charged_cost_usd")),
                    (state, clean_state, ("max_cost_usd", "charged_cost_usd", "remaining_cost_usd")),
                ):
                    for field in fields:
                        amount = source.get(field)
                        if amount is None and field == "observed_cost_usd":
                            target[field] = None
                            continue
                        if not isinstance(amount, str):
                            return None
                        try:
                            target[field] = canonical_decimal_string(amount)
                        except ValueError:
                            return None
                for field in ("max_requests", "requests_reserved", "requests_remaining", "unconfirmed_requests"):
                    number = state.get(field)
                    if not isinstance(number, int) or isinstance(number, bool) or not 0 <= number <= 100000:
                        return None
                    clean_state[field] = number
                if (
                    not 1 <= clean_state["max_requests"] <= policy["probe_limits"]["max_requests"]
                    or not Decimal("0") < Decimal(clean_state["max_cost_usd"]) <= Decimal(policy["probe_limits"]["max_cost_usd"])
                    or clean_state["requests_reserved"] + clean_state["requests_remaining"] != clean_state["max_requests"]
                    or clean_state["unconfirmed_requests"] > clean_state["requests_reserved"]
                    or not isinstance(state.get("poisoned"), bool)
                ):
                    return None
                clean_state["poisoned"] = state["poisoned"]
                clean_preflight["budget_reservation"] = {
                    "reservation_id": token, "reservation": clean_item, "budget": clean_state,
                }
            attempts = preflight.get("attempts")
            if attempts is not None:
                if not isinstance(attempts, list) or not 1 <= len(attempts) <= 20:
                    return None
                clean_attempts = []
                for attempt in attempts:
                    if not isinstance(attempt, dict) or "attempts" in attempt or attempt.get("request_count") not in {0, 1}:
                        return None
                    candidate = {**value, "context_budget": {**raw, "preflight": attempt}}
                    clean = _sanitized_request_context(candidate)
                    if clean is None:
                        return None
                    cleaned = clean["context_budget"]["preflight"]
                    retry = attempt.get("retry")
                    if retry is not None:
                        if (not isinstance(retry, dict) or type(retry.get("attempt")) is not int
                            or not 1 <= retry["attempt"] <= 20 or type(retry.get("will_retry")) is not bool
                            or not isinstance(retry.get("delay_seconds"), (int, float))
                            or not isfinite(retry["delay_seconds"]) or retry["delay_seconds"] < 0
                            or retry.get("reason") not in {"retryable", "non_retryable", "attempt_limit", "delay_budget"}):
                            return None
                        cleaned["retry"] = {k: retry[k] for k in ("attempt", "will_retry", "delay_seconds", "reason")}
                    clean_attempts.append(cleaned)
                if sum(a["request_count"] for a in clean_attempts) != count:
                    return None
                clean_preflight["attempts"] = clean_attempts
                clean_preflight["retry_wait_seconds"] = sum(a.get("retry", {}).get("delay_seconds", 0) for a in clean_attempts)
            elif count > 1:
                return None
            budget["preflight"] = clean_preflight
        result["context_budget"] = budget
    if "native_tool_policy" in value:
        from benchmarks.react_report_building.runtime.native_tool_policy import native_tool_policy_provenance

        raw = value["native_tool_policy"]
        if not isinstance(raw, dict):
            return None
        try:
            policy = native_tool_policy_provenance(raw.get("selection"))
            # Canonical JSON preserves Boolean-vs-integer distinctions that
            # Python mapping equality would erase (True == 1).
            if policy is None or canonical_json(raw) != canonical_json(policy):
                return None
        except (TypeError, ValueError):
            return None
        result["native_tool_policy"] = policy
    if "final_turn_tool_choice_policy" in value:
        from benchmarks.react_report_building.runtime.final_turn_policy import final_turn_policy_provenance

        raw = value["final_turn_tool_choice_policy"]
        if not isinstance(raw, dict):
            return None
        try:
            policy = final_turn_policy_provenance(raw.get("selection"))
        except (TypeError, ValueError):
            return None
        if policy is None or any(raw.get(key) != expected for key, expected in policy.items()):
            return None
        result["final_turn_tool_choice_policy"] = policy
    if "effective_tool_choice" in value:
        choice = value["effective_tool_choice"]
        if isinstance(choice, str) and choice in {"auto", "required", "none"}:
            result["effective_tool_choice"] = choice
        elif isinstance(choice, dict) and choice.get("type") == "function" and isinstance(choice.get("name"), str) and choice["name"] in {"create_report", "create_section", "replace_section", "keep_section"}:
            result["effective_tool_choice"] = {"type": "function", "name": choice["name"]}
        else:
            return None
    return result


def _decode_state(row: Mapping[str, Any]) -> WorkState:
    return WorkState(
        work=_decode_spec(row["spec_json"]),
        status=str(row["status"]),
        attempt_count=int(row["attempt_count"]),
        available_at=float(row["available_at"]),
        lease_owner=(str(row["lease_owner"]) if row["lease_owner"] is not None else None),
        lease_expires_at=(
            float(row["lease_expires_at"])
            if row["lease_expires_at"] is not None
            else None
        ),
        retry_delay_seconds=float(row["retry_delay_seconds"]),
        result=_optional_json(row["result_json"]),
        error=_optional_json(row["error_json"]),
        timing=_optional_json(row["timing_json"]),
    )
