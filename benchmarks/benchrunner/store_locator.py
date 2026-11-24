"""Select a run store without persisting database credentials in artifacts."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .storage import RunStore, RunStoreError
from .work import WorkGraph, canonical_json


STORAGE_LOCATOR_SCHEMA_VERSION = "benchrunner.storage_locator/v1"
STORAGE_LOCATOR_NAME = "storage.json"
SQLITE_DATABASE_NAME = "run.sqlite3"
SUPPORTED_STORAGE_BACKENDS = frozenset({"sqlite", "postgresql"})


def open_run_store(
    run_dir: Path | str,
    graph: WorkGraph | None = None,
    *,
    journal_mode: str = "wal",
    require_existing: bool = False,
) -> RunStore:
    """Open the immutable store selected for one run directory.

    The locator records only the backend and the non-secret run identifier.
    PostgreSQL credentials always come from ``BENCHRUN_DATABASE_URL`` at
    process start and are never written into the artifact tree.
    """

    root = Path(run_dir).resolve()
    locator_path = root / STORAGE_LOCATOR_NAME
    sqlite_path = root / SQLITE_DATABASE_NAME
    locator = _read_locator(locator_path) if locator_path.is_file() else None

    configured_backend = str(
        os.environ.get("BENCHRUN_STORAGE_BACKEND") or ""
    ).strip().lower()
    if configured_backend and configured_backend not in SUPPORTED_STORAGE_BACKENDS:
        raise RunStoreError(
            "BENCHRUN_STORAGE_BACKEND must be 'sqlite' or 'postgresql'"
        )

    if locator is not None:
        backend = str(locator["backend"])
        if configured_backend and configured_backend != backend:
            raise RunStoreError(
                "configured storage backend differs from the persisted run locator"
            )
    elif sqlite_path.is_file():
        backend = "sqlite"
        if configured_backend and configured_backend != backend:
            raise RunStoreError(
                "existing SQLite run cannot be reopened with a different backend"
            )
    else:
        if require_existing:
            raise RunStoreError(f"run store does not exist under {root}")
        backend = configured_backend or "sqlite"
        root.mkdir(parents=True, exist_ok=True)
        locator = _new_locator(backend)
        if backend == "postgresql" and not str(
            os.environ.get("BENCHRUN_DATABASE_URL") or ""
        ).strip():
            raise RunStoreError(
                "BENCHRUN_DATABASE_URL is required for PostgreSQL"
            )
        _atomic_write_locator(locator_path, locator)

    if backend == "sqlite":
        return RunStore(sqlite_path, graph, journal_mode=journal_mode)

    database_url = str(os.environ.get("BENCHRUN_DATABASE_URL") or "").strip()
    if not database_url:
        raise RunStoreError(
            "BENCHRUN_DATABASE_URL is required by the persisted PostgreSQL run"
        )
    assert locator is not None
    return RunStore(
        sqlite_path,
        graph,
        journal_mode=journal_mode,
        database_url=database_url,
        run_id=str(locator["run_id"]),
    )


def run_store_exists(run_dir: Path | str) -> bool:
    root = Path(run_dir)
    return (root / STORAGE_LOCATOR_NAME).is_file() or (
        root / SQLITE_DATABASE_NAME
    ).is_file()


def _new_locator(backend: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": STORAGE_LOCATOR_SCHEMA_VERSION,
        "backend": backend,
    }
    if backend == "postgresql":
        run_id = (os.environ.get("BENCHRUN_RUN_ID") or "").strip()
        if not run_id:
            raise RunStoreError("BENCHRUN_RUN_ID is required for PostgreSQL")
        if len(run_id) > 255 or any(ord(character) < 32 for character in run_id):
            raise RunStoreError("PostgreSQL run ID is invalid")
        payload["run_id"] = run_id
    return payload


def _read_locator(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunStoreError(f"invalid run storage locator: {path}") from exc
    if not isinstance(payload, dict):
        raise RunStoreError(f"invalid run storage locator: {path}")
    if payload.get("schema_version") != STORAGE_LOCATOR_SCHEMA_VERSION:
        raise RunStoreError("unsupported run storage locator schema")
    backend = payload.get("backend")
    if backend not in SUPPORTED_STORAGE_BACKENDS:
        raise RunStoreError("run storage locator has an unsupported backend")
    if backend == "postgresql" and not str(payload.get("run_id") or "").strip():
        raise RunStoreError("PostgreSQL run storage locator is missing run_id")
    return payload


def _atomic_write_locator(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = canonical_json(payload) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
