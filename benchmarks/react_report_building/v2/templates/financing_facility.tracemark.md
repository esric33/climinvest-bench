# {dt.project.title}

<!-- GCF bankability report contract: financing facilities and investment
programmes. Tables hold evidence and deterministic calculations. Each section
has one prompt-controlled llm component that interprets rather than repeats its
tables. Enriched inputs remain benchmark assumptions, not due-diligence facts. -->

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

:::calculation {#gcf_instrument_total_usd}
label: Total configured GCF instrument face amount
expression: sum(dt.project.gcf_grant_usd, dt.project.gcf_concessional_loan_usd, dt.project.gcf_reimbursable_grant_usd, dt.project.gcf_guarantee_usd, dt.project.gcf_equity_usd)
:::

:::calculation {#gcf_instrument_reconciliation_gap_usd}
label: Aggregate GCF financing less configured instrument total
expression: dt.project.gcf_financing_usd - gcf_instrument_total_usd
:::

:::calculation {#gcf_instrument_reconciliation_gap_abs_usd}
label: Absolute GCF instrument reconciliation gap
expression: abs(gcf_instrument_reconciliation_gap_usd)
:::

:::calculation {#gcf_instrument_reconciliation_gap_pct}
label: GCF instrument gap as share of aggregate GCF financing
expression: percentage(gcf_instrument_reconciliation_gap_abs_usd, dt.project.gcf_financing_usd)
:::

:::calculation {#gcf_instrument_reconciliation_status}
label: GCF instrument reconciliation status
expression: if(gcf_instrument_reconciliation_gap_pct <= 0.1, "reconciled_within_0.1_pct_tolerance", "not_reconciled_within_0.1_pct_tolerance")
:::

:::calculation {#gcf_grant_share_pct}
label: Grant share of configured GCF instrument face amount
expression: percentage(dt.project.gcf_grant_usd, gcf_instrument_total_usd)
:::

:::calculation {#gcf_concessional_loan_share_pct}
label: Concessional-loan share of configured GCF instrument face amount
expression: percentage(dt.project.gcf_concessional_loan_usd, gcf_instrument_total_usd)
:::

:::calculation {#gcf_reimbursable_grant_share_pct}
label: Reimbursable-grant share of configured GCF instrument face amount
expression: percentage(dt.project.gcf_reimbursable_grant_usd, gcf_instrument_total_usd)
:::

:::calculation {#gcf_guarantee_share_pct}
label: Guarantee share of configured GCF instrument face amount
expression: percentage(dt.project.gcf_guarantee_usd, gcf_instrument_total_usd)
:::

:::calculation {#gcf_equity_share_pct}
label: Equity share of configured GCF instrument face amount
expression: percentage(dt.project.gcf_equity_usd, gcf_instrument_total_usd)
:::

:::calculation {#deployment_envelope_per_gcf_dollar}
label: Facility deployment envelope per GCF dollar
expression: ratio(dt.project.facility_deployment_envelope_usd, dt.project.gcf_financing_usd)
:::

:::calculation {#deployment_envelope_per_portfolio_unit}
label: Facility deployment envelope per typed portfolio unit
expression: if(dt.project.portfolio_unit_count > 0, ratio(dt.project.facility_deployment_envelope_usd, dt.project.portfolio_unit_count), null)
:::

:::calculation {#additional_capital_mobilized_mid_usd}
label: Midpoint of applicable additional-capital objective
expression: if(dt.project.mobilization_applicability == "applicable", mean(dt.project.additional_capital_mobilized_min_usd, dt.project.additional_capital_mobilized_max_usd), null)
:::

:::calculation {#additional_capital_per_gcf_dollar_low}
label: Low additional-capital objective per GCF dollar
expression: if(dt.project.mobilization_applicability == "applicable", ratio(dt.project.additional_capital_mobilized_min_usd, dt.project.gcf_financing_usd), null)
:::

:::calculation {#additional_capital_per_gcf_dollar_high}
label: High additional-capital objective per GCF dollar
expression: if(dt.project.mobilization_applicability == "applicable", ratio(dt.project.additional_capital_mobilized_max_usd, dt.project.gcf_financing_usd), null)
:::

:::calculation {#additional_capital_per_deployment_envelope_dollar_low}
label: Low additional-capital objective per deployment-envelope dollar
expression: if(dt.project.mobilization_applicability == "applicable", ratio(dt.project.additional_capital_mobilized_min_usd, dt.project.facility_deployment_envelope_usd), null)
:::

:::calculation {#additional_capital_per_deployment_envelope_dollar_high}
label: High additional-capital objective per deployment-envelope dollar
expression: if(dt.project.mobilization_applicability == "applicable", ratio(dt.project.additional_capital_mobilized_max_usd, dt.project.facility_deployment_envelope_usd), null)
:::

:::calculation {#total_enabled_capital_min_usd}
label: Low total enabled capital including applicable additional capital
expression: if(dt.project.mobilization_applicability == "applicable", dt.project.facility_deployment_envelope_usd + dt.project.additional_capital_mobilized_min_usd, null)
:::

:::calculation {#total_enabled_capital_max_usd}
label: High total enabled capital including applicable additional capital
expression: if(dt.project.mobilization_applicability == "applicable", dt.project.facility_deployment_envelope_usd + dt.project.additional_capital_mobilized_max_usd, null)
:::

:::calculation {#enabled_capital_per_portfolio_unit_low}
label: Low enabled capital per typed portfolio unit
expression: if(dt.project.mobilization_applicability == "applicable" && dt.project.portfolio_unit_count > 0, ratio(total_enabled_capital_min_usd, dt.project.portfolio_unit_count), null)
:::

:::calculation {#enabled_capital_per_portfolio_unit_high}
label: High enabled capital per typed portfolio unit
expression: if(dt.project.mobilization_applicability == "applicable" && dt.project.portfolio_unit_count > 0, ratio(total_enabled_capital_max_usd, dt.project.portfolio_unit_count), null)
:::

## Executive summary {#executive_summary}

### Decision evidence {#executive_summary_decision_evidence}

:::table {#executive_summary_table}
type: key-value
title: Executive decision evidence
data: dt.project.total_cost_usd, dt.project.gcf_financing_usd, dt.project.cofinance_usd, cofinance_per_gcf_dollar, funding_reconciliation_status, dt.project.ghg_reduction_tco2e, project_cost_per_reported_tco2e, dt.project.facility_deployment_envelope_usd, additional_capital_per_gcf_dollar_low, additional_capital_per_gcf_dollar_high, calc.maximum_risk_priority_score, calc.maximum_priority_risk_count, calc.kpi_priority_cutoff, calc.priority_kpi_count, req.project_status, req.financial_model, req.technical_design_maturity, req.environmental_social_safeguards
headers: [Decision item, Position]
:::

### Executive interpretation {#executive_summary_interpretation}

:::llm {#executive_summary_text}
title: Executive assessment and critical issues
estimated_max_words: 220
output_contract: benchmark.executive_assessment.v1
instructions: |
  Give an investment-committee-style assessment, not a table recap. Identify the
  facility proposition, intended additionality and outcome, then explain the two
  or three issues that most affect whether it can be assessed. Use
  {funding_reconciliation_status}, the
  exact maximum-tied risk set {calc.maximum_priority_risks}, and priority KPI set
  {calc.priority_kpis}. Preserve {dt.project.funding_scope_qualification},
  {dt.project.instrument_terms_qualification},
  {dt.project.mobilization_qualification}, and
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
  row. Explain what the facility finances, shares or enables, and use
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
  Explain how the accredited entity, implementation agency and financial
  intermediaries divide responsibility. Identify the delivery dependency that
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
data: dt.project.mitigation_areas, dt.project.adaptation_areas, dt.project.energy_technologies, dt.project.countries, dt.project.target_market_segment, dt.project.ghg_reduction_tco2e, dt.project.ghg_target_horizon_years, annualised_reported_ghg_target_tco2e, req.climate_rationale, req.ghg_target_horizon
headers: [Climate-rationale item, Position]
:::

### Strategic interpretation {#climate_rationale_and_strategic_fit_interpretation}

:::llm {#climate_rationale_and_strategic_fit_text}
title: Climate rationale and strategic fit
estimated_max_words: 180
output_contract: benchmark.interpretive_assessment.v1
instructions: |
  Explain the causal link between the financing barrier, target market,
  intervention and intended climate result. Use the project description but do not
  invent hazard projections, loss baselines or policy alignment. State how
  {req.climate_rationale} and {req.ghg_target_horizon} limit the case. Treat
  {annualised_reported_ghg_target_tco2e} as an accounting normalisation only.
profile: neutral
:::

## Market rationale and financial additionality {#market_rationale_and_additionality}

### Market evidence {#market_rationale_and_additionality_evidence}

:::table {#market_rationale_and_additionality_table}
type: key-value
title: Market rationale and financial additionality
data: dt.project.facility_archetype, dt.project.target_market_segment, dt.project.market_financing_barrier, dt.project.financial_additionality, dt.project.eligibility_criteria, dt.project.facility_profile_scope
headers: [Market-rationale item, Position]
:::

### Additionality assessment {#market_rationale_and_additionality_assessment}

:::llm {#market_rationale_and_additionality_text}
title: Market rationale and financial additionality
estimated_max_words: 190
output_contract: benchmark.interpretive_assessment.v1
instructions: |
  Explain the identified financing barrier and how the facility mechanism is
  intended to address it. Assess whether the additionality claim is logically
  connected to the target segment and eligibility criteria. Do not equate
  concessionality with demonstrated additionality or infer market failure beyond
  {dt.project.market_financing_barrier}. Preserve
  {dt.project.facility_profile_scope} and synthetic-input disclosure.
profile: neutral
:::

## Instrument structure and terms {#instrument_structure_and_terms}

### Instrument calculations {#instrument_structure_and_terms_calculations}

:::table {#instrument_structure_and_terms_table}
type: key-value
title: GCF instrument structure and reconciliation
data: dt.project.gcf_financing_usd, dt.project.gcf_grant_usd, dt.project.gcf_concessional_loan_usd, dt.project.gcf_reimbursable_grant_usd, dt.project.gcf_guarantee_usd, dt.project.gcf_equity_usd, gcf_instrument_total_usd, gcf_instrument_reconciliation_gap_usd, gcf_instrument_reconciliation_status, gcf_grant_share_pct, gcf_concessional_loan_share_pct, gcf_reimbursable_grant_share_pct, gcf_guarantee_share_pct, gcf_equity_share_pct, dt.project.instrument_terms_qualification
headers: [Instrument item, Value]
:::

### Instrument interpretation {#instrument_structure_and_terms_interpretation}

:::llm {#instrument_structure_and_terms_text}
title: Instrument structure and terms
estimated_max_words: 200
output_contract: benchmark.interpretive_assessment.v1
instructions: |
  Identify the instruments that materially shape risk allocation and explain their
  shares without enumerating zero-value rows. State
  {gcf_instrument_reconciliation_status} as an arithmetic check. Preserve
  {dt.project.instrument_terms_qualification}; face amount is not grant-equivalent
  cost, and instrument mix alone does not establish concessionality, repayment
  capacity or expected return.
profile: neutral
:::

## Allocation and utilisation profile {#allocation_and_utilisation_profile}

### Deployment-basis evidence {#allocation_and_utilisation_profile_evidence}

:::table {#allocation_and_utilisation_profile_table}
type: key-value
title: Facility allocation and utilisation evidence
data: dt.project.facility_deployment_envelope_usd, dt.project.facility_deployment_basis, deployment_envelope_per_gcf_dollar, dt.project.eligibility_criteria, dt.project.implementation_sequence, req.detailed_implementation_schedule, req.procurement_plan, req.mrv_plan_status
headers: [Deployment item, Position]
:::

### Deployment assessment {#allocation_and_utilisation_profile_assessment}

:::llm {#allocation_and_utilisation_profile_text}
title: Allocation and utilisation profile
estimated_max_words: 180
output_contract: benchmark.interpretive_assessment.v1
instructions: |
  Explain the declared deployment basis, eligibility controls and sequence. Do not
  invent period allocations, utilisation rates or recycling. Interpret
  {deployment_envelope_per_gcf_dollar} only as a scope descriptor and state whether
  actual allocation, utilisation and monitoring can be assessed from
  {req.detailed_implementation_schedule}, {req.procurement_plan}, and
  {req.mrv_plan_status}.
profile: neutral
:::

## Portfolio scale and mobilisation {#portfolio_scale_and_mobilisation}

### Scale and mobilisation calculations {#portfolio_scale_and_mobilisation_calculations}

:::table {#portfolio_scale_and_mobilisation_table}
type: key-value
title: Portfolio scale and expected mobilisation
data: dt.project.portfolio_unit_count, dt.project.portfolio_unit_type, dt.project.portfolio_unit_count_basis, dt.project.portfolio_unit_count_qualification, deployment_envelope_per_portfolio_unit, dt.project.additional_capital_mobilized_min_usd, additional_capital_mobilized_mid_usd, dt.project.additional_capital_mobilized_max_usd, additional_capital_per_gcf_dollar_low, additional_capital_per_gcf_dollar_high, additional_capital_per_deployment_envelope_dollar_low, additional_capital_per_deployment_envelope_dollar_high, total_enabled_capital_min_usd, total_enabled_capital_max_usd, enabled_capital_per_portfolio_unit_low, enabled_capital_per_portfolio_unit_high, dt.project.mobilization_qualification
headers: [Portfolio or mobilisation item, Value]
:::

### Scale interpretation {#portfolio_scale_and_mobilisation_interpretation}

:::llm {#portfolio_scale_and_mobilisation_text}
title: Portfolio scale and mobilisation
estimated_max_words: 210
output_contract: benchmark.interpretive_assessment.v1
instructions: |
  Interpret the expected scale and mobilisation range only when
  {dt.project.mobilization_applicability} is applicable. Explain what the typed
  portfolio-unit denominator represents using
  {dt.project.portfolio_unit_count_basis} and
  {dt.project.portfolio_unit_count_qualification}. The ratios are ex-ante
  allocation or mobilisation objectives, not realised leverage, portfolio quality,
  returns or unique beneficiary counts. Preserve
  {dt.project.mobilization_qualification}.
profile: neutral
:::

## Technical feasibility and implementation readiness {#technical_feasibility_and_readiness}

### Operational-readiness evidence {#technical_feasibility_and_readiness_evidence}

:::table {#technical_feasibility_and_readiness_table}
type: key-value
title: Facility design and implementation readiness
data: dt.project.facility_archetype, dt.project.eligibility_criteria, dt.project.delivery_mechanism, dt.project.implementation_sequence, dt.project.implementation_years, req.project_status, req.technical_feasibility_status, req.technical_design_maturity, req.procurement_plan, req.detailed_implementation_schedule
headers: [Readiness item, Position]
:::

### Readiness assessment {#technical_feasibility_and_readiness_assessment}

:::llm {#technical_feasibility_and_readiness_text}
title: Technical feasibility and implementation readiness
estimated_max_words: 180
output_contract: benchmark.interpretive_assessment.v1
instructions: |
  State what the evidence establishes about facility design and operational
  readiness, then identify the most material unresolved implementation items.
  Treat absent eligibility procedures, appraisal capacity, procurement or schedule
  evidence as limitations, not negative findings. Do not derive a readiness score
  or infer a viable pipeline from a target portfolio count.
profile: neutral
:::

## Costs and financing structure {#costs_and_financing_structure}

### Financing calculations {#costs_and_financing_structure_calculations}

:::table {#costs_and_financing_structure_table}
type: key-value
title: Costs and aggregate financing structure
data: dt.project.total_cost_usd, dt.project.gcf_financing_usd, dt.project.cofinance_usd, committed_funding_sources_usd, funding_reconciliation_gap_usd, funding_reconciliation_gap_pct, funding_reconciliation_status, funding_source_coverage_pct, gcf_financing_share_of_cost_pct, cofinance_share_of_cost_pct, cofinance_per_gcf_dollar, dt.project.total_cost_scope, dt.project.gcf_financing_scope, dt.project.cofinance_scope, dt.project.funding_scope_comparability, dt.project.funding_scope_qualification
headers: [Financing item, Position]
:::

### Financing interpretation {#costs_and_financing_structure_interpretation}

:::llm {#costs_and_financing_structure_text}
title: Costs and financing structure
estimated_max_words: 200
output_contract: benchmark.interpretive_assessment.v1
instructions: |
  Interpret the aggregate structure and arithmetic reconciliation rather than
  repeating amounts. Explain what {cofinance_per_gcf_dollar} says about stated
  cofinance and what it does not say about additionality, viability or return. Use
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
data: dt.project.financial_additionality, dt.project.instrument_terms_qualification, dt.project.facility_recycling_qualification, req.business_model, req.revenue_model, req.lifecycle_opex, req.financial_model, req.financial_returns
headers: [Sustainability item, Position]
:::

### Sustainability assessment {#financial_sustainability_and_business_model_assessment}

:::llm {#financial_sustainability_and_business_model_text}
title: Financial sustainability and business model
estimated_max_words: 200
output_contract: benchmark.interpretive_assessment.v1
instructions: |
  Explain whether operating sustainability, repayment capacity, recycling or
  returns can be assessed from {req.business_model}, {req.revenue_model},
  {req.lifecycle_opex}, {req.financial_model}, and {req.financial_returns}.
  Preserve {dt.project.instrument_terms_qualification} and
  {dt.project.facility_recycling_qualification}. Do not derive FIRR, NPV, DSCR,
  portfolio performance or financial viability without cash-flow and term evidence.
profile: neutral
:::

## Impact, ESG, and safeguards {#impact_esg_and_safeguards}

### Impact and safeguards evidence {#impact_esg_and_safeguards_evidence}

:::table {#impact_esg_and_safeguards_table}
type: key-value
title: Impact, ESG, and safeguards
data: dt.project.ghg_reduction_tco2e, dt.project.ghg_target_horizon_years, annualised_reported_ghg_target_tco2e, project_cost_per_reported_tco2e, gcf_financing_per_reported_tco2e, dt.project.target_market_segment, dt.project.eligibility_criteria, req.environmental_social_safeguards, req.gender_assessment_and_action_plan, req.stakeholder_engagement, req.ghg_target_horizon
headers: [Impact or safeguards item, Position]
:::

### Impact and safeguards assessment {#impact_esg_and_safeguards_assessment}

:::llm {#impact_esg_and_safeguards_text}
title: Impact, ESG, and safeguards
estimated_max_words: 210
output_contract: benchmark.interpretive_assessment.v1
instructions: |
  Interpret the scale and boundary of intended climate outcomes. Use
  {project_cost_per_reported_tco2e} only when its scope gate permits and call both
  financing-per-impact values ex-ante allocation intensities, not realised
  abatement cost. Explain whether eligibility, safeguards, gender and stakeholder
  evidence is sufficient; do not infer downstream-project compliance from facility
  eligibility language.
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
data: funding_reconciliation_status, cofinance_per_gcf_dollar, deployment_envelope_per_gcf_dollar, additional_capital_per_gcf_dollar_low, additional_capital_per_gcf_dollar_high, calc.maximum_risk_priority_score, calc.maximum_priority_risk_count, calc.scored_risk_count, calc.incomplete_risk_count, calc.kpi_priority_cutoff, calc.priority_kpi_count, calc.available_kpi_priority_count, calc.incomplete_kpi_priority_count, calc.mrv_ready_kpi_count, calc.kpi_compatible_target_delta_count
headers: [Conclusion input, Position]
:::

### Due-diligence evidence readiness {#conclusions_and_evidence_requirements_readiness}

:::table {#evidence_readiness_and_conditions_table}
type: key-value
title: Evidence readiness and conditions for further review
data: req.project_status, req.promoter_financial_standing, req.promoter_track_record, req.climate_rationale, req.technical_feasibility_status, req.technical_design_maturity, req.procurement_plan, req.detailed_implementation_schedule, req.business_model, req.revenue_model, req.lifecycle_opex, req.financial_model, req.financial_returns, req.environmental_social_safeguards, req.gender_assessment_and_action_plan, req.stakeholder_engagement, req.mrv_plan_status, req.synthetic_evidence_disclosure
headers: [Evidence requirement, Current evidence position]
:::

### Evidence and calculation register {#conclusions_and_evidence_requirements_register}

:::table {#evidence_and_calculation_register_table}
type: key-value
title: Evidence and calculation register
data: committed_funding_sources_usd, funding_reconciliation_gap_usd, funding_reconciliation_gap_pct, funding_reconciliation_status, funding_source_coverage_pct, gcf_financing_share_of_cost_pct, cofinance_share_of_cost_pct, cofinance_per_gcf_dollar, project_cost_per_reported_tco2e, gcf_financing_per_reported_tco2e, annualised_reported_ghg_target_tco2e, deployment_envelope_per_gcf_dollar, additional_capital_per_gcf_dollar_low, additional_capital_per_gcf_dollar_high, total_enabled_capital_min_usd, total_enabled_capital_max_usd, calc.prioritized_kpi_count, calc.available_kpi_priority_count, calc.incomplete_kpi_priority_count, calc.kpi_priority_cutoff, calc.priority_kpi_count, calc.mrv_ready_kpi_count, calc.kpi_compatible_target_delta_count, risk_count, calc.scored_risk_count, calc.incomplete_risk_count, calc.maximum_risk_priority_score, calc.maximum_priority_risk_count, dt.project.funding_scope_qualification, dt.project.instrument_terms_qualification, dt.project.mobilization_qualification, req.synthetic_evidence_disclosure
headers: [Registered item, Value or qualification]
:::

### Evidence-based conclusion {#conclusions_and_evidence_requirements_interpretation}

:::llm {#conclusions_and_evidence_requirements_text}
title: Conclusions and evidence requirements
estimated_max_words: 260
output_contract: benchmark.evidence_requirements.v1
instructions: |
  Give a bounded conclusion on what is currently assessable. Integrate funding
  reconciliation {funding_reconciliation_status}, instrument-terms evidence,
  financial additionality, expected mobilisation, maximum-risk result
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
