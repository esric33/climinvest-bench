"""Explicit, state-checked aliases for run-scoped fact interventions.

Only the single-source declarations emitted by ``add_source_alias`` qualify.
Equal values, similar labels and multi-source derivations establish no alias.
Source archives are never modified by these helpers.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable


ALIAS_INTERVENTION_POLICY = "react_report.alias_intervention/v1-single-source-closure"


def source_alias_groups(twin: dict[str, Any]) -> tuple[tuple[str, ...], ...]:
    """Return declared connected components, rejecting inconsistent copies."""
    nodes = twin.get("nodes", {})
    neighbours: dict[str, set[str]] = {}
    for node_id, node in nodes.items():
        normalization = node.get("normalization") or {}
        if normalization.get("canonical_alias") is not True:
            continue
        # add_source_derivation also sets canonical_alias. Its plural inputs
        # are deliberately outside this policy, even for a one-element list.
        if "source_node_ids" in normalization or "source_node_ids" in (node.get("provenance") or {}):
            continue
        source_id = normalization.get("source_node_id")
        if not isinstance(source_id, str) or not source_id:
            continue
        source = nodes.get(source_id)
        if not isinstance(source, dict) or source_id == node_id:
            raise ValueError(f"{node_id}: invalid declared source alias {source_id!r}")
        provenance_id = (node.get("provenance") or {}).get("source_node_id")
        if provenance_id != source_id:
            raise ValueError(f"{node_id}: source alias provenance disagrees")
        if node.get("kind") != "scalar" or source.get("kind") != "scalar":
            raise ValueError(f"{node_id}: only declared scalar source aliases are supported")
        if _state(node) != _state(source):
            raise ValueError(f"{node_id}: declared source alias has inconsistent state with {source_id}")
        neighbours.setdefault(node_id, set()).add(source_id)
        neighbours.setdefault(source_id, set()).add(node_id)
    groups = []
    unseen = set(neighbours)
    while unseen:
        pending = [min(unseen)]
        group: set[str] = set()
        while pending:
            current = pending.pop()
            if current not in group:
                group.add(current)
                pending.extend(neighbours[current] - group)
        unseen.difference_update(group)
        groups.append(tuple(sorted(group)))
    return tuple(sorted(groups))


def _state(node: dict[str, Any]) -> tuple[Any, ...]:
    return (node.get("status"), node.get("value"), node.get("unit"),
            (node.get("applicability") or {}).get("status", "applicable"))


def expand_source_alias_ids(twin: dict[str, Any], node_ids: Iterable[str]) -> list[str]:
    """Preserve primary ID order and append all explicitly equivalent copies."""
    requested = list(dict.fromkeys(node_ids))
    expanded = set(requested)
    for group in source_alias_groups(twin):
        if expanded.intersection(group):
            expanded.update(group)
    return requested + sorted(expanded.difference(requested))


def expand_source_alias_changes(twin: dict[str, Any], changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Declare the same replacement for every copy; conflicting changes fail."""
    output = deepcopy(changes)
    by_id = {change["node_id"]: change for change in output}
    if len(by_id) != len(output):
        raise ValueError("mutation changes contain duplicate node IDs")
    for change in changes:
        if change.get("operation") != "replace_value":
            continue
        for alias_id in expand_source_alias_ids(twin, [change["node_id"]]):
            if alias_id in by_id:
                other = by_id[alias_id]
                if any(other.get(key) != change.get(key) for key in
                       ("operation", "old_status", "new_status", "old_value", "new_value")):
                    raise ValueError(f"{alias_id}: conflicting replacements in one source-alias group")
                continue
            alias_change = {**deepcopy(change), "node_id": alias_id,
                            "alias_of": change["node_id"]}
            output.append(alias_change)
            by_id[alias_id] = alias_change
    return output


def validate_mask_alias_closure(twin: dict[str, Any], condition: dict[str, Any]) -> None:
    """Versioned new conditions must enumerate their full effective mask."""
    policy = condition.get("alias_intervention_policy")
    if policy is None:
        return  # Historical conditions retain their original semantics.
    if policy != ALIAS_INTERVENTION_POLICY:
        raise ValueError("unsupported source-alias intervention policy")
    masked = list(condition.get("masked_ids") or [])
    if set(masked) != set(expand_source_alias_ids(twin, masked)):
        raise ValueError("missingness condition omits an equivalent source alias")
