from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


TOOL_MARKDOWN_BEGIN_MARKER = "<<<BEGIN_TOOL_MARKDOWN>>>"
TOOL_MARKDOWN_END_MARKER = "<<<END_TOOL_MARKDOWN>>>"
RAW_MARKDOWN_TERMINAL_TOOLS = frozenset({"create_report", "create_section", "replace_section"})


@dataclass(frozen=True)
class ParsedTurn:
    calls: list[dict[str, Any]]
    raw: str
    envelopes: list[dict[str, Any]]


def parse_textual_tool_turn(text: str) -> ParsedTurn:
    """Parse one ordered, open-loop textual action batch.

    A provider response may contain one or more top-level JSON action
    envelopes.  Every envelope is validated before any calls are returned so
    malformed batches remain atomic.  Calls are flattened in emitted envelope
    and array order; the controller supplies the single observation boundary
    after the complete batch has executed.
    """

    raw = str(text or "")
    try:
        # Try the established JSON-only protocol first so a marker-shaped
        # string inside a valid legacy ``arguments.markdown`` value remains
        # ordinary document content.
        return _parse_json_action_batch(raw)
    except ValueError as json_error:
        if (
            TOOL_MARKDOWN_BEGIN_MARKER in raw
            or TOOL_MARKDOWN_END_MARKER in raw
        ):
            return _parse_terminal_markdown_turn(raw)
        try:
            return _parse_terminal_remainder_turn(raw)
        except ValueError:
            raise json_error


def _parse_json_action_batch(raw: str) -> ParsedTurn:
    """Parse a batch made exclusively from top-level JSON envelopes."""

    decoder = json.JSONDecoder()
    cursor = 0
    envelopes: list[dict[str, Any]] = []
    flattened_calls: list[dict[str, Any]] = []
    while True:
        while cursor < len(raw) and raw[cursor].isspace():
            cursor += 1
        if cursor >= len(raw):
            break
        envelope_start = cursor
        try:
            value, cursor = decoder.raw_decode(raw, cursor)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "assistant action batch is invalid JSON at envelope "
                f"{len(envelopes)}: {exc.msg}"
            ) from exc
        envelope_index = len(envelopes)
        if not isinstance(value, dict) or value.get("action") != "tool_calls":
            raise ValueError(
                f"action envelope {envelope_index} must always be "
                "'tool_calls'; put get_data, calculate, create_report, or "
                "create_section in calls[].tool"
            )
        calls = value.get("calls")
        if not isinstance(calls, list) or not calls:
            raise ValueError(
                f"action envelope {envelope_index} tool_calls requires a "
                "non-empty calls array"
            )
        normalized_calls: list[dict[str, Any]] = []
        for call_index, call in enumerate(calls):
            if not isinstance(call, dict):
                raise ValueError(
                    f"action envelope {envelope_index} calls[{call_index}] "
                    "must be an object"
                )
            tool = str(call.get("tool") or "").strip()
            arguments = call.get("arguments")
            if not tool or not isinstance(arguments, dict):
                raise ValueError(
                    f"action envelope {envelope_index} calls[{call_index}] "
                    "requires tool and object arguments"
                )
            normalized_calls.append({"tool": tool, "arguments": arguments})
        envelopes.append(
            {
                "envelope_index": envelope_index,
                "raw": raw[envelope_start:cursor],
                "action": "tool_calls",
                "calls": normalized_calls,
            }
        )
        flattened_calls.extend(normalized_calls)
    if not envelopes:
        raise ValueError(
            "assistant response must contain one or more JSON action objects"
        )
    return ParsedTurn(
        calls=flattened_calls,
        raw=raw,
        envelopes=envelopes,
    )


def _parse_terminal_markdown_turn(raw: str) -> ParsedTurn:
    """Parse one terminal call followed by an unescaped Markdown block.

    The JSON header deliberately omits ``arguments.markdown``.  Keeping the
    potentially long document body outside JSON avoids failures caused by
    unescaped quotes, newlines, and backslashes while retaining the existing
    ``create_report`` and ``create_section`` call schemas after parsing.
    """

    if raw.count(TOOL_MARKDOWN_BEGIN_MARKER) != 1:
        raise ValueError(
            "terminal Markdown frame requires exactly one begin marker"
        )
    if raw.count(TOOL_MARKDOWN_END_MARKER) != 1:
        raise ValueError(
            "terminal Markdown frame requires exactly one end marker"
        )
    begin_matches = list(
        re.finditer(
            rf"(?m)^{re.escape(TOOL_MARKDOWN_BEGIN_MARKER)}\r?$",
            raw,
        )
    )
    end_matches = list(
        re.finditer(
            rf"(?m)^{re.escape(TOOL_MARKDOWN_END_MARKER)}\r?$",
            raw,
        )
    )
    if len(begin_matches) != 1 or len(end_matches) != 1:
        raise ValueError(
            "terminal Markdown frame markers must each appear on an exact line"
        )
    begin = begin_matches[0]
    end = end_matches[0]
    if end.start() <= begin.end():
        raise ValueError(
            "terminal Markdown frame end marker must follow its begin marker"
        )
    if raw[end.end() :].strip():
        raise ValueError(
            "terminal Markdown frame end marker must be the final content"
        )

    header = _parse_json_action_batch(raw[: begin.start()])
    body_start = begin.end()
    if raw.startswith("\n", body_start):
        body_start += 1
    markdown = raw[body_start : end.start()]
    if markdown.endswith("\r\n"):
        markdown = markdown[:-2]
    elif markdown.endswith("\n"):
        markdown = markdown[:-1]
    framed_raw = (
        f"{header.envelopes[0]['raw']}\n"
        f"{raw[begin.start() : end.end()]}"
    )
    return _terminal_parsed_turn(
        header,
        markdown=markdown,
        raw=raw,
        framed_raw=framed_raw,
    )


def _parse_terminal_remainder_turn(raw: str) -> ParsedTurn:
    """Parse a one-line terminal header followed by response-bound Markdown."""

    line_end = raw.find("\n")
    if line_end < 0:
        raise ValueError("terminal remainder frame requires a header line")
    header_raw = raw[:line_end].rstrip("\r")
    markdown = raw[line_end + 1 :]
    # A visually clearer blank line after the JSON header is recommended but
    # optional.  The provider response boundary itself terminates Markdown, so
    # no fragile end sentinel is required.
    if markdown.startswith("\r\n"):
        markdown = markdown[2:]
    elif markdown.startswith("\n"):
        markdown = markdown[1:]
    if not markdown.strip():
        raise ValueError("terminal remainder frame requires Markdown content")
    header = _parse_json_action_batch(header_raw)
    return _terminal_parsed_turn(
        header,
        markdown=markdown,
        raw=raw,
        framed_raw=raw,
    )


def _terminal_parsed_turn(
    header: ParsedTurn,
    *,
    markdown: str,
    raw: str,
    framed_raw: str,
) -> ParsedTurn:
    """Validate a terminal header and attach its out-of-JSON Markdown."""

    if len(header.envelopes) != 1 or len(header.calls) != 1:
        raise ValueError(
            "terminal Markdown frame requires exactly one action envelope "
            "containing exactly one call"
        )
    call = header.calls[0]
    if call["tool"] not in RAW_MARKDOWN_TERMINAL_TOOLS:
        raise ValueError(
            "terminal Markdown frame is only valid for create_report or "
            "create_section"
        )
    arguments = call["arguments"]
    if "markdown" in arguments:
        raise ValueError(
            "terminal Markdown frame JSON header must omit arguments.markdown"
        )

    framed_call = {
        "tool": call["tool"],
        "arguments": {**arguments, "markdown": markdown},
    }
    json_raw = header.envelopes[0]["raw"]
    framed_envelope = {
        **header.envelopes[0],
        "raw": framed_raw,
        "json_raw": json_raw,
        "calls": [framed_call],
        "terminal_markdown_frame": True,
    }
    return ParsedTurn(
        calls=[framed_call],
        raw=raw,
        envelopes=[framed_envelope],
    )


def render_tool_observations(results: list[dict[str, Any]]) -> str:
    return json.dumps(
        {"role": "tool_observations", "results": results},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
