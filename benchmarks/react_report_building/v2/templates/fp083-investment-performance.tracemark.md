# {dt.project.title}

<!--
ARCHIVED COMPATIBILITY TEMPLATE — not compiled or used by the active v2
benchmark. The three bankability family templates are authoritative.

FP083 benchmark v2 realism candidate. Deterministic setup uses source-backed
ranges, financing instruments, disbursement periods, and leave-one-out peers.
Every generated paragraph uses one neutral prompt-controlled llm component.
-->

:::calculation {#gcf_funding_total}
label: GCF financing amount
expression: sum(dt.project.gcf_soft_loan_usd, dt.project.gcf_reimbursable_grant_usd, dt.project.gcf_grant_usd)
:::

:::calculation {#funding_sources_total}
label: Committed funding sources
expression: gcf_funding_total + dt.project.cofinance_usd
:::

:::calculation {#funding_reconciliation_gap}
label: Committed funding reconciliation gap
expression: dt.project.total_cost_usd - funding_sources_total
:::

:::calculation {#funding_reconciliation_gap_abs}
label: Absolute committed funding reconciliation gap
expression: abs(funding_reconciliation_gap)
:::

:::calculation {#funding_reconciliation_gap_pct}
label: Absolute committed funding gap as share of total cost
expression: percentage(funding_reconciliation_gap_abs, dt.project.total_cost_usd)
:::

:::calculation {#funding_reconciliation_status}
label: Committed funding reconciliation status
expression: if(funding_reconciliation_gap_abs <= 1, "reconciled to the nearest USD", "not reconciled to the nearest USD")
:::

:::calculation {#gcf_financing_share_pct}
label: GCF financing share of committed project cost
expression: percentage(gcf_funding_total, dt.project.total_cost_usd)
:::

:::calculation {#cofinance_share_pct}
label: Cofinance share of committed project cost
expression: percentage(dt.project.cofinance_usd, dt.project.total_cost_usd)
:::

:::calculation {#cofinance_per_gcf_dollar}
label: Committed cofinance per GCF dollar
expression: ratio(dt.project.cofinance_usd, gcf_funding_total)
:::

:::calculation {#total_funding_per_gcf_dollar}
label: Total committed funding per GCF dollar
expression: ratio(funding_sources_total, gcf_funding_total)
:::

:::calculation {#gcf_soft_loan_share_pct}
label: Soft loan share of GCF financing
expression: percentage(dt.project.gcf_soft_loan_usd, gcf_funding_total)
:::

:::calculation {#gcf_reimbursable_grant_share_pct}
label: Reimbursable grant share of GCF financing
expression: percentage(dt.project.gcf_reimbursable_grant_usd, gcf_funding_total)
:::

:::calculation {#gcf_grant_share_pct}
label: Grant share of GCF financing
expression: percentage(dt.project.gcf_grant_usd, gcf_funding_total)
:::

:::calculation {#soft_loan_disbursement_period_1_usd}
label: Soft loan disbursement in period 1
expression: dt.project.gcf_soft_loan_usd * dt.project.gcf_soft_loan_disbursement_period_1_share
:::

:::calculation {#reimbursable_grant_disbursement_period_1_usd}
label: Reimbursable grant disbursement in period 1
expression: dt.project.gcf_reimbursable_grant_usd * dt.project.gcf_reimbursable_grant_disbursement_period_1_share
:::

:::calculation {#grant_disbursement_period_1_usd}
label: Grant disbursement in period 1
expression: dt.project.gcf_grant_usd * dt.project.gcf_grant_disbursement_period_1_share
:::

:::calculation {#cofinance_disbursement_period_1_usd}
label: Cofinance disbursement in period 1
expression: dt.project.cofinance_usd * dt.project.cofinance_disbursement_period_1_share
:::

:::calculation {#gcf_disbursement_period_1_usd}
label: Total GCF disbursement in period 1
expression: sum(soft_loan_disbursement_period_1_usd, reimbursable_grant_disbursement_period_1_usd, grant_disbursement_period_1_usd)
:::

:::calculation {#total_disbursement_period_1_usd}
label: Total funding disbursement in period 1
expression: gcf_disbursement_period_1_usd + cofinance_disbursement_period_1_usd
:::

:::calculation {#soft_loan_disbursement_period_2_usd}
label: Soft loan disbursement in period 2
expression: dt.project.gcf_soft_loan_usd * dt.project.gcf_soft_loan_disbursement_period_2_share
:::

:::calculation {#reimbursable_grant_disbursement_period_2_usd}
label: Reimbursable grant disbursement in period 2
expression: dt.project.gcf_reimbursable_grant_usd * dt.project.gcf_reimbursable_grant_disbursement_period_2_share
:::

:::calculation {#grant_disbursement_period_2_usd}
label: Grant disbursement in period 2
expression: dt.project.gcf_grant_usd * dt.project.gcf_grant_disbursement_period_2_share
:::

:::calculation {#cofinance_disbursement_period_2_usd}
label: Cofinance disbursement in period 2
expression: dt.project.cofinance_usd * dt.project.cofinance_disbursement_period_2_share
:::

:::calculation {#gcf_disbursement_period_2_usd}
label: Total GCF disbursement in period 2
expression: sum(soft_loan_disbursement_period_2_usd, reimbursable_grant_disbursement_period_2_usd, grant_disbursement_period_2_usd)
:::

:::calculation {#total_disbursement_period_2_usd}
label: Total funding disbursement in period 2
expression: gcf_disbursement_period_2_usd + cofinance_disbursement_period_2_usd
:::

:::calculation {#soft_loan_disbursement_period_3_usd}
label: Soft loan disbursement in period 3
expression: dt.project.gcf_soft_loan_usd * dt.project.gcf_soft_loan_disbursement_period_3_share
:::

:::calculation {#reimbursable_grant_disbursement_period_3_usd}
label: Reimbursable grant disbursement in period 3
expression: dt.project.gcf_reimbursable_grant_usd * dt.project.gcf_reimbursable_grant_disbursement_period_3_share
:::

:::calculation {#grant_disbursement_period_3_usd}
label: Grant disbursement in period 3
expression: dt.project.gcf_grant_usd * dt.project.gcf_grant_disbursement_period_3_share
:::

:::calculation {#cofinance_disbursement_period_3_usd}
label: Cofinance disbursement in period 3
expression: dt.project.cofinance_usd * dt.project.cofinance_disbursement_period_3_share
:::

:::calculation {#gcf_disbursement_period_3_usd}
label: Total GCF disbursement in period 3
expression: sum(soft_loan_disbursement_period_3_usd, reimbursable_grant_disbursement_period_3_usd, grant_disbursement_period_3_usd)
:::

:::calculation {#total_disbursement_period_3_usd}
label: Total funding disbursement in period 3
expression: gcf_disbursement_period_3_usd + cofinance_disbursement_period_3_usd
:::

:::calculation {#soft_loan_disbursement_period_4_usd}
label: Soft loan disbursement in period 4
expression: dt.project.gcf_soft_loan_usd * dt.project.gcf_soft_loan_disbursement_period_4_share
:::

:::calculation {#reimbursable_grant_disbursement_period_4_usd}
label: Reimbursable grant disbursement in period 4
expression: dt.project.gcf_reimbursable_grant_usd * dt.project.gcf_reimbursable_grant_disbursement_period_4_share
:::

:::calculation {#grant_disbursement_period_4_usd}
label: Grant disbursement in period 4
expression: dt.project.gcf_grant_usd * dt.project.gcf_grant_disbursement_period_4_share
:::

:::calculation {#cofinance_disbursement_period_4_usd}
label: Cofinance disbursement in period 4
expression: dt.project.cofinance_usd * dt.project.cofinance_disbursement_period_4_share
:::

:::calculation {#gcf_disbursement_period_4_usd}
label: Total GCF disbursement in period 4
expression: sum(soft_loan_disbursement_period_4_usd, reimbursable_grant_disbursement_period_4_usd, grant_disbursement_period_4_usd)
:::

:::calculation {#total_disbursement_period_4_usd}
label: Total funding disbursement in period 4
expression: gcf_disbursement_period_4_usd + cofinance_disbursement_period_4_usd
:::

:::calculation {#cumulative_disbursement_period_1_usd}
label: Cumulative disbursement through period 1
expression: total_disbursement_period_1_usd
:::

:::calculation {#cumulative_disbursement_period_2_usd}
label: Cumulative disbursement through period 2
expression: cumulative_disbursement_period_1_usd + total_disbursement_period_2_usd
:::

:::calculation {#cumulative_disbursement_period_3_usd}
label: Cumulative disbursement through period 3
expression: cumulative_disbursement_period_2_usd + total_disbursement_period_3_usd
:::

:::calculation {#cumulative_disbursement_period_4_usd}
label: Cumulative disbursement through period 4
expression: cumulative_disbursement_period_3_usd + total_disbursement_period_4_usd
:::

:::calculation {#gcf_frontloaded_share_pct}
label: GCF financing scheduled in period 1
expression: percentage(gcf_disbursement_period_1_usd, gcf_funding_total)
:::

:::calculation {#peak_disbursement_period_usd}
label: Peak single-period disbursement
expression: max(total_disbursement_period_1_usd, total_disbursement_period_2_usd, total_disbursement_period_3_usd, total_disbursement_period_4_usd)
:::

:::calculation {#peak_disbursement_share_pct}
label: Peak-period share of committed funding
expression: percentage(peak_disbursement_period_usd, funding_sources_total)
:::

:::calculation {#funding_schedule_residual_usd}
label: Funding schedule residual after period 4
expression: funding_sources_total - cumulative_disbursement_period_4_usd
:::

:::calculation {#funding_schedule_residual_abs_usd}
label: Absolute funding schedule residual after period 4
expression: abs(funding_schedule_residual_usd)
:::

:::calculation {#funding_schedule_residual_pct}
label: Absolute funding schedule residual as share of committed funding
expression: percentage(funding_schedule_residual_abs_usd, funding_sources_total)
:::

:::calculation {#funding_schedule_reconciliation_status}
label: Funding schedule reconciliation status
expression: if(funding_schedule_residual_pct <= 0.01, "reconciled within 0.01%", "not reconciled within 0.01%")
:::

:::calculation {#ghg_reduction_midpoint_tco2e}
label: Midpoint of expected lifetime GHG reduction range
expression: mean(dt.project.ghg_reduction_min_tco2e, dt.project.ghg_reduction_max_tco2e)
:::

:::calculation {#ghg_reduction_range_width_tco2e}
label: Width of expected lifetime GHG reduction range
expression: dt.project.ghg_reduction_max_tco2e - dt.project.ghg_reduction_min_tco2e
:::

:::calculation {#ghg_reduction_range_width_pct}
label: GHG range width relative to range midpoint
expression: percentage(ghg_reduction_range_width_tco2e, ghg_reduction_midpoint_tco2e)
:::

:::calculation {#total_financing_per_tco2e_low}
label: Total committed financing per tCO2e, low-intensity bound
expression: funding_sources_total / dt.project.ghg_reduction_max_tco2e
:::

:::calculation {#total_financing_per_tco2e_midpoint}
label: Total committed financing per tCO2e, midpoint scenario
expression: funding_sources_total / ghg_reduction_midpoint_tco2e
:::

:::calculation {#total_financing_per_tco2e_high}
label: Total committed financing per tCO2e, high-intensity bound
expression: funding_sources_total / dt.project.ghg_reduction_min_tco2e
:::

:::calculation {#gcf_financing_per_tco2e_low}
label: GCF financing per tCO2e, low-intensity bound
expression: gcf_funding_total / dt.project.ghg_reduction_max_tco2e
:::

:::calculation {#gcf_financing_per_tco2e_midpoint}
label: GCF financing per tCO2e, midpoint scenario
expression: gcf_funding_total / ghg_reduction_midpoint_tco2e
:::

:::calculation {#gcf_financing_per_tco2e_high}
label: GCF financing per tCO2e, high-intensity bound
expression: gcf_funding_total / dt.project.ghg_reduction_min_tco2e
:::

:::calculation {#simple_funding_per_implementation_year}
label: Simple average committed funding per implementation year
expression: funding_sources_total / dt.project.implementation_years
:::

:::calculation {#simple_gcf_per_implementation_year}
label: Simple average GCF financing per implementation year
expression: gcf_funding_total / dt.project.implementation_years
:::

:::calculation {#enabled_capacity_midpoint_mw}
label: Midpoint of enabled geothermal capacity range
expression: mean(dt.project.enabled_capacity_min_mw, dt.project.enabled_capacity_max_mw)
:::

:::calculation {#funding_per_enabled_mw_low}
label: Committed funding per enabled MW, low bound
expression: funding_sources_total / dt.project.enabled_capacity_max_mw
:::

:::calculation {#funding_per_enabled_mw_high}
label: Committed funding per enabled MW, high bound
expression: funding_sources_total / dt.project.enabled_capacity_min_mw
:::

:::calculation {#gcf_per_enabled_mw_low}
label: GCF financing per enabled MW, low bound
expression: gcf_funding_total / dt.project.enabled_capacity_max_mw
:::

:::calculation {#gcf_per_enabled_mw_high}
label: GCF financing per enabled MW, high bound
expression: gcf_funding_total / dt.project.enabled_capacity_min_mw
:::

:::calculation {#mobilized_capital_per_gcf_dollar_low}
label: Expected mobilized capital per GCF dollar, low bound
expression: ratio(dt.project.mobilized_capital_min_usd, gcf_funding_total)
:::

:::calculation {#mobilized_capital_per_gcf_dollar_high}
label: Expected mobilized capital per GCF dollar, high bound
expression: ratio(dt.project.mobilized_capital_max_usd, gcf_funding_total)
:::

:::calculation {#mobilized_capital_per_committed_dollar_low}
label: Expected mobilized capital per committed funding dollar, low bound
expression: ratio(dt.project.mobilized_capital_min_usd, funding_sources_total)
:::

:::calculation {#mobilized_capital_per_committed_dollar_high}
label: Expected mobilized capital per committed funding dollar, high bound
expression: ratio(dt.project.mobilized_capital_max_usd, funding_sources_total)
:::

:::calculation {#mobilized_capital_per_enabled_mw_low}
label: Expected mobilized capital per enabled MW, low bound
expression: dt.project.mobilized_capital_min_usd / dt.project.enabled_capacity_max_mw
:::

:::calculation {#mobilized_capital_per_enabled_mw_high}
label: Expected mobilized capital per enabled MW, high bound
expression: dt.project.mobilized_capital_max_usd / dt.project.enabled_capacity_min_mw
:::

:::calculation {#funding_per_explored_project}
label: Committed funding per targeted explored project
expression: funding_sources_total / dt.project.projects_explored_target
:::

:::calculation {#gcf_per_explored_project}
label: GCF financing per targeted explored project
expression: gcf_funding_total / dt.project.projects_explored_target
:::

:::calculation {#first_tranche_impact_min_tco2e}
label: Implied first-tranche GHG impact, lower estimate
expression: dt.project.ghg_reduction_min_tco2e * ratio(dt.project.first_tranche_impact_share_pct, 100)
:::

:::calculation {#first_tranche_impact_max_tco2e}
label: Implied first-tranche GHG impact, upper estimate
expression: dt.project.ghg_reduction_max_tco2e * ratio(dt.project.first_tranche_impact_share_pct, 100)
:::

:::calculation {#remaining_impact_min_tco2e}
label: Implied remaining GHG impact, lower estimate
expression: dt.project.ghg_reduction_min_tco2e - first_tranche_impact_min_tco2e
:::

:::calculation {#remaining_impact_max_tco2e}
label: Implied remaining GHG impact, upper estimate
expression: dt.project.ghg_reduction_max_tco2e - first_tranche_impact_max_tco2e
:::

:::calculation {#first_tranche_gcf_share_pct}
label: First-tranche share of GCF financing
expression: percentage(dt.project.first_tranche_gcf_usd, gcf_funding_total)
:::

:::calculation {#remaining_gcf_financing_usd}
label: GCF financing after the first tranche
expression: gcf_funding_total - dt.project.first_tranche_gcf_usd
:::

:::calculation {#first_tranche_gcf_per_tco2e_low}
label: Implied first-tranche GCF financing per tCO2e, low bound
expression: dt.project.first_tranche_gcf_usd / first_tranche_impact_max_tco2e
:::

:::calculation {#first_tranche_gcf_per_tco2e_high}
label: Implied first-tranche GCF financing per tCO2e, high bound
expression: dt.project.first_tranche_gcf_usd / first_tranche_impact_min_tco2e
:::

:::calculation {#remaining_gcf_per_tco2e_low}
label: Implied remaining GCF financing per tCO2e, low bound
expression: remaining_gcf_financing_usd / remaining_impact_max_tco2e
:::

:::calculation {#remaining_gcf_per_tco2e_high}
label: Implied remaining GCF financing per tCO2e, high bound
expression: remaining_gcf_financing_usd / remaining_impact_min_tco2e
:::

:::calculation {#fossil_generation_share_pct}
label: 2017 fossil-fuel generation share
expression: sum(dt.project.energy_mix_coal_pct, dt.project.energy_mix_gas_pct, dt.project.energy_mix_diesel_pct)
:::

:::calculation {#energy_mix_total_check_pct}
label: 2017 generation mix total check
expression: sum(fossil_generation_share_pct, dt.project.energy_mix_renewables_pct)
:::

:::calculation {#renewables_policy_gap_pct}
label: Renewables policy target gap from 2017 share (percentage points)
expression: dt.project.renewables_policy_target_pct - dt.project.energy_mix_renewables_pct
:::

:::calculation {#implementation_to_commitment_ratio}
label: Implementation period relative to facility commitment period
expression: ratio(dt.project.implementation_years, dt.project.commitment_period_years)
:::

:::calculation {#simple_funding_per_commitment_year}
label: Simple average committed funding per facility commitment year
expression: funding_sources_total / dt.project.commitment_period_years
:::

:::calculation {#selected_kpi_count}
label: Selected KPI record count
expression: count(dt.selected_kpis)
:::

:::calculation {#country_count}
label: Project country count
expression: count(dt.project.countries)
:::

:::calculation {#risk_count}
label: Project risk record count
expression: count(dt.risks)
:::

:::calculation {#project_cost_vs_peer_median_ratio}
label: Project cost relative to leave-one-out peer median
expression: ratio(dt.project.total_cost_usd, reference.climatefund20.v2.fp083_leave_one_out.median_project_cost_usd)
:::

:::calculation {#ghg_midpoint_vs_peer_median_ratio}
label: GHG range midpoint relative to leave-one-out peer median
expression: ratio(ghg_reduction_midpoint_tco2e, reference.climatefund20.v2.fp083_leave_one_out.median_ghg_reduction_tco2e)
:::

:::calculation {#implementation_vs_peer_median_ratio}
label: Implementation period relative to leave-one-out peer median
expression: ratio(dt.project.implementation_years, reference.climatefund20.v2.fp083_leave_one_out.median_implementation_years)
:::

:::calculation {#lifespan_vs_peer_median_ratio}
label: Stated lifespan relative to leave-one-out peer median
expression: ratio(dt.project.lifespan_years, reference.climatefund20.v2.fp083_leave_one_out.median_lifespan_years)
:::

:::calculation {#country_count_vs_peer_median_ratio}
label: Country count relative to leave-one-out peer median
expression: ratio(country_count, reference.climatefund20.v2.fp083_leave_one_out.median_country_count)
:::

:::calculation {#cost_intensity_low_vs_peer_median_ratio}
label: Low-bound cost intensity relative to leave-one-out peer median
expression: ratio(total_financing_per_tco2e_low, reference.climatefund20.v2.fp083_leave_one_out.median_total_cost_per_tco2e)
:::

:::calculation {#cost_intensity_midpoint_vs_peer_median_ratio}
label: Midpoint cost intensity relative to leave-one-out peer median
expression: ratio(total_financing_per_tco2e_midpoint, reference.climatefund20.v2.fp083_leave_one_out.median_total_cost_per_tco2e)
:::

:::calculation {#cost_intensity_high_vs_peer_median_ratio}
label: High-bound cost intensity relative to leave-one-out peer median
expression: ratio(total_financing_per_tco2e_high, reference.climatefund20.v2.fp083_leave_one_out.median_total_cost_per_tco2e)
:::

:::calculation {#cost_intensity_midpoint_vs_public_energy_median_ratio}
label: Midpoint cost intensity relative to public-energy peer median
expression: ratio(total_financing_per_tco2e_midpoint, reference.climatefund20.v2.fp083_leave_one_out.public_energy_median_total_cost_per_tco2e)
:::

:::calculation {#cost_intensity_peer_band_position}
label: Project cost-intensity range position against peer interquartile band
expression: if(total_financing_per_tco2e_high < reference.climatefund20.v2.fp083_leave_one_out.q1_total_cost_per_tco2e, "entire range below peer lower quartile", if(total_financing_per_tco2e_low > reference.climatefund20.v2.fp083_leave_one_out.q3_total_cost_per_tco2e, "entire range above peer upper quartile", "range overlaps peer interquartile band"))
:::

## Executive summary {#executive_summary}

:::table {#executive_summary_table}
type: key-value
title: Executive evidence
data: dt.project.total_cost_usd, gcf_funding_total, funding_reconciliation_status, dt.project.ghg_reduction_min_tco2e, dt.project.ghg_reduction_max_tco2e, total_financing_per_tco2e_low, total_financing_per_tco2e_high, dt.project.enabled_capacity_min_mw, dt.project.enabled_capacity_max_mw, mobilized_capital_per_gcf_dollar_low, mobilized_capital_per_gcf_dollar_high, cost_intensity_peer_band_position
headers: [Executive indicator, Value]
:::

:::llm {#executive_summary_text}
title: Executive summary
instructions: |
  Write a compact executive summary for {dt.project.code} and {dt.project.title}.
  State committed cost {dt.project.total_cost_usd}, GCF financing
  {gcf_funding_total}, reconciliation {funding_reconciliation_status}, expected
  GHG range {dt.project.ghg_reduction_min_tco2e} to
  {dt.project.ghg_reduction_max_tco2e}, financing intensity range
  {total_financing_per_tco2e_low} to {total_financing_per_tco2e_high}, enabled
  capacity {dt.project.enabled_capacity_min_mw} to
  {dt.project.enabled_capacity_max_mw}, and expected mobilisation per GCF dollar
  {mobilized_capital_per_gcf_dollar_low} to
  {mobilized_capital_per_gcf_dollar_high}. State
  {cost_intensity_peer_band_position} as a descriptive peer result, not a return
  or investment recommendation. Preserve every qualification.
profile: neutral
:::

## Project identity and mandate {#project_identity_and_mandate}

:::table {#project_identity_table}
type: key-value
title: Project identity and mandate
data: dt.project.code, dt.project.title, dt.project.type, dt.project.sector, dt.project.size, dt.project.entity_name, dt.project.countries, dt.project.mitigation_areas, dt.project.energy_technologies
headers: [Project field, Value]
:::

:::llm {#project_identity_text}
title: Project identity and mandate
instructions: |
  Identify {dt.project.code}, {dt.project.title}, accredited entity
  {dt.project.entity_name}, countries {dt.project.countries}, project type
  {dt.project.type}, sector {dt.project.sector}, mitigation areas
  {dt.project.mitigation_areas}, and technologies
  {dt.project.energy_technologies}. Explain the
  stated intervention using {dt.project.description}, clearly separating source
  description from interpretation. Keep the synthesis compact, do not reproduce
  the full source description, and do not infer current delivery status.
profile: neutral
:::

## Climate and policy context {#climate_and_policy_context}

:::table {#climate_policy_table}
type: key-value
title: Climate and power-sector context
data: dt.project.energy_mix_coal_pct, dt.project.energy_mix_gas_pct, dt.project.energy_mix_diesel_pct, dt.project.energy_mix_renewables_pct, fossil_generation_share_pct, energy_mix_total_check_pct, dt.project.renewables_policy_target_pct, renewables_policy_gap_pct, dt.project.ndc_reduction_target_pct, dt.project.ndc_target_year
headers: [Context indicator, Value]
:::

:::llm {#climate_policy_text}
title: Climate and policy context
instructions: |
  Describe the source-dated 2017 generation mix using
  {dt.project.energy_mix_coal_pct}, {dt.project.energy_mix_gas_pct},
  {dt.project.energy_mix_diesel_pct}, and {dt.project.energy_mix_renewables_pct};
  verify it through
  {energy_mix_total_check_pct}. State fossil share {fossil_generation_share_pct},
  the renewables target {dt.project.renewables_policy_target_pct}, the arithmetic
  target gap {renewables_policy_gap_pct}, and the NDC commitment
  {dt.project.ndc_reduction_target_pct} for {dt.project.ndc_target_year}. Keep historical
  context distinct from current conditions and from project-attributable outcomes.
profile: neutral
:::

## Delivery mechanism and governance {#delivery_mechanism_and_governance}

:::table {#delivery_mechanism_table}
type: key-value
title: Delivery mechanism and governance
data: dt.project.delivery_mechanism, dt.project.implementation_agency, dt.project.implementation_sequence, dt.project.monitoring_reporting_process, dt.project.commitment_period_years, dt.project.implementation_years
headers: [Delivery field, Source-backed position]
:::

:::llm {#delivery_mechanism_text}
title: Delivery mechanism and governance
instructions: |
  Explain the facility mechanism {dt.project.delivery_mechanism}, implementing
  agency {dt.project.implementation_agency}, high-level sequence
  {dt.project.implementation_sequence}, and monitoring process
  {dt.project.monitoring_reporting_process}. Distinguish commitment period
  {dt.project.commitment_period_years} from overall implementation period
  {dt.project.implementation_years}, and do not invent dated milestones.
profile: neutral
:::

## Capital structure and instrument mix {#capital_structure_and_instrument_mix}

:::table {#capital_structure_table}
type: key-value
title: Capital structure and GCF instrument mix
data: dt.project.total_cost_usd, dt.project.gcf_soft_loan_usd, dt.project.gcf_reimbursable_grant_usd, dt.project.gcf_grant_usd, gcf_funding_total, dt.project.cofinance_usd, funding_sources_total, gcf_financing_share_pct, cofinance_share_pct, cofinance_per_gcf_dollar, total_funding_per_gcf_dollar, gcf_soft_loan_share_pct, gcf_reimbursable_grant_share_pct, gcf_grant_share_pct
headers: [Capital indicator, Value]
:::

:::llm {#capital_structure_text}
title: Capital structure and instrument mix
instructions: |
  Trace GCF financing from soft loan {dt.project.gcf_soft_loan_usd}, reimbursable
  grant {dt.project.gcf_reimbursable_grant_usd}, and grant
  {dt.project.gcf_grant_usd} to {gcf_funding_total}; explain their respective GCF
  shares {gcf_soft_loan_share_pct}, {gcf_reimbursable_grant_share_pct}, and
  {gcf_grant_share_pct}. Then explain cofinance, total committed sources, shares,
  and leverage using {dt.project.cofinance_usd}, {funding_sources_total},
  {gcf_financing_share_pct}, {cofinance_share_pct},
  {cofinance_per_gcf_dollar}, and {total_funding_per_gcf_dollar}. Treat instrument
  amounts as financing, not grant-equivalent cost,
  because pricing, repayment, and concessionality terms are not configured.
profile: neutral
:::

## Funding reconciliation {#funding_reconciliation}

:::table {#funding_reconciliation_table}
type: key-value
title: Committed funding reconciliation
data: dt.project.total_cost_usd, funding_sources_total, funding_reconciliation_gap, funding_reconciliation_gap_abs, funding_reconciliation_gap_pct, funding_reconciliation_status
headers: [Reconciliation indicator, Value]
:::

:::llm {#funding_reconciliation_text}
title: Funding reconciliation
instructions: |
  Reconcile committed sources {funding_sources_total} to stated project cost
  {dt.project.total_cost_usd}. Report signed gap {funding_reconciliation_gap},
  absolute gap {funding_reconciliation_gap_abs}, percentage gap
  {funding_reconciliation_gap_pct}, and {funding_reconciliation_status}. Describe
  this as an arithmetic consistency check, not an audit or a measure of project
  quality.
profile: neutral
:::

## Disbursement profile {#disbursement_profile}

:::table {#disbursement_profile_table}
type: key-value
title: Source-backed four-period disbursement profile
data: gcf_disbursement_period_1_usd, cofinance_disbursement_period_1_usd, total_disbursement_period_1_usd, gcf_disbursement_period_2_usd, cofinance_disbursement_period_2_usd, total_disbursement_period_2_usd, gcf_disbursement_period_3_usd, cofinance_disbursement_period_3_usd, total_disbursement_period_3_usd, gcf_disbursement_period_4_usd, cofinance_disbursement_period_4_usd, total_disbursement_period_4_usd, cumulative_disbursement_period_4_usd, gcf_frontloaded_share_pct, peak_disbursement_period_usd, peak_disbursement_share_pct, funding_schedule_residual_usd, funding_schedule_residual_pct, funding_schedule_reconciliation_status
headers: [Disbursement indicator, Value]
:::

:::llm {#disbursement_profile_text}
title: Disbursement profile
instructions: |
  Describe the four configured schedule periods using GCF values
  {gcf_disbursement_period_1_usd}, {gcf_disbursement_period_2_usd},
  {gcf_disbursement_period_3_usd}, and {gcf_disbursement_period_4_usd}; cofinance
  values {cofinance_disbursement_period_1_usd},
  {cofinance_disbursement_period_2_usd}, {cofinance_disbursement_period_3_usd}, and
  {cofinance_disbursement_period_4_usd}; and total values
  {total_disbursement_period_1_usd}, {total_disbursement_period_2_usd},
  {total_disbursement_period_3_usd}, and {total_disbursement_period_4_usd}.
  Identify cumulative scheduled funding {cumulative_disbursement_period_4_usd},
  front-loading
  {gcf_frontloaded_share_pct}, peak
  concentration {peak_disbursement_share_pct}, and
  final residual {funding_schedule_residual_pct}. Call them schedule periods, not
  calendar years, and do not infer a detailed implementation critical path.
profile: neutral
:::

## Impact range and financing intensity {#impact_range_and_financing_intensity}

:::table {#impact_range_table}
type: key-value
title: Expected impact range and financing intensity
data: dt.project.ghg_reduction_min_tco2e, ghg_reduction_midpoint_tco2e, dt.project.ghg_reduction_max_tco2e, ghg_reduction_range_width_tco2e, ghg_reduction_range_width_pct, total_financing_per_tco2e_low, total_financing_per_tco2e_midpoint, total_financing_per_tco2e_high, gcf_financing_per_tco2e_low, gcf_financing_per_tco2e_midpoint, gcf_financing_per_tco2e_high, dt.project.ghg_accounting_qualification
headers: [Impact indicator, Value]
:::

:::llm {#impact_range_text}
title: Impact range and financing intensity
instructions: |
  Present the expected lifetime GHG range through
  {dt.project.ghg_reduction_min_tco2e}, {ghg_reduction_midpoint_tco2e},
  {dt.project.ghg_reduction_max_tco2e}, and {ghg_reduction_range_width_pct}.
  Explain total financing intensity {total_financing_per_tco2e_low} to
  {total_financing_per_tco2e_high} and GCF intensity
  {gcf_financing_per_tco2e_low} to {gcf_financing_per_tco2e_high}. Explain
  that the low-intensity bound divides by the higher impact estimate and vice
  versa. Preserve {dt.project.ghg_accounting_qualification}; do not annualize the
  range or describe ex-ante financing intensity as realised abatement cost.
profile: neutral
:::

## Capacity and expected capital mobilisation {#capacity_and_expected_capital_mobilisation}

:::table {#capacity_mobilisation_table}
type: key-value
title: Enabled capacity and expected capital mobilisation
data: dt.project.enabled_capacity_min_mw, enabled_capacity_midpoint_mw, dt.project.enabled_capacity_max_mw, funding_per_enabled_mw_low, funding_per_enabled_mw_high, gcf_per_enabled_mw_low, gcf_per_enabled_mw_high, dt.project.mobilized_capital_min_usd, dt.project.mobilized_capital_max_usd, mobilized_capital_per_gcf_dollar_low, mobilized_capital_per_gcf_dollar_high, mobilized_capital_per_committed_dollar_low, mobilized_capital_per_committed_dollar_high, mobilized_capital_per_enabled_mw_low, mobilized_capital_per_enabled_mw_high, dt.project.projects_explored_target, funding_per_explored_project, gcf_per_explored_project
headers: [Scale or mobilisation indicator, Value]
:::

:::llm {#capacity_mobilisation_text}
title: Capacity and expected capital mobilisation
instructions: |
  Explain enabled capacity {dt.project.enabled_capacity_min_mw} to
  {dt.project.enabled_capacity_max_mw}, expected mobilisation
  {dt.project.mobilized_capital_min_usd} to
  {dt.project.mobilized_capital_max_usd}, financing per MW
  {funding_per_enabled_mw_low} to {funding_per_enabled_mw_high}, mobilisation per
  GCF dollar {mobilized_capital_per_gcf_dollar_low} to
  {mobilized_capital_per_gcf_dollar_high}, mobilisation per committed dollar
  {mobilized_capital_per_committed_dollar_low} to
  {mobilized_capital_per_committed_dollar_high}, and funding per targeted explored
  project {funding_per_explored_project}. State that
  mobilised capital is an expected downstream amount, mostly private, and must
  not be added to committed project funding or described as already secured.
profile: neutral
:::

## Tranche profile {#tranche_profile}

:::table {#tranche_profile_table}
type: key-value
title: First-tranche impact and financing profile
data: dt.project.first_tranche_gcf_usd, first_tranche_gcf_share_pct, dt.project.first_tranche_impact_share_pct, first_tranche_impact_min_tco2e, first_tranche_impact_max_tco2e, remaining_gcf_financing_usd, remaining_impact_min_tco2e, remaining_impact_max_tco2e, first_tranche_gcf_per_tco2e_low, first_tranche_gcf_per_tco2e_high, remaining_gcf_per_tco2e_low, remaining_gcf_per_tco2e_high
headers: [Tranche indicator, Value]
:::

:::llm {#tranche_profile_text}
title: Tranche profile
instructions: |
  Trace first-tranche GCF {dt.project.first_tranche_gcf_usd}, its share
  {first_tranche_gcf_share_pct}, and approximate impact share
  {dt.project.first_tranche_impact_share_pct} into implied first-tranche impact
  {first_tranche_impact_min_tco2e} to {first_tranche_impact_max_tco2e}, remaining
  financing {remaining_gcf_financing_usd}, and remaining impact
  {remaining_impact_min_tco2e} to {remaining_impact_max_tco2e}. Report first-tranche
  financing-intensity bounds {first_tranche_gcf_per_tco2e_low} to
  {first_tranche_gcf_per_tco2e_high} and remaining bounds
  {remaining_gcf_per_tco2e_low} to {remaining_gcf_per_tco2e_high}. Clearly
  label these values as arithmetic implications of the stated 60% approximation,
  not a separate verified GHG forecast or a statement of realised performance.
profile: neutral
:::

## Delivery scale {#delivery_scale}

:::table {#delivery_scale_table}
type: key-value
title: Delivery scale and simple averages
data: dt.project.implementation_years, dt.project.commitment_period_years, implementation_to_commitment_ratio, dt.project.lifespan_years, simple_funding_per_implementation_year, simple_gcf_per_implementation_year, simple_funding_per_commitment_year, country_count
headers: [Delivery indicator, Value]
:::

:::llm {#delivery_scale_text}
title: Delivery scale
instructions: |
  Distinguish implementation {dt.project.implementation_years}, facility
  commitment {dt.project.commitment_period_years}, and stated lifespan
  {dt.project.lifespan_years}. Explain {implementation_to_commitment_ratio},
  {simple_funding_per_implementation_year}, {simple_gcf_per_implementation_year},
  and {simple_funding_per_commitment_year}. Explicitly state that these averages assume
  uniform allocation and are not actual annual cash flows; do not annualize GHG
  impact because its target horizon is unresolved.
profile: neutral
:::

## Selected performance indicators and MRV {#selected_performance_indicators_and_mrv}

:::table {#selected_kpi_table}
type: records
title: Selected performance indicators
data: dt.selected_kpis
headers: [Indicator, Baseline, Intermediate target, Final target, Verification, Assumptions]
:::

:::llm {#selected_kpi_text}
title: Selected performance indicators and MRV
instructions: |
  In one compact paragraph, synthesize all {selected_kpi_count} records in
  {dt.selected_kpis} in source order. Identify each indicator theme and its key
  targets, preserve missing baseline or target states, and summarize shared or
  materially different verification methods and assumptions without repeating
  every table cell. Relate them to {dt.project.monitoring_reporting_process} and
  the formal MRV evidence gap {req.mrv_plan_status}. Cite at least one relevant
  field from each record and do not convert record count into a performance score.
profile: neutral
:::

## Risk landscape {#risk_landscape}

:::table {#risk_landscape_table}
type: records
title: Project risks
data: dt.risks
headers: [Risk, Type, Probability, Impact, Description, Mitigation]
:::

:::llm {#risk_landscape_text}
title: Risk landscape
instructions: |
  In one compact paragraph, synthesize every one of the {risk_count} records in
  {dt.risks}. Group regulatory, facility-design, institutional, procurement, and
  environmental themes; preserve each record's stated probability and impact;
  and summarize, rather than reproduce, its description and mitigation. Cite at
  least one relevant field from every record. Do not invent a financial loss
  estimate or an undisclosed composite risk score.
profile: neutral
:::

## Robust peer comparison {#robust_peer_comparison}

:::table {#robust_peer_table}
type: key-value
title: Frozen leave-one-out peer comparison
data: reference.climatefund20.v2.fp083_leave_one_out.sample_count, reference.climatefund20.v2.fp083_leave_one_out.median_project_cost_usd, project_cost_vs_peer_median_ratio, reference.climatefund20.v2.fp083_leave_one_out.median_ghg_reduction_tco2e, ghg_midpoint_vs_peer_median_ratio, reference.climatefund20.v2.fp083_leave_one_out.median_implementation_years, implementation_vs_peer_median_ratio, reference.climatefund20.v2.fp083_leave_one_out.median_lifespan_years, lifespan_vs_peer_median_ratio, reference.climatefund20.v2.fp083_leave_one_out.median_country_count, country_count_vs_peer_median_ratio, reference.climatefund20.v2.fp083_leave_one_out.q1_total_cost_per_tco2e, reference.climatefund20.v2.fp083_leave_one_out.median_total_cost_per_tco2e, reference.climatefund20.v2.fp083_leave_one_out.q3_total_cost_per_tco2e, cost_intensity_low_vs_peer_median_ratio, cost_intensity_midpoint_vs_peer_median_ratio, cost_intensity_high_vs_peer_median_ratio, reference.climatefund20.v2.fp083_leave_one_out.public_energy_sample_count, reference.climatefund20.v2.fp083_leave_one_out.public_energy_median_total_cost_per_tco2e, cost_intensity_midpoint_vs_public_energy_median_ratio, cost_intensity_peer_band_position, reference.climatefund20.v2.fp083_leave_one_out.methodology
headers: [Peer indicator, Value]
:::

:::llm {#robust_peer_text}
title: Robust peer comparison
instructions: |
  Compare scale, timing, country count, and the FP083 financing-intensity range
  through {project_cost_vs_peer_median_ratio}, {ghg_midpoint_vs_peer_median_ratio},
  {implementation_vs_peer_median_ratio}, {lifespan_vs_peer_median_ratio},
  {country_count_vs_peer_median_ratio}, and
  {cost_intensity_low_vs_peer_median_ratio} to
  {cost_intensity_high_vs_peer_median_ratio}. Use frozen cohort size
  {reference.climatefund20.v2.fp083_leave_one_out.sample_count}, quartiles
  {reference.climatefund20.v2.fp083_leave_one_out.q1_total_cost_per_tco2e} and
  {reference.climatefund20.v2.fp083_leave_one_out.q3_total_cost_per_tco2e}, and
  methodology {reference.climatefund20.v2.fp083_leave_one_out.methodology}. State
  overall cohort size and the public-energy subset size
  {reference.climatefund20.v2.fp083_leave_one_out.public_energy_sample_count};
  compare the midpoint with the public-energy median using
  {cost_intensity_midpoint_vs_public_energy_median_ratio}, and state
  {cost_intensity_peer_band_position}. Use project-to-median ratios, not inverted
  efficiency percentages. Explain that the public-energy subset is not geothermal
  matched and that differing project and GHG-accounting boundaries limit inference.
profile: neutral
:::

## Evidence gaps and investment synthesis {#evidence_gaps_and_investment_synthesis}

:::table {#evidence_gaps_table}
type: key-value
title: Material evidence gaps and synthesis anchors
data: req.project_status, req.technical_feasibility_status, req.permitting_status, req.detailed_implementation_schedule, req.revenue_model, req.lifecycle_opex, req.financial_returns, req.mrv_plan_status, req.ghg_target_horizon, funding_reconciliation_status, funding_schedule_reconciliation_status, total_financing_per_tco2e_low, total_financing_per_tco2e_high, mobilized_capital_per_gcf_dollar_low, mobilized_capital_per_gcf_dollar_high, cost_intensity_peer_band_position
headers: [Evidence or synthesis item, Current position]
:::

:::llm {#evidence_gaps_text}
title: Evidence gaps and investment synthesis
instructions: |
  Synthesize funding checks {funding_reconciliation_status} and
  {funding_schedule_reconciliation_status}, impact intensity
  {total_financing_per_tco2e_low} to {total_financing_per_tco2e_high}, expected
  mobilisation {mobilized_capital_per_gcf_dollar_low} to
  {mobilized_capital_per_gcf_dollar_high}, and peer position
  {cost_intensity_peer_band_position}; note {selected_kpi_count} selected KPI
  records and {risk_count} risk records without treating counts as performance.
  Enumerate {req.project_status},
  {req.technical_feasibility_status}, {req.permitting_status},
  {req.detailed_implementation_schedule}, {req.revenue_model},
  {req.lifecycle_opex}, {req.financial_returns}, {req.mrv_plan_status}, and
  {req.ghg_target_horizon}; explain why missing
  status, feasibility, permitting, schedule, revenue, OPEX, returns, MRV, and GHG
  horizon evidence prevents a bankability conclusion. Missing evidence is not a
  negative project result. Do not issue an investment recommendation.
profile: neutral
:::
