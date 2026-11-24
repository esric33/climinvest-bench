# {dt.project.title}

<!-- GCF bankability report contract: asset and physical-delivery projects.
Tables hold evidence and deterministic calculations. Each section has one
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
label: Countries covered by the project
expression: count(dt.project.countries)
:::

:::calculation {#risk_count}
label: Risk records available to the report
expression: count(dt.risks)
:::

:::calculation {#emission_factor_delta_tco2e_per_mwh}
label: Baseline less project operating emission factor
expression: dt.project.baseline_grid_emission_factor_tco2e_per_mwh - dt.project.project_operating_emission_factor_tco2e_per_mwh
:::

:::calculation {#renewable_policy_gap_pct}
label: Renewable-generation percentage-point gap to policy target
expression: dt.project.policy_renewable_target_pct - dt.project.baseline_renewable_generation_pct
:::

:::calculation {#full_build_gross_generation_mwh_per_year}
label: Simple full-build annual gross generation scenario
expression: dt.project.installed_capacity_target_mw * 8760 * dt.project.capacity_factor_pct / 100
:::

:::calculation {#full_build_net_generation_mwh_per_year}
label: Simple full-build annual net generation scenario after stated grid loss
expression: full_build_gross_generation_mwh_per_year * (100 - dt.project.grid_loss_pct) / 100
:::

:::calculation {#full_build_avoided_ghg_tco2e_per_year}
label: Simple full-build annual avoided-GHG scenario
expression: full_build_net_generation_mwh_per_year * emission_factor_delta_tco2e_per_mwh
:::

:::calculation {#simple_horizon_avoided_ghg_tco2e}
label: Simple full-operation avoided-GHG scenario over the explicit target horizon
expression: full_build_avoided_ghg_tco2e_per_year * dt.project.ghg_target_horizon_years
:::

:::calculation {#modelled_vs_reported_ghg_ratio}
label: Boundary-qualified simple-scenario to reported GHG ratio
expression: if(dt.project.reported_ghg_comparison_status == "comparable", ratio(simple_horizon_avoided_ghg_tco2e, dt.project.ghg_reduction_tco2e), null)
:::

:::calculation {#reported_minus_modelled_ghg_tco2e}
label: Boundary-qualified reported target less simple-scenario GHG
expression: if(dt.project.reported_ghg_comparison_status == "comparable", dt.project.ghg_reduction_tco2e - simple_horizon_avoided_ghg_tco2e, null)
:::

:::calculation {#project_cost_per_installed_mw}
label: Scope-qualified stated project cost per installed or enabled MW
expression: if(dt.project.total_cost_scope == "whole_project", ratio(dt.project.total_cost_usd, dt.project.installed_capacity_target_mw), null)
:::

:::calculation {#gcf_financing_per_installed_mw}
label: GCF allocation per installed or enabled MW
expression: ratio(dt.project.gcf_financing_usd, dt.project.installed_capacity_target_mw)
:::

:::calculation {#beneficiaries_per_installed_mw}
label: Intended direct beneficiaries per installed or enabled MW
expression: ratio(dt.project.direct_beneficiaries_target, dt.project.installed_capacity_target_mw)
:::

:::calculation {#gcf_financing_per_service_connection}
label: GCF allocation per intended service connection
expression: ratio(dt.project.gcf_financing_usd, dt.project.service_connections_target)
:::

:::calculation {#direct_beneficiaries_per_service_connection}
label: Intended direct beneficiaries per service connection
expression: ratio(dt.project.direct_beneficiaries_target, dt.project.service_connections_target)
:::

## Executive summary {#executive_summary}

### Decision evidence {#executive_summary_decision_evidence}

:::table {#executive_summary_table}
type: key-value
title: Executive decision evidence
data: dt.project.total_cost_usd, dt.project.gcf_financing_usd, dt.project.cofinance_usd, cofinance_per_gcf_dollar, funding_reconciliation_status, dt.project.ghg_reduction_tco2e, project_cost_per_reported_tco2e, dt.project.installed_capacity_target_mw, calc.maximum_risk_priority_score, calc.maximum_priority_risk_count, calc.kpi_priority_cutoff, calc.priority_kpi_count, req.project_status, req.financial_model, req.technical_design_maturity, req.environmental_social_safeguards
headers: [Decision item, Position]
:::

### Executive interpretation {#executive_summary_interpretation}

:::llm {#executive_summary_text}
title: Executive assessment and critical issues
estimated_max_words: 220
output_contract: benchmark.executive_assessment.v1
instructions: |
  Give an investment-committee-style assessment, not a table recap. Identify the
  financing and impact proposition, then explain the two or three issues that most
  affect whether it can be assessed. Use {funding_reconciliation_status},
  {project_cost_per_reported_tco2e}, and the exact maximum-tied risk set
  {calc.maximum_priority_risks}. Use the priority KPI set {calc.priority_kpis} only
  to identify what the results framework treats as most important. Preserve
  {dt.project.funding_scope_qualification}, {dt.project.ghg_accounting_qualification},
  and {req.synthetic_evidence_disclosure}. Do not issue an investment recommendation.
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
  Identify the project, accredited entity, geography, sector and intended mandate
  using the table and {dt.project.description}. Do not reproduce every table row.
  Explain what is being financed or enabled and the boundary of the project as
  described. Use {req.project_status} rather than inferring implementation status.
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
  Explain how the promoter, implementation agency and governance arrangements
  divide responsibility. Identify the delivery dependency that matters most.
  Assess only what the evidence supports about capacity or track record; use
  {req.promoter_financial_standing} and {req.promoter_track_record} as explicit
  evidence requirements rather than filling the gaps. Preserve synthetic-input
  status through {req.synthetic_evidence_disclosure}.
profile: neutral
:::

## Climate rationale and strategic fit {#climate_rationale_and_strategic_fit}

### Climate and policy evidence {#climate_rationale_and_strategic_fit_evidence}

:::table {#climate_rationale_and_strategic_fit_table}
type: key-value
title: Climate rationale and strategic fit
data: dt.project.mitigation_areas, dt.project.adaptation_areas, dt.project.energy_technologies, dt.project.countries, dt.project.ghg_reduction_tco2e, dt.project.ghg_target_horizon_years, annualised_reported_ghg_target_tco2e, req.climate_rationale, req.ghg_target_horizon
headers: [Climate-rationale item, Position]
:::

### Strategic interpretation {#climate_rationale_and_strategic_fit_interpretation}

:::llm {#climate_rationale_and_strategic_fit_text}
title: Climate rationale and strategic fit
estimated_max_words: 180
output_contract: benchmark.interpretive_assessment.v1
instructions: |
  Explain the causal link between the stated climate need, intervention and
  intended mitigation or adaptation result. Use the project description and
  sector evidence, but do not invent hazard projections, loss baselines or policy
  alignment. State how {req.climate_rationale} and {req.ghg_target_horizon} limit
  the case. Treat {annualised_reported_ghg_target_tco2e} as an accounting
  normalisation only.
profile: neutral
:::

## System baseline and policy context {#system_baseline_and_policy_context}

### Baseline and policy calculations {#system_baseline_and_policy_context_calculations}

:::table {#system_baseline_and_policy_context_table}
type: key-value
title: Source-dated system context
data: dt.project.baseline_electricity_access_pct, dt.project.baseline_fossil_generation_pct, dt.project.baseline_renewable_generation_pct, dt.project.policy_renewable_target_pct, dt.project.policy_target_year, renewable_policy_gap_pct, dt.project.baseline_grid_emission_factor_tco2e_per_mwh, dt.project.project_operating_emission_factor_tco2e_per_mwh, emission_factor_delta_tco2e_per_mwh
headers: [System indicator, Value]
:::

### Relevance to the intervention {#system_baseline_and_policy_context_interpretation}

:::llm {#system_baseline_and_policy_context_text}
title: System baseline and policy context
estimated_max_words: 180
output_contract: benchmark.interpretive_assessment.v1
instructions: |
  Use the baseline and policy values to explain why the asset intervention may be
  material. Focus on {renewable_policy_gap_pct} and
  {emission_factor_delta_tco2e_per_mwh}; do not enumerate the table. Preserve the
  dated and bounded nature of the evidence and do not present enriched benchmark
  inputs as independently verified current statistics.
profile: neutral
:::

## Capacity and output {#capacity_and_output}

### Capacity and allocation calculations {#capacity_and_output_calculations}

:::table {#capacity_and_output_table}
type: key-value
title: Full-build capacity and service output
data: dt.project.installed_capacity_target_mw, dt.project.capacity_delivery_relationship, dt.project.capacity_factor_pct, dt.project.grid_loss_pct, full_build_gross_generation_mwh_per_year, full_build_net_generation_mwh_per_year, project_cost_per_installed_mw, gcf_financing_per_installed_mw, dt.project.service_connections_target, gcf_financing_per_service_connection, beneficiaries_per_installed_mw, direct_beneficiaries_per_service_connection, dt.project.generation_accounting_boundary
headers: [Capacity or service indicator, Value]
:::

### Capacity interpretation {#capacity_and_output_interpretation}

:::llm {#capacity_and_output_text}
title: Capacity and output
estimated_max_words: 200
output_contract: benchmark.interpretive_assessment.v1
instructions: |
  Explain what capacity is delivered, financed or merely enabled using
  {dt.project.capacity_delivery_relationship}. Interpret only relationships
  material to the delivery proposition. Preserve
  {dt.project.generation_accounting_boundary}; call the generation values simple
  ex-ante scenarios, not forecasts, and do not infer affordability or financial
  returns from allocation intensity.
profile: neutral
:::

## Commissioning evidence and dependencies {#commissioning_profile}

### Commissioning-readiness evidence {#commissioning_profile_evidence}

:::table {#commissioning_profile_table}
type: key-value
title: Commissioning evidence and dependencies
data: dt.project.implementation_sequence, dt.project.capacity_delivery_relationship, dt.project.service_connections_target, req.technical_design_maturity, req.permitting_status, req.land_and_access_status, req.procurement_plan, req.detailed_implementation_schedule
headers: [Commissioning dependency, Position]
:::

### Commissioning assessment {#commissioning_profile_interpretation}

:::llm {#commissioning_profile_text}
title: Commissioning evidence and dependencies
estimated_max_words: 170
output_contract: benchmark.interpretive_assessment.v1
instructions: |
  Identify the few sequencing, permitting, access, procurement or connection
  dependencies most capable of delaying commissioning or reducing delivered
  output. Do not invent a period schedule. Distinguish an evidenced readiness
  position from an information request, and do not infer milestones or approvals
  where the corresponding req item is missing.
profile: neutral
:::

## Operational impact consistency {#operational_impact_consistency}

### Bottom-up calculation {#operational_impact_consistency_calculation}

:::table {#operational_impact_consistency_table}
type: key-value
title: Restricted-boundary GHG consistency check
data: full_build_net_generation_mwh_per_year, emission_factor_delta_tco2e_per_mwh, full_build_avoided_ghg_tco2e_per_year, dt.project.ghg_target_horizon_years, simple_horizon_avoided_ghg_tco2e, dt.project.ghg_reduction_tco2e, modelled_vs_reported_ghg_ratio, reported_minus_modelled_ghg_tco2e, dt.project.reported_ghg_comparison_status, dt.project.reported_ghg_comparison_qualification, dt.project.asset_impact_boundary_qualification
headers: [GHG consistency item, Value]
:::

### Consistency interpretation {#operational_impact_consistency_interpretation}

:::llm {#operational_impact_consistency_text}
title: Operational impact consistency
estimated_max_words: 200
output_contract: benchmark.interpretive_assessment.v1
instructions: |
  Trace the short calculation from net generation and emission-factor delta to
  annual and horizon GHG. Compare it with the reported target only when
  {dt.project.reported_ghg_comparison_status} permits, using
  {modelled_vs_reported_ghg_ratio} and {reported_minus_modelled_ghg_tco2e}.
  Explain the most plausible boundary limitation using
  {dt.project.reported_ghg_comparison_qualification} and
  {dt.project.asset_impact_boundary_qualification}. This is a consistency check,
  not replacement GCF accounting.
profile: neutral
:::

## Technical feasibility and implementation readiness {#technical_feasibility_and_readiness}

### Readiness evidence {#technical_feasibility_and_readiness_evidence}

:::table {#technical_feasibility_and_readiness_table}
type: key-value
title: Technical feasibility and implementation readiness
data: dt.project.delivery_mechanism, dt.project.implementation_sequence, dt.project.implementation_years, req.project_status, req.technical_feasibility_status, req.technical_design_maturity, req.permitting_status, req.land_and_access_status, req.procurement_plan, req.detailed_implementation_schedule
headers: [Technical-readiness item, Position]
:::

### Feasibility assessment {#technical_feasibility_and_readiness_assessment}

:::llm {#technical_feasibility_and_readiness_text}
title: Technical feasibility and implementation readiness
estimated_max_words: 180
output_contract: benchmark.interpretive_assessment.v1
instructions: |
  State what the evidence establishes about technical feasibility and delivery
  maturity, then identify the most material unresolved readiness items. Treat
  absent design, permits, access, procurement or schedule evidence as limitations,
  not negative findings. Do not derive a readiness score or claim bankability from
  the implementation sequence alone.
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
  repeating the amounts. Explain what {cofinance_per_gcf_dollar} says about stated
  mobilisation and what it does not say about viability or return. Use
  {funding_reconciliation_status} only under
  {dt.project.funding_scope_comparability}. When scopes are not comparable or are
  undetermined, do not report a funding gap, coverage percentage or cost share;
  describe {committed_funding_sources_usd} only as an unqualified arithmetic sum.
  Preserve every funding scope and call any assessable reconciliation an arithmetic
  check, not an audit finding.
profile: neutral
:::

## Financial sustainability and business model {#financial_sustainability_and_business_model}

### Sustainability evidence {#financial_sustainability_and_business_model_evidence}

:::table {#financial_sustainability_and_business_model_table}
type: key-value
title: Financial sustainability and business-model evidence
data: project_cost_per_installed_mw, gcf_financing_per_installed_mw, project_cost_per_reported_tco2e, gcf_financing_per_reported_tco2e, req.business_model, req.revenue_model, req.lifecycle_opex, req.financial_model, req.financial_returns
headers: [Sustainability item, Position]
:::

### Sustainability assessment {#financial_sustainability_and_business_model_assessment}

:::llm {#financial_sustainability_and_business_model_text}
title: Financial sustainability and business model
estimated_max_words: 190
output_contract: benchmark.interpretive_assessment.v1
instructions: |
  Explain whether operating sustainability, repayment capacity or returns can be
  assessed from {req.business_model}, {req.revenue_model}, {req.lifecycle_opex},
  {req.financial_model}, and {req.financial_returns}. Use the unit-allocation
  calculations only as scale descriptors. Do not derive FIRR, EIRR, NPV, DSCR,
  affordability or financial viability without the required cash-flow evidence.
profile: neutral
:::

## Impact, ESG, and safeguards {#impact_esg_and_safeguards}

### Impact and safeguards evidence {#impact_esg_and_safeguards_evidence}

:::table {#impact_esg_and_safeguards_table}
type: key-value
title: Impact, ESG, and safeguards
data: dt.project.ghg_reduction_tco2e, dt.project.ghg_target_horizon_years, annualised_reported_ghg_target_tco2e, project_cost_per_reported_tco2e, gcf_financing_per_reported_tco2e, dt.project.direct_beneficiaries_target, dt.project.environmental_cobenefits, dt.project.social_cobenefits, req.environmental_social_safeguards, req.gender_assessment_and_action_plan, req.stakeholder_engagement, dt.project.ghg_accounting_qualification
headers: [Impact or safeguards item, Position]
:::

### Impact and safeguards assessment {#impact_esg_and_safeguards_assessment}

:::llm {#impact_esg_and_safeguards_text}
title: Impact, ESG, and safeguards
estimated_max_words: 210
output_contract: benchmark.interpretive_assessment.v1
instructions: |
  Interpret the scale and boundary of intended climate and social results. Use
  {project_cost_per_reported_tco2e} only when its scope gate permits and call both
  financing-per-impact values ex-ante allocation intensities, not realised
  abatement cost. Explain whether safeguards, gender and stakeholder evidence is
  sufficient; do not infer compliance from co-benefit descriptions. Preserve
  {dt.project.ghg_accounting_qualification}.
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
  {req.mrv_plan_status}; do not invent missing values or compare incompatible units.
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
data: funding_reconciliation_status, cofinance_per_gcf_dollar, project_cost_per_reported_tco2e, modelled_vs_reported_ghg_ratio, calc.maximum_risk_priority_score, calc.maximum_priority_risk_count, calc.scored_risk_count, calc.incomplete_risk_count, calc.kpi_priority_cutoff, calc.priority_kpi_count, calc.available_kpi_priority_count, calc.incomplete_kpi_priority_count, calc.mrv_ready_kpi_count, calc.kpi_compatible_target_delta_count
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
data: committed_funding_sources_usd, funding_reconciliation_gap_usd, funding_reconciliation_gap_pct, funding_reconciliation_status, funding_source_coverage_pct, gcf_financing_share_of_cost_pct, cofinance_share_of_cost_pct, cofinance_per_gcf_dollar, project_cost_per_reported_tco2e, gcf_financing_per_reported_tco2e, annualised_reported_ghg_target_tco2e, emission_factor_delta_tco2e_per_mwh, full_build_gross_generation_mwh_per_year, full_build_net_generation_mwh_per_year, full_build_avoided_ghg_tco2e_per_year, simple_horizon_avoided_ghg_tco2e, modelled_vs_reported_ghg_ratio, project_cost_per_installed_mw, gcf_financing_per_installed_mw, gcf_financing_per_service_connection, calc.prioritized_kpi_count, calc.available_kpi_priority_count, calc.incomplete_kpi_priority_count, calc.kpi_priority_cutoff, calc.priority_kpi_count, calc.mrv_ready_kpi_count, calc.kpi_compatible_target_delta_count, risk_count, calc.scored_risk_count, calc.incomplete_risk_count, calc.maximum_risk_priority_score, calc.maximum_priority_risk_count, dt.project.funding_scope_qualification, dt.project.ghg_accounting_qualification, dt.project.generation_accounting_boundary, req.synthetic_evidence_disclosure
headers: [Registered item, Value or qualification]
:::

### Evidence-based conclusion {#conclusions_and_evidence_requirements_interpretation}

:::llm {#conclusions_and_evidence_requirements_text}
title: Conclusions and evidence requirements
estimated_max_words: 260
output_contract: benchmark.evidence_requirements.v1
instructions: |
  Give a bounded conclusion on what is currently assessable. Integrate the funding
  check {funding_reconciliation_status}, asset GHG consistency check,
  maximum-priority result {calc.maximum_risk_priority_score} and priority-KPI
  cutoff {calc.kpi_priority_cutoff} without restating their tables. Convert the
  few gaps most material to assessment, including {req.financial_model},
  {req.technical_design_maturity} and {req.environmental_social_safeguards}, into
  specific evidence requests or conditions for further review.
  Distinguish source-backed facts, deterministic calculations, synthetic benchmark
  assumptions and missing due-diligence evidence. Explain that the calculation
  register improves traceability without validating its inputs. Do not approve,
  decline or make an investment recommendation.
profile: neutral
:::
