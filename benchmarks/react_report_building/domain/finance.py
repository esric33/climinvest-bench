from __future__ import annotations

from pathlib import Path
from typing import Any

from ..util import read_yaml


FINANCE_FIELDS = [
    "gcf_financing_usd",
    "cofinance_usd",
]


def load_finance_enrichment(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = read_yaml(path)
    if not isinstance(value, dict):
        raise ValueError("finance enrichment must be a mapping")
    return value


def project_finance(
    project_id: str, enrichment: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    project = enrichment.get(project_id) or {}
    output: dict[str, dict[str, Any]] = {}
    for field in FINANCE_FIELDS:
        item = project.get(field)
        if isinstance(item, dict):
            output[field] = {
                "value": item.get("value"),
                "locator": item.get("locator"),
            }
        else:
            output[field] = {"value": None, "locator": None}
    return output
