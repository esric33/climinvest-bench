"""Explicit endpoint-qualified terminal choice, without guessing capabilities.

Selecting a policy declares the intended wire behavior; it does not assert that
an endpoint supports it. Model owners must bind conformance receipts to it.
Legacy episodes preserve their adapter default when no policy was selected.
"""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from .episode import RESERVE_FINAL_TURN, SPLIT_TERMINAL_PROTOCOL, TERMINAL_TOOLS


FINAL_TURN_TOOL_CHOICE_POLICIES = frozenset({"auto", "required", "named"})


def final_turn_policy_provenance(policy: str | None) -> dict[str, Any] | None:
    if policy is None:
        return None
    if policy not in FINAL_TURN_TOOL_CHOICE_POLICIES:
        raise ValueError("final_turn_tool_choice_policy must be auto, required, or named")
    value = {
        "schema_version": "react_report.final_turn_tool_choice_policy/v1",
        "selection": policy,
        "scope": "reserved_final_turn_only",
        "terminal_calls": "exactly_one",
        "update_choice": "model_selects_keep_or_replace",
        "capability_evidence": "requires_separate_endpoint_conformance_receipt",
        "unsupported_behavior": "fail_without_fallback_or_repair",
    }
    return {
        **value,
        "sha256": sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
    }


def final_turn_tool_choice(
    episode: Any, policy: str | None, *, transport: str, ordinary_choice: Any,
) -> Any:
    """Resolve the selected policy before making any provider request."""

    final_turn_policy_provenance(policy)  # Validate even ordinary/no-tool calls.
    reserved = getattr(episode, "turn_policy", None) == RESERVE_FINAL_TURN
    corrected = getattr(episode, "terminal_protocol_version", None) == SPLIT_TERMINAL_PROTOCOL
    if reserved and corrected and policy is None:
        raise ValueError("corrected 7+1 episodes require an explicit final_turn_tool_choice_policy")
    terminal = sorted(getattr(episode, "allowed_tools", frozenset()) & TERMINAL_TOOLS)
    if reserved and policy == "named" and len(terminal) != 1:
        raise ValueError("named final-turn choice requires one terminal; section updates require required or explicit auto")
    if getattr(episode, "turn_phase", None) != "finalization" or policy is None:
        return ordinary_choice
    if not terminal:
        raise ValueError("final-turn tool choice requires terminal tools")
    if transport == "anthropic_messages":
        return {"type": "tool", "name": terminal[0]} if policy == "named" else {"type": "any" if policy == "required" else "auto"}
    if policy != "named":
        return policy
    if transport == "openai_compatible":
        return {"type": "function", "function": {"name": terminal[0]}}
    if transport == "openai_responses":
        return {"type": "function", "name": terminal[0]}
    raise ValueError(f"unsupported final-turn policy transport {transport!r}")
