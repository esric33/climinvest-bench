from __future__ import annotations

from typing import Any


def validate_split(
    arguments: dict[str, Any],
    *,
    tool: str,
    expected_section_id: str,
    episode_kind: str,
    original_markdown: str | None,
    max_chars: int = 80_000,
) -> dict[str, Any]:
    """Validate the v2 terminals without inferring an omitted action/mode."""

    modes = {"create_section": "create", "replace_section": "replace", "keep_section": "keep"}
    mode = modes[tool]
    expected_tools = (
        {"create_section"}
        if episode_kind in {"section_create", "oracle_section"}
        else {"replace_section", "keep_section"}
        if episode_kind == "section_update"
        else set()
    )
    if tool not in expected_tools:
        return {"tool": tool, "status": "invalid_context", "message": f"{tool} is unavailable in this episode"}
    expected_keys = {"section_id"} if mode == "keep" else {"section_id", "markdown"}
    if set(arguments) != expected_keys:
        return {
            "tool": tool,
            "status": "invalid_arguments",
            "message": f"arguments must contain exactly {sorted(expected_keys)}",
        }
    result = validate(
        {**arguments, "mode": mode},
        expected_section_id=expected_section_id,
        episode_kind=episode_kind,
        original_markdown=original_markdown,
        max_chars=max_chars,
    )
    # Keep mode in the saved result for scoring and historical trace readers;
    # it is derived only from the explicitly selected tool, never from text.
    result["tool"] = tool
    return result


def validate(
    arguments: dict[str, Any],
    *,
    expected_section_id: str,
    episode_kind: str,
    original_markdown: str | None,
    max_chars: int = 80_000,
) -> dict[str, Any]:
    section_id = arguments.get("section_id")
    mode = arguments.get("mode")
    markdown = arguments.get("markdown")
    if section_id != expected_section_id:
        return {
            "tool": "create_section",
            "status": "invalid_arguments",
            "message": f"section_id must be {expected_section_id!r}",
        }
    allowed = (
        {"create"}
        if episode_kind in {"section_create", "oracle_section"}
        else {"keep", "replace"}
    )
    if mode not in allowed:
        return {
            "tool": "create_section",
            "status": "invalid_arguments",
            "message": f"mode must be one of {sorted(allowed)}",
        }
    if mode == "keep":
        if markdown is not None:
            return {
                "tool": "create_section",
                "status": "invalid_arguments",
                "message": "keep must not provide markdown",
            }
        if original_markdown is None:
            return {
                "tool": "create_section",
                "status": "invalid_arguments",
                "message": "keep requires an original section",
            }
        accepted_markdown = original_markdown
    else:
        if not isinstance(markdown, str) or not markdown.strip():
            return {
                "tool": "create_section",
                "status": "invalid_arguments",
                "message": f"{mode} requires non-empty markdown",
            }
        if len(markdown) > max_chars:
            return {
                "tool": "create_section",
                "status": "invalid_arguments",
                "message": f"markdown exceeds {max_chars} characters",
            }
        accepted_markdown = markdown
    return {
        "tool": "create_section",
        "status": "accepted",
        "terminal": True,
        "section_id": section_id,
        "mode": mode,
        "markdown": accepted_markdown,
    }
