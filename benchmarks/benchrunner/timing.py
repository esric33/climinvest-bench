"""Monotonic timing primitives that separate named scheduler activities."""

from __future__ import annotations

import math
import threading
import time
from contextlib import contextmanager
from typing import Callable, Iterator


class TimingRecorder:
    """Accumulate non-overwriting named durations for one work attempt."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._started_at = float(clock())
        self._totals: dict[str, float] = {}
        self._counts: dict[str, int] = {}
        self._lock = threading.RLock()

    def add(self, name: str, seconds: float, *, count: int = 0) -> None:
        label = str(name or "").strip()
        duration = float(seconds)
        if not label:
            raise ValueError("timing name must be non-empty")
        if not math.isfinite(duration) or duration < 0:
            raise ValueError("timing duration must be finite and non-negative")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("timing count must be a non-negative integer")
        with self._lock:
            self._totals[label] = self._totals.get(label, 0.0) + duration
            if count:
                self._counts[label] = self._counts.get(label, 0) + int(count)

    @contextmanager
    def span(self, name: str) -> Iterator[None]:
        started = float(self._clock())
        try:
            yield
        finally:
            elapsed = max(0.0, float(self._clock()) - started)
            self.add(name, elapsed, count=1)

    def snapshot(self) -> dict[str, object]:
        elapsed = max(0.0, float(self._clock()) - self._started_at)
        with self._lock:
            return {
                "elapsed_seconds": elapsed,
                "durations_seconds": dict(sorted(self._totals.items())),
                "span_counts": dict(sorted(self._counts.items())),
            }
