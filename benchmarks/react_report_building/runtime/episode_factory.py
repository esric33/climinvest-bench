from __future__ import annotations

from typing import Any

from ..paths import CATALOGUE_ROOT, PROMPT_ROOT, REFERENCE_ROOT
from ..util import compact_json, read_json
from .calculator import Calculator
from .episode import (
    Episode, UNRESTRICTED_TURNS, LEGACY_TERMINAL_PROTOCOL,
    SPLIT_TERMINAL_PROTOCOL, TERMINAL_TOOLS,
)
from .evidence_store import EvidenceStore


REACT_ALLOWED_TOOLS = {
    "report_create": frozenset({"get_data", "calculate", "create_report"}),
    "report_update": frozenset({"get_data", "calculate", "create_report"}),
    "section_create": frozenset({"get_data", "calculate", "create_section"}),
    "section_update": frozenset({"get_data", "calculate", "create_section"}),
}


def load_reference() -> dict[str, Any]:
    return read_json(REFERENCE_ROOT / "climatefund20-v1.json")


def load_catalogue() -> dict[str, Any]:
    return read_json(CATALOGUE_ROOT / "global_catalogue.json")


def prompt(name: str, **values: Any) -> str:
    template = (PROMPT_ROOT / name).read_text(encoding="utf-8")
    return template.format(**values)


def make_episode(
    *,
    episode_id: str,
    episode_kind: str,
    twin: dict[str, Any],
    user_prompt: str,
    max_turns: int,
    turn_policy: str = UNRESTRICTED_TURNS,
    masked_ids: set[str] | None = None,
    section_id: str | None = None,
    original_markdown: str | None = None,
    update_event: dict[str, Any] | None = None,
    allowed_tools: frozenset[str] | None = None,
    system_prompt_name: str = "v2_react_system.md",
    calculation_registry: dict[str, dict[str, Any]] | None = None,
    benchmark_version: str = "v2",
    report_renderer: Any = None,
    report_output_validator: Any = None,
    section_renderer: Any = None,
    section_output_validator: Any = None,
    retained_section_proof: dict[str, Any] | None = None,
    reference: dict[str, Any] | None = None,
    terminal_protocol_version: str = LEGACY_TERMINAL_PROTOCOL,
) -> Episode:
    """Build one report-building episode around the shared runtime contract."""

    store = EvidenceStore(
        twin,
        reference if reference is not None else load_reference(),
        masked_ids=masked_ids,
    )
    selected_tools = (
        allowed_tools
        if allowed_tools is not None
        else REACT_ALLOWED_TOOLS.get(
            episode_kind,
            frozenset(
                {"get_data", "calculate", "create_report", "create_section"}
            ),
        )
    )
    if (
        allowed_tools is None
        and terminal_protocol_version == SPLIT_TERMINAL_PROTOCOL
        and episode_kind == "section_update"
    ):
        selected_tools = frozenset(
            {"get_data", "calculate", "replace_section", "keep_section"}
        )
    system_prompt = (PROMPT_ROOT / system_prompt_name).read_text(encoding="utf-8")
    if "{available_tools}" in system_prompt or "{terminal_tool}" in system_prompt:
        terminal_tools = selected_tools & TERMINAL_TOOLS
        if not terminal_tools:
            raise ValueError("ReAct episodes must expose a terminal tool")
        terminal_tool = " or ".join(sorted(terminal_tools))
        available_tools = ", ".join(
            tool
            for tool in (
                "get_data",
                "calculate",
                "create_report",
                "create_section",
                "replace_section",
                "keep_section",
            )
            if tool in selected_tools
        )
        system_prompt = (
            system_prompt.replace("{available_tools}", available_tools)
            .replace("{terminal_tool}", terminal_tool)
        )
    return Episode(
        episode_id=episode_id,
        episode_kind=episode_kind,
        project_id=twin["project_id"],
        store=store,
        calculator=Calculator(store, registry=calculation_registry),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_turns=max_turns,
        turn_policy=turn_policy,
        terminal_protocol_version=terminal_protocol_version,
        allowed_tools=selected_tools,
        section_id=section_id,
        original_markdown=original_markdown,
        update_event=update_event,
        benchmark_version=benchmark_version,
        report_renderer=report_renderer,
        report_output_validator=report_output_validator,
        section_renderer=section_renderer,
        section_output_validator=section_output_validator,
        retained_section_proof=retained_section_proof,
    )


def catalogue_text() -> str:
    return compact_json(load_catalogue())
