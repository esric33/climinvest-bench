"""Read-only HTTP API for sanitized benchmark progress rollups.

The API reads only ``public.benchrunner_run_progress``.  That relation is a
rebuildable registry/rollup, not the authoritative scheduler or checkpoint
store.  Database credentials are accepted only through an environment variable
by the command-line entry point and are never included in responses.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable, Mapping, Protocol, Sequence
from urllib.parse import parse_qs, unquote, urlsplit


RUN_PROGRESS_SCHEMA_VERSION = "benchrunner.run_progress/v1"
RUN_PROGRESS_COLLECTION_SCHEMA_VERSION = "benchrunner.run_progress_collection/v1"
HEALTH_SCHEMA_VERSION = "benchrunner.progress_api_health/v1"
ERROR_SCHEMA_VERSION = "benchrunner.progress_api_error/v1"

DEFAULT_LIMIT = 100
MAX_LIMIT = 200
STALE_AFTER_SECONDS = 120
MIN_ETA_ELAPSED_SECONDS = 300
MIN_ETA_TERMINAL_WORK = 3

_RUN_ID = re.compile(r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")
_FILTER_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_TERMINAL_RUN_STATES = frozenset(
    {
        "cancelled",
        "completed",
        "completed_with_failures",
        "failed",
        "interrupted",
        "succeeded",
    }
)
_PUBLIC_METADATA_KEYS = frozenset(
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

_SELECT_COLUMNS = (
    "run_id",
    "backend",
    "cluster_profile",
    "model_alias",
    "study_id",
    "plan_id",
    "run_label",
    "state",
    "total",
    "pending",
    "retry_wait",
    "running",
    "completed",
    "failed",
    "blocked",
    "episodes_total",
    "episodes_completed",
    "records_total",
    "records_completed",
    "provider_turns",
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "cached_input_tokens",
    "started_at",
    "updated_at",
    "finished_at",
    "artifact_ref",
    "metadata_json",
)
_SELECT_LIST = ", ".join(_SELECT_COLUMNS)


class ProgressAPIError(RuntimeError):
    """Base error for progress registry reads and response validation."""


class QueryError(ProgressAPIError):
    """Raised for an invalid HTTP query."""


class ProgressRepository(Protocol):
    """Minimal read contract used by the HTTP layer."""

    def health(self) -> None: ...

    def list_runs(
        self,
        *,
        state: str | None = None,
        backend: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> Sequence[Mapping[str, Any]]: ...

    def get_run(self, run_id: str) -> Mapping[str, Any] | None: ...


class PostgresProgressRepository:
    """Read the explicit public columns of the PostgreSQL progress registry."""

    def __init__(
        self,
        database_url: str,
        *,
        connect: Callable[[], Any] | None = None,
    ) -> None:
        value = str(database_url or "").strip()
        if not value:
            raise ProgressAPIError("the progress database URL is not configured")
        self._database_url = value
        self._connect_override = connect

    def _connect(self) -> Any:
        if self._connect_override is not None:
            return self._connect_override()
        try:
            import psycopg  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - depends on install extra
            raise ProgressAPIError(
                "PostgreSQL support requires the optional psycopg dependency"
            ) from exc
        return psycopg.connect(
            self._database_url,
            connect_timeout=5,
            options=(
                "-c default_transaction_read_only=on "
                "-c statement_timeout=3000 "
                "-c lock_timeout=1000 "
                "-c idle_in_transaction_session_timeout=5000"
            ),
        )

    def health(self) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                # Verify the exact v1 projection, not merely that a relation of
                # the expected name exists.  A partially migrated registry must
                # not make the Deployment ready while every real read fails.
                cursor.execute(
                    f"SELECT {_SELECT_LIST} "
                    "FROM public.benchrunner_run_progress LIMIT 0"
                )

    def list_runs(
        self,
        *,
        state: str | None = None,
        backend: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> Sequence[Mapping[str, Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if state is not None:
            clauses.append("state = %s")
            parameters.append(state)
        if backend is not None:
            clauses.append("backend = %s")
            parameters.append(backend)
        where = "" if not clauses else " WHERE " + " AND ".join(clauses)
        statement = (
            f"SELECT {_SELECT_LIST} FROM public.benchrunner_run_progress"
            f"{where} ORDER BY updated_at DESC NULLS LAST, run_id ASC LIMIT %s"
        )
        parameters.append(limit)
        return self._query(statement, parameters)

    def get_run(self, run_id: str) -> Mapping[str, Any] | None:
        rows = self._query(
            (
                f"SELECT {_SELECT_LIST} FROM public.benchrunner_run_progress "
                "WHERE run_id = %s"
            ),
            [run_id],
        )
        return rows[0] if rows else None

    def _query(
        self,
        statement: str,
        parameters: Sequence[Any],
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(statement, tuple(parameters))
                description = cursor.description or ()
                names = []
                for column in description:
                    name = getattr(column, "name", None)
                    names.append(str(column[0] if name is None else name))
                return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


@dataclass(frozen=True, slots=True)
class _ListQuery:
    state: str | None
    backend: str | None
    limit: int


@dataclass(frozen=True, slots=True)
class ProgressResponse:
    status: int
    value: Mapping[str, Any]
    headers: Mapping[str, str]


class ProgressApplication:
    """Pure request dispatcher, kept independent from sockets for testing."""

    def __init__(self, repository: ProgressRepository) -> None:
        self.repository = repository

    def handle(
        self,
        method: str,
        target: str,
        *,
        observed_at: datetime | None = None,
    ) -> ProgressResponse:
        if method not in {"GET", "HEAD"}:
            return self._error(
                405,
                "method_not_allowed",
                "only GET is supported",
                headers={"Allow": "GET"},
            )
        try:
            parsed = urlsplit(target)
            if parsed.path == "/healthz":
                if parsed.query:
                    raise QueryError(
                        "health endpoint does not accept query parameters"
                    )
                self.repository.health()
                return ProgressResponse(
                    200,
                    {
                        "schema_version": HEALTH_SCHEMA_VERSION,
                        "status": "ok",
                    },
                    {},
                )
            now = observed_at or datetime.now(timezone.utc)
            if parsed.path == "/v1/runs":
                query = _parse_list_query(parsed.query)
                rows = self.repository.list_runs(
                    state=query.state,
                    backend=query.backend,
                    limit=query.limit,
                )
                runs = [_public_run(row, observed_at=now) for row in rows]
                return ProgressResponse(
                    200,
                    {
                        "schema_version": RUN_PROGRESS_COLLECTION_SCHEMA_VERSION,
                        "generated_at": _timestamp(now),
                        "count": len(runs),
                        "filters": {
                            "state": query.state,
                            "backend": query.backend,
                            "limit": query.limit,
                        },
                        "runs": runs,
                    },
                    {},
                )
            prefix = "/v1/runs/"
            if parsed.path.startswith(prefix):
                if parsed.query:
                    raise QueryError(
                        "run detail endpoint does not accept query parameters"
                    )
                run_id = unquote(parsed.path[len(prefix) :])
                _validate_run_id(run_id)
                row = self.repository.get_run(run_id)
                if row is None:
                    return self._error(404, "run_not_found", "run not found")
                return ProgressResponse(
                    200,
                    _public_run(row, observed_at=now),
                    {},
                )
            return self._error(404, "not_found", "endpoint not found")
        except QueryError as exc:
            return self._error(400, "invalid_request", str(exc))
        except Exception:
            # Database errors can include connection strings, usernames, hosts,
            # and server details.  Keep all such material out of HTTP responses.
            return self._error(
                503,
                "progress_unavailable",
                "progress data is unavailable",
            )

    @staticmethod
    def _error(
        status: int,
        code: str,
        message: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> ProgressResponse:
        return ProgressResponse(
            status,
            {
                "schema_version": ERROR_SCHEMA_VERSION,
                "error": {"code": code, "message": message},
            },
            dict(headers or {}),
        )


class ProgressHTTPServer(HTTPServer):
    """Bounded single-process HTTP server carrying a read-only repository.

    Overview clients need one aggregate request, so a single request worker is
    sufficient and avoids an unbounded thread/connection fan-out. PostgreSQL
    connect, statement, and lock timeouts bound a slow request.
    """

    def __init__(
        self,
        server_address: tuple[str, int],
        repository: ProgressRepository,
    ) -> None:
        self.repository = repository
        self.application = ProgressApplication(repository)
        super().__init__(server_address, ProgressRequestHandler)


class ProgressRequestHandler(BaseHTTPRequestHandler):
    """Serve versioned JSON without revealing backend exception details."""

    server: ProgressHTTPServer
    protocol_version = "HTTP/1.1"
    server_version = "benchrun-progress-api"
    sys_version = ""

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        self._dispatch()

    def do_HEAD(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        self._dispatch(head=True)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        self._dispatch()

    def do_PUT(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        self._dispatch()

    def do_DELETE(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        self._dispatch()

    def do_PATCH(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        self._dispatch()

    def do_OPTIONS(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        self._dispatch()

    def log_message(self, format: str, *args: Any) -> None:
        # Keep the default operational log shape while ensuring values are
        # rendered by BaseHTTPRequestHandler rather than interpolated as data.
        super().log_message(format, *args)

    def _dispatch(self, *, head: bool = False) -> None:
        response = self.server.application.handle(self.command, self.path)
        self._json(
            response.status,
            response.value,
            head=head,
            extra_headers=response.headers,
        )

    def _json(
        self,
        status: int,
        value: Mapping[str, Any],
        *,
        head: bool = False,
        extra_headers: Mapping[str, str] | None = None,
    ) -> None:
        body = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, header_value in (extra_headers or {}).items():
            self.send_header(name, header_value)
        self.end_headers()
        if not head:
            self.wfile.write(body)
        self.close_connection = True


def _parse_list_query(query: str) -> _ListQuery:
    values = parse_qs(query, keep_blank_values=True, strict_parsing=False)
    unknown = sorted(set(values) - {"backend", "limit", "state"})
    if unknown:
        raise QueryError("unknown query parameter(s): " + ", ".join(unknown))

    def optional(name: str) -> str | None:
        candidates = values.get(name, [])
        if not candidates:
            return None
        if len(candidates) != 1:
            raise QueryError(f"query parameter {name!r} may be supplied only once")
        value = candidates[0]
        if not _FILTER_VALUE.fullmatch(value):
            raise QueryError(f"query parameter {name!r} is invalid")
        return value

    raw_limit = values.get("limit", [str(DEFAULT_LIMIT)])
    if len(raw_limit) != 1:
        raise QueryError("query parameter 'limit' may be supplied only once")
    try:
        limit = int(raw_limit[0])
    except ValueError as exc:
        raise QueryError("query parameter 'limit' must be an integer") from exc
    if not 1 <= limit <= MAX_LIMIT:
        raise QueryError(
            f"query parameter 'limit' must be between 1 and {MAX_LIMIT}"
        )
    return _ListQuery(state=optional("state"), backend=optional("backend"), limit=limit)


def _validate_run_id(run_id: str) -> str:
    if len(run_id) > 63 or _RUN_ID.fullmatch(run_id) is None:
        raise QueryError(
            "run ID must be a lowercase DNS label of at most 63 characters"
        )
    return run_id


def format_run_progress(
    row: Mapping[str, Any],
    *,
    observed_at: datetime,
) -> dict[str, Any]:
    """Build the sanitized portable schema, retaining unavailable telemetry."""
    return _public_run(row, observed_at=observed_at, allow_unknown_provider_counts=True)


def _public_run(
    row: Mapping[str, Any],
    *,
    observed_at: datetime,
    allow_unknown_provider_counts: bool = False,
) -> dict[str, Any]:
    try:
        run_id = _validate_run_id(str(row.get("run_id") or ""))
    except QueryError as exc:
        raise ProgressAPIError("stored progress run ID is invalid") from exc
    counts = {
        name: _counter(row, name)
        for name in (
            "pending",
            "retry_wait",
            "running",
            "completed",
            "failed",
            "blocked",
        )
    }
    total = _counter(row, "total")
    if sum(counts.values()) != total:
        raise ProgressAPIError(f"progress counters are inconsistent for run {run_id}")
    terminal = counts["completed"] + counts["failed"] + counts["blocked"]
    fraction = None if total == 0 else terminal / total

    episodes_total = _counter(row, "episodes_total")
    episodes_completed = _counter(row, "episodes_completed")
    records_total = _counter(row, "records_total")
    records_completed = _counter(row, "records_completed")
    if episodes_completed > episodes_total or records_completed > records_total:
        raise ProgressAPIError(f"kind counters are inconsistent for run {run_id}")

    started_at = _datetime(row.get("started_at"), field="started_at")
    updated_at = _datetime(row.get("updated_at"), field="updated_at")
    finished_at = _datetime(row.get("finished_at"), field="finished_at", optional=True)
    state = str(row.get("state") or "unknown").strip().lower()
    timing = _derived_timing(
        state=state,
        total=total,
        terminal=terminal,
        started_at=started_at,
        updated_at=updated_at,
        finished_at=finished_at,
        observed_at=observed_at,
    )
    metadata = _public_metadata(row.get("metadata_json"))
    artifact_ref = _public_artifact_ref(row.get("artifact_ref"))

    return {
        "schema_version": RUN_PROGRESS_SCHEMA_VERSION,
        "run_id": run_id,
        "backend": _optional_text(row.get("backend")),
        "cluster_profile": _optional_text(row.get("cluster_profile")),
        "model_alias": _optional_text(row.get("model_alias")),
        "study_id": _optional_text(row.get("study_id")),
        "plan_id": _optional_text(row.get("plan_id")),
        "run_label": _optional_text(row.get("run_label")),
        "state": state,
        "observed_at": _timestamp(observed_at),
        "progress": {
            "terminal": terminal,
            "total": total,
            "fraction": fraction,
            **counts,
        },
        "episodes": {
            "completed": episodes_completed,
            "total": episodes_total,
        },
        "records": {
            "completed": records_completed,
            "total": records_total,
        },
        "provider": {
            public_name: (None if allow_unknown_provider_counts and row.get(field) is None else _counter(row, field))
            for public_name, field in (
                ("turns", "provider_turns"), ("input_tokens", "input_tokens"),
                ("output_tokens", "output_tokens"), ("reasoning_tokens", "reasoning_tokens"),
                ("cached_input_tokens", "cached_input_tokens"),
            )
        },
        "timing": timing,
        "artifact_ref": artifact_ref,
        "metadata": metadata,
    }


def _counter(row: Mapping[str, Any], name: str) -> int:
    value = row.get(name)
    if isinstance(value, bool):
        raise ProgressAPIError(f"progress field {name} must be a non-negative integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ProgressAPIError(
            f"progress field {name} must be a non-negative integer"
        ) from exc
    if result < 0 or result != value:
        raise ProgressAPIError(f"progress field {name} must be a non-negative integer")
    return result


def _datetime(
    value: Any,
    *,
    field: str,
    optional: bool = False,
) -> datetime | None:
    if value is None and optional:
        return None
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            result = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ProgressAPIError(f"progress field {field} is not a timestamp") from exc
    else:
        raise ProgressAPIError(f"progress field {field} is not a timestamp")
    if result.tzinfo is None:
        raise ProgressAPIError(f"progress field {field} must include a timezone")
    return result.astimezone(timezone.utc)


def _derived_timing(
    *,
    state: str,
    total: int,
    terminal: int,
    started_at: datetime | None,
    updated_at: datetime | None,
    finished_at: datetime | None,
    observed_at: datetime,
) -> dict[str, Any]:
    if started_at is None or updated_at is None:  # pragma: no cover - required above
        raise ProgressAPIError("progress timestamps are missing")
    elapsed = max(0.0, (updated_at - started_at).total_seconds())
    age = max(0.0, (observed_at - updated_at).total_seconds())
    terminal_state = state in _TERMINAL_RUN_STATES
    freshness = (
        "terminal"
        if terminal_state
        else ("fresh" if age <= STALE_AFTER_SECONDS else "stale")
    )
    rate = (terminal / elapsed * 3600.0) if elapsed > 0 and terminal > 0 else None
    remaining = max(0, total - terminal)
    eta_seconds: float | None = None
    completion: datetime | None = None
    eta_basis: str | None = None
    if terminal_state or remaining == 0:
        eta_seconds = 0.0
        completion = finished_at or updated_at
        eta_basis = "terminal"
    elif (
        elapsed >= MIN_ETA_ELAPSED_SECONDS
        and terminal >= MIN_ETA_TERMINAL_WORK
        and rate is not None
        and rate > 0
        and freshness == "fresh"
    ):
        eta_seconds = remaining / rate * 3600.0
        completion = observed_at + timedelta(seconds=eta_seconds)
        eta_basis = "mean_terminal_work_rate_since_start"
    return {
        "started_at": _timestamp(started_at),
        "updated_at": _timestamp(updated_at),
        "finished_at": (
            _timestamp(finished_at) if finished_at is not None else None
        ),
        "elapsed_seconds": elapsed,
        "terminal_work_per_hour": rate,
        "eta_seconds": eta_seconds,
        "estimated_completion_at": (
            _timestamp(completion) if completion is not None else None
        ),
        "eta_basis": eta_basis,
        "freshness": freshness,
        "age_seconds": age,
        "stale_after_seconds": STALE_AFTER_SECONDS,
    }


def _public_metadata(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ProgressAPIError("progress metadata is invalid JSON") from exc
    if not isinstance(value, Mapping):
        raise ProgressAPIError("progress metadata must be an object")
    return {
        key: value[key]
        for key in sorted(_PUBLIC_METADATA_KEYS)
        if key in value and _is_public_metadata_value(value[key])
    }


def _is_public_metadata_value(value: Any) -> bool:
    if value is None or isinstance(value, (bool, int, float, str)):
        return not isinstance(value, float) or value == value
    if isinstance(value, list):
        return all(_is_public_metadata_value(item) for item in value)
    return False


def _public_artifact_ref(value: Any) -> str | None:
    text = _optional_text(value)
    if text is None:
        return None
    parsed = urlsplit(text)
    if parsed.username or parsed.password:
        return None
    if parsed.scheme.lower() in {"postgres", "postgresql"} or parsed.query:
        return None
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="benchrun-progress-api",
        description="Serve sanitized benchmark progress from PostgreSQL.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--database-url-env",
        default="BENCHRUN_DATABASE_URL",
        help="environment variable holding the PostgreSQL URL",
    )
    return parser


def serve_progress_api(
    *,
    host: str,
    port: int,
    database_url_env: str = "BENCHRUN_DATABASE_URL",
) -> int:
    if not 1 <= port <= 65535:
        print("progress API port must be between 1 and 65535", file=sys.stderr)
        return 2
    database_url = os.environ.get(database_url_env, "")
    if not database_url.strip():
        print(
            f"progress database URL environment variable {database_url_env!r} is not set",
            file=sys.stderr,
        )
        return 2
    try:
        repository = PostgresProgressRepository(database_url)
        server = ProgressHTTPServer((host, port), repository)
    except (OSError, ProgressAPIError) as exc:
        # Construction errors are configuration-only and never include the URL.
        print(f"could not start progress API: {exc}", file=sys.stderr)
        return 1
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return serve_progress_api(
        host=args.host,
        port=args.port,
        database_url_env=args.database_url_env,
    )


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI
    raise SystemExit(main())
