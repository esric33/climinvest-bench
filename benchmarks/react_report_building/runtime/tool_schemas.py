from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from .episode import SPLIT_TERMINAL_PROTOCOL


TOOL_ORDER = (
    "get_data", "calculate", "create_report", "create_section",
    "replace_section", "keep_section",
)
EVIDENCE_ID_PATTERN = r"^(dt|reference|req)\.[a-z0-9_]+(\.[a-z0-9_]+)*$"
CALCULATION_ID_PATTERN = r"^calc\.[a-z0-9_]+$"
_BENCHMARK_VERSION_MAJOR = re.compile(
    r"^[vV]?(?P<major>0|[1-9][0-9]*)(?=$|[.-])"
)


def uses_compact_calculation_actions(episode: Any) -> bool:
    """Return whether an episode uses the v2 compact calculation interface."""

    version = str(getattr(episode, "benchmark_version", "")).strip()
    match = _BENCHMARK_VERSION_MAJOR.match(version)
    return match is not None and int(match.group("major")) == 2


def semantic_tool_definitions(episode: Any) -> list[dict[str, Any]]:
    """Return the provider-neutral tool surface for one benchmark episode."""

    allowed_tools = getattr(
        episode,
        "active_allowed_tools",
        getattr(episode, "allowed_tools", frozenset()),
    )
    if not allowed_tools:
        return []

    compact_calculation_actions = uses_compact_calculation_actions(episode)
    calculate_definition = (
        {
            "name": "calculate",
            "description": (
                "Execute canonical registered calculations by exact calc.* ID. "
                "Request only results needed by the output contract; the "
                "controller resolves and stores their deterministic dependency "
                "closure and returns only the requested targets. Put every "
                "independent target needed at this observation boundary in one "
                "ids array. Do not retrieve calculation dependencies first."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "ids": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "pattern": CALCULATION_ID_PATTERN,
                        },
                        "minItems": 1,
                        "description": (
                            "Complete canonical calc.* calculation IDs."
                        ),
                    }
                },
                "required": ["ids"],
                "additionalProperties": False,
            },
        }
        if compact_calculation_actions
        else {
            "name": "calculate",
            "description": (
                "Execute one or more canonical registered calculations. Copy "
                "result_id, operation_id, input_ids, and parameters exactly "
                "from the calculation catalogue. Put dependent registered "
                "calculations in canonical dependency order in one operations "
                "array. There are no alternative calculation paths."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "operations": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "result_id": {"type": "string"},
                                "operation_id": {"type": "string"},
                                "input_ids": {
                                    "type": "object",
                                    "additionalProperties": {"type": "string"},
                                },
                                "parameters": {"type": "object"},
                            },
                            "required": [
                                "result_id",
                                "operation_id",
                                "input_ids",
                                "parameters",
                            ],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["operations"],
                "additionalProperties": False,
            },
        }
    )
    definitions = {
        "get_data": {
            "name": "get_data",
            "description": (
                (
                    "Retrieve authoritative evidence nodes or collections by "
                    "exact documented dt.*, reference.*, or req.* ID. "
                    "Calculation IDs belong to calculate, never get_data. "
                )
                if compact_calculation_actions
                else (
                    "Retrieve authoritative evidence nodes or collections by "
                    "exact documented ID. "
                )
            )
            + (
                "Put every ID needed at the same observation boundary in one "
                "ids array. The returned values are the only project-specific "
                "evidence available for report claims."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "ids": {
                        "type": "array",
                        "items": (
                            {
                                "type": "string",
                                "pattern": EVIDENCE_ID_PATTERN,
                            }
                            if compact_calculation_actions
                            else {"type": "string"}
                        ),
                        "minItems": 1,
                        "description": (
                            (
                                "Exact documented dt.*, reference.*, or req.* "
                                "IDs."
                            )
                            if compact_calculation_actions
                            else "Exact documented node or collection IDs."
                        ),
                    }
                },
                "required": ["ids"],
                "additionalProperties": False,
            },
        },
        "calculate": calculate_definition,
        "create_report": {
            "name": "create_report",
            "description": (
                "Submit the complete final Markdown report and terminate the "
                "episode. Call this only after all required evidence and "
                "calculation observations have been received. It must be the "
                "only tool call in its model turn."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "markdown": {
                        "type": "string",
                        "description": "The complete report Markdown.",
                    }
                },
                "required": ["markdown"],
                "additionalProperties": False,
            },
        },
        "create_section": {
            "name": "create_section",
            "description": (
                "Submit the requested final Markdown section, or keep the "
                "original section in an update episode, and terminate this "
                "episode. Call this only after all required observations have "
                "been received. It must be the only tool call in its model turn."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "section_id": {
                        "type": "string",
                        "enum": [getattr(episode, "section_id", None)],
                        "description": "The exact requested section ID.",
                    },
                    "mode": {
                        "type": "string",
                        "enum": (
                            ["create"]
                            if getattr(episode, "episode_kind", None)
                            in {"section_create", "oracle_section"}
                            else ["keep", "replace"]
                        ),
                    },
                    "markdown": {
                        "type": "string",
                        "description": (
                            "Complete section Markdown. Required for create or "
                            "replace and omitted for keep. It must begin with "
                            "the exact level-2 (`##`) section heading specified "
                            "in the user prompt."
                        ),
                    },
                },
                "required": ["section_id", "mode"],
                "additionalProperties": False,
            },
        },
    }
    if getattr(episode, "terminal_protocol_version", None) == SPLIT_TERMINAL_PROTOCOL:
        section_properties = {
            "section_id": {
                "type": "string",
                "enum": [getattr(episode, "section_id", None)],
                "description": "The exact requested section ID.",
            },
            "markdown": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "Complete section Markdown. It must begin with the exact "
                    "level-2 (`##`) section heading specified in the user prompt."
                ),
            },
        }
        for name, purpose in (
            ("create_section", "Submit the complete newly generated section"),
            ("replace_section", "Replace the original with the complete updated section"),
            ("keep_section", "Retain the original section byte for byte"),
        ):
            properties = deepcopy(section_properties)
            if name == "keep_section":
                properties.pop("markdown")
            definitions[name] = {
                "name": name,
                "description": (
                    f"{purpose} and terminate this episode. Decide from the "
                    "task evidence after receiving all required observations. "
                    "It must be the only tool call in its model turn."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": properties,
                    "required": list(properties),
                    "additionalProperties": False,
                },
            }
    return [
        deepcopy(definitions[name])
        for name in TOOL_ORDER
        if name in allowed_tools
    ]


def openai_responses_tools(episode: Any, *, strict: bool = False) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": item["name"],
            "description": item["description"],
            "parameters": item["input_schema"],
            "strict": strict,
        }
        for item in semantic_tool_definitions(episode)
    ]


def openai_chat_tools(episode: Any) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": item["name"],
                "description": item["description"],
                "parameters": item["input_schema"],
                "strict": False,
            },
        }
        for item in semantic_tool_definitions(episode)
    ]


def anthropic_tools(episode: Any) -> list[dict[str, Any]]:
    return [
        {
            "name": item["name"],
            "description": item["description"],
            "input_schema": item["input_schema"],
            "strict": False,
        }
        for item in semantic_tool_definitions(episode)
    ]
