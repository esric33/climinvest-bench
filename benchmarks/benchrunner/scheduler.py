"""Fair, bounded execution of persisted provider/model work graphs."""

from __future__ import annotations

import os
import socket
import time
import uuid
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Mapping

from .checkpoints import CheckpointSink, StoreCheckpointSink
from .retry import (
    RetryPolicy,
    WorkExecutionError,
    decide_retry,
    normalize_execution_error,
)
from .storage import RunStore, WorkClaim
from .timing import TimingRecorder
from .work import WorkGraph, WorkSpec, canonical_json


MAX_CONCURRENCY = 256


@dataclass(frozen=True, slots=True)
class ConcurrencyLimits:
    """Hierarchical work-level concurrency limits with a hard safety ceiling."""

    max_workers: int = 10
    provider_limits: Mapping[str, int] = field(default_factory=dict)
    model_limits: Mapping[tuple[str, str], int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_limit(self.max_workers, "max_workers")
        providers: dict[str, int] = {}
        for provider, limit in self.provider_limits.items():
            key = str(provider or "").strip()
            if not key:
                raise ValueError("provider limit keys must be non-empty")
            _validate_limit(limit, f"provider limit {key}")
            providers[key] = int(limit)
        models: dict[tuple[str, str], int] = {}
        for raw_key, limit in self.model_limits.items():
            if not isinstance(raw_key, tuple) or len(raw_key) != 2:
                raise ValueError("model limit keys must be (provider, model) tuples")
            key = (str(raw_key[0] or "").strip(), str(raw_key[1] or "").strip())
            if not all(key):
                raise ValueError("model limit keys must be non-empty")
            _validate_limit(limit, f"model limit {key[0]}/{key[1]}")
            models[key] = int(limit)
        object.__setattr__(self, "provider_limits", MappingProxyType(providers))
        object.__setattr__(self, "model_limits", MappingProxyType(models))

    def provider_limit(self, provider: str) -> int:
        return min(self.max_workers, self.provider_limits.get(provider, self.max_workers))

    def model_limit(self, provider: str, model: str) -> int:
        return min(
            self.provider_limit(provider),
            self.model_limits.get((provider, model), self.provider_limit(provider)),
        )


@dataclass(slots=True)
class ExecutionContext:
    work: WorkSpec
    attempt: int
    retry_cycle: int
    cycle_attempt: int
    timing: TimingRecorder
    checkpoints: CheckpointSink
    heartbeat: Callable[[], None]

    def checkpoint(self, name: str, payload: Any, *, replace: bool = False) -> None:
        self.checkpoints.save(name, payload, replace=replace)


@dataclass(frozen=True, slots=True)
class RunSummary:
    status: str
    graph_id: str
    owner: str
    recovered_leases: int
    elapsed_seconds: float
    counts: Mapping[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "graph_id": self.graph_id,
            "owner": self.owner,
            "recovered_leases": self.recovered_leases,
            "elapsed_seconds": self.elapsed_seconds,
            "counts": dict(self.counts),
        }


@dataclass(frozen=True, slots=True)
class _AttemptOutcome:
    result: Any | None
    error: WorkExecutionError | None
    timing: Mapping[str, Any]


WorkExecutor = Callable[[WorkSpec, ExecutionContext], Any]
EventHandler = Callable[[Mapping[str, Any]], None]


class Scheduler:
    """Execute a graph with durable leases and provider/model round-robin fairness."""

    def __init__(
        self,
        store: RunStore,
        graph: WorkGraph,
        executor: WorkExecutor,
        *,
        limits: ConcurrencyLimits | None = None,
        retry_policy: RetryPolicy | None = None,
        owner: str | None = None,
        lease_seconds: float = 300.0,
        heartbeat_interval_seconds: float | None = None,
        poll_interval_seconds: float = 0.5,
        on_event: EventHandler | None = None,
        wall_clock: Callable[[], float] = time.time,
        monotonic_clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        execution_work_ids: tuple[str, ...] | None = None,
    ) -> None:
        if not callable(executor):
            raise TypeError("executor must be callable")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be greater than zero")
        heartbeat = (
            min(30.0, lease_seconds / 3)
            if heartbeat_interval_seconds is None
            else float(heartbeat_interval_seconds)
        )
        if heartbeat <= 0 or heartbeat >= lease_seconds:
            raise ValueError(
                "heartbeat interval must be greater than zero and shorter than the lease"
            )
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be greater than zero")
        selected_ids = None if execution_work_ids is None else set(execution_work_ids)
        if selected_ids is not None:
            known = {item.work_id for item in graph}
            if not selected_ids or selected_ids - known:
                raise ValueError("execution selection must be a nonempty subset of the graph")
            if any(set(item.dependencies) - selected_ids for item in graph
                   if item.work_id in selected_ids):
                raise ValueError("execution selection must include every dependency")
        scheduled_graph = graph if selected_ids is None else WorkGraph(
            item for item in graph if item.work_id in selected_ids)
        self.execution_work_ids = None if selected_ids is None else tuple(sorted(selected_ids))
        self.store = store
        self.graph = graph
        self.executor = executor
        self.limits = limits or ConcurrencyLimits()
        self.retry_policy = retry_policy or RetryPolicy()
        self.owner = str(owner or _default_owner())
        self.lease_seconds = float(lease_seconds)
        self.heartbeat_interval_seconds = heartbeat
        self.poll_interval_seconds = float(poll_interval_seconds)
        self.on_event = on_event
        self.wall_clock = wall_clock
        self.monotonic_clock = monotonic_clock
        self.sleeper = sleeper
        self._fair_last_key: dict[int, tuple[str, str]] = {}
        dispatch_key_count = len({item.dispatch_key for item in graph})
        self._candidate_limit = max(
            64,
            self.limits.max_workers * 8,
            dispatch_key_count * 8,
        )
        self._episode_groups = _record_groups(scheduled_graph)
        self._finished_groups: set[str] = set()
        self._other_work: dict[tuple[str, str], list[str]] = defaultdict(list)
        for item in scheduled_graph:
            if item.kind != "react_episode" or not item.identity.get("record_key"):
                self._other_work[item.dispatch_key].append(item.work_id)
        self.store.initialize(graph)

    def run(self) -> RunSummary:
        started = float(self.monotonic_clock())
        recovered_ids = list(
            self.store.recover_expired_leases(now=self.wall_clock(), work_ids=self.execution_work_ids)
        )
        for work_id in recovered_ids:
            self._emit("lease_recovered", work_id=work_id)

        pool = ThreadPoolExecutor(
            max_workers=self.limits.max_workers,
            thread_name_prefix="benchrunner",
        )
        active: dict[Future[_AttemptOutcome], WorkClaim] = {}
        next_heartbeat = self.wall_clock() + self.heartbeat_interval_seconds
        try:
            while True:
                self.store.block_failed_dependents(now=self.wall_clock(), work_ids=self.execution_work_ids)
                self._dispatch(pool, active)

                if not active:
                    newly_recovered = self.store.recover_expired_leases(
                        now=self.wall_clock(), work_ids=self.execution_work_ids
                    )
                    for work_id in newly_recovered:
                        if work_id not in recovered_ids:
                            recovered_ids.append(work_id)
                        self._emit("lease_recovered", work_id=work_id)
                    if self.store.is_terminal(work_ids=self.execution_work_ids):
                        break
                    ready = self.store.list_ready(now=self.wall_clock(), work_ids=self.execution_work_ids)
                    if ready:
                        # A ready task may be temporarily excluded only by a
                        # configuration bug; dispatch again without sleeping.
                        continue
                    next_available = self.store.next_wakeup_at(work_ids=self.execution_work_ids)
                    if next_available is None:
                        self.store.block_failed_dependents(now=self.wall_clock(), work_ids=self.execution_work_ids)
                        if self.store.is_terminal(work_ids=self.execution_work_ids):
                            break
                        raise RuntimeError("scheduler made no progress with nonterminal work")
                    delay = max(0.0, next_available - self.wall_clock())
                    self.sleeper(min(delay, self.poll_interval_seconds))
                    continue

                now = self.wall_clock()
                heartbeat_wait = max(0.0, next_heartbeat - now)
                timeout = min(self.poll_interval_seconds, heartbeat_wait)
                finished, _ = wait(
                    tuple(active),
                    timeout=timeout,
                    return_when=FIRST_COMPLETED,
                )
                for future in finished:
                    claim = active.pop(future)
                    self._finish(claim, future.result())

                if self.wall_clock() >= next_heartbeat:
                    self._renew_active(active)
                    next_heartbeat = self.wall_clock() + self.heartbeat_interval_seconds
        except BaseException:
            for future in active:
                future.cancel()
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            pool.shutdown(wait=True)

        counts = self.store.summary(work_ids=self.execution_work_ids)
        status = (
            "completed"
            if counts["failed"] == 0 and counts["blocked"] == 0
            else "completed_with_failures"
        )
        summary = RunSummary(
            status=status,
            graph_id=self.graph.graph_id,
            owner=self.owner,
            recovered_leases=len(recovered_ids),
            elapsed_seconds=max(0.0, float(self.monotonic_clock()) - started),
            counts=MappingProxyType(counts),
        )
        self._emit("run_finished", **summary.to_dict())
        return summary

    def _dispatch(
        self,
        pool: ThreadPoolExecutor,
        active: dict[Future[_AttemptOutcome], WorkClaim],
    ) -> None:
        ready = self._ready_candidates()
        while len(active) < self.limits.max_workers:
            selected = self._select_fair(tuple(ready), active)
            if selected is None:
                return
            ready.remove(selected)
            claim = self.store.claim(
                selected.work_id,
                owner=self.owner,
                lease_seconds=self.lease_seconds,
                now=self.wall_clock(),
            )
            if claim is None:
                continue
            self._emit(
                "work_started",
                work_id=claim.work.work_id,
                provider=claim.work.provider,
                model=claim.work.model,
                attempt=claim.attempt,
                retry_cycle=claim.retry_cycle,
                cycle_attempt=claim.cycle_attempt,
            )
            future = pool.submit(self._execute, claim)
            active[future] = claim

    def _ready_candidates(self) -> list[WorkSpec]:
        """Find completable record groups without a global hash-prefix window.

        Every dispatch key gets a window. A section group's remaining ready
        episodes precede the next group; an in-flight or delayed group may yield
        unused capacity. Scoped reads contain only small groups and never load
        stored episode bodies. Completed prefixes are skipped on later passes.
        """

        ready: list[WorkSpec] = []
        now = self.wall_clock()
        for key in sorted(self._episode_groups):
            selected_count = 0
            for group in self._episode_groups[key]:
                group_id = group[0].work_id
                if group_id in self._finished_groups:
                    continue
                work_ids = tuple(item.work_id for item in group)
                candidates = self.store.list_ready(now=now, work_ids=work_ids)
                if candidates:
                    ready.extend(candidates)
                    selected_count += len(candidates)
                    if selected_count >= self.limits.max_workers:
                        break
                else:
                    statuses = self.store.work_statuses(work_ids)
                    if len(statuses) == len(work_ids) and all(
                        status in {"completed", "failed", "blocked"}
                        for status in statuses.values()
                    ):
                        self._finished_groups.add(group_id)
        for work_ids in self._other_work.values():
            for start in range(0, len(work_ids), self._candidate_limit):
                ready.extend(self.store.list_ready(
                    now=now,
                    work_ids=tuple(work_ids[start:start + self._candidate_limit]),
                    limit=self.limits.max_workers,
                ))
        return ready

    def _select_fair(
        self,
        ready: tuple[WorkSpec, ...],
        active: Mapping[Future[_AttemptOutcome], WorkClaim],
    ) -> WorkSpec | None:
        if not ready:
            return None
        provider_active: dict[str, int] = {}
        model_active: dict[tuple[str, str], int] = {}
        for claim in active.values():
            provider = claim.work.provider
            key = claim.work.capacity_key
            provider_active[provider] = provider_active.get(provider, 0) + 1
            model_active[key] = model_active.get(key, 0) + 1

        groups: dict[tuple[str, str], list[WorkSpec]] = {}
        for item in ready:
            if provider_active.get(item.provider, 0) >= self.limits.provider_limit(
                item.provider
            ) or model_active.get(item.capacity_key, 0) >= self.limits.model_limit(
                *item.capacity_key
            ):
                continue
            groups.setdefault(item.dispatch_key, []).append(item)
        if not groups:
            return None
        highest_priority = max(item.priority for items in groups.values() for item in items)
        groups = {
            key: [item for item in items if item.priority == highest_priority]
            for key, items in groups.items()
            if any(item.priority == highest_priority for item in items)
        }
        keys = sorted(groups)
        previous = self._fair_last_key.get(highest_priority)
        start = next(
            (index for index, key in enumerate(keys) if previous is None or key > previous),
            0,
        )
        for offset in range(len(keys)):
            index = (start + offset) % len(keys)
            dispatch_key = keys[index]
            provider, _alias = dispatch_key
            if provider_active.get(provider, 0) >= self.limits.provider_limit(provider):
                continue

            # _ready_candidates already orders each model's record groups.
            candidates = groups[dispatch_key]
            selected = next(
                (
                    item
                    for item in candidates
                    if model_active.get(item.capacity_key, 0)
                    < self.limits.model_limit(*item.capacity_key)
                ),
                None,
            )
            if selected is None:
                continue
            self._fair_last_key[highest_priority] = dispatch_key
            return selected
        return None

    def _execute(self, claim: WorkClaim) -> _AttemptOutcome:
        timing = TimingRecorder(clock=self.monotonic_clock)
        timing.add("queue_seconds", claim.queue_seconds)
        if claim.retry_delay_seconds:
            timing.add("prior_retry_delay_seconds", claim.retry_delay_seconds)
        checkpoints = StoreCheckpointSink(
            self.store,
            claim.work.work_id,
            claim.owner,
        )

        def heartbeat() -> None:
            self.store.renew_lease(
                claim.work.work_id,
                owner=claim.owner,
                lease_seconds=self.lease_seconds,
                now=self.wall_clock(),
            )

        context = ExecutionContext(
            work=claim.work,
            attempt=claim.attempt,
            retry_cycle=claim.retry_cycle,
            cycle_attempt=claim.cycle_attempt,
            timing=timing,
            checkpoints=checkpoints,
            heartbeat=heartbeat,
        )
        try:
            with timing.span("executor_seconds"):
                result = self.executor(claim.work, context)
            canonical_json(result)
        except BaseException as exc:
            if not isinstance(exc, Exception):
                raise
            error = normalize_execution_error(exc)
            return _AttemptOutcome(None, error, timing.snapshot())
        return _AttemptOutcome(result, None, timing.snapshot())

    def _finish(self, claim: WorkClaim, outcome: _AttemptOutcome) -> None:
        if outcome.error is None:
            self.store.complete(
                claim.work.work_id,
                owner=claim.owner,
                result=outcome.result,
                timing=outcome.timing,
                now=self.wall_clock(),
            )
            self._emit(
                "work_completed",
                work_id=claim.work.work_id,
                attempt=claim.attempt,
                retry_cycle=claim.retry_cycle,
                cycle_attempt=claim.cycle_attempt,
            )
            return

        decision = decide_retry(
            outcome.error,
            self.retry_policy,
            attempt=claim.cycle_attempt,
            prior_delay_seconds=claim.retry_delay_seconds,
        )
        retry_at = (
            self.wall_clock() + decision.delay_seconds if decision.retry else None
        )
        status = self.store.fail_attempt(
            claim.work.work_id,
            owner=claim.owner,
            error={**outcome.error.to_dict(), "retry_decision": decision.reason},
            retry_at=retry_at,
            retry_delay_seconds=(decision.delay_seconds if decision.retry else 0.0),
            timing=outcome.timing,
            now=self.wall_clock(),
        )
        self._emit(
            "work_retry_scheduled" if decision.retry else "work_failed",
            work_id=claim.work.work_id,
            attempt=claim.attempt,
            retry_cycle=claim.retry_cycle,
            cycle_attempt=claim.cycle_attempt,
            status=status,
            error_code=outcome.error.code,
            delay_seconds=decision.delay_seconds,
        )

    def _renew_active(
        self,
        active: Mapping[Future[_AttemptOutcome], WorkClaim],
    ) -> None:
        for future, claim in active.items():
            if future.done():
                continue
            self.store.renew_lease(
                claim.work.work_id,
                owner=claim.owner,
                lease_seconds=self.lease_seconds,
                now=self.wall_clock(),
            )

    def _emit(self, event: str, **values: Any) -> None:
        if self.on_event is None:
            return
        self.on_event(
            {
                "event": event,
                "timestamp": self.wall_clock(),
                **values,
            }
        )


def _record_groups(
    graph: WorkGraph,
) -> dict[tuple[str, str], list[tuple[WorkSpec, ...]]]:
    """Round robin task/scope/category strata, then project and replicate.

    This is an operational ordering only: no dependencies, identity fields, or
    model inputs change. Keeping each record together yields interpretable
    partial runs; cycling strata avoids exhausting one scientific cell first.
    """

    grouped: dict[tuple[str, str], dict[str, list[WorkSpec]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for item in graph:
        record_key = item.identity.get("record_key")
        if item.kind == "react_episode" and record_key:
            grouped[item.dispatch_key][str(record_key)].append(item)
    ordered = {}
    for dispatch_key, records in grouped.items():
        strata: dict[tuple[str, str, str], list[tuple[WorkSpec, ...]]] = defaultdict(list)
        for episodes in records.values():
            group = tuple(sorted(episodes, key=lambda item: item.work_id))
            identity = group[0].identity
            strata[tuple(str(identity.get(key) or "") for key in (
                "task", "scope", "category"
            ))].append(group)
        for groups in strata.values():
            groups.sort(key=lambda group: (
                str(group[0].identity.get("project_id") or ""),
                int(group[0].identity.get("replicate") or 0),
                str(group[0].identity["record_key"]),
            ))
        ordered[dispatch_key] = [
            strata[key][index]
            for index in range(max(map(len, strata.values())))
            for key in sorted(strata)
            if index < len(strata[key])
        ]
    return ordered


def _validate_limit(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if not 1 <= value <= MAX_CONCURRENCY:
        raise ValueError(
            f"{field_name} must be between 1 and {MAX_CONCURRENCY}"
        )


def _default_owner() -> str:
    host = socket.gethostname().split(".")[0] or "host"
    return f"{host}:{os.getpid()}:{uuid.uuid4().hex[:12]}"
