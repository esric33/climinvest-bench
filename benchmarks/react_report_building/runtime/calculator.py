from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from ..domain.calculations import calculation_registry
from ..domain.ids import missing_id
from ..domain.priority_calculations import (
    CollectionCalculationUnavailable,
    assess_kpi_mrv,
    assess_kpi_target_deltas,
    count_field_status,
    filter_equal_available,
    filter_field_value,
    filter_threshold_available,
    join_kpi_priorities,
    maximum_available_field,
    score_risks as score_risk_priorities,
    top_k_cutoff,
)
from .evidence_store import EvidenceStore, model_visible_node


RISK_SCORES = {"low": 1, "medium": 2, "high": 3}
REQUIRED_OPERATION_FIELDS = (
    "result_id",
    "operation_id",
    "input_ids",
    "parameters",
)


class CalculationError(ValueError):
    pass


def model_visible_calculation_response(
    response: dict[str, Any],
) -> dict[str, Any]:
    """Compact calculation results while leaving stored audit nodes intact."""

    output = {
        key: deepcopy(value)
        for key, value in response.items()
        if key != "results"
    }
    results = response.get("results", [])
    output["results"] = [
        model_visible_node(item)
        for item in results
        if isinstance(item, dict)
    ]
    return output


class CalculationDependencyUnavailable(CalculationError):
    def __init__(self, node_id: str, status: str) -> None:
        super().__init__(f"{node_id}: dependency is {status}")
        self.node_id = node_id
        self.status = status


class _UnavailableExpressionValue:
    def __init__(self, node_id: str, status: str) -> None:
        self.node_id = node_id
        self.status = status


class Calculator:
    def __init__(
        self,
        store: EvidenceStore,
        registry: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.store = store
        self.registry = deepcopy(registry or calculation_registry())

    def execute(self, operations: list[dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(operations, list) or not operations:
            return {
                "status": "invalid_arguments",
                "message": "operations must be a non-empty array",
                "results": [],
                "required_operation_fields": list(REQUIRED_OPERATION_FIELDS),
            }
        for index, item in enumerate(operations):
            if not isinstance(item, dict):
                return self._invalid_operation(
                    index,
                    "each operation must be an object",
                )
            missing_fields = [
                field
                for field in REQUIRED_OPERATION_FIELDS
                if field not in item
            ]
            extra_fields = sorted(
                set(item) - set(REQUIRED_OPERATION_FIELDS)
            )
            if missing_fields or extra_fields:
                detail = []
                if missing_fields:
                    detail.append(
                        f"missing fields: {', '.join(missing_fields)}"
                    )
                if extra_fields:
                    detail.append(
                        f"unsupported fields: {', '.join(extra_fields)}"
                    )
                if "calculation_id" in item:
                    detail.append(
                        "use the canonical calc.* ID as result_id instead of "
                        "calculation_id"
                    )
                return self._invalid_operation(index, "; ".join(detail))
        pending = {str(item.get("result_id") or ""): deepcopy(item) for item in operations}
        if "" in pending or len(pending) != len(operations):
            return {
                "status": "invalid_arguments",
                "message": (
                    "result_id values must be nonempty, unique, complete "
                    "canonical calc.* IDs"
                ),
                "results": [],
                "required_operation_fields": list(REQUIRED_OPERATION_FIELDS),
            }
        results: list[dict[str, Any]] = []
        completed: set[str] = set()
        while pending:
            progressed = False
            for result_id, request in list(pending.items()):
                definition = self.registry.get(result_id)
                if definition is None:
                    suggestion = self._canonical_id_suggestion(result_id)
                    result = {
                        "id": result_id,
                        "kind": "error",
                        "status": "unknown_calculation",
                        "message": (
                            "result_id must equal a complete canonical calc.* "
                            "catalogue key"
                        ),
                    }
                    if suggestion:
                        result["suggested_result_id"] = suggestion
                elif not self._matches_definition(request, definition):
                    result = {
                        "id": result_id,
                        "kind": "error",
                        "status": "calculation_definition_mismatch",
                        "expected": deepcopy(definition),
                        "expected_request": self._request_for(definition),
                        "message": (
                            "copy operation_id, input_ids, and parameters exactly "
                            "from the calculation catalogue entry"
                        ),
                    }
                else:
                    dependencies = list(definition["input_ids"].values())
                    unresolved = [
                        item
                        for item in dependencies
                        if item.startswith("calc.")
                        and item in pending
                        and item not in completed
                    ]
                    if unresolved:
                        continue
                    result = self._execute_definition(definition)
                self.store.put_calculated(result)
                results.append(result)
                completed.add(result_id)
                del pending[result_id]
                progressed = True
            if not progressed:
                cycle = sorted(pending)
                for result_id in cycle:
                    result = {
                        "id": result_id,
                        "kind": "error",
                        "status": "calculation_cycle",
                        "dependencies": list(
                            self.registry.get(result_id, {}).get("input_ids", {}).values()
                        ),
                    }
                    self.store.put_calculated(result)
                    results.append(result)
                    del pending[result_id]
        return {"status": "completed", "results": results}

    def execute_ids(self, calculation_ids: Any) -> dict[str, Any]:
        """Execute requested canonical calculations and their private closure.

        The v2 model-facing action names only the results it needs.  Registry
        definitions remain the single source of truth: this method expands
        deterministic calculation dependencies, executes them in one local
        transaction, stores the complete audit graph, and returns only the
        requested target nodes to the model.
        """

        if (
            not isinstance(calculation_ids, list)
            or not calculation_ids
            or any(
                not isinstance(item, str) or not item.strip()
                for item in calculation_ids
            )
        ):
            return {
                "status": "invalid_arguments",
                "message": "ids must be a non-empty canonical calc.* string array",
                "results": [],
            }

        requested = list(dict.fromkeys(calculation_ids))
        unknown = [item for item in requested if item not in self.registry]
        if unknown:
            return {
                "status": "invalid_arguments",
                "message": "ids contains unknown canonical calculations",
                "results": [
                    {
                        "id": item,
                        "kind": "error",
                        "status": "unknown_calculation",
                        "message": "use an exact calc.* key from the catalogue",
                        **(
                            {"suggested_result_id": suggestion}
                            if (suggestion := self._canonical_id_suggestion(item))
                            else {}
                        ),
                    }
                    for item in unknown
                ],
            }

        ordered: list[str] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(calculation_id: str) -> None:
            if calculation_id in visited:
                return
            if calculation_id in visiting:
                raise CalculationError(
                    f"calculation registry contains a cycle at {calculation_id}"
                )
            visiting.add(calculation_id)
            definition = self.registry[calculation_id]
            for dependency_id in definition["input_ids"].values():
                if dependency_id.startswith("calc."):
                    visit(dependency_id)
            visiting.remove(calculation_id)
            visited.add(calculation_id)
            ordered.append(calculation_id)

        for calculation_id in requested:
            visit(calculation_id)

        executed = self.execute(
            [self._request_for(self.registry[item]) for item in ordered]
        )
        by_id = {
            item["id"]: item
            for item in executed.get("results", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        return {
            "status": executed.get("status", "completed"),
            "results": [deepcopy(by_id[item]) for item in requested],
        }

    def _invalid_operation(
        self,
        index: int,
        message: str,
    ) -> dict[str, Any]:
        return {
            "status": "invalid_arguments",
            "message": f"operations[{index}]: {message}",
            "results": [],
            "required_operation_fields": list(REQUIRED_OPERATION_FIELDS),
            "example": self._request_for(
                self.registry["calc.country_count"]
            ),
        }

    def _canonical_id_suggestion(self, result_id: str) -> str | None:
        normalized = result_id.removeprefix("calc.")
        return next(
            (
                calculation_id
                for calculation_id in self.registry
                if calculation_id.removeprefix("calc.") == normalized
            ),
            None,
        )

    @staticmethod
    def _request_for(definition: dict[str, Any]) -> dict[str, Any]:
        return {
            "result_id": definition["id"],
            "operation_id": definition["operation_id"],
            "input_ids": deepcopy(definition["input_ids"]),
            "parameters": deepcopy(definition["parameters"]),
        }

    @staticmethod
    def _matches_definition(
        request: dict[str, Any], definition: dict[str, Any]
    ) -> bool:
        return (
            request.get("operation_id") == definition["operation_id"]
            and request.get("input_ids") == definition["input_ids"]
            and (request.get("parameters") or {}) == definition["parameters"]
        )

    def _execute_definition(self, definition: dict[str, Any]) -> dict[str, Any]:
        inputs = {
            role: self.store.get(node_id)
            for role, node_id in definition["input_ids"].items()
        }
        blocked = [
            node
            for node in inputs.values()
            if node.get("status") != "available"
        ]
        dependencies = list(definition["input_ids"].values())
        if blocked and definition["operation_id"] != "expression":
            statuses = {str(node.get("status")) for node in blocked}
            resolved_not_applicable = statuses <= {
                "not_applicable",
                "not_applicable_dependency",
            }
            return {
                "id": definition["id"],
                "kind": "calculated",
                "status": (
                    "not_applicable_dependency"
                    if resolved_not_applicable
                    else "missing_dependency"
                ),
                "value": None,
                "unit": definition["unit"],
                "operation_id": definition["operation_id"],
                "dependencies": dependencies,
                "missing_dependencies": [node["id"] for node in blocked],
                "missing_id": missing_id(definition["id"]),
            }
        try:
            value = self._apply(
                definition["operation_id"],
                inputs,
                definition["parameters"],
                definition=definition,
            )
        except CalculationDependencyUnavailable as exc:
            resolved_not_applicable = exc.status in {
                "not_applicable",
                "not_applicable_dependency",
            }
            return {
                "id": definition["id"],
                "kind": "calculated",
                "status": (
                    "not_applicable_dependency"
                    if resolved_not_applicable
                    else "missing_dependency"
                ),
                "value": None,
                "unit": definition["unit"],
                "operation_id": definition["operation_id"],
                "dependencies": dependencies,
                "missing_dependencies": [exc.node_id],
                "missing_id": missing_id(definition["id"]),
            }
        except CollectionCalculationUnavailable as exc:
            return {
                "id": definition["id"],
                "kind": "calculated",
                "status": "missing_dependency",
                "value": None,
                "unit": definition["unit"],
                "operation_id": definition["operation_id"],
                "dependencies": dependencies,
                "missing_dependencies": list(exc.dependency_ids),
                "missing_id": missing_id(definition["id"]),
                "message": str(exc),
            }
        except (ArithmeticError, TypeError, ValueError, KeyError) as exc:
            return {
                "id": definition["id"],
                "kind": "calculated",
                "status": "invalid_input",
                "value": None,
                "unit": definition["unit"],
                "operation_id": definition["operation_id"],
                "dependencies": dependencies,
                "message": str(exc),
            }
        if definition["operation_id"] == "expression" and value is None:
            return {
                "id": definition["id"],
                "kind": "calculated",
                "status": "not_applicable_dependency",
                "value": None,
                "unit": definition["unit"],
                "operation_id": definition["operation_id"],
                "dependencies": dependencies,
                "missing_dependencies": [],
                "missing_id": missing_id(definition["id"]),
                "message": "conditional expression resolved as not applicable",
            }
        return {
            "id": definition["id"],
            "kind": "calculated",
            "status": "available",
            "value": value,
            "unit": definition["unit"],
            "operation_id": definition["operation_id"],
            "dependencies": dependencies,
        }

    def _apply(
        self,
        operation_id: str,
        inputs: dict[str, dict[str, Any]],
        parameters: dict[str, Any],
        *,
        definition: dict[str, Any] | None = None,
    ) -> Any:
        if operation_id == "expression":
            ast = (definition or {}).get("expression_ast")
            if not isinstance(ast, dict):
                raise CalculationError("expression calculation lacks a compiled AST")
            values = {
                role: self._expression_value(node)
                for role, node in inputs.items()
            }
            return self._evaluate_expression(ast, values)
        values = {role: self._value(node) for role, node in inputs.items()}
        if operation_id == "sum":
            return sum(float(value) for value in values.values())
        if operation_id == "subtract":
            return float(values["minuend"]) - float(values["subtrahend"])
        if operation_id == "divide":
            denominator = float(values["denominator"])
            if denominator == 0:
                raise ArithmeticError("division by zero")
            return float(values["numerator"]) / denominator
        if operation_id == "percentage":
            whole = float(values["whole"])
            if whole == 0:
                raise ArithmeticError("division by zero")
            return float(values["part"]) / whole * 100
        if operation_id == "count_records":
            return len(self._records(inputs["records"]))
        if operation_id == "count_unavailable_field":
            field = str(parameters["field"])
            return sum(
                1
                for record in self._records(inputs["records"])
                if record.get("fields", {}).get(field, {}).get("status")
                != "available"
            )
        if operation_id == "zero_status":
            value = float(values["value"])
            if math.isclose(value, 0.0, rel_tol=1e-12, abs_tol=1e-6):
                return "balanced"
            return "sources below cost" if value > 0 else "sources above cost"
        if operation_id == "score_risks":
            return self._score_risks(self._records(inputs["records"]))
        if operation_id == "score_risk_priorities":
            return score_risk_priorities(
                self._records(inputs["records"]),
                result_id=str((definition or {})["id"]),
            )
        if operation_id == "count_field_status":
            return count_field_status(
                self._records(inputs["records"]),
                str(parameters["field"]),
                available=bool(parameters["available"]),
            )
        if operation_id == "max_available_field":
            return maximum_available_field(
                self._records(inputs["records"]),
                str(parameters["field"]),
            )
        if operation_id == "filter_equal_available":
            return filter_equal_available(
                self._records(inputs["records"]),
                str(parameters["field"]),
                float(values["target"]),
            )
        if operation_id == "join_kpi_priorities":
            return join_kpi_priorities(
                self._records(inputs["records"]),
                self._records(inputs["priorities"]),
                result_id=str((definition or {})["id"]),
            )
        if operation_id == "top_k_cutoff":
            return top_k_cutoff(
                self._records(inputs["records"]),
                str(parameters["field"]),
                k=int(parameters["k"]),
            )
        if operation_id == "filter_threshold_available":
            return filter_threshold_available(
                self._records(inputs["records"]),
                str(parameters["field"]),
                float(values["threshold"]),
                comparison=str(parameters["comparison"]),
            )
        if operation_id == "assess_kpi_mrv":
            return assess_kpi_mrv(
                self._records(inputs["records"]),
                result_id=str((definition or {})["id"]),
            )
        if operation_id == "assess_kpi_target_deltas":
            return assess_kpi_target_deltas(
                self._records(inputs["records"]),
                result_id=str((definition or {})["id"]),
            )
        if operation_id == "filter_field_value":
            return filter_field_value(
                self._records(inputs["records"]),
                str(parameters["field"]),
                parameters.get("value"),
            )
        if operation_id == "top_by":
            records = self._records(inputs["records"])
            field = str(parameters["field"])
            reverse = parameters["order"] == "descending"
            tie_break = str(parameters["tie_break"])
            return sorted(
                records,
                key=lambda item: (
                    self._field_number(item, field) * (-1 if reverse else 1),
                    self._field_number(item, tie_break),
                ),
            )[: int(parameters["k"])]
        if operation_id == "max_field":
            records = self._records(inputs["records"])
            return max(
                self._field_number(item, str(parameters["field"]))
                for item in records
            )
        if operation_id == "filter_equal":
            records = self._records(inputs["records"])
            target = float(values["target"])
            return [
                item
                for item in records
                if math.isclose(
                    self._field_number(item, str(parameters["field"])),
                    target,
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                )
            ]
        if operation_id == "compare":
            left = float(values["left"])
            right = float(values["right"])
            if math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12):
                return "="
            return "<" if left < right else ">"
        raise CalculationError(f"unsupported operation {operation_id!r}")

    @classmethod
    def _evaluate_expression(
        cls,
        ast: dict[str, Any],
        values: dict[str, Any],
    ) -> Any:
        node_type = ast.get("type")
        if node_type == "literal":
            return ast.get("value")
        if node_type == "identifier":
            name = str(ast.get("name") or "")
            if name not in values:
                raise CalculationError(f"unresolved expression input {name!r}")
            return cls._require_expression_value(values[name])
        if node_type == "array":
            return [
                cls._evaluate_expression(item, values)
                for item in ast.get("elements", [])
            ]
        if node_type == "unary":
            value = cls._evaluate_expression(ast["argument"], values)
            operator = ast.get("operator")
            if operator == "+":
                return float(value)
            if operator == "-":
                return -float(value)
            if operator == "!":
                return not bool(value)
            raise CalculationError(f"unsupported unary operator {operator!r}")
        if node_type == "binary":
            left = cls._evaluate_expression(ast["left"], values)
            operator = str(ast.get("operator") or "")
            if operator == "&&" and not bool(left):
                return left
            if operator == "||" and bool(left):
                return left
            right = cls._evaluate_expression(ast["right"], values)
            return cls._apply_expression_operator(operator, left, right)
        if node_type == "call":
            name = str(ast.get("name") or "")
            arguments_ast = ast.get("args", [])
            if name.lower() == "if" and len(arguments_ast) == 3:
                condition = cls._evaluate_expression(arguments_ast[0], values)
                selected = arguments_ast[1] if condition else arguments_ast[2]
                return cls._evaluate_expression(selected, values)
            arguments = [
                cls._evaluate_expression(item, values)
                for item in arguments_ast
            ]
            return cls._apply_expression_function(
                name, arguments
            )
        raise CalculationError(f"unsupported expression node {node_type!r}")

    @staticmethod
    def _apply_expression_operator(operator: str, left: Any, right: Any) -> Any:
        if operator == "+":
            return float(left) + float(right)
        if operator == "-":
            return float(left) - float(right)
        if operator == "*":
            return float(left) * float(right)
        if operator == "/":
            denominator = float(right)
            if denominator == 0:
                raise ArithmeticError("division by zero")
            return float(left) / denominator
        if operator == "%":
            denominator = float(right)
            if denominator == 0:
                raise ArithmeticError("division by zero")
            return float(left) % denominator
        if operator == "^":
            return float(left) ** float(right)
        if operator in {"<", "<=", ">", ">=", "==", "!="}:
            return {
                "<": left < right,
                "<=": left <= right,
                ">": left > right,
                ">=": left >= right,
                "==": left == right,
                "!=": left != right,
            }[operator]
        if operator == "&&":
            return right
        if operator == "||":
            return right
        raise CalculationError(f"unsupported binary operator {operator!r}")

    @classmethod
    def _apply_expression_function(
        cls,
        name: str,
        arguments: list[Any],
    ) -> Any:
        key = name.lower()
        numbers = cls._flatten_numeric(arguments)
        if key == "sum":
            return sum(numbers)
        if key in {"avg", "mean"}:
            return sum(numbers) / len(numbers) if numbers else 0
        if key == "min":
            return min(numbers) if numbers else 0
        if key == "max":
            return max(numbers) if numbers else 0
        if key == "abs" and len(arguments) == 1:
            return abs(float(arguments[0]))
        if key == "round" and arguments:
            digits = max(0, int(arguments[1] if len(arguments) > 1 else 0))
            factor = 10**digits
            return math.floor(float(arguments[0]) * factor + 0.5) / factor
        if key == "floor" and len(arguments) == 1:
            return math.floor(float(arguments[0]))
        if key == "ceil" and len(arguments) == 1:
            return math.ceil(float(arguments[0]))
        if key == "pow" and len(arguments) == 2:
            return float(arguments[0]) ** float(arguments[1])
        if key == "sqrt" and len(arguments) == 1:
            return math.sqrt(float(arguments[0]))
        if key == "log" and len(arguments) == 1:
            return math.log(float(arguments[0]))
        if key == "exp" and len(arguments) == 1:
            return math.exp(float(arguments[0]))
        if key == "clamp" and len(arguments) == 3:
            return min(
                float(arguments[2]),
                max(float(arguments[1]), float(arguments[0])),
            )
        if key == "count":
            return len(cls._flatten_values(arguments))
        if key == "percentage" and len(arguments) == 2:
            denominator = float(arguments[1])
            return 0 if denominator == 0 else float(arguments[0]) / denominator * 100
        if key == "ratio" and len(arguments) == 2:
            denominator = float(arguments[1])
            return 0 if denominator == 0 else float(arguments[0]) / denominator
        if key == "if" and len(arguments) == 3:
            return arguments[1] if arguments[0] else arguments[2]
        if key == "coalesce":
            return next(
                (
                    item
                    for item in arguments
                    if item is not None and item != ""
                ),
                None,
            )
        if key in {"series", "dataset"}:
            return cls._flatten_values(arguments)
        raise CalculationError(f"unsupported expression function {name!r}")

    @classmethod
    def _flatten_values(cls, values: list[Any]) -> list[Any]:
        output: list[Any] = []
        for value in values:
            if isinstance(value, list):
                output.extend(cls._flatten_values(value))
            else:
                output.append(value)
        return output

    @classmethod
    def _flatten_numeric(cls, values: list[Any]) -> list[float]:
        output = []
        for value in cls._flatten_values(values):
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(numeric):
                output.append(numeric)
        return output

    @staticmethod
    def _value(node: dict[str, Any]) -> Any:
        if node.get("kind") == "collection":
            return node.get("records", [])
        return node.get("value")

    @staticmethod
    def _expression_value(node: dict[str, Any]) -> Any:
        status = str(node.get("status") or "unknown")
        if status == "available":
            return Calculator._value(node)
        return _UnavailableExpressionValue(str(node.get("id") or ""), status)

    @staticmethod
    def _require_expression_value(value: Any) -> Any:
        if isinstance(value, _UnavailableExpressionValue):
            raise CalculationDependencyUnavailable(value.node_id, value.status)
        return value

    @staticmethod
    def _records(node: dict[str, Any]) -> list[dict[str, Any]]:
        if node.get("kind") == "collection":
            return deepcopy(node.get("records") or [])
        value = node.get("value")
        if not isinstance(value, list):
            raise TypeError(f"{node.get('id')}: expected record collection")
        return deepcopy(value)

    @staticmethod
    def _field_value(record: dict[str, Any], field: str) -> Any:
        item = record.get("fields", {}).get(field)
        if not isinstance(item, dict) or item.get("status") != "available":
            raise ValueError(f"{record.get('id')}.{field} is unavailable")
        return item.get("value")

    @classmethod
    def _field_number(cls, record: dict[str, Any], field: str) -> float:
        return float(cls._field_value(record, field))

    @classmethod
    def _score_risks(cls, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        scored = deepcopy(records)
        for record in scored:
            probability_label = str(
                cls._field_value(record, "probability")
            ).strip().lower()
            impact_label = str(cls._field_value(record, "impact")).strip().lower()
            if probability_label not in RISK_SCORES or impact_label not in RISK_SCORES:
                raise ValueError(f"{record['id']}: unsupported probability or impact")
            probability_score = RISK_SCORES[probability_label]
            impact_score = RISK_SCORES[impact_label]
            for name, value in (
                ("probability_score", probability_score),
                ("impact_score", impact_score),
                ("severity", probability_score * impact_score),
            ):
                record.setdefault("fields", {})[name] = {
                    "id": f"{record['id']}.{name}",
                    "kind": "scalar",
                    "description": name.replace("_", " "),
                    "status": "available",
                    "value": value,
                    "unit": "score",
                }
        return scored
