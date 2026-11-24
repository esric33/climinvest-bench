from __future__ import annotations

from typing import Any

from ..calculator import Calculator, model_visible_calculation_response


def execute(calculator: Calculator, arguments: dict[str, Any]) -> dict[str, Any]:
    result = (
        calculator.execute_ids(arguments.get("ids"))
        if "ids" in arguments
        else calculator.execute(arguments.get("operations"))
    )
    return {"tool": "calculate", **model_visible_calculation_response(result)}
