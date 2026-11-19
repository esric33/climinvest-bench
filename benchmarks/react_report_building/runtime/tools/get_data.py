from __future__ import annotations

from typing import Any

from ..evidence_store import EvidenceStore


def execute(store: EvidenceStore, arguments: dict[str, Any]) -> dict[str, Any]:
    ids = arguments.get("ids")
    if (
        not isinstance(ids, list)
        or not ids
        or any(not isinstance(item, str) or not item.strip() for item in ids)
    ):
        return {
            "tool": "get_data",
            "status": "invalid_arguments",
            "message": "ids must be a non-empty string array",
        }
    return {
        "tool": "get_data",
        "status": "completed",
        "results": [store.get_model_view(item) for item in ids],
    }
