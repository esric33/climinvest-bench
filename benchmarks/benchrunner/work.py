"""Stable work identities and dependency graphs for reusable benchmark runs."""

from __future__ import annotations

import hashlib
import heapq
import json
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Iterable, Mapping


WORK_SCHEMA_VERSION = "benchrunner.work/v1"
GRAPH_SCHEMA_VERSION = "benchrunner.work_graph/v1"
_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


class WorkGraphError(ValueError):
    """Raised when work identities or graph dependencies are invalid."""


def canonical_json(value: Any) -> str:
    """Return strict, deterministic JSON suitable for identities and storage."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise WorkGraphError(f"work metadata must be strict JSON: {exc}") from exc


def _normalized_json_object(
    value: Mapping[str, Any],
    *,
    field_name: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise WorkGraphError(f"{field_name} must be a mapping")
    rendered = canonical_json(value)
    decoded = json.loads(rendered)
    if not isinstance(decoded, dict):  # pragma: no cover - guarded by Mapping
        raise WorkGraphError(f"{field_name} must encode to an object")
    return MappingProxyType(decoded)


def _required_text(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise WorkGraphError(f"{field_name} must be non-empty")
    return text


def _slug(value: str) -> str:
    normalized = _SLUG_PATTERN.sub("-", value.lower()).strip("-")
    return (normalized or "work")[:32]


@dataclass(frozen=True, slots=True)
class WorkSpec:
    """One independently leaseable unit of work.

    ``identity`` contains semantic inputs that affect the produced result.
    Operational metadata such as ``priority`` deliberately does not change the
    work ID, although it remains part of the graph fingerprint.
    """

    kind: str
    provider: str
    model: str
    identity: Mapping[str, Any]
    dependencies: tuple[str, ...] = ()
    priority: int = 0
    labels: Mapping[str, Any] = field(default_factory=dict)
    work_id: str = field(init=False)

    def __post_init__(self) -> None:
        kind = _required_text(self.kind, "kind")
        provider = _required_text(self.provider, "provider")
        model = _required_text(self.model, "model")
        identity = _normalized_json_object(self.identity, field_name="identity")
        labels = _normalized_json_object(self.labels, field_name="labels")
        dependencies = tuple(
            sorted(
                {
                    _required_text(item, "dependency ID")
                    for item in self.dependencies
                }
            )
        )
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise WorkGraphError("priority must be an integer")

        identity_payload = {
            "schema_version": WORK_SCHEMA_VERSION,
            "kind": kind,
            "provider": provider,
            "model": model,
            "identity": dict(identity),
            "dependencies": list(dependencies),
        }
        digest = hashlib.sha256(
            canonical_json(identity_payload).encode("utf-8")
        ).hexdigest()

        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "identity", identity)
        object.__setattr__(self, "labels", labels)
        object.__setattr__(self, "dependencies", dependencies)
        object.__setattr__(self, "work_id", f"{_slug(kind)}-{digest[:24]}")

    @property
    def dispatch_key(self) -> tuple[str, str]:
        """Return the alias-level key used to schedule work fairly."""

        return self.provider, self.model

    @property
    def capacity_key(self) -> tuple[str, str]:
        """Return the backend resource whose concurrent capacity this work uses.

        Study-plan work stores the immutable backend model ID in ``identity``
        while ``model`` remains the treatment alias used for fair dispatch.
        Generic work that has no such identity continues to use ``model``.
        """

        model_id = str(self.identity.get("model_id") or "").strip()
        return self.provider, model_id or self.model

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": WORK_SCHEMA_VERSION,
            "work_id": self.work_id,
            "kind": self.kind,
            "provider": self.provider,
            "model": self.model,
            "identity": dict(self.identity),
            "dependencies": list(self.dependencies),
            "priority": self.priority,
            "labels": dict(self.labels),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkSpec":
        if value.get("schema_version") != WORK_SCHEMA_VERSION:
            raise WorkGraphError("unexpected work schema version")
        result = cls(
            kind=str(value.get("kind") or ""),
            provider=str(value.get("provider") or ""),
            model=str(value.get("model") or ""),
            identity=value.get("identity") or {},
            dependencies=tuple(value.get("dependencies") or ()),
            priority=value.get("priority", 0),
            labels=value.get("labels") or {},
        )
        supplied_id = value.get("work_id")
        if supplied_id is not None and supplied_id != result.work_id:
            raise WorkGraphError("work ID does not match its canonical identity")
        return result


@dataclass(frozen=True, slots=True)
class WorkGraph:
    """Validated, deterministic DAG of :class:`WorkSpec` objects."""

    work: tuple[WorkSpec, ...]
    graph_id: str = field(init=False)
    _by_id: Mapping[str, WorkSpec] = field(init=False, repr=False)

    def __init__(self, work: Iterable[WorkSpec]) -> None:
        items = tuple(work)
        by_id: dict[str, WorkSpec] = {}
        for item in items:
            if not isinstance(item, WorkSpec):
                raise WorkGraphError("work graph entries must be WorkSpec values")
            if item.work_id in by_id:
                raise WorkGraphError(f"duplicate work ID {item.work_id!r}")
            by_id[item.work_id] = item

        known_ids = set(by_id)
        for item in items:
            if item.work_id in item.dependencies:
                raise WorkGraphError(f"{item.work_id}: work cannot depend on itself")
            unknown = sorted(set(item.dependencies) - known_ids)
            if unknown:
                raise WorkGraphError(
                    f"{item.work_id}: unknown dependencies: {', '.join(unknown)}"
                )
        _topological_ids(by_id)

        ordered = tuple(sorted(items, key=lambda item: item.work_id))
        graph_payload = {
            "schema_version": GRAPH_SCHEMA_VERSION,
            "work": [item.to_dict() for item in ordered],
        }
        digest = hashlib.sha256(
            canonical_json(graph_payload).encode("utf-8")
        ).hexdigest()
        object.__setattr__(self, "work", ordered)
        object.__setattr__(self, "graph_id", f"graph-{digest}")
        object.__setattr__(self, "_by_id", MappingProxyType(by_id))

    def __len__(self) -> int:
        return len(self.work)

    def __iter__(self):
        return iter(self.work)

    def get(self, work_id: str) -> WorkSpec:
        try:
            return self._by_id[work_id]
        except KeyError as exc:
            raise WorkGraphError(f"unknown work ID {work_id!r}") from exc

    def topological(self) -> tuple[WorkSpec, ...]:
        return tuple(self._by_id[item] for item in _topological_ids(self._by_id))

    def ready(self, completed: Iterable[str]) -> tuple[WorkSpec, ...]:
        complete = set(completed)
        return tuple(
            sorted(
                (
                    item
                    for item in self.work
                    if item.work_id not in complete
                    and set(item.dependencies) <= complete
                ),
                key=lambda item: (-item.priority, item.work_id),
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": GRAPH_SCHEMA_VERSION,
            "graph_id": self.graph_id,
            "work": [item.to_dict() for item in self.work],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkGraph":
        if value.get("schema_version") != GRAPH_SCHEMA_VERSION:
            raise WorkGraphError("unexpected work-graph schema version")
        result = cls(WorkSpec.from_dict(item) for item in value.get("work") or [])
        supplied_id = value.get("graph_id")
        if supplied_id is not None and supplied_id != result.graph_id:
            raise WorkGraphError("graph ID does not match its canonical contents")
        return result


def _topological_ids(work: Mapping[str, WorkSpec]) -> tuple[str, ...]:
    indegree = {work_id: len(item.dependencies) for work_id, item in work.items()}
    children: dict[str, list[str]] = {work_id: [] for work_id in work}
    for work_id, item in work.items():
        for dependency in item.dependencies:
            children[dependency].append(work_id)

    ready = [work_id for work_id, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    ordered: list[str] = []
    while ready:
        work_id = heapq.heappop(ready)
        ordered.append(work_id)
        for child in sorted(children[work_id]):
            indegree[child] -= 1
            if indegree[child] == 0:
                heapq.heappush(ready, child)
    if len(ordered) != len(work):
        cyclic = sorted(work_id for work_id, degree in indegree.items() if degree)
        raise WorkGraphError("work graph contains a cycle involving: " + ", ".join(cyclic))
    return tuple(ordered)
