from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .calculator import Calculator
from .evidence_store import EvidenceStore


UNRESTRICTED_TURNS = "unrestricted"
RESERVE_FINAL_TURN = "reserve_final_turn"
TURN_POLICIES = frozenset({UNRESTRICTED_TURNS, RESERVE_FINAL_TURN})
LEGACY_TERMINAL_PROTOCOL = "react_report.terminal_protocol/v1"
SPLIT_TERMINAL_PROTOCOL = "react_report.terminal_protocol/v2"
TERMINAL_PROTOCOLS = frozenset({LEGACY_TERMINAL_PROTOCOL, SPLIT_TERMINAL_PROTOCOL})
TERMINAL_TOOLS = frozenset(
    {"create_report", "create_section", "replace_section", "keep_section"}
)


@dataclass
class Episode:
    episode_id: str
    episode_kind: str
    project_id: str
    store: EvidenceStore
    calculator: Calculator
    messages: list[dict[str, str]]
    max_turns: int
    allowed_tools: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {"get_data", "calculate", "create_report", "create_section"}
        )
    )
    section_id: str | None = None
    original_markdown: str | None = None
    update_event: dict[str, Any] | None = None
    benchmark_version: str = "v1"
    report_renderer: Callable[[EvidenceStore], str] | None = None
    report_output_validator: (
        Callable[[str, EvidenceStore], dict[str, Any]] | None
    ) = None
    section_renderer: Callable[[str, EvidenceStore], str] | None = None
    section_output_validator: (
        Callable[[str, EvidenceStore], dict[str, Any]] | None
    ) = None
    retained_section_proof: dict[str, Any] | None = None
    turns: list[dict[str, Any]] = field(default_factory=list)
    terminal: dict[str, Any] | None = None
    turn_policy: str = UNRESTRICTED_TURNS
    terminal_protocol_version: str = LEGACY_TERMINAL_PROTOCOL

    def __post_init__(self) -> None:
        if self.terminal_protocol_version not in TERMINAL_PROTOCOLS:
            raise ValueError("unsupported terminal protocol version")
        if self.terminal_protocol_version == SPLIT_TERMINAL_PROTOCOL:
            expected = {
                "report_create": {"create_report"},
                "report_update": {"create_report"},
                "oracle_report": {"create_report"},
                "section_create": {"create_section"},
                "oracle_section": {"create_section"},
                "section_update": {"keep_section", "replace_section"},
            }.get(self.episode_kind)
            if expected is not None and self.allowed_tools & TERMINAL_TOOLS != expected:
                raise ValueError("split terminal palette must match the episode kind")
        if self.turn_policy not in TURN_POLICIES:
            raise ValueError(f"unsupported turn policy {self.turn_policy!r}")
        if self.turn_policy == RESERVE_FINAL_TURN and self.max_turns < 2:
            raise ValueError(
                "reserve_final_turn requires at least two provider turns"
            )
        if self.turn_policy == RESERVE_FINAL_TURN:
            terminal = self.allowed_tools & TERMINAL_TOOLS
            valid_update_choice = (
                self.terminal_protocol_version == SPLIT_TERMINAL_PROTOCOL
                and self.episode_kind == "section_update"
                and terminal == {"replace_section", "keep_section"}
            )
            if len(terminal) != 1 and not valid_update_choice:
                raise ValueError(
                    "reserve_final_turn requires one terminal tool or the "
                    "split section-update keep/replace choice"
                )

    @property
    def turn_phase(self) -> str:
        if self.turn_policy != RESERVE_FINAL_TURN:
            return UNRESTRICTED_TURNS
        return (
            "finalization"
            if len(self.turns) == self.max_turns - 1
            else "ordinary"
        )

    @property
    def active_allowed_tools(self) -> frozenset[str]:
        """Return the semantic tools available on the next provider call."""

        if self.turn_policy != RESERVE_FINAL_TURN:
            return self.allowed_tools
        if self.turn_phase == "finalization":
            return self.allowed_tools & TERMINAL_TOOLS
        return self.allowed_tools

    @property
    def terminal_tool(self) -> str | None:
        tools = self.allowed_tools & TERMINAL_TOOLS
        return next(iter(tools)) if len(tools) == 1 else None

    @property
    def terminal_action_description(self) -> str:
        return " or ".join(sorted(self.allowed_tools & TERMINAL_TOOLS))

    def turn_instruction(self) -> str | None:
        """Describe the configured phase without suppressing model reasoning."""

        if self.turn_policy != RESERVE_FINAL_TURN:
            return None
        turn_number = len(self.turns) + 1
        if self.turn_phase == "finalization":
            return (
                f"FINALIZATION TURN (turn {turn_number} of {self.max_turns}). "
                "This is the final provider call. Continue your ordinary "
                "reasoning before choosing the action; reasoning is not "
                "disabled or shortened. You must now submit exactly one "
                f"{self.terminal_action_description} call. Choose the action "
                "yourself using the task evidence. Do not retrieve evidence or request a "
                "calculation. No observation or repair turn follows."
            )
        return (
            f"ORDINARY TURN (ordinary turn {turn_number} of "
            f"{self.max_turns - 1}; at most {self.max_turns} provider calls "
            "total). "
            "The ordinary full tool palette is available. You may finish now "
            f"with exactly one {self.terminal_action_description} call if the output is ready. "
            f"If the episode remains unfinished after {self.max_turns - 1} "
            "ordinary turns, the final provider call will offer only the "
            "terminal action."
        )
