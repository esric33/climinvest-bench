"""Version-two benchmark contract and compiler bridge."""

from .contract import contract_summary, load_compiled_contract, validate_compiled_contract
from .contract_registry import (
    DEFAULT_CONTRACT_REGISTRY,
    ContractBinding,
    ContractRegistry,
)


def __getattr__(name: str):
    """Load runtime-heavy helpers lazily.

    This keeps ``python -m ...v2.enrichment_all20`` from importing the target
    module through package initialisation before ``runpy`` executes it.
    """

    if name == "preflight_project_contract":
        from .preflight import preflight_project_contract

        return preflight_project_contract
    if name in {
        "build_executable_gold",
        "validate_resolved_gold_population",
        "write_resolved_gold_population",
    }:
        from .oracle import (
            build_executable_gold,
            validate_resolved_gold_population,
            write_resolved_gold_population,
        )

        return {
            "build_executable_gold": build_executable_gold,
            "validate_resolved_gold_population": validate_resolved_gold_population,
            "write_resolved_gold_population": write_resolved_gold_population,
        }[name]
    raise AttributeError(name)

__all__ = [
    "contract_summary",
    "ContractBinding",
    "ContractRegistry",
    "DEFAULT_CONTRACT_REGISTRY",
    "build_executable_gold",
    "load_compiled_contract",
    "preflight_project_contract",
    "validate_compiled_contract",
    "validate_resolved_gold_population",
    "write_resolved_gold_population",
]
