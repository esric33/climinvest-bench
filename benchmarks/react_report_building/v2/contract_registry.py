from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ..util import read_json
from .contract import V2_ROOT
from .study_design import (
    POPULATION_PATH,
    load_population,
    project_specialisation_assignments,
    projects_by_specialisation,
    validate_study_population,
)


CONTRACT_ROOT = V2_ROOT / "data" / "contracts"
CONTRACT_IDS = (
    "asset_delivery",
    "financing_facility",
    "land_use_nature",
)
# Compatibility name for callers that used the FP083 pilot's sole binding.
CURRENT_CONTRACT_ID = "financing_facility"


def normalize_project_id(project_id: str) -> str:
    normalized = str(project_id or "").strip().upper()
    if not normalized:
        raise ValueError("project_id must be non-empty")
    return normalized


@dataclass(frozen=True)
class ContractBinding:
    """Bind one compiled document contract to its supported project cohort.

    Compiled artifacts are project-neutral, while bindings always retain the
    explicit fixed population cohort for which that template was selected.
    """

    contract_id: str
    compiled_contract_path: Path
    project_ids: frozenset[str] | None

    def __post_init__(self) -> None:
        contract_id = str(self.contract_id or "").strip()
        if not contract_id:
            raise ValueError("contract_id must be non-empty")
        object.__setattr__(self, "contract_id", contract_id)
        object.__setattr__(self, "compiled_contract_path", Path(self.compiled_contract_path))
        if self.project_ids is not None:
            normalized = frozenset(normalize_project_id(item) for item in self.project_ids)
            if not normalized:
                raise ValueError(
                    "project_ids must be non-empty or None for a project-neutral contract"
                )
            object.__setattr__(self, "project_ids", normalized)

    def supports(self, project_id: str) -> bool:
        project = normalize_project_id(project_id)
        return self.project_ids is None or project in self.project_ids

    def load(self) -> dict[str, Any]:
        if not self.compiled_contract_path.is_file():
            raise ValueError(
                f"{self.contract_id}: compiled contract is missing: "
                f"{self.compiled_contract_path}"
            )
        payload = read_json(self.compiled_contract_path)
        if payload.get("schema_version") != "react_report.compiled_contract/v2":
            raise ValueError(
                f"{self.contract_id}: unexpected compiled-contract schema version"
            )
        declared_id = payload.get("contract_id")
        if declared_id is not None and declared_id != self.contract_id:
            raise ValueError(
                f"{self.contract_id}: compiled contract declares {declared_id!r}"
            )
        template_id = payload.get("template_id")
        if template_id is not None and template_id != self.contract_id:
            raise ValueError(
                f"{self.contract_id}: compiled contract declares template "
                f"{template_id!r}"
            )
        if payload.get("project_neutral") is not True:
            raise ValueError(
                f"{self.contract_id}: compiled family contract must be project-neutral"
            )
        if payload.get("project_code") not in {None, ""}:
            raise ValueError(
                f"{self.contract_id}: project-neutral contract declares a project code"
            )
        population_binding = payload.get("population_binding")
        if not isinstance(population_binding, dict):
            raise ValueError(
                f"{self.contract_id}: compiled contract lacks a population binding"
            )
        if population_binding.get("template_is_experimental_condition") is not False:
            raise ValueError(
                f"{self.contract_id}: template must not be an experimental condition"
            )
        if (
            population_binding.get("manifest_path")
            != "v2/data/study/twenty-project-study-population.json"
        ):
            raise ValueError(
                f"{self.contract_id}: compiled contract points at an unexpected "
                "population manifest"
            )
        actual_hash = hashlib.sha256(POPULATION_PATH.read_bytes()).hexdigest()
        if population_binding.get("manifest_sha256") != actual_hash:
            raise ValueError(
                f"{self.contract_id}: compiled contract population binding is stale"
            )
        if self.project_ids is not None:
            declared_projects = frozenset(
                normalize_project_id(item)
                for item in population_binding.get("assigned_project_ids", [])
            )
            if declared_projects != self.project_ids:
                raise ValueError(
                    f"{self.contract_id}: compiled contract cohort differs from "
                    "the authoritative population"
                )
            if population_binding.get("assigned_project_count") != len(self.project_ids):
                raise ValueError(
                    f"{self.contract_id}: compiled contract cohort count is incorrect"
                )
        return payload


class ContractRegistry:
    """Resolve explicit or cohort-compatible compiled contracts without fallback."""

    def __init__(self, bindings: Iterable[ContractBinding]) -> None:
        by_id: dict[str, ContractBinding] = {}
        for binding in bindings:
            if binding.contract_id in by_id:
                raise ValueError(f"duplicate contract_id {binding.contract_id!r}")
            by_id[binding.contract_id] = binding
        if not by_id:
            raise ValueError("contract registry requires at least one binding")
        self._by_id = by_id

    @classmethod
    def from_population(
        cls,
        population: dict[str, Any] | None = None,
        *,
        contract_root: Path = CONTRACT_ROOT,
    ) -> "ContractRegistry":
        """Build the only default registry: the frozen twenty-project mapping."""

        payload = population if population is not None else load_population()
        errors = validate_study_population(payload)
        if errors:
            raise ValueError("invalid study population: " + "; ".join(errors))
        assignments = project_specialisation_assignments(payload)
        unknown_templates = sorted(set(assignments.values()) - set(CONTRACT_IDS))
        missing_templates = sorted(set(CONTRACT_IDS) - set(assignments.values()))
        if unknown_templates or missing_templates:
            raise ValueError(
                "study population does not map exactly to compiled contracts; "
                f"unknown={unknown_templates}, missing={missing_templates}"
            )
        projects_by_template = projects_by_specialisation(payload)
        return cls(
            ContractBinding(
                contract_id=contract_id,
                compiled_contract_path=(
                    Path(contract_root) / f"{contract_id}.compiled.json"
                ),
                project_ids=frozenset(projects_by_template[contract_id]),
            )
            for contract_id in CONTRACT_IDS
        )

    def contract_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_id))

    def get(self, contract_id: str) -> ContractBinding:
        key = str(contract_id or "").strip()
        try:
            return self._by_id[key]
        except KeyError as exc:
            raise ValueError(
                f"unknown v2 contract {key!r}; available: {', '.join(self.contract_ids())}"
            ) from exc

    def resolve(
        self,
        *,
        project_id: str,
        contract_id: str | None = None,
    ) -> ContractBinding:
        project = normalize_project_id(project_id)
        if contract_id is not None:
            binding = self.get(contract_id)
            if not binding.supports(project):
                raise ValueError(
                    f"v2 contract {binding.contract_id!r} does not support {project}"
                )
            return binding

        candidates = [
            binding for binding in self._by_id.values() if binding.supports(project)
        ]
        if not candidates:
            raise ValueError(f"no registered v2 contract supports {project}")
        if len(candidates) > 1:
            choices = ", ".join(sorted(item.contract_id for item in candidates))
            raise ValueError(
                f"multiple v2 contracts support {project}; select one of: {choices}"
            )
        return candidates[0]


DEFAULT_CONTRACT_REGISTRY = ContractRegistry.from_population()
