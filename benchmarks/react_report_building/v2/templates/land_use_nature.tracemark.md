# {dt.project.title}

<!-- GCF bankability report contract: land-use and nature programmes. Tables
hold evidence and deterministic calculations. Each section has one
prompt-controlled llm component that interprets rather than repeats its tables.
Enriched inputs remain benchmark assumptions, not due-diligence facts. -->

:::calculation {#committed_funding_sources_usd}
label: Unqualified arithmetic sum of stated GCF finance and cofinance
expression: dt.project.gcf_financing_usd + dt.project.cofinance_usd
:::

:::calculation {#funding_reconciliation_gap_usd}
label: Scope-qualified signed stated-cost less stated-funding gap
expression: if(dt.project.funding_scope_comparability == "comparable", dt.project.total_cost_usd - committed_funding_sources_usd, null)
:::

:::calculation {#funding_reconciliation_gap_abs_usd}
label: Scope-qualified absolute stated funding reconciliation gap
expression: if(dt.project.funding_scope_comparability == "comparable", abs(funding_reconciliation_gap_usd), null)
:::

:::calculation {#funding_reconciliation_gap_pct}
label: Scope-qualified absolute funding gap as share of stated cost
expression: if(dt.project.funding_scope_comparability == "comparable", percentage(funding_reconciliation_gap_abs_usd, dt.project.total_cost_usd), null)
:::

:::calculation {#funding_reconciliation_status}
label: Scope-qualified funding reconciliation status
expression: if(dt.project.funding_scope_comparability == "comparable", if(funding_reconciliation_gap_pct <= 0.1, "reconciled_within_0.1_pct_tolerance", "not_reconciled_within_0.1_pct_tolerance"), "not_assessable_scope_mismatch")
:::

:::calculation {#funding_source_coverage_pct}
label: Scope-qualified share of stated cost covered by stated sources
expression: if(dt.project.funding_scope_comparability == "comparable", percentage(committed_funding_sources_usd, dt.project.total_cost_usd), null)
:::

:::calculation {#gcf_financing_share_of_cost_pct}
label: Scope-qualified GCF share of stated project cost
expression: if(dt.project.funding_scope_comparability == "comparable", percentage(dt.project.gcf_financing_usd, dt.project.total_cost_usd), null)
:::

:::calculation {#cofinance_share_of_cost_pct}
label: Scope-qualified cofinance share of stated project cost
expression: if(dt.project.funding_scope_comparability == "comparable", percentage(dt.project.cofinance_usd, dt.project.total_cost_usd), null)
:::

:::calculation {#cofinance_per_gcf_dollar}
label: Stated cofinance per GCF dollar
expression: if(dt.project.funding_scope_comparability == "comparable", ratio(dt.project.cofinance_usd, dt.project.gcf_financing_usd), null)
:::

:::calculation {#project_cost_per_reported_tco2e}
label: Scope-qualified stated project cost per reported target tCO2e
expression: if(dt.project.total_cost_scope == "whole_project" && dt.project.funding_scope_comparability == "comparable", ratio(dt.project.total_cost_usd, dt.project.ghg_reduction_tco2e), null)
:::

:::calculation {#gcf_financing_per_reported_tco2e}
label: GCF allocation per reported target tCO2e
expression: ratio(dt.project.gcf_financing_usd, dt.project.ghg_reduction_tco2e)
:::

:::calculation {#annualised_reported_ghg_target_tco2e}
label: Reported GHG target divided by explicit accounting horizon
expression: if(dt.project.ghg_target_horizon_years > 0, ratio(dt.project.ghg_reduction_tco2e, dt.project.ghg_target_horizon_years), null)
:::

:::calculation {#country_count}
label: Countries covered by the programme
expression: count(dt.project.countries)
:::

:::calculation {#risk_count}
label: Risk records available to the report
expression: count(dt.risks)
:::

:::calculation {#avoided_deforestation_rate_pct_per_year}
label: Applicable reduction in annual deforestation rate
expression: if(dt.project.protection_pathway_applicability == "applicable", dt.project.baseline_deforestation_rate_pct_per_year - dt.project.project_deforestation_rate_pct_per_year, null)
:::

:::calculation {#jurisdictional_gross_reduction_tco2e_per_year}
label: Applicable independently seeded jurisdictional scenario difference
expression: if(dt.project.jurisdictional_pathway_applicability == "applicable", dt.project.jurisdictional_reference_emissions_tco2e_per_year - dt.project.jurisdictional_program_emissions_tco2e_per_year, null)
:::

:::calculation {#allocated_intervention_area_ha}
label: Sum of applicable mutually exclusive activity-area allocations
expression: sum(if(dt.project.protection_pathway_applicability == "applicable", dt.project.forest_protection_area_target_ha, 0), if(dt.project.restoration_pathway_applicability == "applicable", dt.project.restoration_area_target_ha, 0), if(dt.project.plantation_afforestation_pathway_applicability == "applicable", dt.project.plantation_afforestation_area_target_ha, 0), if(dt.project.sustainable_management_pathway_applicability == "applicable", dt.project.sustainable_management_area_target_ha, 0))
:::

:::calculation {#land_area_reconciliation_gap_ha}
label: Signed intervention-area allocation gap
expression: if(dt.project.land_accounting_mode == "jurisdictional", null, dt.project.intervention_area_target_ha - allocated_intervention_area_ha)
:::

:::calculation {#land_area_reconciliation_gap_pct}
label: Absolute intervention-area allocation gap as share of stated total
expression: if(dt.project.land_accounting_mode == "jurisdictional", null, percentage(abs(land_area_reconciliation_gap_ha), dt.project.intervention_area_target_ha))
:::

:::calculation {#land_area_reconciliation_status}
label: Accounting-mode-qualified area reconciliation status
expression: if(dt.project.land_accounting_mode == "jurisdictional", "not_applicable_jurisdictional_boundary", if(land_area_reconciliation_gap_pct <= 0.1, "reconciled_within_0.1_pct_tolerance", "not_reconciled_within_0.1_pct_tolerance"))
:::

:::calculation {#protection_area_share_pct}
label: Applicable protection share of stated intervention area
expression: if(dt.project.protection_pathway_applicability == "applicable" && dt.project.land_accounting_mode != "jurisdictional", percentage(dt.project.forest_protection_area_target_ha, dt.project.intervention_area_target_ha), null)
:::

:::calculation {#restoration_area_share_pct}
label: Applicable restoration share of stated intervention area
expression: if(dt.project.restoration_pathway_applicability == "applicable" && dt.project.land_accounting_mode != "jurisdictional", percentage(dt.project.restoration_area_target_ha, dt.project.intervention_area_target_ha), null)
:::

:::calculation {#plantation_afforestation_area_share_pct}
label: Applicable plantation or afforestation share of stated intervention area
expression: if(dt.project.plantation_afforestation_pathway_applicability == "applicable" && dt.project.land_accounting_mode != "jurisdictional", percentage(dt.project.plantation_afforestation_area_target_ha, dt.project.intervention_area_target_ha), null)
:::

:::calculation {#sustainable_management_area_share_pct}
label: Applicable sustainable-management share of stated intervention area
expression: if(dt.project.sustainable_management_pathway_applicability == "applicable" && dt.project.land_accounting_mode != "jurisdictional", percentage(dt.project.sustainable_management_area_target_ha, dt.project.intervention_area_target_ha), null)
:::

:::calculation {#gross_protection_ghg_tco2e_per_year}
label: Applicable full-area annual gross protection-pathway GHG scenario
expression: if(dt.project.protection_pathway_applicability == "applicable", dt.project.forest_protection_area_target_ha * avoided_deforestation_rate_pct_per_year / 100 * dt.project.forest_carbon_stock_tco2e_per_ha, 0)
:::

:::calculation {#gross_restoration_ghg_tco2e_per_year}
label: Applicable full-area annual gross restoration-pathway GHG scenario
expression: if(dt.project.restoration_pathway_applicability == "applicable", dt.project.restoration_area_target_ha * dt.project.restoration_sequestration_tco2e_per_ha_year, 0)
:::

:::calculation {#gross_plantation_afforestation_ghg_tco2e_per_year}
label: Applicable full-area annual gross plantation or afforestation GHG scenario
expression: if(dt.project.plantation_afforestation_pathway_applicability == "applicable", dt.project.plantation_afforestation_area_target_ha * dt.project.plantation_afforestation_sequestration_tco2e_per_ha_year, 0)
:::

:::calculation {#gross_sustainable_management_ghg_tco2e_per_year}
label: Applicable full-area annual gross sustainable-management GHG scenario
expression: if(dt.project.sustainable_management_pathway_applicability == "applicable", dt.project.sustainable_management_area_target_ha * dt.project.sustainable_management_mitigation_tco2e_per_ha_year, 0)
:::

:::calculation {#full_enrolment_gross_ghg_tco2e_per_year}
label: Gross annual in-boundary GHG scenario at full coverage
expression: if(dt.project.land_accounting_mode == "jurisdictional", jurisdictional_gross_reduction_tco2e_per_year, sum(gross_protection_ghg_tco2e_per_year, gross_restoration_ghg_tco2e_per_year, gross_plantation_afforestation_ghg_tco2e_per_year, gross_sustainable_management_ghg_tco2e_per_year))
:::

:::calculation {#full_enrolment_effective_ghg_tco2e_per_year}
label: Full-coverage annual GHG after applicable effectiveness adjustment
expression: if(dt.project.implementation_effectiveness_adjustment_applicability == "apply", full_enrolment_gross_ghg_tco2e_per_year * dt.project.implementation_effectiveness_pct / 100, full_enrolment_gross_ghg_tco2e_per_year)
:::

:::calculation {#full_enrolment_post_leakage_ghg_tco2e_per_year}
label: Full-coverage annual GHG after applicable leakage deduction
expression: if(dt.project.leakage_adjustment_applicability == "apply", full_enrolment_effective_ghg_tco2e_per_year * (100 - dt.project.leakage_deduction_pct) / 100, full_enrolment_effective_ghg_tco2e_per_year)
:::

:::calculation {#full_enrolment_net_ghg_tco2e_per_year}
label: Full-coverage annual GHG after applicable permanence reserve
expression: if(dt.project.permanence_buffer_adjustment_applicability == "apply", full_enrolment_post_leakage_ghg_tco2e_per_year * (100 - dt.project.permanence_buffer_pct) / 100, full_enrolment_post_leakage_ghg_tco2e_per_year)
:::

:::calculation {#modelled_net_accounting_ghg_tco2e}
label: Simple full-coverage net GHG scenario over the stated land-accounting horizon
expression: full_enrolment_net_ghg_tco2e_per_year * dt.project.land_accounting_horizon_years
:::

:::calculation {#modelled_vs_reported_ghg_ratio}
label: Boundary-qualified independent-scenario to reported-target diagnostic ratio
expression: if(dt.project.reported_ghg_comparison_status == "comparable", ratio(modelled_net_accounting_ghg_tco2e, dt.project.ghg_reduction_tco2e), null)
:::

:::calculation {#reported_minus_modelled_ghg_tco2e}
label: Boundary-qualified reported target less independent land-GHG scenario
expression: if(dt.project.reported_ghg_comparison_status == "comparable", dt.project.ghg_reduction_tco2e - modelled_net_accounting_ghg_tco2e, null)
:::

:::calculation {#women_beneficiary_share_pct}
label: Ex-ante women allocation share of intended direct beneficiaries
expression: percentage(dt.project.women_beneficiaries_target, dt.project.direct_beneficiaries_target)
:::

:::calculation {#local_community_beneficiary_share_pct}
label: Ex-ante local-community allocation share of intended direct beneficiaries
expression: percentage(dt.project.local_community_beneficiaries_target, dt.project.direct_beneficiaries_target)
:::

:::calculation {#project_cost_per_intervention_hectare}
label: Scope-qualified stated project cost per activity hectare
expression: if(dt.project.total_cost_scope == "whole_project" && dt.project.land_accounting_mode != "jurisdictional", ratio(dt.project.total_cost_usd, dt.project.intervention_area_target_ha), null)
:::

:::calculation {#gcf_financing_per_intervention_hectare}
label: GCF allocation per activity hectare
expression: if(dt.project.land_accounting_mode != "jurisdictional", ratio(dt.project.gcf_financing_usd, dt.project.intervention_area_target_ha), null)
:::

:::calculation {#project_cost_per_direct_beneficiary}
label: Scope-qualified stated project cost per intended direct beneficiary
expression: if(dt.project.total_cost_scope == "whole_project", ratio(dt.project.total_cost_usd, dt.project.direct_beneficiaries_target), null)
:::

:::calculation {#gcf_financing_per_direct_beneficiary}
label: GCF allocation per intended direct beneficiary
expression: ratio(dt.project.gcf_financing_usd, dt.project.direct_beneficiaries_target)
:::

:::calculation {#gcf_financing_per_livelihood_enterprise}
label: GCF allocation per intended livelihood enterprise
expression: ratio(dt.project.gcf_financing_usd, dt.project.livelihood_enterprises_target)
:::

## Executive summary {#executive_summary}

### Decision evidence {#executive_summary_decision_evidence}

:::table {#executive_summary_table}
type: key-value
title: Executive decision evidence
data: dt.project.total_cost_usd, dt.project.gcf_financing_usd, dt.project.cofinance_usd, cofinance_per_gcf_dollar, funding_reconciliation_status, dt.project.ghg_reduction_tco2e, project_cost_per_reported_tco2e, dt.project.land_accounting_mode, dt.project.intervention_area_target_ha, modelled_vs_reported_ghg_ratio, calc.maximum_risk_priority_score, calc.maximum_priority_risk_count, calc.kpi_priority_cutoff, calc.priority_kpi_count, req.project_status, req.financial_model, req.technical_design_maturity, req.environmental_social_safeguards
headers: [Decision item, Position]
:::

### Executive interpretation {#executive_summary_interpretation}

:::llm {#executive_summary_text}
title: Executive assessment and critical issues
estimated_max_words: 220
output_contract: benchmark.executive_assessment.v1
instructions: |
  Give an investment-committee-style assessment, not a table recap. Identify the
  financing, land-use and intended impact proposition, then explain the two or
  three issues that most affect whether it can be assessed. Use
  {funding_reconciliation_status}, the boundary-qualified
  {modelled_vs_reported_ghg_ratio}, the exact maximum-tied risk set
  {calc.maximum_priority_risks}, and priority KPI set {calc.priority_kpis}.
  Preserve {dt.project.land_accounting_qualification},
  {dt.project.funding_scope_qualification}, and
  {req.synthetic_evidence_disclosure}. Do not issue an investment recommendation.
profile: neutral
:::

## Project identification and status {#project_identification_and_status}

### Project evidence {#project_identification_and_status_evidence}

:::table {#project_identification_and_status_table}
type: key-value
title: Project identification and stated status
data: dt.project.code, dt.project.title, dt.project.type, dt.project.sector, dt.project.size, dt.project.entity_name, dt.project.entity_type, dt.project.entity_sector, dt.project.entity_size, dt.project.countries, country_count, req.project_status
headers: [Field, Value]
:::

### Project mandate {#project_identification_and_status_mandate}

:::llm {#project_identification_and_status_text}
title: Project identification and status
estimated_max_words: 140
output_contract: benchmark.interpretive_assessment.v1
instructions: |
  Identify the programme, accredited entity, geography, sector and intended
  mandate using the table and {dt.project.description}. Do not reproduce every
  row. Explain which land-use or nature outcome is financed, and use
  {req.project_status} rather than inferring implementation status.
profile: neutral
:::

## Promoter and delivery arrangements {#promoter_and_delivery_arrangements}

### Delivery evidence {#promoter_and_delivery_arrangements_evidence}

:::table {#promoter_and_delivery_arrangements_table}
type: key-value
title: Promoter and delivery arrangements
data: dt.project.entity_name, dt.project.entity_type, dt.project.entity_sector, dt.project.entity_size, dt.project.implementation_agency, dt.project.delivery_mechanism, dt.project.governance_arrangements, dt.project.implementation_sequence, dt.project.implementation_years, req.promoter_financial_standing, req.promoter_track_record
headers: [Delivery item, Position]
:::

### Delivery assessment {#promoter_and_delivery_arrangements_assessment}

:::llm {#promoter_and_delivery_arrangements_text}
title: Promoter and delivery assessment
estimated_max_words: 180
output_contract: benchmark.interpretive_assessment.v1
instructions: |
  Explain how the accredited entity, implementation agency, jurisdictions and
  delivery partners divide responsibility. Identify the delivery dependency that
  matters most. Assess only what the evidence supports about institutional or
  financial capacity; use {req.promoter_financial_standing} and
  {req.promoter_track_record} as evidence requirements rather than filling gaps.
profile: neutral
:::

## Climate rationale and strategic fit {#climate_rationale_and_strategic_fit}

### Climate and policy evidence {#climate_rationale_and_strategic_fit_evidence}

:::table {#climate_rationale_and_strategic_fit_table}
type: key-value
title: Climate rationale and strategic fit
data: dt.project.mitigation_areas, dt.project.adaptation_areas, dt.project.countries, dt.project.land_use_baseline, dt.project.ghg_reduction_tco2e, dt.project.ghg_target_horizon_years, annualised_reported_ghg_target_tco2e, req.climate_rationale, req.ghg_target_horizon
headers: [Climate-rationale item, Position]
:::

### Strategic interpretation {#climate_rationale_and_strategic_fit_interpretation}

:::llm {#climate_rationale_and_strategic_fit_text}
title: Climate rationale and strategic fit
estimated_max_words: 180
output_contract: benchmark.interpretive_assessment.v1
instructions: |
  Explain the causal link between the land-use baseline, proposed pathways and
  intended mitigation or adaptation result. Use the project description but do
  not invent hazard projections, economic-loss baselines or policy alignment.
  State how {req.climate_rationale} and {req.ghg_target_horizon} limit the case.
  Treat {annualised_reported_ghg_target_tco2e} as an accounting normalisation only.
profile: neutral
:::

## Land-use baseline and intervention {#land_use_baseline_and_intervention}

### Baseline and pathway evidence {#land_use_baseline_and_intervention_evidence}

:::table {#land_use_baseline_and_intervention_table}
type: key-value
title: Land-use baseline and applicable intervention pathways
data: dt.project.land_use_baseline, dt.project.land_accounting_mode, dt.project.land_pathway_applicability, dt.project.baseline_deforestation_rate_pct_per_year, dt.project.project_deforestation_rate_pct_per_year, avoided_deforestation_rate_pct_per_year, dt.project.jurisdictional_reference_emissions_tco2e_per_year, dt.project.jurisdictional_program_emissions_tco2e_per_year, jurisdictional_gross_reduction_tco2e_per_year, dt.project.jurisdictional_accounting_qualification, dt.project.land_carbon_pathway_boundary
headers: [Baseline or pathway item, Position]
:::

### Intervention interpretation {#land_use_baseline_and_intervention_interpretation}

:::llm {#land_use_baseline_and_intervention_text}
title: Land-use baseline and intervention
estimated_max_words: 200
output_contract: benchmark.interpretive_assessment.v1
instructions: |
  Explain which land-use baseline and intervention pathways are applicable and
  why that matters for attribution. Use {avoided_deforestation_rate_pct_per_year}
  or {jurisdictional_gross_reduction_tco2e_per_year} only under the relevant
  applicability gate. Do not mix activity-area and jurisdictional boundaries.
  Preserve {dt.project.land_carbon_pathway_boundary} and
  {dt.project.jurisdictional_accounting_qualification}. Label enriched rates and
  jurisdictional emissions as independently seeded benchmark-scenario inputs,
  never observed performance or validation of the reported target.
profile: neutral
:::

## Area allocation and enrolment {#area_allocation_and_enrolment}

### Area reconciliation calculations {#area_allocation_and_enrolment_calculations}

:::table {#area_allocation_and_enrolment_table}
type: key-value
title: Area allocation and enrolment evidence
data: dt.project.land_accounting_mode, dt.project.intervention_area_target_ha, dt.project.jurisdictional_accounting_area_ha, dt.project.forest_protection_area_target_ha, protection_area_share_pct, dt.project.restoration_area_target_ha, restoration_area_share_pct, dt.project.plantation_afforestation_area_target_ha, plantation_afforestation_area_share_pct, dt.project.sustainable_management_area_target_ha, sustainable_management_area_share_pct, allocated_intervention_area_ha, land_area_reconciliation_gap_ha, land_area_reconciliation_gap_pct, land_area_reconciliation_status, req.land_and_access_status, req.detailed_implementation_schedule
headers: [Area item, Position]
:::

### Area interpretation {#area_allocation_and_enrolment_interpretation}

:::llm {#area_allocation_and_enrolment_text}
title: Area allocation and enrolment
estimated_max_words: 200
output_contract: benchmark.interpretive_assessment.v1
instructions: |
  Explain the applicable accounting area and whether mutually exclusive pathway
  allocations reconcile through {land_area_reconciliation_status}. Do not invent
  a period enrolment schedule. Interpret pathway shares only for an activity-area
  boundary and identify whether tenure, access or implementation timing can be
  assessed from {req.land_and_access_status} and
  {req.detailed_implementation_schedule}.
profile: neutral
:::

## Carbon-accounting consistency {#carbon_accounting_consistency}

### Bottom-up accounting calculation {#carbon_accounting_consistency_calculation}

:::table {#carbon_accounting_consistency_table}
type: key-value
title: Restricted-boundary independent land GHG scenario diagnostic
data: gross_protection_ghg_tco2e_per_year, gross_restoration_ghg_tco2e_per_year, gross_plantation_afforestation_ghg_tco2e_per_year, gross_sustainable_management_ghg_tco2e_per_year, jurisdictional_gross_reduction_tco2e_per_year, full_enrolment_gross_ghg_tco2e_per_year, dt.project.implementation_effectiveness_pct, dt.project.implementation_effectiveness_adjustment_applicability, full_enrolment_effective_ghg_tco2e_per_year, dt.project.leakage_deduction_pct, dt.project.leakage_adjustment_applicability, full_enrolment_post_leakage_ghg_tco2e_per_year, dt.project.permanence_buffer_pct, dt.project.permanence_buffer_adjustment_applicability, full_enrolment_net_ghg_tco2e_per_year, dt.project.land_accounting_horizon_years, modelled_net_accounting_ghg_tco2e, dt.project.ghg_reduction_tco2e, modelled_vs_reported_ghg_ratio, reported_minus_modelled_ghg_tco2e, dt.project.jurisdictional_accounting_qualification, dt.project.land_adjustment_scope_qualification, dt.project.land_accounting_qualification, dt.project.reported_ghg_comparison_qualification
headers: [Carbon-accounting item, Value]
:::

### Consistency interpretation {#carbon_accounting_consistency_interpretation}

:::llm {#carbon_accounting_consistency_text}
title: Carbon-accounting consistency
estimated_max_words: 230
output_contract: benchmark.interpretive_assessment.v1
instructions: |
  Trace the applicable pathway or jurisdictional gross result through effectiveness,
  leakage and permanence adjustments to {modelled_net_accounting_ghg_tco2e}.
  Explicitly state which adjustments apply, are already embedded or are not
  applicable. Compare with the reported target only when
  {dt.project.reported_ghg_comparison_status} permits, using
  {modelled_vs_reported_ghg_ratio}. For the jurisdictional pathway, state that the
  reference/program values were generated independently of the reported target and
  preserve {dt.project.jurisdictional_accounting_qualification}. Treat the ratio as
  a scenario-to-target gap diagnostic, never a validation result. Preserve all
  boundary qualifications. This is a simple scenario, not replacement GCF carbon
  accounting.
profile: neutral
:::

## People and co-benefits {#people_and_cobenefits}

### Distribution and allocation calculations {#people_and_cobenefits_calculations}

:::table {#people_and_cobenefits_table}
type: key-value
title: Ex-ante reach allocation scenario and co-benefits
data: dt.project.direct_beneficiaries_target, dt.project.women_beneficiaries_target, women_beneficiary_share_pct, dt.project.local_community_beneficiaries_target, local_community_beneficiary_share_pct, dt.project.livelihood_enterprises_target, project_cost_per_direct_beneficiary, gcf_financing_per_direct_beneficiary, gcf_financing_per_livelihood_enterprise, dt.project.beneficiary_allocation_qualification, dt.project.biodiversity_cobenefits, dt.project.livelihood_cobenefits, req.synthetic_evidence_disclosure
headers: [People or co-benefit item, Value]
:::

### Distributional interpretation {#people_and_cobenefits_interpretation}

:::llm {#people_and_cobenefits_text}
title: People and co-benefits
estimated_max_words: 200
output_contract: benchmark.interpretive_assessment.v1
instructions: |
  Interpret intended reach, gender and local-community allocations, and the stated
  biodiversity and livelihood co-benefits. Preserve
  {dt.project.beneficiary_allocation_qualification} and identify which targets are
  source-backed versus synthetic. Treat subgroup shares, per-beneficiary values and
  per-enterprise values only as ex-ante allocation diagnostics, not evidence of
  delivery, participation, equity, performance, benefit value, cost effectiveness
  or unique-person counts. Preserve population-set distinctions and do not monetise
  or assert delivery of qualitative co-benefits.
profile: neutral
:::

## Technical feasibility and implementation readiness {#technical_feasibility_and_readiness}

### Readiness evidence {#technical_feasibility_and_readiness_evidence}

:::table {#technical_feasibility_and_readiness_table}
type: key-value
title: Technical feasibility and implementation readiness
data: dt.project.delivery_mechanism, dt.project.implementation_sequence, dt.project.implementation_years, dt.project.land_accounting_mode, dt.project.land_pathway_applicability, req.project_status, req.technical_feasibility_status, req.technical_design_maturity, req.permitting_status, req.land_and_access_status, req.procurement_plan, req.detailed_implementation_schedule
headers: [Readiness item, Position]
:::

### Readiness assessment {#technical_feasibility_and_readiness_assessment}

:::llm {#technical_feasibility_and_readiness_text}
title: Technical feasibility and implementation readiness
estimated_max_words: 190
output_contract: benchmark.interpretive_assessment.v1
instructions: |
  State what the evidence establishes about pathway design and implementation
  maturity, then identify the most material unresolved readiness items. Treat
  absent design, permits, tenure/access, procurement or schedule evidence as
  limitations, not negative findings. Do not derive a readiness score or treat an
  area target as proof of enrolment or implementation capacity.
profile: neutral
:::

## Costs and financing structure {#costs_and_financing_structure}

### Financing calculations {#costs_and_financing_structure_calculations}

:::table {#costs_and_financing_structure_table}
type: key-value
title: Costs and financing structure
data: dt.project.total_cost_usd, dt.project.gcf_financing_usd, dt.project.cofinance_usd, committed_funding_sources_usd, funding_reconciliation_gap_usd, funding_reconciliation_gap_pct, funding_reconciliation_status, funding_source_coverage_pct, gcf_financing_share_of_cost_pct, cofinance_share_of_cost_pct, cofinance_per_gcf_dollar, dt.project.total_cost_scope, dt.project.gcf_financing_scope, dt.project.cofinance_scope, dt.project.funding_scope_comparability, dt.project.funding_scope_qualification
headers: [Financing item, Position]
:::

### Financing interpretation {#costs_and_financing_structure_interpretation}

:::llm {#costs_and_financing_structure_text}
title: Costs and financing structure
estimated_max_words: 200
output_contract: benchmark.interpretive_assessment.v1
instructions: |
  Interpret the funding structure and arithmetic reconciliation rather than
  repeating amounts. Explain what {cofinance_per_gcf_dollar} says about stated
  cofinance and what it does not say about viability or return. Use
  {funding_reconciliation_status} only under
  {dt.project.funding_scope_comparability}. When scopes are not comparable or are
  undetermined, do not report a funding gap, coverage percentage or cost share;
  describe {committed_funding_sources_usd} only as an unqualified arithmetic sum.
  Preserve every scope and call any assessable reconciliation an arithmetic check,
  not an audit finding.
profile: neutral
:::

## Financial sustainability and business model {#financial_sustainability_and_business_model}

### Sustainability evidence {#financial_sustainability_and_business_model_evidence}

:::table {#financial_sustainability_and_business_model_table}
type: key-value
title: Financial sustainability and business-model evidence
data: project_cost_per_intervention_hectare, gcf_financing_per_intervention_hectare, project_cost_per_direct_beneficiary, gcf_financing_per_direct_beneficiary, req.business_model, req.revenue_model, req.lifecycle_opex, req.financial_model, req.financial_returns
headers: [Sustainability item, Position]
:::

### Sustainability assessment {#financial_sustainability_and_business_model_assessment}

:::llm {#financial_sustainability_and_business_model_text}
title: Financial sustainability and business model
estimated_max_words: 190
output_contract: benchmark.interpretive_assessment.v1
instructions: |
  Explain whether recurrent financing, operating sustainability, repayment capacity
  or returns can be assessed from {req.business_model}, {req.revenue_model},
  {req.lifecycle_opex}, {req.financial_model}, and {req.financial_returns}. Use
  per-hectare and per-beneficiary calculations only as scale descriptors. Do not
  derive FIRR, EIRR, NPV or avoided-damage value without the required evidence.
profile: neutral
:::

## Impact, ESG, and safeguards {#impact_esg_and_safeguards}

### Impact and safeguards evidence {#impact_esg_and_safeguards_evidence}

:::table {#impact_esg_and_safeguards_table}
type: key-value
title: Impact, ESG, and safeguards
data: dt.project.ghg_reduction_tco2e, dt.project.ghg_target_horizon_years, annualised_reported_ghg_target_tco2e, project_cost_per_reported_tco2e, gcf_financing_per_reported_tco2e, dt.project.direct_beneficiaries_target, women_beneficiary_share_pct, local_community_beneficiary_share_pct, dt.project.biodiversity_cobenefits, dt.project.livelihood_cobenefits, req.environmental_social_safeguards, req.gender_assessment_and_action_plan, req.stakeholder_engagement, dt.project.ghg_accounting_qualification
headers: [Impact or safeguards item, Position]
:::

### Impact and safeguards assessment {#impact_esg_and_safeguards_assessment}

:::llm {#impact_esg_and_safeguards_text}
title: Impact, ESG, and safeguards
estimated_max_words: 220
output_contract: benchmark.interpretive_assessment.v1
instructions: |
  Interpret the scale, distribution and accounting boundary of intended climate,
  biodiversity and livelihood results. Use {project_cost_per_reported_tco2e} only
  when its scope gate permits and call financing-per-impact values ex-ante
  allocation intensities. Explain whether safeguards, gender, tenure and
  stakeholder evidence is sufficient; do not infer compliance or benefit-sharing
  quality from target counts. Preserve {dt.project.ghg_accounting_qualification}.
profile: neutral
:::

## Performance indicators and MRV {#performance_indicators_and_mrv}

### Complete KPI register {#performance_indicators_and_mrv_register}

:::table {#performance_indicators_and_mrv_table}
type: records
title: Results indicators with benchmark priority and MRV readiness
data: calc.kpi_mrv_assessments
headers: [Indicator, Baseline, Intermediate target, Final target, Verification, Benchmark reporting priority, Benchmark priority basis, MRV readiness status, MRV missing fields, Assumptions]
:::

### Compatible target-change calculations {#performance_indicators_and_mrv_target_deltas}

:::table {#performance_indicator_target_deltas_table}
type: records
title: Baseline-to-final-target calculations
data: calc.kpi_target_delta_assessments
headers: [Indicator, Baseline, Final target, Benchmark reporting priority, Target delta status, Target absolute change, Target percentage change (pct)]
:::

### Priority results and measurability {#performance_indicators_and_mrv_interpretation}

:::llm {#performance_indicators_and_mrv_text}
title: Performance indicators and MRV
estimated_max_words: 220
output_contract: benchmark.kpi_priority.v1
instructions: |
  Do not narrate every KPI row. Discuss exactly the priority set
  {calc.priority_kpis}, selected at inclusive cutoff {calc.kpi_priority_cutoff},
  including all ties; state that {calc.priority_kpi_count} records were selected
  from {calc.available_kpi_priority_count} rankable records out of
  {calc.prioritized_kpi_count} total. State that
  {calc.incomplete_kpi_priority_count} records remain unranked rather than being
  scored as zero. For each selected KPI, explain its intended
  result, its status in {calc.kpi_mrv_assessments}, and any available compatible
  change in {calc.kpi_target_delta_assessments}. State the overall MRV-ready count
  {calc.mrv_ready_kpi_count} and compatible-delta count
  {calc.kpi_compatible_target_delta_count} as coverage diagnostics, not performance.
  Relate weaknesses to {dt.project.monitoring_reporting_process} and
  {req.mrv_plan_status}; do not compare incompatible units.
profile: neutral
:::

## Risk and bankability constraints {#risk_and_bankability_constraints}

### Complete scored risk register {#risk_and_bankability_constraints_register}

:::table {#risk_and_bankability_constraints_table}
type: records
title: Risk register with ordinal benchmark priority score
data: calc.scored_risks
headers: [Risk, Type, Probability, Impact, Probability score, Impact score, Priority score, Priority scoring status, Description, Mitigation]
:::

### Maximum-priority risks {#risk_and_bankability_constraints_interpretation}

:::llm {#risk_and_bankability_constraints_text}
title: Risk and bankability constraints
estimated_max_words: 230
output_contract: benchmark.risk_priority.v1
instructions: |
  Do not narrate every risk row. Discuss exactly all scoreable risks tied at the
  maximum ordinal score {calc.maximum_risk_priority_score}, using the complete set
  {calc.maximum_priority_risks} in source order and stating the selected count
  {calc.maximum_priority_risk_count}. State that {calc.scored_risk_count} risks are
  scored and {calc.incomplete_risk_count} are unscored. Explain why each selected
  risk matters and whether its mitigation leaves a material residual issue. The
  score is probability rank times impact rank with low=1, medium=2 and high=3; it
  is a benchmark screening index, not expected loss. Treat unscored records as an
  evidence limitation, never as low risk.
profile: neutral
:::

## Conclusions and evidence requirements {#conclusions_and_evidence_requirements}

### Deterministic bankability anchors {#conclusions_and_evidence_requirements_anchors}

:::table {#conclusions_and_evidence_requirements_table}
type: key-value
title: Deterministic bankability anchors
data: funding_reconciliation_status, cofinance_per_gcf_dollar, land_area_reconciliation_status, modelled_vs_reported_ghg_ratio, women_beneficiary_share_pct, local_community_beneficiary_share_pct, calc.maximum_risk_priority_score, calc.maximum_priority_risk_count, calc.scored_risk_count, calc.incomplete_risk_count, calc.kpi_priority_cutoff, calc.priority_kpi_count, calc.available_kpi_priority_count, calc.incomplete_kpi_priority_count, calc.mrv_ready_kpi_count, calc.kpi_compatible_target_delta_count
headers: [Conclusion input, Position]
:::

### Due-diligence evidence readiness {#conclusions_and_evidence_requirements_readiness}

:::table {#evidence_readiness_and_conditions_table}
type: key-value
title: Evidence readiness and conditions for further review
data: req.project_status, req.promoter_financial_standing, req.promoter_track_record, req.climate_rationale, req.technical_feasibility_status, req.technical_design_maturity, req.permitting_status, req.land_and_access_status, req.procurement_plan, req.detailed_implementation_schedule, req.business_model, req.revenue_model, req.lifecycle_opex, req.financial_model, req.financial_returns, req.environmental_social_safeguards, req.gender_assessment_and_action_plan, req.stakeholder_engagement, req.mrv_plan_status, req.synthetic_evidence_disclosure
headers: [Evidence requirement, Current evidence position]
:::

### Evidence and calculation register {#conclusions_and_evidence_requirements_register}

:::table {#evidence_and_calculation_register_table}
type: key-value
title: Evidence and calculation register
data: committed_funding_sources_usd, funding_reconciliation_gap_usd, funding_reconciliation_gap_pct, funding_reconciliation_status, funding_source_coverage_pct, gcf_financing_share_of_cost_pct, cofinance_share_of_cost_pct, cofinance_per_gcf_dollar, project_cost_per_reported_tco2e, gcf_financing_per_reported_tco2e, annualised_reported_ghg_target_tco2e, avoided_deforestation_rate_pct_per_year, jurisdictional_gross_reduction_tco2e_per_year, allocated_intervention_area_ha, land_area_reconciliation_gap_pct, land_area_reconciliation_status, full_enrolment_gross_ghg_tco2e_per_year, full_enrolment_effective_ghg_tco2e_per_year, full_enrolment_post_leakage_ghg_tco2e_per_year, full_enrolment_net_ghg_tco2e_per_year, modelled_net_accounting_ghg_tco2e, modelled_vs_reported_ghg_ratio, women_beneficiary_share_pct, local_community_beneficiary_share_pct, project_cost_per_intervention_hectare, gcf_financing_per_intervention_hectare, calc.prioritized_kpi_count, calc.available_kpi_priority_count, calc.incomplete_kpi_priority_count, calc.kpi_priority_cutoff, calc.priority_kpi_count, calc.mrv_ready_kpi_count, calc.kpi_compatible_target_delta_count, risk_count, calc.scored_risk_count, calc.incomplete_risk_count, calc.maximum_risk_priority_score, calc.maximum_priority_risk_count, dt.project.funding_scope_qualification, dt.project.land_carbon_pathway_boundary, dt.project.land_adjustment_scope_qualification, dt.project.land_accounting_qualification, req.synthetic_evidence_disclosure
headers: [Registered item, Value or qualification]
:::

### Evidence-based conclusion {#conclusions_and_evidence_requirements_interpretation}

:::llm {#conclusions_and_evidence_requirements_text}
title: Conclusions and evidence requirements
estimated_max_words: 270
output_contract: benchmark.evidence_requirements.v1
instructions: |
  Give a bounded conclusion on what is currently assessable. Integrate funding
  reconciliation {funding_reconciliation_status}, area reconciliation,
  land-carbon consistency, distributional reach, maximum-risk result
  {calc.maximum_risk_priority_score} and priority-KPI cutoff
  {calc.kpi_priority_cutoff} without restating tables. Convert the few gaps most
  material to assessment, including {req.financial_model},
  {req.technical_design_maturity} and {req.environmental_social_safeguards}, into
  specific evidence requests or conditions for further review. Distinguish source-backed facts, deterministic
  calculations, synthetic benchmark assumptions and missing due-diligence evidence.
  Explain that the register improves traceability without validating its inputs.
  Do not approve, decline or make an investment recommendation.
profile: neutral
:::
