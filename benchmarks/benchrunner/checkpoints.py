"""Small checkpoint interfaces shared by schedulers and work executors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .storage import RunStore


class CheckpointSink(Protocol):
    def save(self, name: str, payload: Any, *, replace: bool = False) -> None:
        ...

    def load(self, name: str) -> Any | None:
        ...

    def names(self) -> tuple[str, ...]:
        ...


@dataclass(slots=True)
class StoreCheckpointSink:
    store: RunStore
    work_id: str
    owner: str

    def save(self, name: str, payload: Any, *, replace: bool = False) -> None:
        self.store.save_checkpoint(
            self.work_id,
            name,
            payload,
            owner=self.owner,
            replace=replace,
        )

    def load(self, name: str) -> Any | None:
        return self.store.load_checkpoint(self.work_id, name)

    def names(self) -> tuple[str, ...]:
        return self.store.checkpoint_names(self.work_id)


@dataclass(slots=True)
class MemoryCheckpointSink:
    """In-memory implementation useful for adapters and focused tests."""

    values: dict[str, Any] = field(default_factory=dict)

    def save(self, name: str, payload: Any, *, replace: bool = False) -> None:
        checkpoint_name = str(name or "").strip()
        if not checkpoint_name:
            raise ValueError("checkpoint name must be non-empty")
        if checkpoint_name in self.values and self.values[checkpoint_name] != payload:
            if not replace:
                raise ValueError(f"checkpoint {checkpoint_name!r} is immutable")
        self.values[checkpoint_name] = payload

    def load(self, name: str) -> Any | None:
        return self.values.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self.values))
