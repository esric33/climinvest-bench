from __future__ import annotations

import re
from typing import Any, Mapping

from ..evaluation.alignment import align_components
from ..evaluation.report_tree import parse_markdown


LINK_PATTERN = re.compile(r"\[([^\]\n]*)\]\(([^)\n]+)\)")


def validate_report_markdown(
    markdown: str,
    contract: dict[str, Any],
    *,
    expected_title: str,
    allowed_ids: set[str] | None = None,
    section_allowed_ids: Mapping[str, set[str]] | None = None,
) -> dict[str, Any]:
    """Validate a complete report as an ordered title plus exact section contracts.

    Trusted callers may override known citation IDs per section, for example
    after checking byte-identical frozen T0 proof. This function does not infer
    inheritance or allow IDs from a different section to leak into that scope.
    """

    errors: list[dict[str, Any]] = []
    if not isinstance(markdown, str) or not markdown.strip():
        return _report_result(
            valid=False,
            errors=[_error("empty_markdown", "report Markdown must be non-empty")],
        )
    lines = markdown.splitlines()
    expected_first_line = f"# {expected_title}"
    if not lines or lines[0] != expected_first_line:
        errors.append(
            _error(
                "incorrect_report_title",
                f"first line must be exactly {expected_first_line!r}",
            )
        )
    section_starts = [
        index for index, line in enumerate(lines) if line.startswith("## ")
    ]
    expected_sections = contract.get("sections")
    if not isinstance(expected_sections, list):
        return _report_result(
            valid=False,
            errors=[
                _error(
                    "invalid_report_contract",
                    "report contract requires an ordered sections list",
                )
            ],
        )
    observed_headings = [lines[index][3:] for index in section_starts]
    expected_headings = [str(item.get("heading") or "") for item in expected_sections]
    if observed_headings != expected_headings:
        errors.append(
            _error(
                "section_sequence",
                f"expected section headings {expected_headings}, received "
                f"{observed_headings}",
            )
        )
    preamble_end = section_starts[0] if section_starts else len(lines)
    if any(line.strip() for line in lines[1:preamble_end]):
        errors.append(
            _error(
                "unexpected_report_preamble",
                "only blank lines may appear between the title and first section",
            )
        )
    section_results: list[dict[str, Any]] = []
    for section_contract in expected_sections:
        positions = [
            index
            for index, heading in enumerate(observed_headings)
            if heading == section_contract.get("heading")
        ]
        if len(positions) == 1:
            position = positions[0]
            start = section_starts[position]
            end = (
                section_starts[position + 1]
                if position + 1 < len(section_starts)
                else len(lines)
            )
            section_markdown = "\n".join(lines[start:end]).strip() + "\n"
            validation = validate_section_markdown(
                section_markdown,
                {"section": section_contract},
                allowed_ids=(section_allowed_ids or {}).get(
                    str(section_contract.get("id") or ""), allowed_ids
                ),
            )
            section_results.append(validation)
            errors.extend(
                {
                    **error,
                    "section_id": section_contract.get("id"),
                }
                for error in validation["errors"]
            )
        else:
            section_results.append(
                _result(
                    section_id=section_contract.get("id"),
                    valid=False,
                    errors=[],
                    validation_available=False,
                    unavailable_reason="missing_section" if not positions else "duplicate_section_heading",
                )
            )
    return _report_result(
        valid=not errors,
        errors=errors,
        expected_section_count=len(expected_sections),
        observed_section_count=len(section_starts),
        sections=section_results,
    )


def validate_section_markdown(
    markdown: str,
    contract: dict[str, Any],
    *,
    allowed_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Validate one submitted section against a compiled component contract.

    This is intentionally a terminal contract check, not a quality score. It
    verifies exact section/component layout, table shape, required citation
    coverage, and (when supplied) citation IDs known to the episode store. Both
    ``node_id`` and ``missing.node_id`` cover the same required canonical ID.
    """

    section_contract = contract.get("section", contract)
    errors: list[dict[str, Any]] = []
    heading = str(section_contract.get("heading") or "")
    section_id = str(section_contract.get("id") or "")
    components = section_contract.get("required_components")
    if not heading or not section_id or not isinstance(components, list):
        return _result(
            section_id=section_id or None,
            valid=False,
            errors=[
                _error(
                    "invalid_section_contract",
                    "section contract requires id, heading, and required_components",
                )
            ],
        )
    if not isinstance(markdown, str) or not markdown.strip():
        return _result(
            section_id=section_id,
            valid=False,
            errors=[_error("empty_markdown", "section Markdown must be non-empty")],
        )

    expected_first_line = f"## {heading}"
    first_line = markdown.splitlines()[0] if markdown.splitlines() else ""
    if first_line != expected_first_line:
        errors.append(
            _error(
                "incorrect_section_heading",
                f"first line must be exactly {expected_first_line!r}",
            )
        )

    try:
        tree = parse_markdown(markdown)
    except Exception as exc:  # pragma: no cover - defensive subprocess boundary
        errors.append(_error("markdown_parse_error", str(exc)))
        return _result(section_id=section_id, valid=False, errors=errors)

    observed_sections = tree.get("sections", [])
    if len(observed_sections) != 1:
        errors.append(
            _error(
                "section_count",
                f"expected exactly one level-two section, received {len(observed_sections)}",
            )
        )
        return _result(section_id=section_id, valid=False, errors=errors)

    observed = observed_sections[0]
    if observed.get("heading") != heading:
        errors.append(
            _error(
                "incorrect_section_heading",
                f"expected heading {heading!r}, received {observed.get('heading')!r}",
            )
        )

    expected_blocks = [
        {
            "table": "table",
            "llm": "prose",
            "subsection": "subsection",
        }.get(
            str(component.get("kind")),
            f"unsupported:{component.get('kind')}",
        )
        for component in components
    ]
    observed_blocks = [str(item.get("kind") or "") for item in observed.get("blocks", [])]
    if observed_blocks != expected_blocks:
        errors.append(
            _error(
                "component_sequence",
                f"expected component blocks {expected_blocks}, received {observed_blocks}",
            )
        )

    alignment = align_components(components, observed)
    component_results = []
    for index, component in enumerate(components):
        component_id = str(component.get("id") or f"component_{index}")
        block_index = alignment["component_block_indices"][index]
        if block_index is None:
            errors.append(
                _error(
                    "missing_component",
                    "no matching observed block for the required component",
                    component_id=component_id,
                )
            )
            component_results.append(
                {
                    "component_id": component_id,
                    "validation_available": False,
                    "unavailable_reason": "unmatched_component",
                    "observed_block_index": None,
                }
            )
            continue
        component_results.append(
            {
                "component_id": component_id,
                "validation_available": True,
                "observed_block_index": block_index,
            }
        )
        block = observed["blocks"][block_index]
        if component.get("kind") == "table" and block.get("kind") == "table":
            table = observed["tables"][block["index"]]
            _validate_table(component, table, errors)
            _validate_required_citations(
                component.get("data_ids", []),
                table.get("raw", ""),
                component_id=component_id,
                errors=errors,
            )
        elif component.get("kind") == "llm" and block.get("kind") == "prose":
            paragraph = observed["paragraphs"][block["index"]]["text"]
            _validate_required_citations(
                component.get("required_ids", []),
                paragraph,
                component_id=component_id,
                errors=errors,
            )
        elif (
            component.get("kind") == "subsection"
            and block.get("kind") == "subsection"
            and block.get("heading") != component.get("heading")
        ):
            errors.append(
                _error(
                    "subsection_heading",
                    f"expected subsection heading {component.get('heading')!r}, "
                    f"received {block.get('heading')!r}",
                    component_id=component_id,
                )
            )

    _validate_links(markdown, allowed_ids=allowed_ids, errors=errors)
    return _result(
        section_id=section_id,
        valid=not errors,
        errors=errors,
        expected_blocks=expected_blocks,
        observed_blocks=observed_blocks,
        component_alignment=alignment,
        components=component_results,
    )


def _validate_table(
    component: dict[str, Any],
    table: dict[str, Any],
    errors: list[dict[str, Any]],
) -> None:
    component_id = str(component.get("id") or "table")
    expected_headers = component.get("headers", [])
    observed_headers = table.get("headers", [])
    if observed_headers != expected_headers:
        errors.append(
            _error(
                "table_headers",
                f"expected headers {expected_headers}, received {observed_headers}",
                component_id=component_id,
            )
        )
    width = len(expected_headers)
    malformed_rows = [
        index
        for index, row in enumerate(table.get("rows", []), start=1)
        if len(row) != width
    ]
    if malformed_rows:
        errors.append(
            _error(
                "table_row_width",
                f"rows with incorrect column count: {malformed_rows}",
                component_id=component_id,
            )
        )
    if component.get("table_type") == "key-value":
        expected_rows = len(component.get("data_ids", []))
        observed_rows = len(table.get("rows", []))
        if observed_rows != expected_rows:
            errors.append(
                _error(
                    "table_row_count",
                    f"expected {expected_rows} key-value rows, received {observed_rows}",
                    component_id=component_id,
                )
            )
        for index, (node_id, row) in enumerate(
            zip(component.get("data_ids", []), table.get("rows", [])),
            start=1,
        ):
            value_cell = row[1] if len(row) > 1 else ""
            targets = [
                _canonical_target(match.group(2))
                for match in LINK_PATTERN.finditer(value_cell)
            ]
            if not any(
                target == node_id or target.startswith(node_id + ".")
                for target in targets
            ):
                errors.append(
                    _error(
                        "table_row_citation",
                        f"key-value row {index} does not cite configured ID {node_id}",
                        component_id=component_id,
                        row=index,
                        required_id=node_id,
                    )
                )
    elif component.get("table_type") == "records":
        data_ids = component.get("data_ids", [])
        if len(data_ids) != 1:
            errors.append(
                _error(
                    "records_table_data_ids",
                    "records table requires exactly one configured collection ID",
                    component_id=component_id,
                )
            )
        elif table.get("rows"):
            collection_id = data_ids[0]
            for index, row in enumerate(table["rows"], start=1):
                targets = [
                    _canonical_target(match.group(2))
                    for match in LINK_PATTERN.finditer(" | ".join(row))
                ]
                if not any(
                    target == collection_id
                    or target.startswith(collection_id + ".")
                    for target in targets
                ):
                    errors.append(
                        _error(
                            "table_row_citation",
                            f"records row {index} does not cite {collection_id}",
                            component_id=component_id,
                            row=index,
                            required_id=collection_id,
                        )
                    )


def _validate_required_citations(
    required_ids: list[str],
    text: str,
    *,
    component_id: str,
    errors: list[dict[str, Any]],
) -> None:
    targets = [_canonical_target(match.group(2)) for match in LINK_PATTERN.finditer(text)]
    missing = [
        required_id
        for required_id in required_ids
        if not any(
            target == required_id or target.startswith(required_id + ".")
            for target in targets
        )
    ]
    if missing:
        errors.append(
            _error(
                "missing_required_citations",
                f"required IDs are not cited: {', '.join(missing)}",
                component_id=component_id,
                required_ids=missing,
            )
        )


def _validate_links(
    markdown: str,
    *,
    allowed_ids: set[str] | None,
    errors: list[dict[str, Any]],
) -> None:
    matches = list(LINK_PATTERN.finditer(markdown))
    malformed_count = max(0, markdown.count("](") - len(matches))
    if malformed_count:
        errors.append(
            _error(
                "malformed_citations",
                f"found {malformed_count} malformed Markdown citation(s)",
            )
        )
    empty_targets = [match.group(2) for match in matches if not match.group(1).strip()]
    if empty_targets:
        errors.append(
            _error(
                "empty_citation_labels",
                f"citation labels must be non-empty: {', '.join(empty_targets)}",
            )
        )
    if allowed_ids is None:
        return
    invalid = sorted(
        {
            match.group(2)
            for match in matches
            if _canonical_target(match.group(2)) not in allowed_ids
        }
    )
    if invalid:
        errors.append(
            _error(
                "invalid_citation_ids",
                f"citation IDs are unavailable in this episode: {', '.join(invalid)}",
                citation_ids=invalid,
            )
        )


def _canonical_target(target: str) -> str:
    return str(target).removeprefix("missing.")


def _error(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **details}


def _result(
    *,
    section_id: str | None,
    valid: bool,
    errors: list[dict[str, Any]],
    **details: Any,
) -> dict[str, Any]:
    return {
        "schema_version": "react_report.section_output_validation/v3",
        "section_id": section_id,
        "valid": valid,
        "errors": errors,
        **details,
    }


def _report_result(
    *,
    valid: bool,
    errors: list[dict[str, Any]],
    **details: Any,
) -> dict[str, Any]:
    return {
        "schema_version": "react_report.report_output_validation/v3",
        "valid": valid,
        "errors": errors,
        **details,
    }
