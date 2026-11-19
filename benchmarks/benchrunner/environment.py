from __future__ import annotations

import os
from collections.abc import MutableMapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values


DEFAULT_LOCAL_ENV_PATH = Path(__file__).resolve().parents[2] / ".env.local"


@dataclass(frozen=True)
class EnvironmentLoadResult:
    """Non-secret summary of one explicit local-environment load."""

    path: Path
    file_found: bool
    loaded_keys: tuple[str, ...] = ()
    preserved_keys: tuple[str, ...] = ()
    skipped_keys: tuple[str, ...] = ()


def load_local_environment(
    path: Path | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> EnvironmentLoadResult:
    """Load a local dotenv file without overriding explicit environment values.

    The default file is exactly ``.env.local`` at the repository root. Merely
    importing this module does not read that file. The returned result contains
    variable names only, never their values.
    """

    env_path = DEFAULT_LOCAL_ENV_PATH if path is None else Path(path)
    target = os.environ if environ is None else environ

    if not env_path.exists():
        return EnvironmentLoadResult(path=env_path, file_found=False)
    if not env_path.is_file():
        raise ValueError(f"local environment path is not a file: {env_path}")

    _reject_insecure_posix_permissions(env_path)
    parsed = dotenv_values(
        dotenv_path=env_path,
        interpolate=False,
        encoding="utf-8",
    )

    loaded: list[str] = []
    preserved: list[str] = []
    skipped: list[str] = []
    for key, value in parsed.items():
        if value is None:
            skipped.append(key)
        elif key in target:
            preserved.append(key)
        else:
            target[key] = value
            loaded.append(key)

    return EnvironmentLoadResult(
        path=env_path,
        file_found=True,
        loaded_keys=tuple(loaded),
        preserved_keys=tuple(preserved),
        skipped_keys=tuple(skipped),
    )


def _reject_insecure_posix_permissions(path: Path) -> None:
    if os.name != "posix":
        return
    mode = path.stat().st_mode
    if mode & 0o077:
        raise PermissionError(
            f"local environment file grants group/world access: {path}; "
            "set its permissions to 0600"
        )
