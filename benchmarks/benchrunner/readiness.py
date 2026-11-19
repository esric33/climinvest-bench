"""Zero-provider benchmark-completeness gate for paid studies."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from benchmarks.react_report_building.paths import NORMALIZED_ROOT
from benchmarks.react_report_building.util import read_json
from benchmarks.react_report_building.v2.missingness_runner import (
    preflight_missingness_case,
)
from benchmarks.react_report_building.v2.perturbations import (
    POPULATION_CONDITIONS_PATH,
)
from benchmarks.react_report_building.v2.preflight import (
    preflight_study_population,
)
from benchmarks.react_report_building.v2.study_design import load_population
from benchmarks.react_report_building.v2.update_runner import (
    prepare_canonical_t0,
    preflight_update_case,
)
from benchmarks.react_report_building.validation import validate_everything

from .artifacts import atomic_write_json
from .config import StudyConfig
from .orchestration import credential_preflight, execute_study
from .plan import StudyPlan, build_study_plan


READINESS_SCHEMA_VERSION = "benchrunner.readiness/v1"


def evaluate_readiness(
    readiness_config: StudyConfig,
    run_dir: Path,
    *,
    target_config: StudyConfig | None = None,
    concurrency: int = 10,
) -> dict[str, Any]:
    """Audit all frozen cells and, only if valid, run the fixture matrix."""

    if concurrency < 1 or concurrency > 10:
        raise ValueError("readiness concurrency must be between 1 and 10")
    root = Path(run_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)

    repository = validate_everything()
    population = preflight_study_population()
    conditions = read_json(POPULATION_CONDITIONS_PATH)
    twins = {
        item["project_id"]: read_json(
            NORMALIZED_ROOT / f"{item['project_id'].lower()}.json"
        )
        for item in load_population()["projects"]
    }
    canonical = {
        project_id: prepare_canonical_t0(twin)
        for project_id, twin in twins.items()
    }
    missingness = _scan_conditions(
        conditions,
        group="masks",
        check=lambda twin, condition: preflight_missingness_case(
            twin, condition
        ),
        twins=twins,
        concurrency=concurrency,
    )
    updates = _scan_conditions(
        conditions,
        group="mutations",
        check=lambda twin, condition: preflight_update_case(
            twin,
            condition,
            canonical_t0=canonical[str(condition["project_id"]).upper()],
        ),
        twins=twins,
        concurrency=concurrency,
    )

    readiness_plan, readiness_plan_error = _try_plan(
        readiness_config,
        enforce=False,
    )
    target_plan: StudyPlan | None = None
    target_error: str | None = None
    target_credentials: dict[str, Any] | None = None
    if target_config is not None:
        target_plan, target_error = _try_plan(target_config, enforce=True)
        try:
            target_credentials = credential_preflight(target_config)
        except (OSError, ValueError) as exc:
            target_error = str(exc)

    static_ready = bool(
        repository.get("valid") is True
        and population.get("all_ready_for_provider_smoke") is True
        and population.get("provider_calls") == 0
        and missingness["failed"] == 0
        and updates["failed"] == 0
        and readiness_plan is not None
        and (target_config is None or target_plan is not None)
        and (
            target_credentials is None
            or target_credentials.get("ready") is True
        )
    )

    fixture: dict[str, Any]
    if static_ready and readiness_plan is not None:
        fixture_result = execute_study(
            readiness_config,
            root / "offline-fixture",
            plan=readiness_plan,
        )
        scheduler = fixture_result["scheduler"]
        export = fixture_result["export"]
        fixture_passed = bool(
            scheduler["status"] == "completed"
            and scheduler["counts"]["completed"]
            == scheduler["counts"]["total"]
            and export["record_statuses"].get("completed", 0)
            == readiness_plan.record_count
        )
        fixture = {
            "status": "passed" if fixture_passed else "failed",
            "provider_calls": 0,
            "result": fixture_result,
        }
    else:
        fixture_passed = False
        fixture = {
            "status": "skipped",
            "provider_calls": 0,
            "reason": "static benchmark gates failed",
        }

    ready = bool(static_ready and fixture_passed)
    report = {
        "schema_version": READINESS_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if ready else "failed",
        "ready_for_paid_smoke": ready,
        "provider_calls": 0,
        "repository_validation": {
            "passed": repository.get("valid") is True,
            "error_count": len(repository.get("errors") or []),
            "errors": repository.get("errors") or [],
        },
        "population_preflight": {
            "passed": population.get("all_ready_for_provider_smoke") is True,
            "project_count": population.get("project_count"),
            "ready_project_count": population.get("ready_project_count"),
            "provider_calls": population.get("provider_calls"),
        },
        "missingness_semantics": missingness,
        "update_semantics": updates,
        "readiness_plan": (
            {
                "plan_id": readiness_plan.plan_id,
                "graph_id": readiness_plan.graph.graph_id,
                "episode_count": readiness_plan.episode_count,
                "record_count": readiness_plan.record_count,
            }
            if readiness_plan is not None
            else {"error": readiness_plan_error}
        ),
        "target_plan": (
            {
                "plan_id": target_plan.plan_id,
                "graph_id": target_plan.graph.graph_id,
                "episode_count": target_plan.episode_count,
                "record_count": target_plan.record_count,
                "credentials": target_credentials,
            }
            if target_plan is not None
            else ({"error": target_error} if target_config is not None else None)
        ),
        "offline_fixture": fixture,
        "canonical_t0_policy": {
            "source_preference": "deterministic_update_fixture",
            "reference_prose_for_quality_scoring": False,
            "manual_review_override_is_optional_compatibility": True,
            "project_count": len(canonical),
        },
    }
    atomic_write_json(root / "readiness.json", report)
    return report


def validate_paid_readiness(
    path: Path,
    *,
    target_plan: StudyPlan,
) -> dict[str, Any]:
    report = read_json(Path(path))
    if report.get("schema_version") != READINESS_SCHEMA_VERSION:
        raise ValueError("readiness report has an unsupported schema")
    if report.get("ready_for_paid_smoke") is not True:
        raise ValueError("readiness report did not pass; paid run is blocked")
    pinned = report.get("target_plan") or {}
    if pinned.get("plan_id") != target_plan.plan_id:
        raise ValueError("readiness report targets a different immutable plan")
    if pinned.get("graph_id") != target_plan.graph.graph_id:
        raise ValueError("readiness report graph differs from the current plan")
    return report


def _scan_conditions(
    manifest: dict[str, Any],
    *,
    group: str,
    check: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    twins: dict[str, dict[str, Any]],
    concurrency: int,
) -> dict[str, Any]:
    selected = [
        condition
        for project in manifest.get("projects", [])
        for condition in project.get(group, [])
    ]
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(
        max_workers=concurrency,
        thread_name_prefix=f"readiness-{group}",
    ) as pool:
        futures = {
            pool.submit(
                check,
                twins[str(condition["project_id"]).upper()],
                condition,
            ): condition
            for condition in selected
        }
        for future in as_completed(futures):
            condition = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # local audit boundary, no provider calls
                result = {
                    "condition_id": condition.get("condition_id"),
                    "project_id": condition.get("project_id"),
                    "ready_for_provider_smoke": False,
                    "provider_calls": 0,
                    "errors": [
                        {
                            "code": "preflight_exception",
                            "message": str(exc),
                            "exception_type": type(exc).__name__,
                        }
                    ],
                }
            result.setdefault("condition_id", condition.get("condition_id"))
            result.setdefault("project_id", condition.get("project_id"))
            if result.get("condition_id") is None:
                result["condition_id"] = condition.get("condition_id")
            if result.get("project_id") is None:
                result["project_id"] = condition.get("project_id")
            result.setdefault("category", condition.get("category"))
            results.append(result)
    results.sort(key=lambda item: str(item.get("condition_id") or ""))
    failures = [
        {
            "condition_id": item.get("condition_id"),
            "project_id": item.get("project_id"),
            "category": item.get("category"),
            "errors": item.get("errors") or [],
        }
        for item in results
        if item.get("ready_for_provider_smoke") is not True
    ]
    return {
        "passed": len(failures) == 0,
        "total": len(results),
        "ready": len(results) - len(failures),
        "failed": len(failures),
        "provider_calls": sum(int(item.get("provider_calls") or 0) for item in results),
        "failures": failures,
    }


def _try_plan(
    config: StudyConfig,
    *,
    enforce: bool,
) -> tuple[StudyPlan | None, str | None]:
    try:
        return (
            build_study_plan(
                config,
                enforce_condition_readiness=enforce,
            ),
            None,
        )
    except (OSError, TypeError, ValueError) as exc:
        return None, str(exc)
