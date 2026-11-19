from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


V2_ROOT = Path(__file__).resolve().parent
PACKAGE_ROOT = V2_ROOT.parent
COMPILED_CONTRACT_PATH = V2_ROOT / "data" / "compiled_contract.json"
# Compatibility alias: the default compiled contract is the financing-facility
# family because FP083 is bound to that family.
TEMPLATE_PATH = V2_ROOT / "templates" / "financing_facility.tracemark.md"

FORBIDDEN_GENERATION_DIRECTIVES = (
    ":::text",
    ":::prose",
    ":::distill",
    ":::conclusion",
)
OUTPUT_CONTRACT_IDS = {
    "benchmark.executive_assessment.v1",
    "benchmark.interpretive_assessment.v1",
    "benchmark.kpi_priority.v1",
    "benchmark.risk_priority.v1",
    "benchmark.evidence_requirements.v1",
}


def load_compiled_contract(path: Path = COMPILED_CONTRACT_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_compiled_contract(contract: dict[str, Any] | None = None) -> list[str]:
    """Return invariant violations for an executable v2 family contract.

    Complexity is descriptive. A contract is accepted because its typed
    structure is coherent and every deterministic calculation is consumed by a
    visible component, not because it meets an arbitrary node-count or depth
    quota.
    """

    payload = contract or load_compiled_contract()
    errors: list[str] = []
    generation = payload.get("generation_contract", {})
    graph = payload.get("graph", {})
    family = payload.get("template_family", {})
    visible_sections = [
        section
        for section in payload.get("structure", {}).get("sections", [])
        if section.get("id") != "front_matter"
    ]
    visible_ids = [str(section.get("id")) for section in visible_sections]

    if payload.get("schema_version") != "react_report.compiled_contract/v2":
        errors.append("unexpected compiled-contract schema version")
    if generation.get("recipes") != ["llm"]:
        errors.append("v2 generation must use only the llm recipe")
    if generation.get("prompt_field") != "instructions":
        errors.append("v2 llm components must use the UI instructions prompt field")
    if generation.get("agent_tools_added") != []:
        errors.append("document-model generation concepts must not add agent tools")

    declared_order = family.get("section_order")
    if not isinstance(declared_order, list) or visible_ids != declared_order:
        errors.append("visible section order differs from the declared family order")
    if family.get("visible_section_count") != len(visible_sections):
        errors.append("visible section count differs from the declared family count")

    counts = payload.get("component_counts", {})
    if counts.get("visible_sections") != len(visible_sections):
        errors.append("component count does not cover every visible section")
    for section_id in visible_ids:
        section_counts = counts.get("by_section", {}).get(section_id, {})
        if section_counts.get("tables", 0) < 1:
            errors.append(f"{section_id}: requires at least one deterministic table")
        if section_counts.get("llm") != 1:
            errors.append(f"{section_id}: requires exactly one prompt-controlled llm")
    if graph.get("llm_component_count") != len(visible_sections):
        errors.append("each visible section must contain exactly one llm component")

    usage = payload.get("calculation_usage", {})
    if usage.get("unused_calculation_ids"):
        errors.append("compiled contract contains calculations unused by visible components")
    if usage.get("calculation_count") != graph.get("calculation_count"):
        errors.append("calculation-usage count differs from the compiled graph")
    if usage.get("consumed_calculation_count") != graph.get("calculation_count"):
        errors.append("not every compiled calculation is transitively consumed")

    llm_artifacts = [
        artifact
        for artifact in payload.get("artifacts", [])
        if artifact.get("type") == "llm"
    ]
    for artifact in llm_artifacts:
        output_contract_id = artifact.get("output_contract_id")
        if output_contract_id not in OUTPUT_CONTRACT_IDS:
            errors.append(
                f"{artifact.get('id')}: unknown or missing output contract "
                f"{output_contract_id!r}"
            )
    if len(llm_artifacts) != len(visible_sections):
        errors.append("compiled artifact list does not contain one llm per section")

    diagnostics = payload.get("diagnostics") or []
    if any(item.get("severity") == "error" for item in diagnostics):
        errors.append("compiled v2 template has TraceMark errors")

    template_relative = payload.get("template_path")
    template_path = PACKAGE_ROOT / str(template_relative or "")
    if not template_relative or not template_path.is_file():
        errors.append(f"v2 template is missing: {template_relative!r}")
    else:
        actual_template_hash = hashlib.sha256(template_path.read_bytes()).hexdigest()
        if payload.get("template_sha256") != actual_template_hash:
            errors.append("v2 template hash differs from the compiled contract")
        source = template_path.read_text(encoding="utf-8").lower()
        for directive in FORBIDDEN_GENERATION_DIRECTIVES:
            if directive in source:
                errors.append(f"forbidden generation directive present: {directive}")

    population = payload.get("population_binding", {})
    manifest_relative = population.get("manifest_path")
    manifest_path = PACKAGE_ROOT / str(manifest_relative or "")
    if not manifest_relative or not manifest_path.is_file():
        errors.append(f"population manifest is missing: {manifest_relative!r}")
    else:
        actual_manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        if population.get("manifest_sha256") != actual_manifest_hash:
            errors.append("population manifest hash differs from the compiled contract")
    assignments = population.get("assigned_project_ids") or []
    if population.get("assigned_project_count") != len(assignments):
        errors.append("population assignment count is inconsistent")
    if not assignments:
        errors.append("compiled family has no assigned projects")
    if population.get("template_is_experimental_condition") is not False:
        errors.append("template family must be fixed metadata, not an experimental condition")

    vendor_root = V2_ROOT / "vendor" / "tracemark-core"
    compiler_files = payload.get("compiler_pin", {}).get("files", {})
    for filename, expected_hash in compiler_files.items():
        compiler_path = vendor_root / filename
        if not compiler_path.is_file():
            errors.append(f"pinned TraceMark compiler file is missing: {filename}")
            continue
        actual_hash = hashlib.sha256(compiler_path.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            errors.append(f"pinned TraceMark compiler hash differs: {filename}")
    return errors


def contract_summary(contract: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = contract or load_compiled_contract()
    sections = [
        section
        for section in payload["structure"]["sections"]
        if section["id"] != "front_matter"
    ]
    graph = payload["graph"]
    artifacts = payload.get("artifacts", [])
    return {
        "benchmark_version": payload["benchmark_version"],
        "contract_id": payload.get("contract_id"),
        "section_count": len(sections),
        "sections": [section["id"] for section in sections],
        "subsection_count": sum(
            len(
                [
                    item
                    for item in section.get("subsections", [])
                    if not item.get("implicit")
                ]
            )
            for section in sections
        ),
        "table_count": sum(item.get("type") == "table" for item in artifacts),
        "calculation_count": graph["calculation_count"],
        "max_calculation_depth": graph["max_calculation_depth"],
        "longest_calculation_chain": graph.get(
            "longest_calculation_chain_names", []
        ),
        "llm_component_count": graph["llm_component_count"],
        "output_contract_ids": sorted(
            {
                item.get("output_contract_id")
                for item in artifacts
                if item.get("type") == "llm"
            }
        ),
        "unused_calculation_count": len(
            payload.get("calculation_usage", {}).get(
                "unused_calculation_ids", []
            )
        ),
        "generation_recipes": payload["generation_contract"]["recipes"],
        "compiler_commit": payload["compiler_pin"]["source_commit"],
    }
