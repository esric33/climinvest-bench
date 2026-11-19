from __future__ import annotations

from statistics import mean
from typing import Any


REFERENCE_ID = "reference.climatefund20.v1"


def build_reference(projects: list[dict[str, Any]]) -> dict[str, Any]:
    if len(projects) != 20:
        raise ValueError(f"reference requires exactly 20 projects, received {len(projects)}")

    def value(project: dict[str, Any], node_id: str) -> float:
        node = project["nodes"][node_id]
        if node["status"] != "available":
            raise ValueError(f"{project['project_id']}: {node_id} is unavailable")
        return float(node["value"])

    project_costs = [value(project, "dt.project.total_cost_usd") for project in projects]
    ghg_values = [
        value(project, "dt.project.ghg_reduction_tco2e") for project in projects
    ]
    implementation = [
        value(project, "dt.project.implementation_years") for project in projects
    ]
    lifespans = [value(project, "dt.project.lifespan_years") for project in projects]
    country_counts = [
        len(project["collections"]["dt.project.countries"]["records"])
        for project in projects
    ]
    cost_per_tco2e = [
        project_cost / ghg
        for project_cost, ghg in zip(project_costs, ghg_values, strict=True)
    ]
    values = {
        "average_project_cost_usd": (mean(project_costs), "USD"),
        "average_ghg_reduction_tco2e": (mean(ghg_values), "tCO2e"),
        "average_implementation_years": (mean(implementation), "years"),
        "average_lifespan_years": (mean(lifespans), "years"),
        "average_country_count": (mean(country_counts), "countries"),
        "average_total_cost_per_tco2e": (mean(cost_per_tco2e), "USD/tCO2e"),
    }
    return {
        "schema_version": "react_report.reference_registry/v1",
        "id": REFERENCE_ID,
        "label": "ClimateFund 20-project baseline reference",
        "version": 1,
        "frozen": True,
        "project_ids": [project["project_id"] for project in projects],
        "nodes": {
            f"{REFERENCE_ID}.{name}": {
                "id": f"{REFERENCE_ID}.{name}",
                "kind": "scalar",
                "description": label_for_reference(name),
                "status": "available",
                "value": result,
                "unit": unit,
                "reference_version": 1,
            }
            for name, (result, unit) in values.items()
        },
    }


def label_for_reference(name: str) -> str:
    return "Frozen baseline " + name.replace("_", " ")

