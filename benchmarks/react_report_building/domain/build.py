from __future__ import annotations

from typing import Any

from ..paths import (
    CATALOGUE_ROOT,
    CLIMATEFUND_SOURCE_PATH,
    DATA_ROOT,
    NORMALIZED_ROOT,
    RAW_CLIMATEFUND_PATH,
    REFERENCE_ROOT,
    SELECTION_ROOT,
)
from ..util import read_json, read_yaml, sha256_json, write_json
from .catalogue import build_catalogue
from .finance import load_finance_enrichment
from .normalization import EXCLUDED_PROJECT, normalize_project
from .references import build_reference


def build_dataset() -> dict[str, Any]:
    if not RAW_CLIMATEFUND_PATH.is_file():
        raise FileNotFoundError(
            "ClimateFund source not found. Set CLIMATEFUND_DATA_PATH or place "
            "the pinned climatefund.json at "
            f"{RAW_CLIMATEFUND_PATH}. See sources/climatefund.json."
        )
    source = read_json(RAW_CLIMATEFUND_PATH)
    if not isinstance(source, list):
        raise ValueError("ClimateFund source must be a JSON array")
    enrichment = load_finance_enrichment(DATA_ROOT / "finance_enrichment.yaml")
    canonical_overrides = read_yaml(DATA_ROOT / "canonical_overrides.yaml") or {}
    projects: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    for raw_project in source:
        if raw_project.get("code") == EXCLUDED_PROJECT:
            continue
        project, audit = normalize_project(
            raw_project,
            enrichment,
            canonical_overrides,
        )
        projects.append(project)
        audits.append(audit)
        write_json(NORMALIZED_ROOT / f"{project['project_id'].lower()}.json", project)
        write_json(
            SELECTION_ROOT / f"{project['project_id'].lower()}.json",
            audit,
        )
    if len(projects) != 20:
        raise ValueError(f"expected 20 normalized projects, received {len(projects)}")
    reference = build_reference(projects)
    write_json(REFERENCE_ROOT / "climatefund20-v1.json", reference)
    catalogue = build_catalogue(projects, reference)
    write_json(CATALOGUE_ROOT / "global_catalogue.json", catalogue)
    manifest = {
        "schema_version": "react_report.dataset_manifest/v1",
        "inputs": {
            "climatefund_twins": {
                "path": CLIMATEFUND_SOURCE_PATH,
                "sha256": sha256_json(source),
            },
            "canonical_overrides": {
                "path": "canonical_overrides.yaml",
                "sha256": sha256_json(canonical_overrides),
            },
            "finance_enrichment": {
                "path": "finance_enrichment.yaml",
                "sha256": sha256_json(enrichment),
            },
        },
        "project_ids": [project["project_id"] for project in projects],
        "projects": [
            {
                "project_id": project["project_id"],
                "path": f"normalized/projects/{project['project_id'].lower()}.json",
                "sha256": sha256_json(project),
            }
            for project in projects
        ],
        "reference": {
            "path": "references/climatefund20-v1.json",
            "sha256": sha256_json(reference),
        },
        "catalogue": {
            "path": "catalogues/global_catalogue.json",
            "sha256": sha256_json(catalogue),
        },
    }
    write_json(DATA_ROOT / "manifest.json", manifest)
    return manifest
