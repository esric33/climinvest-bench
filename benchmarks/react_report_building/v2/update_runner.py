"""Public v2 canonical-update API.

The implementation shares the v2 runtime context in :mod:`.runner`; this module
provides a stable, update-specific import path for planners and schedulers.
"""

from .perturbations import public_mutation_event, public_mutation_twin
from .runner import (
    UpdateReadinessError,
    prepare_canonical_t0,
    prepare_update_case,
    preflight_update_case,
    reduce_section_update_results,
    run_report_update,
    run_section_update,
    run_section_updates,
)

__all__ = [
    "UpdateReadinessError",
    "prepare_canonical_t0",
    "prepare_update_case",
    "preflight_update_case",
    "public_mutation_event",
    "public_mutation_twin",
    "reduce_section_update_results",
    "run_report_update",
    "run_section_update",
    "run_section_updates",
]
