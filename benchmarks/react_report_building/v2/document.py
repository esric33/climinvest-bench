from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from .contract import load_compiled_contract


VISIBLE_COMPONENT_TYPES = {"table", "llm"}
PUBLIC_COMPONENT_DEPENDENCY_FIELDS = (
    "data_ids",
    "context_ids",
    "instruction_dependency_ids",
)
PROMPT_POLICY_VERSION = "react_report.prompt_policy/v3-full-catalogue-semantic-requirements"


def model_visible_output_contract(
    output_contract: dict[str, Any], catalogue: dict[str, Any],
) -> dict[str, Any]:
    """Expose output requirements without per-component retrieval bindings.

    The evaluator retains the original compiled bindings. Public catalogue
    descriptions, never resolved values or private gold, describe what to
    produce. This projection is shared by report/section create/update tasks.
    """
    definitions = {**catalogue["data"], **catalogue["calculations"]}

    def description(identifier: str) -> str:
        canonical = identifier if identifier in definitions else f"calc.{identifier}"
        value = definitions.get(canonical, {}).get("description")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"public requirement lacks a catalogue description: {identifier}")
        if re.search(r"\b(?:dt|req|calc|reference)\.[a-z0-9_]", value):
            raise ValueError(f"public requirement description contains a retrieval binding: {identifier}")
        return value

    def instructions(text: str) -> str:
        text = re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_.]*)\}",
                      lambda match: f'“{description(match[1])}”', text)
        return re.sub(r"\b(?:dt|req|calc|reference)\.[a-z0-9_]+(?:\.[a-z0-9_]+)*",
                      lambda match: f'“{description(match[0])}”', text)

    def section_view(section: dict[str, Any]) -> dict[str, Any]:
        components = []
        for component in section["required_components"]:
            item = {key: deepcopy(component[key]) for key in (
                "id", "kind", "heading", "title", "title_visibility", "table_type", "headers", "format",
            ) if key in component}
            if component["kind"] == "llm":
                item["instructions"] = instructions(component["instructions"])
            elif component["kind"] == "table":
                requirements = [description(node_id) for node_id in component["data_ids"]]
                item["record_sources" if component["table_type"] == "records" else "required_rows"] = requirements
            components.append(item)
        return {"id": section["id"], "heading": section["heading"],
                "subsections": deepcopy(section["subsections"]), "required_components": components}

    visible = {"schema_version": "react_report.model_output_requirements/v1",
               "prompt_policy": PROMPT_POLICY_VERSION}
    if "section" in output_contract:
        visible["section"] = section_view(output_contract["section"])
    else:
        visible["title_requirement"] = "Use the authoritative project title as the report title."
        visible["sections"] = [section_view(section) for section in output_contract["sections"]]
    return visible


def section_contracts(
    contract: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Derive the candidate output contract from the compiled gold document."""

    payload = contract or load_compiled_contract()
    artifacts = [
        artifact
        for artifact in payload["artifacts"]
        if artifact["type"] in VISIBLE_COMPONENT_TYPES
    ]

    output = []
    for section in payload["structure"]["sections"]:
        if section["id"] == "front_matter":
            continue
        section_artifacts = [
            artifact
            for artifact in artifacts
            if artifact["section_id"] == section["id"]
        ]
        explicit_subsections = [
            subsection
            for subsection in section.get("subsections", [])
            if subsection.get("implicit") is not True
        ]
        ordered_items = [
            *(
                {
                    "type": "subsection",
                    "id": subsection["id"],
                    "title": subsection["title"],
                    "start": subsection["start"],
                }
                for subsection in explicit_subsections
            ),
            *section_artifacts,
        ]
        components = [
            _component_contract(item)
            for item in sorted(ordered_items, key=lambda item: item["start"])
        ]
        output.append(
            {
                "id": section["id"],
                "heading": section["title"],
                "subsections": [
                    {
                        "id": subsection["id"],
                        "heading": subsection["title"],
                    }
                    for subsection in explicit_subsections
                ],
                "required_components": components,
            }
        )
    return output


def report_output_contract(
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = contract or load_compiled_contract()
    return {
        "schema_version": "react_report.output_contract/v2",
        "benchmark_version": payload["benchmark_version"],
        "title_source": "dt.project.title",
        "sections": section_contracts(payload),
        "generation": {
            "component": "llm",
            "prompt_field": "instructions",
            "recipes": ["llm"],
        },
    }


def section_output_contract(
    section_id: str,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    section = next(
        (item for item in section_contracts(contract) if item["id"] == section_id),
        None,
    )
    if section is None:
        raise ValueError(f"unknown v2 section {section_id!r}")
    return {
        "schema_version": "react_report.section_output_contract/v2",
        "section": section,
    }


def section_dependency_ids(output_contract: dict[str, Any]) -> list[str]:
    """Return the dependencies disclosed by a public section contract.

    The list is deliberately derived only from candidate-visible component
    fields.  It is suitable for scoping an initial catalogue, whereas private
    executable-gold requirements and update-impact labels are not.
    """

    section = output_contract.get("section")
    if not isinstance(section, dict):
        raise ValueError("section output contract lacks a section object")
    components = section.get("required_components")
    if not isinstance(components, list):
        raise ValueError("section output contract lacks required_components")

    dependencies: set[str] = set()
    for component in components:
        if not isinstance(component, dict):
            raise ValueError("section component must be an object")
        for field in PUBLIC_COMPONENT_DEPENDENCY_FIELDS:
            values = component.get(field, [])
            if not isinstance(values, list) or any(
                not isinstance(item, str) or not item
                for item in values
            ):
                raise ValueError(
                    f"section component {component.get('id')!r} has invalid {field}"
                )
            dependencies.update(values)
    return sorted(dependencies)


def compose_report(
    sections: dict[str, str],
    *,
    title: str,
    contract: dict[str, Any] | None = None,
) -> str:
    expected = [item["id"] for item in section_contracts(contract)]
    missing = [section_id for section_id in expected if section_id not in sections]
    if missing:
        raise ValueError(f"cannot compose v2 report; missing sections {missing}")
    return (
        f"# {title}\n\n"
        + "\n\n".join(sections[section_id].strip() for section_id in expected)
        + "\n"
    )


def _component_contract(artifact: dict[str, Any]) -> dict[str, Any]:
    if artifact["type"] == "subsection":
        return {
            "id": artifact["id"],
            "kind": "subsection",
            "heading": artifact["title"],
            "format": "one exact level-three Markdown heading",
        }
    if artifact["type"] == "table":
        return {
            "id": artifact["id"].rsplit(".", 1)[-1],
            "kind": "table",
            "title": artifact["title"],
            "title_visibility": "metadata_only",
            "table_type": artifact["table_type"],
            "headers": deepcopy(artifact["headers"]),
            "data_ids": deepcopy(artifact["data_ids"]),
            "format": "one Markdown table",
        }
    return {
        "id": artifact["id"].rsplit(".", 1)[-1],
        "kind": "llm",
        "title": artifact["title"],
        "instructions": artifact["prompt"],
        # Prompt dependencies define the available analytical context. They are
        # not a terminal-format checklist: requiring every one here rewarded
        # citation dumping and table regurgitation. Semantic requirements are
        # resolved project-by-project by the executable-gold oracle.
        "required_ids": [],
        "context_ids": deepcopy(artifact["canonical_dependencies"]),
        "instruction_dependency_ids": deepcopy(
            artifact.get("instruction_dependency_ids", [])
        ),
        "output_contract_id": artifact.get("output_contract_id"),
        "format": "one Markdown paragraph generated from these instructions",
    }
