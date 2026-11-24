"""Durable, per-run/model limits for paid input-count probes.

The artifact directory must provide coherent POSIX advisory locks, atomic rename,
and fsync (including directory fsync). CephFS and local POSIX filesystems provide
these primitives; object stores and independently copied run directories do not.
Every HTTP attempt needs a new reservation. Reservations never expire, and an
unconfirmed attempt retains its full liability after crashes or restarts.
"""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal, InvalidOperation, ROUND_CEILING, localcontext
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterator, Mapping
import uuid

from benchmarks.react_report_building.runtime.provider_cost import canonical_decimal_string


PROBE_BUDGET_SCHEMA = "benchrunner.context_probe_budget/v1"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_RESERVATION_ID = re.compile(r"[0-9a-f]{32}\Z")
_MAX_REQUESTS = 100_000
_MAX_STATE_BYTES = 128 * 1024 * 1024


class ProbeBudgetError(RuntimeError):
    """Nonretryable failure; callers must not send the probe HTTP request."""

    retryable = False

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _money(value: Any) -> Decimal:
    try:
        if isinstance(value, bool) or not isinstance(value, (Decimal, str, int, float)):
            raise ValueError
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > Decimal("1e12"):
            raise ValueError
        if amount.as_tuple().exponent < -18:
            raise ValueError
        return amount
    except (InvalidOperation, ValueError, TypeError):
        raise ProbeBudgetError("invalid_probe_budget", "Probe costs must be finite nonnegative decimal amounts.") from None


def _amount(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _total_cost(reservations: Mapping[str, Any]) -> Decimal:
    with localcontext() as context:
        # Provider-reported overruns may exceed the ordinary reservation domain.
        # Preserve their full bounded provider-cost precision for the audit.
        context.prec = 1024
        return sum((_recorded_money(item["charged_cost_usd"]) for item in reservations.values()), Decimal(0))


def _recorded_money(value: Any) -> Decimal:
    try:
        return Decimal(canonical_decimal_string(value))
    except ValueError:
        raise ProbeBudgetError("invalid_probe_budget", "Reported probe cost is not a supported finite decimal.") from None


def _digest(value: Any) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ProbeBudgetError("invalid_probe_budget", "A lowercase SHA-256 digest is required.")
    return value


def worst_case_probe_cost(
    context_window_tokens: int,
    input_price_per_million: Any,
    output_price_per_million: Any,
    *, max_observed_output_tokens: int = 1,
) -> Decimal:
    """Reserve the advertised input window plus all accepted probe output tokens."""
    if isinstance(context_window_tokens, bool) or not isinstance(context_window_tokens, int) or not 1 <= context_window_tokens <= 10**12:
        raise ProbeBudgetError("invalid_probe_budget", "Probe context window must be a positive integer.")
    if isinstance(max_observed_output_tokens, bool) or not isinstance(max_observed_output_tokens, int) or not 1 <= max_observed_output_tokens <= 32:
        raise ProbeBudgetError("invalid_probe_budget", "Accepted probe output must be between one and 32 tokens.")
    with localcontext() as context:
        context.prec = 64
        amount = (context_window_tokens * _money(input_price_per_million) + max_observed_output_tokens * _money(output_price_per_million)) / Decimal(1_000_000)
        return amount.quantize(Decimal("0.000000000000000001"), rounding=ROUND_CEILING)


def _receipt(receipt: Mapping[str, Any] | None) -> dict[str, Any]:
    """Keep only typed accounting fields: never bodies, prompts, IDs, or errors."""
    if receipt is None:
        return {}
    if not isinstance(receipt, Mapping):
        raise ProbeBudgetError("invalid_probe_receipt", "Probe receipt must be a mapping.")
    clean: dict[str, Any] = {}
    allowed_statuses = {"completed", "incomplete", "failed", "unknown", "transport_error", "provider_error"}
    if "status" in receipt:
        if not isinstance(receipt["status"], str) or receipt["status"] not in allowed_statuses:
            raise ProbeBudgetError("invalid_probe_receipt", "Probe receipt status is invalid.")
        clean["status"] = receipt["status"]
    for name in ("request_payload_sha256", "response_sha256"):
        if name in receipt:
            clean[name] = _digest(receipt[name])
    for name in ("input_tokens", "output_tokens", "reasoning_tokens", "cached_input_tokens", "http_status"):
        if name not in receipt:
            continue
        value = receipt[name]
        if value is None and name != "http_status":
            clean[name] = None
        elif isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 10**12:
            raise ProbeBudgetError("invalid_probe_receipt", "Probe receipt numeric accounting is invalid.")
        elif name == "http_status" and not 100 <= value <= 599:
            raise ProbeBudgetError("invalid_probe_receipt", "Probe receipt HTTP status is invalid.")
        else:
            clean[name] = value
    if "latency_seconds" in receipt:
        value = receipt["latency_seconds"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 31_536_000:
            raise ProbeBudgetError("invalid_probe_receipt", "Probe receipt latency is invalid.")
        clean["latency_seconds"] = value
    if "usage_warnings" in receipt:
        if (receipt["usage_warnings"] != ["reasoning_tokens_exceed_output_tokens"]
            or not isinstance(clean.get("reasoning_tokens"), int)
            or not isinstance(clean.get("output_tokens"), int)
            or clean["reasoning_tokens"] <= clean["output_tokens"]):
            raise ProbeBudgetError("invalid_probe_receipt", "Probe usage warning is invalid.")
        clean["usage_warnings"] = list(receipt["usage_warnings"])
    # Unknown fields are intentionally discarded, including nested raw responses.
    return clean


class ProbeBudgetLedger:
    """A locked accounting file in a run directory, shared by every model worker.

    Creation is idempotent only for identical model/treatment/limit settings.
    The persistent lock file also marks initialization: a missing ledger after
    initialization cannot silently reset a spent budget.
    """

    def __init__(
        self,
        run_dir: Path,
        *,
        model_alias: str,
        treatment_sha256: str,
        max_requests: int,
        max_cost_usd: Any,
    ) -> None:
        if not isinstance(model_alias, str) or not model_alias or len(model_alias) > 200 or any(ord(c) < 32 for c in model_alias):
            raise ProbeBudgetError("invalid_probe_budget", "Probe budget model alias is invalid.")
        if isinstance(max_requests, bool) or not isinstance(max_requests, int) or not 1 <= max_requests <= _MAX_REQUESTS:
            raise ProbeBudgetError("invalid_probe_budget", "Probe request limit must be between 1 and 100000.")
        self._identity = {
            "schema_version": PROBE_BUDGET_SCHEMA,
            "model_alias": model_alias,
            "treatment_sha256": _digest(treatment_sha256),
            "max_requests": max_requests,
            "max_cost_usd": _amount(_money(max_cost_usd)),
        }
        self.directory = Path(run_dir) / "context-probe-budgets"
        name = hashlib.sha256(model_alias.encode("utf-8")).hexdigest()
        self.path = self.directory / f"{name}.json"
        self._lock_path = self.directory / f"{name}.lock"
        self._marker = hashlib.sha256(self._encode(self._identity)).hexdigest().encode("ascii")
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self._fsync_directory(self.directory.parent)
            with self._locked(initializing=True) as descriptor:
                marker = os.read(descriptor, 65)
                if marker:
                    if re.fullmatch(b"[0-9a-f]{64}", marker) is None:
                        raise ProbeBudgetError("corrupt_probe_budget", "Probe budget initialization marker is invalid or storage was poisoned.")
                    if marker != self._marker:
                        raise ProbeBudgetError("incompatible_probe_budget", "Existing probe budget identity or limits differ.")
                    self._load()
                elif self.path.exists():
                    raise ProbeBudgetError("corrupt_probe_budget", "Probe ledger initialization is incomplete; budget remains closed.")
                else:
                    self._write({**self._identity, "reservations": {}})
                    os.write(descriptor, self._marker)
                    os.fsync(descriptor)
                    self._fsync_directory(self.directory)
        except OSError:
            raise ProbeBudgetError("probe_budget_storage_error", "Probe budget could not be durably initialized.") from None

    @staticmethod
    def _encode(value: Any) -> bytes:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @contextmanager
    def _locked(self, *, initializing: bool = False) -> Iterator[int]:
        descriptor = os.open(self._lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            if not initializing and os.read(descriptor, 65) != self._marker:
                raise ProbeBudgetError("corrupt_probe_budget", "Probe budget initialization marker is missing or invalid.")
            yield descriptor
        finally:
            os.close(descriptor)

    def _write(self, state: Mapping[str, Any]) -> None:
        descriptor, temporary = tempfile.mkstemp(prefix=f".{self.path.stem}.", dir=self.directory)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                encoded = self._encode(state)
                if len(encoded) > _MAX_STATE_BYTES:
                    raise ProbeBudgetError("probe_budget_storage_error", "Probe budget exceeds the durable state size limit.")
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            self._fsync_directory(self.directory)
        except OSError:
            # The caller still holds the exclusive lock. In particular, an
            # uncertain settlement must not permit a future process to resume
            # from an older, lower liability after a transient storage error.
            try:
                poison = os.open(self._lock_path, os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0))
                try:
                    os.write(poison, b"poisoned:storage-durability-failure")
                    os.ftruncate(poison, len(b"poisoned:storage-durability-failure"))
                    os.fsync(poison)
                finally:
                    os.close(poison)
            except OSError:
                pass  # An unavailable filesystem cannot acknowledge any write.
            raise
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def _load(self) -> dict[str, Any]:
        try:
            if self.path.stat().st_size > _MAX_STATE_BYTES:
                raise ValueError
            def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
                result: dict[str, Any] = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError
                    result[key] = value
                return result
            with self.path.open("rb") as stream:
                state = json.load(stream, object_pairs_hook=unique_object)
            if not isinstance(state, dict) or set(state) != {*self._identity, "reservations"}:
                raise ValueError
            if self._encode({key: state[key] for key in self._identity}) != self._encode(self._identity):
                raise ProbeBudgetError("incompatible_probe_budget", "Existing probe budget identity or limits differ.")
            reservations = state["reservations"]
            if not isinstance(reservations, dict) or len(reservations) > self._identity["max_requests"]:
                raise ValueError
            for token, item in reservations.items():
                if not isinstance(token, str) or _RESERVATION_ID.fullmatch(token) is None or not isinstance(item, dict):
                    raise ValueError
                if set(item) != {"request_payload_sha256", "worst_case_cost_usd", "observed_cost_usd", "charged_cost_usd", "state", "receipt"}:
                    raise ValueError
                _digest(item["request_payload_sha256"])
                worst_case = _money(item["worst_case_cost_usd"])
                charged = _recorded_money(item["charged_cost_usd"])
                observed = None if item["observed_cost_usd"] is None else _recorded_money(item["observed_cost_usd"])
                if item["state"] in {"reserved", "unknown"}:
                    if observed is not None or charged != worst_case:
                        raise ValueError
                    if item["state"] == "reserved" and item["receipt"]:
                        raise ValueError
                elif item["state"] in {"known", "overrun"}:
                    _money(item["observed_cost_usd"])
                    if observed is None or charged != observed or (observed > worst_case) != (item["state"] == "overrun"):
                        raise ValueError
                elif item["state"] == "unsupported_cost":
                    if charged != max(worst_case, observed if observed is not None else worst_case):
                        raise ValueError
                else:
                    raise ValueError
                if not isinstance(item["receipt"], dict) or _receipt(item["receipt"]) != item["receipt"]:
                    raise ValueError
            total = _total_cost(reservations)
            if total > _money(self._identity["max_cost_usd"]) and not any(item["state"] in {"overrun", "unsupported_cost"} for item in reservations.values()):
                raise ValueError
            return state
        except ProbeBudgetError as error:
            if error.code == "incompatible_probe_budget":
                raise
            raise ProbeBudgetError("corrupt_probe_budget", "Probe budget state is invalid; probes remain disabled.") from None
        except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
            raise ProbeBudgetError("corrupt_probe_budget", "Probe budget state is unreadable or invalid; probes remain disabled.") from None

    @staticmethod
    def _summary(state: Mapping[str, Any], *, include_reservations: bool = False) -> dict[str, Any]:
        reservations = state["reservations"]
        charged = _total_cost(reservations)
        with localcontext() as context:
            context.prec = 1024
            remaining = max(Decimal(0), _money(state["max_cost_usd"]) - charged)
        summary = {
            **{key: value for key, value in state.items() if key != "reservations"},
            "requests_reserved": len(reservations),
            "requests_remaining": state["max_requests"] - len(reservations),
            "charged_cost_usd": _amount(charged),
            "remaining_cost_usd": _amount(remaining),
            "unconfirmed_requests": sum(item["state"] in {"reserved", "unknown"} for item in reservations.values()),
            "poisoned": any(item["state"] in {"overrun", "unsupported_cost"} for item in reservations.values()),
        }
        if include_reservations:
            summary["reservations"] = reservations
        return summary

    def reserve(self, *, worst_case_cost_usd: Any, request_payload_sha256: str) -> str:
        """Durably charge liability before the HTTP attempt; never reuse a token."""
        cost = _money(worst_case_cost_usd)
        digest = _digest(request_payload_sha256)
        try:
            with self._locked():
                state = self._load()
                summary = self._summary(state)
                if summary["poisoned"]:
                    raise ProbeBudgetError("probe_price_cap_breached", "A probe exceeded its price reservation; further probes are disabled.")
                if summary["requests_remaining"] <= 0:
                    raise ProbeBudgetError("probe_request_limit", "The run/model probe request limit is exhausted.")
                if cost > _money(summary["remaining_cost_usd"]):
                    raise ProbeBudgetError("probe_cost_limit", "The next probe would exceed the run/model cost limit.")
                token = uuid.uuid4().hex
                if token in state["reservations"]:
                    raise ProbeBudgetError("probe_budget_storage_error", "Probe reservation identity collided; no request may be sent.")
                state["reservations"][token] = {
                    "request_payload_sha256": digest,
                    "worst_case_cost_usd": _amount(cost),
                    "observed_cost_usd": None,
                    "charged_cost_usd": _amount(cost),
                    "state": "reserved",
                    "receipt": {},
                }
                self._write(state)
                return token
        except OSError:
            raise ProbeBudgetError("probe_budget_storage_error", "Probe reservation was not confirmed durable; do not send the request.") from None

    def settle(
        self,
        reservation_id: str,
        *,
        observed_cost_usd: Any = None,
        receipt: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Finalize once. Unknown charges retain the reservation permanently.

        Identical repeated settlements are idempotent. Conflicting settlement
        attempts fail closed. A price-cap overrun is saved before raising and
        permanently prevents further reservations, even below the overall cap.
        """
        unsupported_observed = False
        try:
            observed = None if observed_cost_usd is None else _money(observed_cost_usd)
        except ProbeBudgetError:
            # Settlement happens after HTTP: rejecting a monetary domain cannot
            # erase an expensive response or reopen capacity after a restart.
            unsupported_observed = True
            try:
                observed = _recorded_money(observed_cost_usd)
            except ProbeBudgetError:
                observed = None
        clean_receipt = _receipt(receipt)
        if not isinstance(reservation_id, str) or _RESERVATION_ID.fullmatch(reservation_id) is None:
            raise ProbeBudgetError("unknown_probe_reservation", "Probe reservation identifier is invalid.")
        try:
            with self._locked():
                state = self._load()
                item = state["reservations"].get(reservation_id)
                if item is None:
                    raise ProbeBudgetError("unknown_probe_reservation", "Probe reservation does not exist.")
                worst_case = _money(item["worst_case_cost_usd"])
                changed = {
                    **item,
                    "observed_cost_usd": None if observed is None else _amount(observed),
                    "charged_cost_usd": _amount(max(worst_case, observed or Decimal(0)) if unsupported_observed else worst_case if observed is None else observed),
                    "state": "unsupported_cost" if unsupported_observed else "unknown" if observed is None else "overrun" if observed > worst_case else "known",
                    "receipt": clean_receipt,
                }
                if item["state"] != "reserved" and item != changed:
                    raise ProbeBudgetError("conflicting_probe_settlement", "A settled probe cannot be changed or refunded again.")
                state["reservations"][reservation_id] = changed
                if item != changed:
                    self._write(state)
                if changed["state"] == "unsupported_cost":
                    raise ProbeBudgetError("probe_cost_accounting_unsupported", "Probe reported an unsupported monetary amount; its available cost evidence is recorded and further probes are disabled.")
                if changed["state"] == "overrun":
                    raise ProbeBudgetError("probe_price_cap_breached", "Probe cost exceeded its reservation; actual cost is recorded and further probes are disabled.")
                return {"reservation_id": reservation_id, "reservation": changed, "budget": self._summary(state)}
        except OSError:
            raise ProbeBudgetError("probe_budget_storage_error", "Probe settlement was not confirmed durable; its liability remains reserved.") from None

    def snapshot(self, *, include_reservations: bool = True) -> dict[str, Any]:
        try:
            with self._locked():
                return self._summary(self._load(), include_reservations=include_reservations)
        except OSError:
            raise ProbeBudgetError("probe_budget_storage_error", "Probe budget accounting is unavailable; probes remain disabled.") from None
