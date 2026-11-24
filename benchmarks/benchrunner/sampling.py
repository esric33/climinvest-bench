"""A reproducible Smoke B slice of the unchanged full study graph."""

from collections import defaultdict
from typing import Any

from benchmarks.react_report_building.util import sha256_json

from .plan import StudyPlan, StudyPlanError


def smoke_b_selection(plan: StudyPlan) -> dict[str, Any]:
    """Sample one project/replicate per task/category, paired across scopes/models.

    Selection depends only on the configured seed and scientific cell labels,
    never on model identities, outputs, work hashes or the order of input rows.
    Section records retain every canonical section episode and dependency.
    """
    if plan.execution_shard is not None:
        raise StudyPlanError("Smoke B requires the canonical unsharded study")
    groups = defaultdict(list)
    for record in plan.records:
        if record.get("partial_smoke"):
            raise StudyPlanError("Smoke B cannot reuse truncated section records")
        groups[(record["task"], record.get("category"))].append(record)
    selected = []
    for (task, category), records in sorted(groups.items(), key=lambda item: str(item[0])):
        strata = defaultdict(set)
        for record in records:
            strata[(record["model_alias"], record["scope"])].add(
                (record["project_id"], record["replicate"]))
        candidates = set.intersection(*strata.values())
        if not candidates:
            raise StudyPlanError("Smoke B requires common instances across models and scopes")
        chosen = min(candidates, key=lambda candidate: sha256_json({
            "seed": plan.config.analysis_seed, "task": task, "category": category,
            "project_id": candidate[0], "replicate": candidate[1],
        }))
        selected.extend(record for record in records
                        if (record["project_id"], record["replicate"]) == chosen)
    if not selected:
        raise StudyPlanError("Smoke B requires a nonempty study")
    by_id = {item.work_id: item for item in plan.graph}
    work_ids = {str(record["work_id"]) for record in selected}
    pending = list(work_ids)
    while pending:
        for dependency in by_id[pending.pop()].dependencies:
            if dependency not in work_ids:
                work_ids.add(dependency)
                pending.append(dependency)
    cells = [{key: record.get(key) for key in (
        "model_alias", "project_id", "task", "category", "scope", "replicate",
        "condition_id", "work_id", "episode_work_ids", "section_ids",
    )} for record in selected]
    cells.sort(key=lambda row: (row["model_alias"], row["task"], str(row["category"]), row["scope"]))
    return {
        "schema_version": "benchrunner.smoke_b_selection/v1",
        "strategy": "seeded_task_category_project_replicate_paired_scopes/v1",
        "analysis_seed": plan.config.analysis_seed,
        "parent_plan_id": plan.plan_id,
        "parent_graph_id": plan.graph.graph_id,
        "canonical_record_count": plan.record_count,
        "selected_record_count": len(selected),
        "selected_episode_count": sum(by_id[key].kind == "react_episode" for key in work_ids),
        "selected_work_ids": sorted(work_ids),
        "cells": cells,
        "reuse_policy": "same_full_run_store_and_unchanged_work_ids; retain_all_outcomes",
    }
