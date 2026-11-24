from __future__ import annotations

import re
from typing import Any


SECTION_IDS = {
    "Project overview": "project_overview",
    "Scale and calculated indicators": "scale_and_calculated_indicators",
    "Selected performance indicators": "selected_performance_indicators",
    "Priority risks": "priority_risks",
    "Overall evidence summary": "overall_evidence_summary",
}

_LINK_PATTERN = re.compile(r"\[([^\]\n]+)\]\(([^)\n]+)\)")
_SECTION_PATTERN = re.compile(r"^##\s+(.+?)(?:\s+\{#[^}]+\})?\s*$")
_SUBSECTION_PATTERN = re.compile(r"^###\s+(.+?)(?:\s+\{#[^}]+\})?\s*$")
_ALIGNMENT_PATTERN = re.compile(r"^:?-{3,}:?$")


def _utf16_length(value: str) -> int:
    """Return JavaScript String.length for *value*."""

    return len(value.encode("utf-16-le")) // 2


def _links(text: str) -> list[dict[str, Any]]:
    return [
        {
            "text": match.group(1),
            "target": match.group(2),
            "start": _utf16_length(text[: match.start()]),
        }
        for match in _LINK_PATTERN.finditer(text)
    ]


def _markdown_table_cells(raw_line: str) -> list[str] | None:
    line = str(raw_line or "").strip()
    if "|" not in line:
        return None
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]

    cells: list[str] = []
    current: list[str] = []
    in_code = False
    index = 0
    while index < len(line):
        character = line[index]
        if character == "\\" and index + 1 < len(line) and line[index + 1] == "|":
            current.append("|")
            index += 2
            continue
        if character == "`":
            in_code = not in_code
        if character == "|" and not in_code:
            cells.append("".join(current).strip())
            current = []
            index += 1
            continue
        current.append(character)
        index += 1

    cells.append("".join(current).strip())
    return cells if len(cells) > 1 else None


def _markdown_table_alignment(marker: str) -> str:
    value = str(marker or "").strip()
    if not _ALIGNMENT_PATTERN.fullmatch(value):
        return ""
    if value.startswith(":") and value.endswith(":"):
        return "center"
    if value.endswith(":"):
        return "right"
    return "left"


def _parse_markdown_table_at(
    lines: list[str], start_index: int
) -> dict[str, Any] | None:
    if start_index + 1 >= len(lines):
        return None

    headers = _markdown_table_cells(lines[start_index])
    markers = _markdown_table_cells(lines[start_index + 1])
    if headers is None or markers is None or len(headers) != len(markers):
        return None

    alignments = [_markdown_table_alignment(marker) for marker in markers]
    if any(not alignment for alignment in alignments):
        return None

    rows: list[list[str]] = []
    end_index = start_index + 2
    while end_index < len(lines):
        cells = _markdown_table_cells(lines[end_index])
        if cells is None:
            break
        rows.append(
            [
                cells[index] if index < len(cells) and cells[index] else ""
                for index in range(len(headers))
            ]
        )
        end_index += 1

    return {
        "headers": headers,
        "alignments": alignments,
        "rows": rows,
        "end_index": end_index,
    }


def _slug(heading: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", heading.lower())
    return value.strip("_")


def parse_markdown(markdown: str) -> dict[str, Any]:
    """Parse benchmark Markdown without requiring a Node.js runtime.

    The returned structure intentionally mirrors ``parse_markdown.js``. CI keeps
    the JavaScript implementation as an independent parity oracle.
    """

    source = str(markdown or "")
    lines = re.split(r"\r?\n", source)
    title: str | None = None
    sections: list[dict[str, Any]] = []

    for line in lines:
        if re.match(r"^#\s+", line):
            title = re.sub(r"^#\s+", "", line, count=1).strip()
            break

    cursor = 0
    while cursor < len(lines):
        section_match = _SECTION_PATTERN.match(lines[cursor])
        if section_match is None:
            cursor += 1
            continue

        heading = section_match.group(1).strip()
        end_index = cursor + 1
        while end_index < len(lines) and not re.match(r"^##\s+", lines[end_index]):
            end_index += 1

        body_lines = lines[cursor + 1 : end_index]
        section: dict[str, Any] = {
            "id": SECTION_IDS.get(heading, _slug(heading)),
            "heading": heading,
            "start_line": cursor + 1,
            "end_line": end_index,
            "headings": [],
            "tables": [],
            "paragraphs": [],
            "blocks": [],
            "links": _links("\n".join(body_lines)),
        }

        paragraph_lines: list[str] = []

        def flush_paragraph() -> None:
            if not paragraph_lines:
                return
            text = "\n".join(paragraph_lines).strip()
            paragraph_lines.clear()
            if not text:
                return
            paragraph = {"text": text, "links": _links(text)}
            section["paragraphs"].append(paragraph)
            section["blocks"].append(
                {
                    "kind": "prose",
                    "index": len(section["paragraphs"]) - 1,
                }
            )

        inner = 0
        while inner < len(body_lines):
            line = body_lines[inner]
            subsection_match = _SUBSECTION_PATTERN.match(line)
            if subsection_match is not None:
                flush_paragraph()
                subsection = subsection_match.group(1).strip()
                section["headings"].append(
                    {"level": 3, "text": subsection, "line": cursor + inner + 2}
                )
                section["blocks"].append(
                    {
                        "kind": "subsection",
                        "index": len(section["headings"]) - 1,
                        "heading": subsection,
                    }
                )
                inner += 1
                continue

            table = _parse_markdown_table_at(body_lines, inner)
            if table is not None:
                flush_paragraph()
                raw = "\n".join(body_lines[inner : table["end_index"]])
                table_index = len(section["tables"])
                section["tables"].append(
                    {
                        "index": table_index,
                        "headers": table["headers"],
                        "alignments": table["alignments"],
                        "rows": table["rows"],
                        "links": _links(raw),
                        "raw": raw,
                    }
                )
                section["blocks"].append({"kind": "table", "index": table_index})
                inner = table["end_index"]
                continue

            if not line.strip():
                flush_paragraph()
            else:
                paragraph_lines.append(line)
            inner += 1

        flush_paragraph()
        sections.append(section)
        cursor = end_index

    return {
        "title": title,
        "sections": sections,
        "links": _links(source),
        "markdown_length": _utf16_length(source),
    }


def section_map(tree: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {section["id"]: section for section in tree["sections"]}
