from __future__ import annotations

from typing import Any


def validate(arguments: dict[str, Any], max_chars: int = 200_000) -> dict[str, Any]:
    markdown = arguments.get("markdown")
    if not isinstance(markdown, str) or not markdown.strip():
        return {
            "tool": "create_report",
            "status": "invalid_arguments",
            "message": "markdown must be a non-empty string",
        }
    if len(markdown) > max_chars:
        return {
            "tool": "create_report",
            "status": "invalid_arguments",
            "message": f"markdown exceeds {max_chars} characters",
        }
    return {
        "tool": "create_report",
        "status": "accepted",
        "terminal": True,
        "markdown": markdown,
    }

