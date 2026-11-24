"""Small redraw-in-place terminal dashboard for long benchmark runs."""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any, Mapping, TextIO

from .storage import RunStore


class LiveRunProgress:
    """Render a bounded seven-line dashboard on interactive terminals."""

    line_count = 7

    def __init__(
        self,
        store: RunStore,
        *,
        stream: TextIO | None = None,
        refresh_seconds: float = 1.0,
        width: int | None = None,
        baseline: Mapping[str, Any] | None = None,
        clock=time.monotonic,
    ) -> None:
        if refresh_seconds <= 0:
            raise ValueError("progress refresh interval must be positive")
        self.store = store
        self.stream = stream or sys.stderr
        self.refresh_seconds = float(refresh_seconds)
        self.width = width
        self.baseline = dict(baseline or {})
        self.clock = clock
        self.started_at = float(clock())
        self._enabled = _is_tty(self.stream)
        self._stop = threading.Event()
        self._render_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._rendered = False
        self._last_render_at: float | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def start(self) -> None:
        if not self._enabled or self._thread is not None:
            return
        self.render()
        self._thread = threading.Thread(
            target=self._refresh_loop,
            name="benchrun-progress",
            daemon=True,
        )
        self._thread.start()

    def stop(self, *, clear: bool = True) -> None:
        if not self._enabled:
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.refresh_seconds * 2))
        if clear:
            self.clear()

    def on_event(self, _event: Mapping[str, Any]) -> None:
        if self._enabled and self._render_due():
            self.render()

    def render(self) -> None:
        if not self._enabled:
            return
        with self._render_lock:
            try:
                lines = self._lines()
            except Exception as exc:  # exporter will report the full error later
                lines = [
                    "benchrun status unavailable",
                    f"dashboard error: {type(exc).__name__}",
                    "The scheduler is still running.",
                    "",
                    "",
                    "",
                    "",
                ]
            if self._rendered:
                self.stream.write(f"\x1b[{self.line_count}F")
            for line in lines:
                self.stream.write("\x1b[2K" + line + "\n")
            self.stream.flush()
            self._rendered = True
            self._last_render_at = float(self.clock())

    def clear(self) -> None:
        with self._render_lock:
            if not self._rendered:
                return
            # The dashboard is always the latest terminal output. Move to its
            # first row and erase it plus everything below before final JSON is
            # printed by the CLI.
            self.stream.write(f"\x1b[{self.line_count}F\x1b[J")
            self.stream.flush()
            self._rendered = False

    def _refresh_loop(self) -> None:
        while not self._stop.wait(self.refresh_seconds):
            if self._render_due():
                self.render()

    def _render_due(self) -> bool:
        return (
            self._last_render_at is None
            or float(self.clock()) - self._last_render_at >= self.refresh_seconds
        )

    def _lines(self) -> list[str]:
        snapshot = self.store.progress_snapshot()
        counts = snapshot["scheduler"]
        accounting = snapshot["observed_provider_accounting"]
        diagnostics = snapshot["retry_diagnostics"]
        baseline_counts = self.baseline.get("scheduler") or {}
        baseline_accounting = (
            self.baseline.get("observed_provider_accounting") or {}
        )
        total = int(counts["total"])
        terminal = int(counts["completed"] + counts["failed"] + counts["blocked"])
        ratio = (terminal / total) if total else 1.0
        status = "DONE" if terminal == total else "RUNNING"
        elapsed = max(0.0, float(self.clock()) - self.started_at)
        completed_delta = max(
            0,
            int(counts["completed"])
            - int(baseline_counts.get("completed") or 0),
        )
        token_delta = max(
            0,
            int(accounting["total_tokens"])
            - int(baseline_accounting.get("total_tokens") or 0),
        )
        completed_rate = (completed_delta / elapsed * 60.0) if elapsed else 0.0
        token_rate = (token_delta / elapsed) if elapsed else 0.0
        width = max(20, int(self.width or _terminal_columns(self.stream)))
        bar_width = max(8, min(24, width - 39))
        filled = min(bar_width, int(round(bar_width * ratio)))
        bar = "#" * filled + "-" * (bar_width - filled)
        lines = [
            f"benchrun [{bar}] {terminal}/{total} {ratio * 100:5.1f}% {status}",
            (
                f"work  completed {counts['completed']} | running {counts['running']} | "
                f"pending {counts['pending']} | retry {counts['retry_wait']}"
            ),
            (
                f"issues  failed {counts['failed']} | blocked {counts['blocked']} | "
                f"disconnects {diagnostics['provider_no_response_failures']} | "
                f"resume cycles {diagnostics['retry_cycles']}"
            ),
            (
                f"episodes  {snapshot['episodes']['materialized']}/"
                f"{snapshot['episodes']['total']} | records  "
                f"{snapshot['records']['evaluated']}/{snapshot['records']['total']}"
            ),
            (
                f"tokens  {_quantity(accounting['total_tokens'])} total | "
                f"{_quantity(accounting['input_tokens'])} in | "
                f"{_quantity(accounting['output_tokens'])} out | "
                f"{_quantity(accounting['cached_input_tokens'])} cached"
            ),
            (
                f"this run  {completed_rate:.2f} work/min | "
                f"{_quantity(token_rate)}/s | "
                f"{accounting['response_turns']} responses | "
                f"{accounting.get('normalization_count', 0)} normalized"
            ),
            (
                f"elapsed  {_duration(elapsed)} | provider response time  "
                f"{_duration(accounting['successful_response_latency_seconds'])}"
            ),
        ]
        return [_fit(line, width) for line in lines]


def _is_tty(stream: TextIO) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, OSError):
        return False


def _terminal_columns(stream: TextIO, *, fallback: int = 80) -> int:
    """Measure the terminal actually receiving the dashboard."""

    try:
        return int(os.get_terminal_size(stream.fileno()).columns)
    except (AttributeError, OSError, ValueError):
        return int(fallback)


def _fit(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    return value[: max(1, width - 1)] + "…"


def _quantity(value: float | int) -> str:
    number = float(value)
    for suffix, divisor in (("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if abs(number) >= divisor:
            return f"{number / divisor:.2f}{suffix}"
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}"


def _duration(seconds: float | int) -> str:
    total = max(0, int(round(float(seconds))))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"
