from __future__ import annotations

import json
from typing import Any

from ..episode import SPLIT_TERMINAL_PROTOCOL
from ..rendering import canonical_operations, render_report, render_section
from ..tool_schemas import uses_compact_calculation_actions
from .base import ProviderTurn


class FixtureProvider:
    """Deterministic two-turn agent used for local end-to-end smoke tests."""

    name = "fixture"
    model = "deterministic-fixture-v1"

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        episode: Any,
    ) -> ProviderTurn:
        turn_index = len(episode.turns)
        if getattr(episode, "episode_kind", None) == "gold_component":
            required_ids = tuple(getattr(episode, "required_ids", ()) or ())
            not_applicable_ids = set(
                getattr(episode, "not_applicable_ids", ()) or ()
            )
            citations = ", ".join(
                (
                    f"[not applicable](missing.{node_id})"
                    if node_id in not_applicable_ids
                    else f"[{node_id}]({node_id})"
                )
                for node_id in required_ids
            )
            text = (
                f"Deterministic fixture synthesis for {episode.component_id}: "
                f"{citations}."
            )
            token_estimate = max(1, len(text) // 4)
            return ProviderTurn(
                text=text,
                raw_response={
                    "fixture": True,
                    "turn": turn_index,
                    "status": "completed",
                },
                usage={
                    "input_tokens": max(
                        1,
                        sum(len(item["content"]) for item in messages) // 4,
                    ),
                    "output_tokens": token_estimate,
                    "reasoning_tokens": 0,
                },
                latency_seconds=0.0,
                provider_request_id=(
                    f"fixture-{episode.episode_id}-{turn_index}"
                ),
            )
        report_renderer = episode.report_renderer or render_report
        section_renderer = episode.section_renderer or render_section
        if episode.episode_kind == "oracle_report" and turn_index == 0:
            action = {
                "action": "tool_calls",
                "calls": [
                    {
                        "tool": "create_report",
                        "arguments": {"markdown": report_renderer(episode.store)},
                    }
                ],
            }
        elif episode.episode_kind == "oracle_section" and turn_index == 0:
            action = {
                "action": "tool_calls",
                "calls": [
                    {
                        "tool": "create_section",
                        "arguments": {
                            "section_id": episode.section_id,
                            "mode": "create",
                            "markdown": section_renderer(
                                episode.section_id, episode.store
                            ),
                        },
                    }
                ],
            }
        elif turn_index == 0:
            ids = [
                *episode.store._nodes.keys(),  # fixture intentionally requests the public catalogue
            ]
            action = {
                "action": "tool_calls",
                "calls": [
                    {"tool": "get_data", "arguments": {"ids": ids}},
                    {
                        "tool": "calculate",
                        "arguments": {
                            **(
                                {"ids": list(episode.calculator.registry)}
                                if uses_compact_calculation_actions(episode)
                                else {
                                    "operations": canonical_operations(
                                        episode.calculator
                                    )
                                }
                            )
                        },
                    },
                ],
            }
        else:
            if episode.episode_kind in {"report_create", "report_update"}:
                action = {
                    "action": "tool_calls",
                    "calls": [
                        {
                            "tool": "create_report",
                            "arguments": {"markdown": report_renderer(episode.store)},
                        }
                    ],
                }
            else:
                mode = (
                    "create"
                    if episode.episode_kind == "section_create"
                    else self._update_mode(episode)
                )
                arguments: dict[str, Any] = {
                    "section_id": episode.section_id,
                    "mode": mode,
                }
                if mode != "keep":
                    arguments["markdown"] = section_renderer(
                        episode.section_id, episode.store
                    )
                action = {
                    "action": "tool_calls",
                    "calls": [
                        {"tool": "create_section", "arguments": arguments}
                    ],
                }
        if getattr(episode, "terminal_protocol_version", None) == SPLIT_TERMINAL_PROTOCOL:
            for call in action["calls"]:
                if call["tool"] == "create_section":
                    mode = call["arguments"].pop("mode")
                    call["tool"] = {"create": "create_section", "replace": "replace_section", "keep": "keep_section"}[mode]
        text = _render_textual_action(action)
        token_estimate = max(1, len(text) // 4)
        return ProviderTurn(
            text=text,
            raw_response={"fixture": True, "turn": turn_index},
            usage={
                "input_tokens": max(1, sum(len(item["content"]) for item in messages) // 4),
                "output_tokens": token_estimate,
                "reasoning_tokens": 0,
            },
            latency_seconds=0.0,
            provider_request_id=f"fixture-{episode.episode_id}-{turn_index}",
        )

    @staticmethod
    def _update_mode(episode: Any) -> str:
        renderer = episode.section_renderer or render_section
        current = renderer(episode.section_id, episode.store)
        return "replace" if current != episode.original_markdown else "keep"


def _render_textual_action(action: dict[str, Any]) -> str:
    """Render fixture actions through the same terminal frame as real models."""

    calls = action.get("calls")
    if isinstance(calls, list) and len(calls) == 1:
        call = calls[0]
        arguments = call.get("arguments") if isinstance(call, dict) else None
        tool = str(call.get("tool") or "") if isinstance(call, dict) else ""
        if (
            tool in {"create_report", "create_section", "replace_section"}
            and isinstance(arguments, dict)
            and isinstance(arguments.get("markdown"), str)
        ):
            markdown = arguments["markdown"]
            header = {
                "action": "tool_calls",
                "calls": [
                    {
                        "tool": tool,
                        "arguments": {
                            key: value
                            for key, value in arguments.items()
                            if key != "markdown"
                        },
                    }
                ],
            }
            return (
                f"{json.dumps(header, ensure_ascii=False, separators=(',', ':'))}"
                f"\n\n{markdown}"
            )
    return json.dumps(action, ensure_ascii=False, separators=(",", ":"))
