"""Pure deterministic collection calculations for risk and KPI priorities.

These operations deliberately keep source evidence and benchmark assumptions
separate.  Risk scores are derived from source probability/impact labels.  KPI
priorities are joined from the explicit synthetic enrichment collection; they
are never written into the normalized source records.
"""

from __future__ import annotations

import math
import re
from copy import deepcopy
from typing import Any, Iterable


RISK_ORDINAL_SCORES = {"low": 1, "medium": 2, "high": 3}
KPI_PRIORITY_BY_FAMILY = {
    "climate_impact": 5,
    "climate_resilience": 4,
    "land_nature_outcome": 4,
    "low_emission_capacity": 4,
    "beneficiaries_access": 3,
    "finance_investment": 3,
    "employment_gender": 2,
    "policy_governance": 2,
    "institutional_capacity": 1,
    "other": 1,
}
KPI_PRIORITY_TOP_K = 2
MRV_REQUIRED_FIELDS = ("baseline", "final_target", "verification")

_PLACEHOLDER_VALUES = {
    "",
    "-",
    "n/a",
    "na",
    "nil",
    "none",
    "not applicable",
    "not available",
    "null",
    "tbc",
    "tbd",
}
_NUMBER_WITH_SCALE = re.compile(
    r"^([+-]?(?:(?:\d{1,3}(?:,\d{3})+)|\d+|\d*\.\d+))"
    r"\s*(thousand|million|billion)?\s*%?$",
    re.I,
)
_SCALE = {None: 1.0, "thousand": 1_000.0, "million": 1_000_000.0, "billion": 1_000_000_000.0}


class CollectionCalculationUnavailable(ValueError):
    """Raised when a collection calculation has no scoreable inputs."""

    def __init__(self, dependency_ids: Iterable[str], message: str) -> None:
        self.dependency_ids = tuple(dict.fromkeys(str(item) for item in dependency_ids))
        super().__init__(message)


def score_risks(
    records: list[dict[str, Any]],
    *,
    result_id: str = "calc.scored_risks",
) -> list[dict[str, Any]]:
    """Score every risk without dropping records with unavailable inputs."""

    output: list[dict[str, Any]] = []
    for index, source in enumerate(records, start=1):
        record = _calculated_record(source, result_id, index)
        probability = _ordinal_score(source, "probability")
        impact = _ordinal_score(source, "impact")
        record["fields"]["probability_score"] = _score_field(
            record["id"], "probability_score", probability
        )
        record["fields"]["impact_score"] = _score_field(
            record["id"], "impact_score", impact
        )

        missing_dependencies = [
            dependency
            for item in (probability, impact)
            for dependency in item.get("missing_dependencies", [])
        ]
        invalid_dependencies = [
            dependency
            for item in (probability, impact)
            for dependency in item.get("invalid_dependencies", [])
        ]
        if probability["status"] == impact["status"] == "available":
            score_dependencies = (
                str(record["fields"]["probability_score"]["id"]),
                str(record["fields"]["impact_score"]["id"]),
            )
            priority = _derived_field(
                record["id"],
                "priority_score",
                "Ordinal benchmark risk-priority score (probability × impact)",
                int(probability["value"]) * int(impact["value"]),
                "score",
                dependencies=score_dependencies,
                operation_id="multiply_ordinal_scores",
            )
            scoring_status = "complete"
        elif invalid_dependencies:
            priority = _unavailable_field(
                record["id"],
                "priority_score",
                "Ordinal benchmark risk-priority score (probability × impact)",
                status="invalid_input",
                dependencies=invalid_dependencies,
                unit="score",
            )
            scoring_status = "invalid_label"
        else:
            priority = _unavailable_field(
                record["id"],
                "priority_score",
                "Ordinal benchmark risk-priority score (probability × impact)",
                status="missing_dependency",
                dependencies=missing_dependencies,
                unit="score",
            )
            scoring_status = "incomplete"
        if priority.get("status") != "available":
            # Keep direct field lineage distinct from the unavailable leaf
            # dependencies used to explain why the multiplication is blocked.
            priority["dependencies"] = [
                str(record["fields"]["probability_score"]["id"]),
                str(record["fields"]["impact_score"]["id"]),
            ]
            priority["operation_id"] = "multiply_ordinal_scores"
        record["fields"]["priority_score"] = priority
        record["fields"]["priority_scoring_status"] = _derived_field(
            record["id"],
            "priority_scoring_status",
            "Risk-priority scoring status",
            scoring_status,
            None,
            dependencies=(
                str(record["fields"]["probability_score"]["id"]),
                str(record["fields"]["impact_score"]["id"]),
            ),
            operation_id="risk_input_completeness",
        )
        output.append(record)
    return _source_order(output)


def maximum_available_field(
    records: list[dict[str, Any]], field: str
) -> float | int:
    """Return the maximum over scoreable records only.

    Missing and invalid record fields are excluded, never converted to zero.
    The calculation is unavailable when no record can be scored; callers can
    report the available/incomplete counts alongside a partial maximum.
    """

    available = [
        _numeric_field(record, field)
        for record in records
        if _field(record, field).get("status") == "available"
    ]
    if not available:
        raise CollectionCalculationUnavailable(
            (_field(record, field).get("id", f"{record.get('id')}.{field}") for record in records),
            f"no records have an available {field}",
        )
    maximum = max(available)
    return int(maximum) if float(maximum).is_integer() else maximum


def filter_equal_available(
    records: list[dict[str, Any]], field: str, target: float
) -> list[dict[str, Any]]:
    return _source_order(
        [
            deepcopy(record)
            for record in records
            if _field(record, field).get("status") == "available"
            and math.isclose(
                _numeric_field(record, field),
                float(target),
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
        ]
    )


def count_field_status(
    records: list[dict[str, Any]], field: str, *, available: bool
) -> int:
    return sum(
        (_field(record, field).get("status") == "available") is available
        for record in records
    )


def join_kpi_priorities(
    kpis: list[dict[str, Any]],
    priorities: list[dict[str, Any]],
    *,
    result_id: str = "calc.prioritized_kpis",
) -> list[dict[str, Any]]:
    """Join source KPIs to the separately disclosed benchmark priorities.

    Every KPI is retained. A missing or invalid sidecar mapping yields an
    explicitly unavailable priority field and an ``incomplete`` assignment
    status; it never acquires priority zero.
    """

    by_source_record: dict[str, dict[str, Any]] = {}
    for priority in priorities:
        source_field = _field(priority, "source_record_id")
        if source_field.get("status") == "available":
            source_id = str(source_field.get("value"))
            if source_id in by_source_record:
                raise ValueError(f"duplicate KPI priority mapping for {source_id}")
            by_source_record[source_id] = priority

    output: list[dict[str, Any]] = []
    for index, source in enumerate(kpis, start=1):
        record = _calculated_record(source, result_id, index)
        priority = by_source_record.get(str(source.get("id")))
        if priority is None:
            dependency = f"dt.kpi_reporting_priorities.{_record_suffix(source, index)}"
            record["fields"]["benchmark_reporting_priority"] = _unavailable_field(
                record["id"],
                "benchmark_reporting_priority",
                "Synthetic benchmark reporting priority",
                status="missing_dependency",
                dependencies=(dependency,),
                unit="priority",
            )
            record["fields"]["benchmark_priority_basis"] = _unavailable_field(
                record["id"],
                "benchmark_priority_basis",
                "Synthetic benchmark priority basis",
                status="missing_dependency",
                dependencies=(dependency,),
                unit=None,
            )
            record["fields"]["benchmark_priority_status"] = _derived_field(
                record["id"],
                "benchmark_priority_status",
                "Benchmark reporting-priority assignment status",
                "incomplete",
                None,
                dependencies=(dependency,),
                operation_id="priority_mapping_completeness",
            )
        else:
            priority_field = _field(priority, "benchmark_reporting_priority")
            basis_field = _field(priority, "benchmark_priority_basis")
            mapping_field = _field(priority, "source_record_id")
            record["fields"]["benchmark_reporting_priority"] = _joined_field(
                record["id"],
                "benchmark_reporting_priority",
                priority_field,
                dependencies=(str(priority_field.get("id")), str(mapping_field.get("id"))),
            )
            record["fields"]["benchmark_priority_basis"] = _joined_field(
                record["id"],
                "benchmark_priority_basis",
                basis_field,
                dependencies=(str(basis_field.get("id")), str(mapping_field.get("id"))),
            )
            priority_available = priority_field.get("status") == "available"
            record["fields"]["benchmark_priority_status"] = _derived_field(
                record["id"],
                "benchmark_priority_status",
                "Benchmark reporting-priority assignment status",
                "complete" if priority_available else "incomplete",
                None,
                dependencies=(str(priority_field.get("id")), str(mapping_field.get("id"))),
                operation_id="priority_mapping_completeness",
            )
        output.append(record)
    return _source_order(output)


def top_k_cutoff(
    records: list[dict[str, Any]], field: str, *, k: int
) -> float | int:
    """Return an inclusive top-k cutoff over available priorities only.

    Incomplete priority inputs remain unranked. If fewer than ``k`` priorities
    are available, the cutoff is the lowest available value and every available
    record participates. With no available priority the calculation is itself
    unavailable. Missing values are never treated as zero.
    """

    if k <= 0:
        raise ValueError("k must be positive")
    values = sorted(
        (
            _numeric_field(record, field)
            for record in records
            if _field(record, field).get("status") == "available"
        ),
        reverse=True,
    )
    if not values:
        raise CollectionCalculationUnavailable(
            (_field(record, field).get("id", f"{record.get('id')}.{field}") for record in records),
            f"no records have an available {field}",
        )
    cutoff = values[min(k, len(values)) - 1]
    return int(cutoff) if float(cutoff).is_integer() else cutoff


def filter_threshold_available(
    records: list[dict[str, Any]],
    field: str,
    threshold: float,
    *,
    comparison: str,
) -> list[dict[str, Any]]:
    if comparison not in {">=", "<=", ">", "<"}:
        raise ValueError(f"unsupported threshold comparison {comparison!r}")

    def selected(value: float) -> bool:
        if comparison == ">=":
            return value >= threshold
        if comparison == "<=":
            return value <= threshold
        if comparison == ">":
            return value > threshold
        return value < threshold

    return _source_order(
        [
            deepcopy(record)
            for record in records
            if _field(record, field).get("status") == "available"
            and selected(_numeric_field(record, field))
        ]
    )


def assess_kpi_mrv(
    records: list[dict[str, Any]],
    *,
    result_id: str = "calc.kpi_mrv_assessments",
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for index, source in enumerate(records, start=1):
        record = _calculated_record(source, result_id, index)
        missing = [name for name in MRV_REQUIRED_FIELDS if not _substantive(_field(source, name))]
        available_count = len(MRV_REQUIRED_FIELDS) - len(missing)
        readiness = "ready" if not missing else "partial" if available_count else "incomplete"
        input_dependencies = tuple(
            str(_field(source, name).get("id")) for name in MRV_REQUIRED_FIELDS
        )
        for name, description, value, unit in (
            (
                "mrv_available_field_count",
                "Available MRV fields among baseline, final target and verification",
                available_count,
                "fields",
            ),
            (
                "mrv_required_field_count",
                "Required MRV field count",
                len(MRV_REQUIRED_FIELDS),
                "fields",
            ),
            (
                "mrv_readiness_status",
                "Deterministic MRV readiness status",
                readiness,
                None,
            ),
            (
                "mrv_missing_fields",
                "Missing or placeholder MRV fields",
                missing,
                None,
            ),
        ):
            record["fields"][name] = _derived_field(
                record["id"],
                name,
                description,
                value,
                unit,
                dependencies=(
                    () if name == "mrv_required_field_count" else input_dependencies
                ),
                operation_id=(
                    "benchmark_required_field_count"
                    if name == "mrv_required_field_count"
                    else "assess_mrv_field_completeness"
                ),
            )
        output.append(record)
    return _source_order(output)


def assess_kpi_target_deltas(
    records: list[dict[str, Any]],
    *,
    result_id: str = "calc.kpi_target_delta_assessments",
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for index, source in enumerate(records, start=1):
        record = _calculated_record(source, result_id, index)
        baseline = _field(source, "baseline")
        target = _field(source, "final_target")
        status, baseline_value, target_value, unit = _delta_inputs(baseline, target)
        record["fields"]["target_delta_status"] = _derived_field(
            record["id"],
            "target_delta_status",
            "Target-delta calculation status",
            status,
            None,
            dependencies=(str(baseline.get("id")), str(target.get("id"))),
            operation_id="validate_numeric_unit_compatibility",
        )
        dependencies = (str(baseline.get("id")), str(target.get("id")))
        if status == "available":
            assert baseline_value is not None and target_value is not None
            delta = target_value - baseline_value
            record["fields"]["target_absolute_change"] = _derived_field(
                record["id"],
                "target_absolute_change",
                "Final target minus baseline",
                _int_if_integral(delta),
                unit,
                dependencies=dependencies,
                operation_id="subtract",
            )
            if not math.isclose(baseline_value, 0.0, rel_tol=0, abs_tol=1e-15):
                pct = delta / abs(baseline_value) * 100
                record["fields"]["target_percentage_change_pct"] = _derived_field(
                    record["id"],
                    "target_percentage_change_pct",
                    "Percentage change from the non-zero baseline",
                    pct,
                    "%",
                    dependencies=dependencies,
                    operation_id="percentage_change_from_baseline",
                )
            else:
                record["fields"]["target_percentage_change_pct"] = _unavailable_field(
                    record["id"],
                    "target_percentage_change_pct",
                    "Percentage change from the non-zero baseline",
                    status="not_applicable",
                    dependencies=dependencies,
                    unit="%",
                )
        else:
            for name, description, derived_unit in (
                ("target_absolute_change", "Final target minus baseline", unit),
                (
                    "target_percentage_change_pct",
                    "Percentage change from the non-zero baseline",
                    "%",
                ),
            ):
                record["fields"][name] = _unavailable_field(
                    record["id"],
                    name,
                    description,
                    status="missing_dependency" if status == "missing_input" else "not_applicable",
                    dependencies=dependencies,
                    unit=derived_unit,
                )
        output.append(record)
    return _source_order(output)


def filter_field_value(
    records: list[dict[str, Any]], field: str, value: Any
) -> list[dict[str, Any]]:
    return _source_order(
        [
            deepcopy(record)
            for record in records
            if _field(record, field).get("status") == "available"
            and _field(record, field).get("value") == value
        ]
    )


def _ordinal_score(record: dict[str, Any], field_name: str) -> dict[str, Any]:
    source = _field(record, field_name)
    source_id = str(source.get("id") or f"{record.get('id')}.{field_name}")
    if source.get("status") != "available":
        return {
            "status": "missing_dependency",
            "value": None,
            "dependencies": [source_id],
            "missing_dependencies": [source_id],
            "invalid_dependencies": [],
        }
    label = str(source.get("value") or "").strip().casefold()
    if label not in RISK_ORDINAL_SCORES:
        return {
            "status": "invalid_input",
            "value": None,
            "dependencies": [source_id],
            "missing_dependencies": [],
            "invalid_dependencies": [source_id],
        }
    return {
        "status": "available",
        "value": RISK_ORDINAL_SCORES[label],
        "dependencies": [source_id],
        "missing_dependencies": [],
        "invalid_dependencies": [],
    }


def _score_field(record_id: str, name: str, result: dict[str, Any]) -> dict[str, Any]:
    description = name.replace("_", " ").title()
    if result["status"] == "available":
        return _derived_field(
            record_id,
            name,
            description,
            result["value"],
            "score",
            dependencies=result.get("dependencies", ()),
            operation_id="ordinal_label_score",
        )
    dependencies = result.get("missing_dependencies") or result.get("invalid_dependencies") or []
    return _unavailable_field(
        record_id,
        name,
        description,
        status=str(result["status"]),
        dependencies=dependencies,
        unit="score",
    )


def _calculated_record(
    source: dict[str, Any], result_id: str, index: int
) -> dict[str, Any]:
    record = deepcopy(source)
    record_id = f"{result_id}.{_record_suffix(source, index)}"
    source_record_id = str(source.get("id") or "")
    record["id"] = record_id
    record["kind"] = "record"
    record["status"] = "available"
    record["source_record_id"] = source_record_id
    record.setdefault("fields", {})["source_record_id"] = _derived_field(
        record_id,
        "source_record_id",
        "Source record ID",
        source_record_id,
        None,
        dependencies=(source_record_id,),
        operation_id="record_identity",
    )
    return record


def _record_suffix(record: dict[str, Any], index: int) -> str:
    suffix = str(record.get("id") or "").rsplit(".", 1)[-1]
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", suffix).strip("_")
    return cleaned or f"record_{index}"


def _derived_field(
    record_id: str,
    name: str,
    description: str,
    value: Any,
    unit: str | None,
    *,
    dependencies: Iterable[str] = (),
    operation_id: str | None = None,
) -> dict[str, Any]:
    output = {
        "id": f"{record_id}.{name}",
        "kind": "scalar",
        "description": description,
        "status": "available",
        "value": deepcopy(value),
        "unit": unit,
        "dependencies": list(dict.fromkeys(str(item) for item in dependencies if item)),
    }
    if operation_id:
        output["operation_id"] = operation_id
    return output


def _unavailable_field(
    record_id: str,
    name: str,
    description: str,
    *,
    status: str,
    dependencies: Iterable[str],
    unit: str | None,
) -> dict[str, Any]:
    dependency_ids = list(dict.fromkeys(str(item) for item in dependencies if item))
    output = {
        "id": f"{record_id}.{name}",
        "kind": "scalar",
        "description": description,
        "status": status,
        "value": None,
        "unit": unit,
        "dependencies": dependency_ids,
    }
    if status == "missing_dependency":
        output["missing_dependencies"] = dependency_ids
    elif status == "invalid_input":
        output["invalid_dependencies"] = dependency_ids
    return output


def _joined_field(
    record_id: str,
    name: str,
    source: dict[str, Any],
    *,
    dependencies: Iterable[str],
) -> dict[str, Any]:
    """Copy one joined field while making its direct lineage explicit."""

    source_id = str(source.get("id") or "")
    output = {
        "id": f"{record_id}.{name}",
        "kind": "scalar",
        "description": str(source.get("description") or name.replace("_", " ").title()),
        "status": str(source.get("status") or "missing"),
        "value": deepcopy(source.get("value")),
        "unit": source.get("unit"),
        "source_field_id": source_id,
    }
    output["dependencies"] = list(
        dict.fromkeys(str(item) for item in dependencies if item)
    )
    output["operation_id"] = "join_by_source_record_id"
    if output["status"] != "available":
        output["missing_dependencies"] = list(output["dependencies"])
    return output


def _field(record: dict[str, Any], name: str) -> dict[str, Any]:
    field = record.get("fields", {}).get(name)
    if isinstance(field, dict):
        return field
    return {
        "id": f"{record.get('id')}.{name}",
        "kind": "scalar",
        "status": "missing",
        "value": None,
        "unit": None,
    }


def _numeric_field(record: dict[str, Any], name: str) -> float:
    field = _field(record, name)
    if field.get("status") != "available":
        raise ValueError(f"{field.get('id')}: field is unavailable")
    number = float(field.get("value"))
    if not math.isfinite(number):
        raise ValueError(f"{field.get('id')}: field is not finite")
    return number


def _source_order(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed = list(enumerate(records))

    def key(item: tuple[int, dict[str, Any]]) -> tuple[float, int]:
        index, record = item
        source_order = _field(record, "source_order")
        if source_order.get("status") == "available":
            try:
                return float(source_order.get("value")), index
            except (TypeError, ValueError):
                pass
        return float(index + 1), index

    return [deepcopy(record) for _, record in sorted(indexed, key=key)]


def _substantive(field: dict[str, Any]) -> bool:
    if field.get("status") != "available":
        return False
    value = field.get("value")
    if value is None:
        return False
    if isinstance(value, str) and value.strip().casefold() in _PLACEHOLDER_VALUES:
        return False
    return True


def _parse_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    match = _NUMBER_WITH_SCALE.fullmatch(str(value).strip())
    if match is None:
        return None
    number = float(match.group(1).replace(",", ""))
    return number * _SCALE[match.group(2).casefold() if match.group(2) else None]


def _delta_inputs(
    baseline: dict[str, Any], target: dict[str, Any]
) -> tuple[str, float | None, float | None, str | None]:
    unit = baseline.get("unit") if baseline.get("unit") == target.get("unit") else None
    if baseline.get("status") != "available" or target.get("status") != "available":
        return "missing_input", None, None, unit
    baseline_number = _parse_number(baseline.get("value"))
    target_number = _parse_number(target.get("value"))
    if baseline_number is None or target_number is None:
        return "non_numeric_input", baseline_number, target_number, unit
    baseline_unit = _normalized_unit(baseline.get("unit"))
    target_unit = _normalized_unit(target.get("unit"))
    if baseline_unit is None or target_unit is None:
        return "unit_unspecified", baseline_number, target_number, None
    if baseline_unit != target_unit:
        return "incompatible_unit", baseline_number, target_number, None
    return "available", baseline_number, target_number, str(baseline.get("unit"))


def _normalized_unit(value: Any) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split()).casefold()
    aliases = {
        "mw": "mw",
        "mws": "mw",
        "us$": "usd",
        "usd": "usd",
        "tco2eq": "tco2e",
        "tco2e": "tco2e",
    }
    return aliases.get(normalized, normalized or None)


def _int_if_integral(value: float) -> float | int:
    return int(value) if float(value).is_integer() else value
