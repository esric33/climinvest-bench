"""Hand-reviewed fixture specifications for deterministic v2 enrichment.

The values in this module are benchmark-scenario parameters, not project facts.
They are deliberately small, explicit mappings: project assignment remains in
the study-population manifest, while this module records only the distinctions
that cannot safely be inferred from a project title or a financing amount.
"""

from __future__ import annotations

from typing import Final


GENERATOR_ID: Final = "climatefund20_contract_enrichment"
GENERATOR_VERSION: Final = "2.1.0"
MIN_SPECIALISATION_PEERS: Final = 3


FACILITY_ARCHETYPES: Final[dict[str, str]] = {
    "FP039": "cash_lending_or_investment",
    "FP063": "cash_lending_or_investment",
    "FP064": "revolving_initial_cycle",
    "FP071": "guarantee_or_exposure",
    "FP080": "cash_lending_or_investment",
    "FP081": "cash_lending_or_investment",
    "FP083": "cash_lending_or_investment",
    "FP106": "cash_lending_or_investment",
    "FP140": "cash_lending_or_investment",
    "FP148": "liquidity_relief",
    "FP163": "guarantee_or_exposure",
    "FP178": "guarantee_or_exposure",
    "FP196": "guarantee_or_exposure",
}


FACILITY_DEPLOYMENT_BASIS: Final[dict[str, str]] = {
    "cash_lending_or_investment": "cash advanced or invested",
    "revolving_initial_cycle": "initial-cycle cash advanced or invested",
    "guarantee_or_exposure": "guarantee capacity allocated or exposure activated",
    "liquidity_relief": "liquidity-loan principal advanced",
}


FACILITY_PORTFOLIO_TYPES: Final[dict[str, str]] = {
    "FP039": "subproject",
    "FP063": "borrower/company",
    "FP064": "subproject",
    "FP071": "borrower/company",
    "FP080": "subproject",
    "FP081": "loan",
    "FP083": "subproject",
    "FP106": "transaction",
    "FP140": "borrower/company",
    "FP148": "borrower/company",
    "FP163": "subproject",
    "FP178": "subproject",
    "FP196": "transaction",
}


# Fractions of the observed aggregate GCF financing amount.  Only instruments
# listed for an archetype are applicable; the remainder are explicit N/A nodes.
FACILITY_INSTRUMENT_MIX: Final[dict[str, dict[str, float]]] = {
    "cash_lending_or_investment": {
        "gcf_grant_usd": 0.08,
        "gcf_concessional_loan_usd": 0.92,
    },
    "revolving_initial_cycle": {
        "gcf_grant_usd": 0.04,
        "gcf_concessional_loan_usd": 0.96,
    },
    "guarantee_or_exposure": {
        "gcf_grant_usd": 0.10,
        "gcf_guarantee_usd": 0.90,
    },
    "liquidity_relief": {
        "gcf_concessional_loan_usd": 1.0,
    },
}


# FP083 is the one reviewed exception: its description exposes the complete
# USD 185m GCF mix.  The schedule remains synthetic; these fractions merely
# keep an enrichment fallback coherent if the atomic normalizer has not emitted
# the corresponding contract IDs.
FACILITY_INSTRUMENT_OVERRIDES: Final[dict[str, dict[str, float]]] = {
    "FP083": {
        "gcf_grant_usd": 10 / 185,
        "gcf_concessional_loan_usd": 25 / 185,
        "gcf_reimbursable_grant_usd": 150 / 185,
    },
    "FP178": {
        "gcf_grant_usd": 15 / 150,
        "gcf_concessional_loan_usd": 95 / 150,
        "gcf_guarantee_usd": 40 / 150,
    },
}


FACILITY_MOBILISATION_NOT_APPLICABLE: Final[frozenset[str]] = frozenset({"FP148"})


LAND_MODES: Final[dict[str, str]] = {
    "FP019": "jurisdictional_redd_plus",
    "FP128": "sustainable_plantation",
    "FP193": "forest_enterprise",
}


# Mutually exclusive categories entering the simplified benchmark carbon model.
# Activities outside this declared boundary remain narrative co-benefits.
LAND_PATHWAY_SHARES: Final[dict[str, dict[str, float]]] = {
    "FP019": {},
    "FP128": {"plantation_afforestation": 1.0},
    "FP193": {"forest_protection": 1.0},
}


LAND_DEFAULT_AREA_HA: Final[dict[str, float]] = {
    "FP019": 500_000.0,
    "FP128": 80_000.0,
    "FP193": 8_602.0,
}


ASSET_CAPACITY_RELATIONSHIPS: Final[dict[str, str]] = {
    "FP033": "capacity enabled downstream by programme-supported investment",
    "FP090": "renewable generation capacity financed and commissioned within the boundary",
    "FP102": "solar mini-grid capacity directly delivered by the project",
    "FP138": "solar mini-grid capacity directly delivered by the project",
}


ASSET_GENERATION_BOUNDARIES: Final[dict[str, str]] = {
    "FP033": (
        "Generation from programme-enabled renewable assets only; policy support, "
        "storage, reliability and network effects are excluded."
    ),
    "FP090": (
        "Generation from the renewable generation assets in the declared model "
        "boundary; storage and network-reinforcement effects are excluded."
    ),
    "FP102": "Generation from the 70 isolated solar mini-grid systems only.",
    "FP138": "Generation from the 1,000 solar mini-grid village systems only.",
}


ASSET_COMPARABLE_REPORTED_GHG: Final[frozenset[str]] = frozenset({"FP102", "FP138"})


FUNDING_SCOPE_MISMATCH: Final[frozenset[str]] = frozenset({"FP080", "FP128"})
FUNDING_SCOPE_UNDETERMINED: Final[frozenset[str]] = frozenset(
    {"FP071", "FP102", "FP138"}
)


COMMON_REQUIREMENT_GAPS: Final[dict[str, str]] = {
    "req.climate_rationale": "A complete source-backed climate-hazard, exposure and vulnerability rationale is not available as atomic evidence.",
    "req.promoter_financial_standing": "The promoter's current financial standing is not available as atomic evidence.",
    "req.promoter_track_record": "A comparable source-backed delivery track record for the promoter is not available as atomic evidence.",
    "req.project_status": "Current implementation status is not established by the normalized benchmark source.",
    "req.technical_feasibility_status": "A formal overall technical-feasibility conclusion is not available as atomic evidence.",
    "req.technical_design_maturity": "Technical design maturity is not available as atomic evidence.",
    "req.permitting_status": "A complete permitting status is not available as atomic evidence.",
    "req.procurement_plan": "A source-backed procurement plan and procurement status are not available as atomic evidence.",
    "req.land_and_access_status": "Land tenure, access and site-control status are not available as complete atomic evidence.",
    "req.detailed_implementation_schedule": "No source-backed dated activity-level critical path is present in the normalized evidence.",
    "req.business_model": "A complete source-backed business model is not available as atomic evidence.",
    "req.financial_model": "A complete source-backed financial model and its assumptions are not available as atomic evidence.",
    "req.revenue_model": "A complete revenue model is not available as atomic evidence.",
    "req.lifecycle_opex": "Lifecycle operating expenditure is not available as atomic evidence.",
    "req.financial_returns": "Comparable project-level financial-return measures are not available as atomic evidence.",
    "req.environmental_social_safeguards": "A complete environmental and social safeguards assessment is not available as atomic evidence.",
    "req.gender_assessment_and_action_plan": "A complete gender assessment and action plan are not available as atomic evidence.",
    "req.stakeholder_engagement": "A complete stakeholder-engagement record and grievance mechanism assessment are not available as atomic evidence.",
    "req.mrv_plan_status": "Formal MRV-plan completion status is not available as atomic evidence.",
    "req.ghg_target_horizon": "The source GHG point estimate does not consistently expose a separate atomic accounting horizon.",
    "req.financing_scope_comparability": "Financing-scope comparability is a benchmark qualification, not an audited source conclusion.",
}
