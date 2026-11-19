from __future__ import annotations

from typing import Any

from .provider_cost import add_provider_cost, empty_provider_cost_summary


def episode_turns(episode: dict[str, Any]) -> list[dict[str, Any]]:
    """All generated turns, including a retained unsuccessful first attempt."""
    prior = episode.get("prior_attempts") or []
    if not prior and "episode_retry" not in episode:
        return episode.get("turns") or []
    return [{**turn, "episode_attempt": index}
            for index, attempt in enumerate([*prior, episode])
            for turn in attempt.get("turns") or []]


def aggregate_usage(turns: list[dict[str, Any]]) -> dict[str, Any]:
    fields = [
        "input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "cached_input_tokens",
    ]
    output: dict[str, Any] = {
        field: sum(
            int(turn.get("usage", {}).get(field) or 0)
            for turn in turns
        )
        for field in fields
    }
    output["total_tokens"] = output["input_tokens"] + output["output_tokens"]
    output["model_turns"] = len(turns)
    output["latency_seconds"] = sum(float(turn.get("latency_seconds") or 0) for turn in turns)
    emitted_tool_calls = sum(_emitted_tool_calls(turn) for turn in turns)
    output["tool_calls"] = emitted_tool_calls
    output["emitted_tool_calls"] = emitted_tool_calls
    output["semantic_tool_calls"] = sum(
        _semantic_tool_calls(turn) for turn in turns
    )
    output["executed_tool_calls"] = sum(
        _executed_tool_calls(turn) for turn in turns
    )
    output["action_envelopes"] = sum(
        _batch_integer(turn, "action_envelope_count") for turn in turns
    )
    output["semantic_action_envelopes"] = sum(
        _batch_integer(turn, "semantic_action_envelope_count")
        for turn in turns
    )
    # Explicit alias retained for traces produced before ``action_batch`` made
    # the emitted/semantic distinction first-class.
    output["raw_action_envelopes"] = output["action_envelopes"]
    open_loop_batch_sizes = [
        _executed_tool_calls(turn)
        for turn in turns
        if _is_completed_open_loop_batch(turn)
    ]
    output["open_loop_batches"] = len(open_loop_batch_sizes)
    output["observation_rounds"] = sum(
        _batch_integer(turn, "observation_round_count") for turn in turns
    )
    output["open_loop_tool_calls"] = sum(open_loop_batch_sizes)
    output["max_batch_size"] = max(open_loop_batch_sizes, default=0)
    output["mean_batch_size"] = (
        sum(open_loop_batch_sizes) / len(open_loop_batch_sizes)
        if open_loop_batch_sizes
        else 0.0
    )
    output["protocol_errors"] = sum(
        1 for turn in turns if turn.get("status") == "protocol_error"
    )
    normalization_rules: dict[str, int] = {}
    for turn in turns:
        for event in turn.get("normalizations") or []:
            if not isinstance(event, dict):
                continue
            kind = str(event.get("kind") or "unknown")
            normalization_rules[kind] = normalization_rules.get(kind, 0) + 1
    output["normalization_events"] = sum(normalization_rules.values())
    output["normalization_rules"] = dict(sorted(normalization_rules.items()))
    output["turn_attribution"] = _turn_attribution(turns)
    # This episode-local summary is a derived convenience view. Provider-turn
    # checkpoints remain the authoritative run-level accounting ledger.
    provider_cost = empty_provider_cost_summary()
    for turn in turns:
        add_provider_cost(provider_cost, turn.get("provider_cost"))
    output["provider_cost"] = provider_cost
    return output


def aggregate_report_episodes(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    usage_fields = [
        "input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "cached_input_tokens",
        "total_tokens",
        "model_turns",
        "tool_calls",
        "emitted_tool_calls",
        "semantic_tool_calls",
        "executed_tool_calls",
        "action_envelopes",
        "semantic_action_envelopes",
        "raw_action_envelopes",
        "open_loop_batches",
        "observation_rounds",
        "open_loop_tool_calls",
        "protocol_errors",
        "normalization_events",
    ]
    output = {
        field: sum(int(item.get("accounting", {}).get(field) or 0) for item in episodes)
        for field in usage_fields
    }
    output["latency_seconds"] = sum(
        float(item.get("accounting", {}).get("latency_seconds") or 0)
        for item in episodes
    )
    output["max_batch_size"] = max(
        (
            int(item.get("accounting", {}).get("max_batch_size") or 0)
            for item in episodes
        ),
        default=0,
    )
    output["mean_batch_size"] = (
        output["open_loop_tool_calls"] / output["open_loop_batches"]
        if output["open_loop_batches"]
        else 0.0
    )
    normalization_rules: dict[str, int] = {}
    for item in episodes:
        rules = item.get("accounting", {}).get("normalization_rules") or {}
        if not isinstance(rules, dict):
            continue
        for kind, count in rules.items():
            name = str(kind)
            normalization_rules[name] = normalization_rules.get(name, 0) + int(
                count or 0
            )
    output["normalization_rules"] = dict(sorted(normalization_rules.items()))
    # Section-scope records combine several episode artifacts. Re-aggregate the
    # canonical turn values so their derived record accounting remains exact.
    provider_cost = empty_provider_cost_summary()
    for episode in episodes:
        turns = episode_turns(episode)
        if not isinstance(turns, list):
            continue
        for turn in turns:
            if isinstance(turn, dict):
                add_provider_cost(provider_cost, turn.get("provider_cost"))
    output["provider_cost"] = provider_cost
    return output


def _action_batch(turn: dict[str, Any]) -> dict[str, Any]:
    value = turn.get("action_batch")
    return value if isinstance(value, dict) else {}


def _is_completed_open_loop_batch(turn: dict[str, Any]) -> bool:
    if (
        turn.get("status") != "completed"
        or not turn.get("observations")
        or any(
            isinstance(call, dict)
            and call.get("tool") in {"create_report", "create_section", "replace_section", "keep_section"}
            for call in turn.get("calls") or []
        )
    ):
        return False

    observation_boundary = turn.get("observation_boundary")
    if (
        isinstance(observation_boundary, dict)
        and observation_boundary.get("mode") == "ordered_open_loop_batch"
    ):
        return True

    action_batch = _action_batch(turn)
    return (
        action_batch.get("semantics") == "native_tool_batch"
        and action_batch.get("status") == "completed"
        and action_batch.get("disposition") == "executed_nonterminal_batch"
        and _batch_integer(turn, "observation_round_count") == 1
        and _executed_tool_calls(turn) > 0
    )


def _batch_integer(turn: dict[str, Any], field: str) -> int:
    value = _action_batch(turn).get(field)
    return int(value) if isinstance(value, int) and value >= 0 else 0


def _emitted_tool_calls(turn: dict[str, Any]) -> int:
    value = _action_batch(turn).get("emitted_tool_call_count")
    if isinstance(value, int) and value >= 0:
        return value
    fallback = turn.get("emitted_call_count")
    if isinstance(fallback, int) and fallback >= 0:
        return fallback
    return len(turn.get("calls") or [])


def _semantic_tool_calls(turn: dict[str, Any]) -> int:
    value = _action_batch(turn).get("semantic_tool_call_count")
    if isinstance(value, int) and value >= 0:
        return value
    fallback = turn.get("semantic_call_count")
    if isinstance(fallback, int) and fallback >= 0:
        return fallback
    return len(turn.get("calls") or [])


def _executed_tool_calls(turn: dict[str, Any]) -> int:
    value = _action_batch(turn).get("executed_tool_call_count")
    if isinstance(value, int) and value >= 0:
        return value
    fallback = turn.get("executed_call_count")
    if isinstance(fallback, int) and fallback >= 0:
        return fallback
    return len(turn.get("calls") or []) if turn.get("status") == "completed" else 0


def _turn_attribution(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return an exact per-response token ledger plus size-only context data."""

    output: list[dict[str, Any]] = []
    previous_input: int | None = None
    cumulative_input = 0
    cumulative_output = 0
    previous_attempt = None
    for fallback_index, turn in enumerate(turns):
        if "episode_attempt" in turn and turn["episode_attempt"] != previous_attempt:
            previous_input = None
            previous_attempt = turn["episode_attempt"]
        usage = turn.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        input_tokens = _usage_integer(usage, "input_tokens")
        output_tokens = _usage_integer(usage, "output_tokens")
        reasoning_tokens = _usage_integer(usage, "reasoning_tokens")
        cached_input_tokens = min(
            input_tokens,
            _usage_integer(usage, "cached_input_tokens"),
        )
        cumulative_input += input_tokens
        cumulative_output += output_tokens
        item: dict[str, Any] = {
            "turn_index": int(turn.get("turn_index", fallback_index)),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "reasoning_tokens": reasoning_tokens,
            "cached_input_tokens": cached_input_tokens,
            "uncached_input_tokens": input_tokens - cached_input_tokens,
            "input_token_change_from_previous_turn": (
                None
                if previous_input is None
                else input_tokens - previous_input
            ),
            "cumulative_input_tokens": cumulative_input,
            "cumulative_output_tokens": cumulative_output,
            "cumulative_total_tokens": cumulative_input + cumulative_output,
        }
        context = turn.get("request_context")
        if "episode_attempt" in turn:
            item.update(episode_attempt=turn["episode_attempt"],
                        attempt_turn_index=item["turn_index"], response_index=fallback_index)
        if isinstance(context, dict) and context:
            item["request_context"] = context
        output.append(item)
        previous_input = input_tokens
    return output


def _usage_integer(usage: dict[str, Any], field: str) -> int:
    try:
        value = int(usage.get(field) or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, value)
