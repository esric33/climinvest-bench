"""Structured action-output contracts for Responses-compatible providers.

The primary v2 treatment constrains the provider/action wire boundary and the
declared tool-to-ID namespace routing.  Catalogue membership, relevance,
calculation selection, and report prose remain model decisions.  Nemotron Nano
v2 needs a second wire form because its pinned chat template opens a reasoning
block in the prompt and the generated continuation closes that block before
emitting the action.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from jsonschema import Draft202012Validator

from .episode import TERMINAL_TOOLS
from .tool_schemas import (
    CALCULATION_ID_PATTERN,
    EVIDENCE_ID_PATTERN,
    semantic_tool_definitions,
    uses_compact_calculation_actions,
)


ACTION_JSON_SCHEMA = "action_json_schema"
HARMONY_REASONING_ACTION_JSON = "harmony_reasoning_action_json"
REASONING_THEN_ACTION_JSON = "reasoning_then_action_json"
ACTION_OUTPUT_CONTRACTS = frozenset(
    {
        ACTION_JSON_SCHEMA,
        HARMONY_REASONING_ACTION_JSON,
        REASONING_THEN_ACTION_JSON,
    }
)
ACTION_JSON_SCHEMA_VERSION = "react_report.action_json_schema/v3"
HARMONY_ACTION_OUTPUT_TOOL_NAME = "action_output"
REASONING_CLOSE_TAG = "</think>"

_HARMONY_FUNCTION_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_WS = r"[ \t\r\n]*"
_JSON_STRING = (
    r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"'
)
_EVIDENCE_ID_JSON_STRING = (
    r'"(?:dt|reference|req)\.[a-z0-9_]+(?:\.[a-z0-9_]+)*"'
)
_CALCULATION_ID_JSON_STRING = r'"calc\.[a-z0-9_]+"'
# A regular language for arbitrary generated reasoning that cannot consume the
# first complete ``</think>`` delimiter.  Avoiding ``.*`` is important: an
# ambiguous catch-all prefix would leave every token legal after the delimiter
# and therefore would not actually constrain the JSON suffix token by token.
_REASONING_WITHOUT_CLOSE_TAG = (
    r"(?:[^<]|<[^/]|</[^t]|</t[^h]|</th[^i]|</thi[^n]|</thin[^k]|</think[^>])*"
    r"(?:<|</|</t|</th|</thi|</thin|</think)?"
)


@dataclass(frozen=True, slots=True)
class ReasoningAction:
    reasoning: str
    action: str


def action_json_schema(episode: Any) -> dict[str, Any]:
    """Return the strict, provider-neutral JSON action schema for one turn."""

    nonterminal: list[dict[str, Any]] = []
    terminal: list[dict[str, Any]] = []
    for definition in semantic_tool_definitions(episode):
        name = str(definition["name"])
        call_schema = _call_schema(
            name,
            deepcopy(definition["input_schema"]),
        )
        (terminal if name in TERMINAL_TOOLS else nonterminal).append(
            call_schema
        )

    array_variants: list[dict[str, Any]] = []
    if nonterminal:
        array_variants.append(
            {
                "type": "array",
                "minItems": 1,
                "items": {"anyOf": nonterminal},
            }
        )
    if terminal:
        array_variants.append(
            {
                "type": "array",
                "minItems": 1,
                "maxItems": 1,
                "items": {"anyOf": terminal},
            }
        )
    if not array_variants:
        raise ValueError("structured action output requires at least one tool")

    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["tool_calls"]},
            "calls": {"anyOf": array_variants},
        },
        "required": ["action", "calls"],
        "additionalProperties": False,
    }


def harmony_reasoning_json_structural_tag(
    json_schema: dict[str, Any],
    *,
    tool_name: str = HARMONY_ACTION_OUTPUT_TOOL_NAME,
) -> dict[str, Any]:
    """Return a strict reasoning-then-function Harmony continuation.

    GPT-OSS starts generation immediately after an already-rendered
    ``<|start|>assistant`` token.  This XGrammar structural tag therefore
    admits one unrestricted native analysis message, followed by exactly one
    JSON-schema-constrained function call.  The channel-first header and the
    space before ``<|constrain|>`` are the canonical generated-continuation
    form documented by OpenAI's Harmony format.

    The returned object is intended to be serialized as the value of vLLM's
    ``structured_outputs.structural_tag`` extension.  It describes the model
    wire only; extracting the ordinary Responses ``function_call.arguments``
    carrier remains the provider adapter's responsibility.
    """

    name = str(tool_name)
    if _HARMONY_FUNCTION_NAME.fullmatch(name) is None:
        raise ValueError(
            "Harmony function name must contain 1-64 letters, digits, '-' or '_'"
        )
    schema = deepcopy(json_schema)
    Draft202012Validator.check_schema(schema)
    return {
        "type": "structural_tag",
        "format": {
            "type": "sequence",
            "elements": [
                {
                    "type": "tag",
                    "begin": "<|channel|>analysis<|message|>",
                    "content": {
                        "type": "any_text",
                        "excludes": ["<|return|>", "<|call|>"],
                    },
                    "end": "<|end|>",
                },
                {
                    "type": "const_string",
                    "value": "<|start|>assistant",
                },
                {
                    "type": "tag",
                    "begin": (
                        "<|channel|>commentary "
                        f"to=functions.{name} <|constrain|>json<|message|>"
                    ),
                    "content": {
                        "type": "json_schema",
                        "json_schema": schema,
                    },
                    "end": "<|call|>",
                },
            ],
        },
    }


def harmony_reasoning_action_structural_tag(episode: Any) -> dict[str, Any]:
    """Return the strict GPT-OSS Harmony wire for one controller turn."""

    return harmony_reasoning_json_structural_tag(action_json_schema(episode))


def harmony_action_output_tool(episode: Any) -> dict[str, Any]:
    """Return the sole synthetic Responses tool used by the Harmony wire."""

    return {
        "type": "function",
        "name": HARMONY_ACTION_OUTPUT_TOOL_NAME,
        "description": (
            "Submit exactly one complete controller action JSON envelope."
        ),
        "parameters": action_json_schema(episode),
        "strict": True,
    }


def is_gpt_oss_model(model: str) -> bool:
    """Return whether a model identifier names the GPT-OSS family."""

    leaf = str(model or "").strip().casefold().rsplit("/", 1)[-1]
    return leaf == "gpt-oss" or leaf.startswith("gpt-oss-")


def action_json_regex(episode: Any) -> str:
    """Return an Outlines-compatible regex for the same action language.

    The regex fixes object-key order to keep the DFA compact.  JSON object key
    order is semantically irrelevant, and every admitted output also validates
    against :func:`action_json_schema`.
    """

    definitions = {
        str(item["name"]): item for item in semantic_tool_definitions(episode)
    }
    nonterminal = [
        _tool_call_regex(name, definitions[name], episode)
        for name in ("get_data", "calculate")
        if name in definitions
    ]
    terminal = [
        _tool_call_regex(name, definitions[name], episode)
        for name in sorted(TERMINAL_TOOLS)
        if name in definitions
    ]
    call_arrays: list[str] = []
    if nonterminal:
        item = _alternation(nonterminal)
        call_arrays.append(r"\[" + item + r"(?:" + _WS + r"," + _WS + item + r")*\]")
    if terminal:
        call_arrays.append(r"\[" + _alternation(terminal) + r"\]")
    if not call_arrays:
        raise ValueError("structured action output requires at least one tool")

    return (
        r"\{"
        + _WS
        + _literal_json_string("action")
        + _WS
        + ":"
        + _WS
        + _literal_json_string("tool_calls")
        + _WS
        + ","
        + _WS
        + _literal_json_string("calls")
        + _WS
        + ":"
        + _WS
        + _alternation(call_arrays)
        + _WS
        + r"\}"
    )


def reasoning_then_action_regex(episode: Any) -> str:
    """Constrain a native reasoning continuation followed by one JSON action."""

    return (
        _REASONING_WITHOUT_CLOSE_TAG
        + re.escape(REASONING_CLOSE_TAG)
        + _WS
        + action_json_regex(episode)
    )


def reasoning_then_json_regex(json_regex: str) -> str:
    """Prefix a caller-supplied JSON regex with the Nemotron reasoning frame."""

    if not isinstance(json_regex, str) or not json_regex:
        raise ValueError("json_regex must be a non-empty string")
    return (
        _REASONING_WITHOUT_CLOSE_TAG
        + re.escape(REASONING_CLOSE_TAG)
        + _WS
        + json_regex
    )


def split_reasoning_action(text: str) -> ReasoningAction:
    """Split the configured reasoning wire form without repairing its JSON.

    The first generated close tag is the reasoning boundary.  The grammar
    prevents that delimiter from appearing in the reasoning prefix, while the
    JSON suffix may legitimately contain the same character sequence inside a
    string (for example in authored Markdown).  The opening tag is absent from
    the response body because Nemotron's chat template placed it at the end of
    the prompt.  JSON syntax, full-document consumption, and action semantics
    are deliberately left to the ordinary protocol parser.
    """

    raw = str(text or "")
    if REASONING_CLOSE_TAG not in raw:
        raise ValueError(
            "reasoning-prefixed action requires a </think> boundary"
        )
    reasoning, _, action = raw.partition(REASONING_CLOSE_TAG)
    # The regex explicitly admits only JSON whitespace between the reasoning
    # delimiter and the opening object.  Remove that separator, but preserve
    # the suffix's trailing bytes so verification cannot silently repair an
    # output that the decoder grammar would reject.
    action = action.lstrip(" \t\r\n")
    if not action:
        raise ValueError("reasoning-prefixed action is missing its JSON suffix")
    if not action.startswith("{"):
        raise ValueError("reasoning-prefixed action suffix must begin with JSON")
    if not action.endswith("}"):
        raise ValueError("reasoning-prefixed action suffix must end with JSON")
    return ReasoningAction(reasoning=reasoning, action=action)


def validate_action_json(text: str, episode: Any) -> dict[str, Any]:
    """Decode one complete JSON document and validate the exact turn contract.

    This is a verifier for the constrained-decoding boundary, not a repair
    path.  It never searches for JSON, drops a suffix, removes a fence, or
    changes model output.
    """

    try:
        value = json.loads(str(text or ""))
    except json.JSONDecodeError as exc:
        raise ValueError(
            "structured action output is not one complete JSON document"
        ) from exc
    schema = action_json_schema(episode)
    validator = Draft202012Validator(schema)
    error = next(iter(validator.iter_errors(value)), None)
    if error is not None:
        location = "$"
        for part in error.absolute_path:
            location += f"[{part}]" if isinstance(part, int) else f".{part}"
        raise ValueError(
            "structured action output violates the action contract at "
            f"{location} (validator={error.validator})"
        ) from error
    if not isinstance(value, dict):  # Kept explicit for the return type.
        raise ValueError("structured action output must be a JSON object")
    # JSON Schema patterns use ECMA-262's ``$`` semantics, which permit a
    # match immediately before one final newline.  XGrammar and the hand-built
    # Nemotron regex both consume to the real end of the ID instead.  Apply the
    # same true-full-match verifier to decoded v2 IDs so every transport has
    # identical controller acceptance without adding ``not`` (unsupported by
    # OpenAI strict Structured Outputs) or ``\Z`` (unsupported by XGrammar).
    if uses_compact_calculation_actions(episode):
        _validate_compact_id_namespaces(value)
    return value


def _validate_compact_id_namespaces(value: dict[str, Any]) -> None:
    patterns = {
        "get_data": EVIDENCE_ID_PATTERN,
        "calculate": CALCULATION_ID_PATTERN,
    }
    for call_index, call in enumerate(value.get("calls") or []):
        tool = call.get("tool")
        pattern = patterns.get(tool)
        if pattern is None:
            continue
        for id_index, identifier in enumerate(
            call.get("arguments", {}).get("ids") or []
        ):
            if re.fullmatch(pattern, identifier) is None:
                raise ValueError(
                    "structured action output violates the action contract at "
                    f"$.calls[{call_index}].arguments.ids[{id_index}] "
                    "(validator=true_fullmatch)"
                )


def reasoning_boundary_event(
    parsed: ReasoningAction,
    *,
    output_index: int,
) -> dict[str, Any]:
    """Return content-free audit metadata for one deliberate boundary split."""

    return {
        "schema_version": "react_report.reasoning_boundary/v1",
        "kind": "reasoning_prefixed_textual_action",
        "output_index": int(output_index),
        "delimiter": REASONING_CLOSE_TAG,
        "reasoning_characters": len(parsed.reasoning),
        "reasoning_sha256": sha256(parsed.reasoning.encode("utf-8")).hexdigest(),
        "action_characters": len(parsed.action),
        "generated_open_tag_present": "<think>" in parsed.reasoning,
        "raw_response_preserved": True,
    }


def exact_marker_json_regex(marker: str) -> str:
    """Return a compact exact-object regex used by the provider doctor."""

    return (
        r"\{"
        + _WS
        + _literal_json_string("marker")
        + _WS
        + ":"
        + _WS
        + _literal_json_string(marker)
        + _WS
        + r"\}"
    )


def _call_schema(name: str, input_schema: dict[str, Any]) -> dict[str, Any]:
    argument_variants = (
        _create_section_argument_variants(input_schema)
        if name == "create_section" and "mode" in input_schema.get("properties", {})
        else [_without_annotations(input_schema)]
    )
    arguments: dict[str, Any]
    if len(argument_variants) == 1:
        arguments = argument_variants[0]
    else:
        arguments = {"anyOf": argument_variants}
    return {
        "type": "object",
        "properties": {
            "tool": {"type": "string", "enum": [name]},
            "arguments": arguments,
        },
        "required": ["tool", "arguments"],
        "additionalProperties": False,
    }


def _create_section_argument_variants(
    input_schema: dict[str, Any],
) -> list[dict[str, Any]]:
    properties = input_schema.get("properties") or {}
    section_schema = _without_annotations(properties.get("section_id") or {})
    mode_schema = properties.get("mode") or {}
    modes = [str(item) for item in mode_schema.get("enum") or ()]
    variants: list[dict[str, Any]] = []
    for mode in modes:
        variant_properties: dict[str, Any] = {
            "section_id": deepcopy(section_schema),
            "mode": {"type": "string", "enum": [mode]},
        }
        required = ["section_id", "mode"]
        if mode != "keep":
            variant_properties["markdown"] = {"type": "string"}
            required.append("markdown")
        variants.append(
            {
                "type": "object",
                "properties": variant_properties,
                "required": required,
                "additionalProperties": False,
            }
        )
    if not variants:
        raise ValueError("create_section schema has no supported modes")
    return variants


def _without_annotations(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_annotations(item)
            for key, item in value.items()
            if key not in {"description", "title", "default", "examples"}
        }
    if isinstance(value, list):
        return [_without_annotations(item) for item in value]
    return deepcopy(value)


def _tool_call_regex(name: str, definition: dict[str, Any], episode: Any) -> str:
    if name in {"get_data", "calculate"}:
        properties = definition["input_schema"].get("properties") or {}
        if "ids" not in properties:
            raise ValueError(f"{name} is not the compact v2 IDs interface")
        item_regex = (
            _CALCULATION_ID_JSON_STRING
            if name == "calculate"
            else _EVIDENCE_ID_JSON_STRING
        )
        arguments = _ids_arguments_regex(item_regex)
    elif name == "create_report":
        arguments = _object_regex([("markdown", _JSON_STRING)])
    elif name in {"create_section", "replace_section", "keep_section"} and "mode" not in definition["input_schema"].get("properties", {}):
        fields = [("section_id", _literal_json_string(str(getattr(episode, "section_id", ""))))]
        if name != "keep_section":
            fields.append(("markdown", _JSON_STRING))
        arguments = _object_regex(fields)
    elif name == "create_section":
        section_id = str(getattr(episode, "section_id", ""))
        modes = (
            definition["input_schema"].get("properties", {}).get("mode", {}).get("enum", [])
        )
        variants: list[str] = []
        for raw_mode in modes:
            mode = str(raw_mode)
            fields = [
                ("section_id", _literal_json_string(section_id)),
                ("mode", _literal_json_string(mode)),
            ]
            if mode != "keep":
                fields.append(("markdown", _JSON_STRING))
            variants.append(_object_regex(fields))
        arguments = _alternation(variants)
    else:
        raise ValueError(f"unsupported structured action tool {name!r}")
    return _object_regex(
        [
            ("tool", _literal_json_string(name)),
            ("arguments", arguments),
        ]
    )


def _ids_arguments_regex(item_regex: str) -> str:
    ids = (
        r"\["
        + _WS
        + item_regex
        + r"(?:"
        + _WS
        + r","
        + _WS
        + item_regex
        + r")*"
        + _WS
        + r"\]"
    )
    return _object_regex([("ids", ids)])


def _object_regex(fields: list[tuple[str, str]]) -> str:
    if not fields:
        return r"\{" + _WS + r"\}"
    encoded = []
    for name, value in fields:
        encoded.append(
            _literal_json_string(name) + _WS + ":" + _WS + value
        )
    return r"\{" + _WS + (_WS + "," + _WS).join(encoded) + _WS + r"\}"


def _literal_json_string(value: str) -> str:
    return re.escape(json.dumps(str(value), ensure_ascii=False))


def _alternation(values: list[str]) -> str:
    if not values:
        raise ValueError("structured output alternation cannot be empty")
    if len(values) == 1:
        return values[0]
    return "(?:" + "|".join(values) + ")"


__all__ = [
    "ACTION_JSON_SCHEMA",
    "ACTION_JSON_SCHEMA_VERSION",
    "ACTION_OUTPUT_CONTRACTS",
    "HARMONY_ACTION_OUTPUT_TOOL_NAME",
    "HARMONY_REASONING_ACTION_JSON",
    "REASONING_CLOSE_TAG",
    "REASONING_THEN_ACTION_JSON",
    "ReasoningAction",
    "action_json_regex",
    "action_json_schema",
    "exact_marker_json_regex",
    "harmony_action_output_tool",
    "harmony_reasoning_action_structural_tag",
    "harmony_reasoning_json_structural_tag",
    "is_gpt_oss_model",
    "reasoning_boundary_event",
    "reasoning_then_action_regex",
    "reasoning_then_json_regex",
    "split_reasoning_action",
    "validate_action_json",
]
