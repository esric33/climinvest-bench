"""Dependency-closed execution shards of one immutable canonical study plan."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Iterator

from benchmarks.react_report_building.util import sha256_json

from .artifacts import read_json_file
from .config import StudyConfig, parse_study_config, sanitized_config
from .plan import (
    PLAN_SCHEMA_VERSION,
    StudyPlan,
    StudyPlanError,
    expand_cases,
    _action_interface_hash,
    _adapter_implementation_hash,
    _prompt_bundle_hash,
    _provider_profile_hash,
)
from .work import WorkGraph


SHARD_SCHEMA_VERSION = "benchrunner.execution_shard/v1"
INDEXED_STRATEGY = "sorted_projects_round_robin/v1"
EXPLICIT_STRATEGY = "explicit_projects/v1"


def select_execution_shard(
    plan: StudyPlan,
    *,
    shard_index: int | None = None,
    shard_count: int | None = None,
    project_ids: Iterable[str] | None = None,
) -> StudyPlan:
    """Select whole projects; indices are zero based and never change cell IDs.

    Indexed shards partition sorted canonical project IDs by ``index::count``.
    This guarantees balanced project counts, disjoint membership, and complete
    coverage independent of provider outputs. With no selection, return plan.
    """

    if shard_index is None and shard_count is None and project_ids is None:
        return plan
    if plan.execution_shard is not None or plan.canonical_plan is not None:
        raise StudyPlanError("select shards from a canonical plan, not another shard")
    _validate_record_bindings(plan)
    projects = sorted({str(item["project_id"]) for item in plan.records})
    if not projects:
        raise StudyPlanError("cannot shard a plan with no projects")
    if project_ids is not None:
        if shard_index is not None or shard_count is not None:
            raise StudyPlanError("choose explicit projects or shard index/count, not both")
        supplied = [str(item).strip().upper() for item in project_ids]
        if len(set(supplied)) != len(supplied):
            raise StudyPlanError("explicit shard project IDs must be unique")
        selected = sorted(supplied)
        if not selected or set(selected) - set(projects):
            raise StudyPlanError("shard projects must be a nonempty subset of the canonical plan")
        strategy = EXPLICIT_STRATEGY
    else:
        if (
            isinstance(shard_count, bool) or not isinstance(shard_count, int)
            or not 1 <= shard_count <= len(projects)
        ):
            raise StudyPlanError("shard_count must be between 1 and the canonical project count")
        if (
            isinstance(shard_index, bool) or not isinstance(shard_index, int)
            or not 0 <= shard_index < shard_count
        ):
            raise StudyPlanError("shard_index is zero based and must be less than shard_count")
        selected = projects[shard_index::shard_count]
        strategy = INDEXED_STRATEGY

    selected_set = set(selected)
    work = [item for item in plan.graph if item.identity.get("project_id") in selected_set]
    work_ids = {item.work_id for item in work}
    if any(set(item.dependencies) - work_ids for item in work):
        raise StudyPlanError("project shard crosses a canonical dependency boundary")
    graph = WorkGraph(work)
    records = tuple(item for item in plan.records if item["project_id"] in selected_set)
    selected_record_ids = sorted(str(item["work_id"]) for item in records)
    canonical_record_ids = sorted(str(item["work_id"]) for item in plan.records)
    receipt = {
        "schema_version": SHARD_SCHEMA_VERSION,
        "parent_plan_id": plan.plan_id,
        "parent_plan_sha256": sha256_json(plan.to_dict()),
        "parent_graph_id": plan.graph.graph_id,
        "study_id": plan.config.study_id,
        "partition_strategy": strategy,
        "shard_index_base": 0,
        "shard_index": shard_index,
        "shard_count": shard_count,
        "canonical_projects": projects,
        "selected_projects": selected,
        "canonical_record_count": plan.record_count,
        "canonical_episode_count": plan.episode_count,
        "canonical_work_count": len(plan.graph),
        "selected_record_count": len(records),
        "selected_episode_count": sum(item.kind == "react_episode" for item in graph),
        "selected_work_count": len(graph),
        "execution_graph_id": graph.graph_id,
        "canonical_record_work_ids_sha256": sha256_json(canonical_record_ids),
        "selected_record_work_ids": selected_record_ids,
        "selected_record_keys": sorted(str(item["record_key"]) for item in records),
        "deduplication_key": ["parent_plan_id", "record_work_id"],
        "is_complete_canonical_selection": selected == projects,
        "population_inference_requires_canonical_coverage": True,
        "scientific_identity_policy": "canonical_work_and_record_ids_unchanged",
    }
    return StudyPlan(plan.config, graph, records, receipt, plan)


def load_execution_plan(
    run_dir: Path,
    *,
    config: StudyConfig | None = None,
    verify_current_bindings: bool = True,
) -> StudyPlan:
    """Reconstruct persisted work, checking shard selection and immutable hashes.

    Resume callers use the default current-binding check. Offline historical
    export verification can disable it; this never rebuilds a full study DAG or
    substitutes today's inputs for a persisted canonical treatment.
    """

    root = Path(run_dir)
    payload = read_json_file(root / "plan.json")
    receipt = payload.get("execution_shard")
    if receipt is None:
        plan = _decode_canonical_plan(payload)
    else:
        if not isinstance(receipt, dict) or receipt.get("schema_version") != SHARD_SCHEMA_VERSION:
            raise StudyPlanError("unsupported execution shard receipt")
        canonical = _decode_canonical_plan(read_json_file(root / "canonical-plan.json"))
        strategy = receipt.get("partition_strategy")
        if strategy == INDEXED_STRATEGY:
            plan = select_execution_shard(
                canonical,
                shard_index=receipt.get("shard_index"),
                shard_count=receipt.get("shard_count"),
            )
        elif strategy == EXPLICIT_STRATEGY:
            plan = select_execution_shard(canonical, project_ids=receipt.get("selected_projects"))
        else:
            raise StudyPlanError("unsupported execution shard partition strategy")
        if plan.to_dict() != payload or read_json_file(root / "shard.json") != receipt:
            raise StudyPlanError("persisted shard differs from its canonical plan or receipt")

    manifest = read_json_file(root / "manifest.json")
    if manifest.get("plan_id") != plan.plan_id or manifest.get("graph_id") != plan.graph.graph_id:
        raise StudyPlanError("persisted plan does not match immutable run manifest")
    if manifest.get("execution_shard") != plan.execution_shard:
        raise StudyPlanError("run manifest shard receipt differs from persisted plan")
    if read_json_file(root / "resolved-config.json") != sanitized_config(plan.config):
        raise StudyPlanError("persisted resolved config differs from the canonical plan")
    if config is not None and sanitized_config(config) != sanitized_config(plan.config):
        raise StudyPlanError("requested config differs from the persisted canonical config")
    if verify_current_bindings:
        _validate_current_bindings(plan)
    return plan


def _decode_canonical_plan(payload: dict[str, Any]) -> StudyPlan:
    if payload.get("schema_version") != PLAN_SCHEMA_VERSION or payload.get("execution_shard") is not None:
        raise StudyPlanError("a canonical study plan is required")
    config_payload = dict(payload.get("config") or {})
    config_payload.pop("inferential", None)
    config = parse_study_config(config_payload)
    graph = WorkGraph.from_dict(payload.get("graph") or {})
    records = payload.get("records")
    if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
        raise StudyPlanError("persisted plan records must be JSON objects")
    plan = StudyPlan(config, graph, tuple(records))
    _validate_record_bindings(plan)
    if plan.to_dict() != payload:
        raise StudyPlanError("persisted canonical plan has inconsistent counts or metadata")
    return plan


def _validate_record_bindings(plan: StudyPlan) -> None:
    reducers = {item.work_id: item for item in plan.graph if item.kind == "react_record"}
    records = {str(item.get("work_id") or ""): item for item in plan.records}
    keys = [item.get("record_key") for item in plan.records]
    if len(records) != len(plan.records) or set(records) != set(reducers) or len(set(keys)) != len(keys):
        raise StudyPlanError("canonical record IDs/keys must uniquely cover its reducers")
    for work_id, record in records.items():
        work = reducers[work_id]
        if any(record.get(key) != value for key, value in work.identity.items()):
            raise StudyPlanError("record specification differs from its canonical reducer identity")
        if set(record.get("episode_work_ids") or []) != set(work.dependencies):
            raise StudyPlanError("record episode membership differs from its canonical dependencies")
    if any(not item.identity.get("project_id") for item in plan.graph):
        raise StudyPlanError("every sharded work item must belong to a canonical project")
    expected_cells = Counter(
        (case.project_id, case.task, case.scope, case.category, model.alias,
         replicate, frozenset(case.section_ids))
        for case in expand_cases(plan.config)
        for model in plan.config.models
        for replicate in range(plan.config.replicates)
    )
    observed_cells = Counter(
        (record.get("project_id"), record.get("task"), record.get("scope"),
         record.get("category"), record.get("model_alias"),
         int(record.get("replicate") or 0),
         frozenset(record.get("section_ids") or []) if record.get("partial_smoke") else frozenset())
        for record in plan.records
    )
    if observed_cells != expected_cells:
        raise StudyPlanError("canonical plan does not cover every configured scientific cell")


def _validate_current_bindings(plan: StudyPlan) -> None:
    """Reject a changed runtime, prompt, schema, or endpoint on shard resume."""

    expected: dict[tuple[str, str], str] = {}
    for item in plan.graph:
        identity = item.identity
        checks = (
            ("adapter_implementation_sha256", "adapter", _adapter_implementation_hash),
            ("action_interface_sha256", "actions", _action_interface_hash),
            ("provider_profile_sha256", str(identity.get("provider_profile")),
             lambda: _provider_profile_hash(str(identity["provider_profile"]))),
            ("prompt_bundle_sha256", str((identity.get("task"), identity.get("scope"))),
             lambda: _prompt_bundle_hash(str(identity["task"]), str(identity["scope"]))),
        )
        for field, key, compute in checks:
            if identity.get(field) is None:
                continue
            cache_key = (field, key)
            if cache_key not in expected:
                expected[cache_key] = compute()
            if identity[field] != expected[cache_key]:
                raise StudyPlanError(f"persisted treatment {field} differs from current binding; use its immutable release")


def verify_shard_exports(
    run_dirs: Iterable[Path], *, require_complete: bool = False,
) -> dict[str, Any]:
    """Verify canonical coverage and deduplicate identical offline collections.

    This read-only verifier does not merge databases or overwrite evidence.
    Divergent duplicates are rejected even when their numeric scores agree.
    """

    canonical: StudyPlan | None = None
    canonical_sha256: str | None = None
    observed: dict[str, str] = {}
    duplicate_count = 0
    selected_projects: set[str] = set()
    run_count = 0
    for run_dir in run_dirs:
        plan = load_execution_plan(Path(run_dir), verify_current_bindings=False)
        if plan.execution_shard is None or plan.canonical_plan is None:
            raise StudyPlanError("shard export verification requires execution shard runs")
        parent = plan.canonical_plan
        if canonical is None:
            canonical = parent
            canonical_sha256 = plan.execution_shard["parent_plan_sha256"]
        elif canonical_sha256 != plan.execution_shard["parent_plan_sha256"]:
            raise StudyPlanError("shard collections have different canonical parent plans")
        selected_projects.update(plan.execution_shard["selected_projects"])
        by_key = {str(item["record_key"]): item for item in plan.records}
        for record in _exported_records(Path(run_dir), plan):
            specification = by_key.get(str(record.get("record_key") or ""))
            if specification is None:
                raise StudyPlanError("exported record is outside its assigned shard")
            work_id = str(specification["work_id"])
            identity = plan.graph.get(work_id).identity
            if any(record.get(key) != value for key, value in identity.items()):
                raise StudyPlanError("exported record differs from its canonical treatment")
            digest = sha256_json(record)
            if work_id in observed:
                if observed[work_id] != digest:
                    raise StudyPlanError(f"divergent duplicate record: {work_id}")
                duplicate_count += 1
            else:
                observed[work_id] = digest
        run_count += 1
    if canonical is None:
        raise StudyPlanError("at least one shard collection is required")
    expected = {str(item["work_id"]) for item in canonical.records}
    missing = sorted(expected - set(observed))
    if require_complete and missing:
        raise StudyPlanError(f"canonical collection is incomplete: {len(missing)} missing records")
    return {
        "schema_version": "benchrunner.shard_collection_verification/v1",
        "parent_plan_id": canonical.plan_id,
        "parent_plan_sha256": canonical_sha256,
        "run_count": run_count,
        "selected_projects": sorted(selected_projects),
        "canonical_records": len(expected),
        "unique_finalized_records": len(observed),
        "identical_duplicate_records": duplicate_count,
        "missing_record_work_ids": missing,
        "canonical_collection_complete": not missing,
        "canonical_design_inferential": canonical.config.inferential,
        "scientific_readiness_evaluated": False,
        "deduplication_key": ["parent_plan_id", "record_work_id"],
    }


def _exported_records(root: Path, plan: StudyPlan) -> Iterator[dict[str, Any]]:
    stream = root / "exports" / "record-stream"
    if (stream / "index.json").is_file():
        index = read_json_file(stream / "index.json")
        if index.get("graph_id") != plan.graph.graph_id:
            raise StudyPlanError("record stream belongs to another execution graph")
        observed = 0
        for number in range(1, int(index["shard_count"]) + 1):
            with (stream / f"records-{number:08d}.jsonl").open(encoding="utf-8") as source:
                for line in source:
                    row = json.loads(line)
                    observed += 1
                    record = row["record"]
                    work = plan.graph.get(str(row["work_id"]))
                    if work.kind != "react_record" or work.identity.get("record_key") != record.get("record_key"):
                        raise StudyPlanError("record stream envelope differs from its record identity")
                    yield record
        if observed != int(index["finalized_records"]):
            raise StudyPlanError("record stream count differs from its atomic index")
    elif (root / "exports" / "records.jsonl").is_file():
        with (root / "exports" / "records.jsonl").open(encoding="utf-8") as source:
            for line in source:
                yield json.loads(line)
