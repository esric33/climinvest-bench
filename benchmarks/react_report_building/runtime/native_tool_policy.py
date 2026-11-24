"""Explicit, hash-bound native tool enforcement for qualified serving runs."""

from __future__ import annotations

from hashlib import sha256
import json


STRICT_REQUIRED_V1 = "strict_required_v1"
STRICT_AUTO_V1 = "strict_auto_v1"
NATIVE_TOOL_POLICIES = frozenset({STRICT_REQUIRED_V1, STRICT_AUTO_V1})


def native_tool_policy_provenance(selection: str | None) -> dict | None:
    if selection is None:
        return None
    if not isinstance(selection, str) or selection not in NATIVE_TOOL_POLICIES:
        raise ValueError("native_tool_policy must be strict_required_v1 or strict_auto_v1")
    automatic = selection == STRICT_AUTO_V1
    value = {
        "schema_version": "react_report.native_tool_policy/v1",
        "selection": selection,
        "strict_arguments": True,
        "ordinary_tool_choice": "auto" if automatic else "required",
        "final_tool_choice": "auto" if automatic else "required_or_named",
        "unsupported_behavior": "fail_without_fallback_or_repair",
        "capability_evidence": "requires_endpoint_conformance_receipt",
    }
    return {**value, "sha256": sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}


def validate_native_tool_policy(selection: str | None, *, action_protocol: str,
                                final_turn_tool_choice_policy: str | None) -> dict | None:
    """Validate the declared wire contract consistently at config and runtime."""
    provenance = native_tool_policy_provenance(selection)
    if provenance is None:
        return None
    if action_protocol != "native_tools":
        raise ValueError("strict native tool policy requires native_tools")
    allowed_final = {"auto"} if selection == STRICT_AUTO_V1 else {"required", "named"}
    if final_turn_tool_choice_policy not in allowed_final:
        choices = "auto" if selection == STRICT_AUTO_V1 else "required or named"
        raise ValueError(f"{selection} requires {choices} final tool choice; endpoint qualification is required")
    return provenance
