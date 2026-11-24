"""Rebuild the all-20 source-only corpus and pin its study metadata.

This is deliberately separate from :mod:`enrichment_all20`.  It normalizes the
provided ClimateFund project records, cleans their source KPI/risk collections,
and atomizes additional values found in the same project evidence.  It does not
impute a missing contract value or create a synthetic benchmark assumption.
"""

from __future__ import annotations

import hashlib
from typing import Any

from ..domain.build import build_dataset
from ..paths import DATA_ROOT, NORMALIZED_ROOT, RAW_CLIMATEFUND_PATH, REPO_ROOT
from ..util import read_json, sha256_json, write_json
from .source_normalization import (
    OUTPUT_PATH as FP083_COMPATIBILITY_PATH,
    write_all_source_normalizations,
)
from .study_design import CANARY_PATH, POPULATION_PATH


def normalize_all20() -> dict[str, Any]:
    """Write source-only artifacts and refresh every dependent study hash."""

    descriptor = read_json(REPO_ROOT / "sources" / "climatefund.json")
    raw_source = read_json(RAW_CLIMATEFUND_PATH)
    observed_source_sha256 = sha256_json(raw_source)
    expected_source_sha256 = descriptor.get("sha256")
    if observed_source_sha256 != expected_source_sha256:
        raise ValueError(
            "ClimateFund source differs from the pinned canonical JSON hash: "
            f"{observed_source_sha256} != {expected_source_sha256}"
        )
    dataset_manifest = build_dataset()
    source_bundles = write_all_source_normalizations()
    write_json(FP083_COMPATIBILITY_PATH, source_bundles["FP083"])

    population = read_json(POPULATION_PATH)
    population["dataset_manifest"]["file_sha256"] = hashlib.sha256(
        (DATA_ROOT / "manifest.json").read_bytes()
    ).hexdigest()
    by_project = {
        str(item["project_id"]).upper(): item
        for item in population["projects"]
    }
    for project_id in dataset_manifest["project_ids"]:
        twin = read_json(NORMALIZED_ROOT / f"{project_id.lower()}.json")
        by_project[project_id]["normalized_twin_sha256"] = sha256_json(twin)
    write_json(POPULATION_PATH, population)

    canary = read_json(CANARY_PATH)
    canary["population_manifest"]["file_sha256"] = hashlib.sha256(
        POPULATION_PATH.read_bytes()
    ).hexdigest()
    write_json(CANARY_PATH, canary)

    return {
        "schema_version": "react_report.source_corpus_build/v2",
        "project_count": len(dataset_manifest["project_ids"]),
        "source_normalization_bundle_count": len(source_bundles),
        "synthetic_enrichment_count": 0,
        "evaluated_model_calls": 0,
        "source_revision": descriptor.get("revision"),
        "source_sha256": observed_source_sha256,
        "dataset_manifest_sha256": hashlib.sha256(
            (DATA_ROOT / "manifest.json").read_bytes()
        ).hexdigest(),
        "population_manifest_sha256": hashlib.sha256(
            POPULATION_PATH.read_bytes()
        ).hexdigest(),
    }


def main() -> None:
    result = normalize_all20()
    print(
        f"normalized {result['project_count']} source projects and "
        f"{result['source_normalization_bundle_count']} source-extraction bundles; "
        "synthetic enrichment=0, model calls=0"
    )


if __name__ == "__main__":
    main()
