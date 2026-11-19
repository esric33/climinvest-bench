# V2 full-report citation-question review

> **Status:** Pending human review. These are report- and condition-specific question banks; no answer or citation-support judgments have been run from this file.

Generated 2026-08-31T18:09:45.460678+00:00 with `Qwen/Qwen3-8B` through the private OpenShift vLLM service (temperature 0; seeds 7, 17).

## Scope and provenance

- Full-report experiment run: `v2-luna-condition-gap-report-smoke-v1`
- Full report contexts: 6
- Sections/components per report: 15
- Generated questions: 308
- Citation-answer slots: 358
- Unresolved executable-gold slots: 8
- Generation tokens reported by vLLM: 93,024

Unlike the superseded generic template bank, every bank below is generated from one full report experiment context. Its inputs are the report’s project identity, mutation/mask condition, all 15 LLM component specifications, and the condition-specific executable-gold answer for each canonical citation dependency. Candidate report prose is deliberately excluded to avoid answer leakage from the system being evaluated.

## Coverage summary

| Project | Task | Family | Episode status | Components | Questions | Citation slots | Unresolved slots | Fallback components |
|---|---|---|---|---:|---:|---:|---:|---:|
| `FP083` | `missingness` | `financing_facility` | `turn_limit_exhausted` | 15 | 54 | 61 | 2 | 1 |
| `FP019` | `update` | `land_use_nature` | `completed` | 15 | 50 | 60 | 1 | 1 |
| `FP033` | `update` | `asset_delivery` | `completed` | 15 | 50 | 58 | 1 | 0 |
| `FP019` | `missingness` | `land_use_nature` | `completed` | 15 | 51 | 60 | 1 | 1 |
| `FP033` | `missingness` | `asset_delivery` | `completed` | 15 | 49 | 58 | 1 | 0 |
| `FP083` | `update` | `financing_facility` | `completed` | 15 | 54 | 61 | 2 | 1 |

# FP083 — Indonesia Geothermal Resource Risk Mitigation Project — missingness

Template `financing_facility` · condition `fp083.v2.population.mask.collection_with_dependents_cross_section` · episode `turn_limit_exhausted`

Executable gold `d765e79f850ba4b07d1029f5d69d159f2fd85397c3f7f77a40e96ac7c02a7044` · contract `d5098ba0ebfc7d33eb43ec844f6111611e9f8c2c5947902d55028fe367a49baa`

## 1. Executive assessment and critical issues

Section `executive_summary` · component `executive_summary_text` · output contract `benchmark.executive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the status of funding reconciliation for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.funding_reconciliation_status` | reconciled_within_0.1_pct_tolerance | `resolved` |

### Q2. What is the maximum set of priority risks identified for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.maximum_priority_risks` | missing | `resolved` |

### Q3. What is the set of priority KPIs defined for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.priority_kpis` | none | `resolved` |

### Q4. How are the reported aggregate amounts treated for benchmark arithmetic?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.funding_scope_qualification` | For benchmark arithmetic, the reported aggregate amounts are treated as one committed financing envelope; this is not an audit conclusion. | `resolved` |

### Q5. How are instrument amounts treated in the benchmark?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.instrument_terms_qualification` | Instrument amounts are face-value benchmark allocations, not grant equivalents; pricing, repayment and subsidy values are not inferred. Unused exhaustive instrument categories are reported as not applicable; their zero amounts and zero-percent shares are arithmetic balance placeholders only. | `resolved` |

### Q6. How is the mobilization range characterized for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.mobilization_qualification` | The range is a deterministic benchmark objective for incremental capital outside the deployment envelope; it is not committed or realized finance and is not a return. | `resolved` |

### Q7. How is the synthetic evidence used in the benchmark instance?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.synthetic_evidence_disclosure` | This benchmark instance combines immutable normalized source evidence with visibly labelled deterministic synthetic assumptions. It is not a factual due-diligence record. | `resolved` |

## 2. Project identification and status

Section `project_identification_and_status` · component `project_identification_and_status_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. What is the description of the project's objectives and expected outcomes?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.description` | The national grid in Indonesia has been dominated by fossil-fueled generation. Based on PLN’s RUPTL 2018, the 2017 generation mix was 58.3 percent coal, 23.2 percent gas, 6 percent diesel, 12.5 percent renewables. At the 2015 COP21 in Paris, Indonesia committed to a Nationally Determined Contribution (NDC) at 29 percent reduction of GHG emissions by 2030. In support of the Indonesian Government’s NDC and plan to increase the share of renewable energy in the power generation mix to 23 percent by 2026, the proposed Project aims to support a scale-up of investment in geothermal energy development. As a result, the Project is expected to contrib… | `resolved` |

### Q2. What is the current implementation status of the project according to the normalized benchmark source?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.project_status` | Current implementation status is not established by the normalized benchmark source. | `resolved` |

## 3. Promoter and delivery assessment

Section `promoter_and_delivery_arrangements` · component `promoter_and_delivery_arrangements_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. What is the current financial standing of the promoter for the Indonesia Geothermal Resource Risk Mitigation Project, and is there a comparable source-backed delivery track record available?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.promoter_financial_standing` | The promoter's current financial standing is not available as atomic evidence. | `resolved` |
| `req.promoter_track_record` | A comparable source-backed delivery track record for the promoter is not available as atomic evidence. | `resolved` |

## 4. Climate rationale and strategic fit

Section `climate_rationale_and_strategic_fit` · component `climate_rationale_and_strategic_fit_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the annualised reported GHG target for the project in tonnes of CO2 equivalent per year?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.annualised_reported_ghg_target_tco2e` | 18,700,000.00 tCO2e/year | `resolved` |

### Q2. What is the climate rationale for the project's intervention?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.climate_rationale` | A complete source-backed climate-hazard, exposure and vulnerability rationale is not available as atomic evidence. | `resolved` |

### Q3. What is the GHG target horizon for the project's accounting?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.ghg_target_horizon` | The source GHG point estimate does not consistently expose a separate atomic accounting horizon. | `resolved` |

## 5. Market rationale and financial additionality

Section `market_rationale_and_additionality` · component `market_rationale_and_additionality_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. What is the scope of the facility's profile and how does it define the deployment approach for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.facility_profile_scope` | full configured deployment profile without recycling or released-capacity reuse | `resolved` |

### Q2. What is the identified financing barrier that the facility is intended to address for the target segment?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.market_financing_barrier` | Insufficient tenor, risk appetite or affordable liquidity for otherwise eligible climate investments. | `resolved` |

## 6. Instrument structure and terms

Section `instrument_structure_and_terms` · component `instrument_structure_and_terms_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the status of the reconciliation of instrument amounts across the project's benchmark allocations?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.gcf_instrument_reconciliation_status` | reconciled_within_0.1_pct_tolerance | `resolved` |

### Q2. How are the instrument terms qualified in terms of their allocation and valuation?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.instrument_terms_qualification` | Instrument amounts are face-value benchmark allocations, not grant equivalents; pricing, repayment and subsidy values are not inferred. Unused exhaustive instrument categories are reported as not applicable; their zero amounts and zero-percent shares are arithmetic balance placeholders only. | `resolved` |

## 7. Allocation and utilisation profile

Section `allocation_and_utilisation_profile` · component `allocation_and_utilisation_profile_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the deployment envelope per GCF dollar declared for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.deployment_envelope_per_gcf_dollar` | 0.95x | `resolved` |

### Q2. Is there a source-backed dated activity-level critical path present in the normalized evidence for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.detailed_implementation_schedule` | No source-backed dated activity-level critical path is present in the normalized evidence. | `resolved` |

### Q3. Is the formal MRV-plan completion status available as atomic evidence for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.mrv_plan_status` | Formal MRV-plan completion status is not available as atomic evidence. | `resolved` |

### Q4. Are a source-backed procurement plan and procurement status available as atomic evidence for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.procurement_plan` | A source-backed procurement plan and procurement status are not available as atomic evidence. | `resolved` |

## 8. Portfolio scale and mobilisation

Section `portfolio_scale_and_mobilisation` · component `portfolio_scale_and_mobilisation_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. Under what condition should the expected scale and mobilisation range be interpreted for this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.mobilization_applicability` | No exact resolved state found. | `unresolved` |

### Q2. What is the nature of the range provided for mobilisation in this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.mobilization_qualification` | The range is a deterministic benchmark objective for incremental capital outside the deployment envelope; it is not committed or realized finance and is not a return. | `resolved` |

### Q3. What is the basis for the portfolio-unit count used in this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.portfolio_unit_count_basis` | synthetic expected final portfolio for benchmark arithmetic | `resolved` |

### Q4. How should the portfolio-unit count be interpreted in this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.portfolio_unit_count_qualification` | The count retains its stated type and basis; per-unit amounts are allocation intensities, not universal ticket sizes. | `resolved` |

## 9. Technical feasibility and implementation readiness

Section `technical_feasibility_and_readiness` · component `technical_feasibility_and_readiness_text` · output contract `benchmark.interpretive_assessment.v1`

> **Contract coverage gap:** no canonical citation-answer dependencies are bound to this LLM component, so no question can be generated from the specification.

## 10. Costs and financing structure

Section `costs_and_financing_structure` · component `costs_and_financing_structure_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the ratio of cofinance to GCF dollars for this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.cofinance_per_gcf_dollar` | 1.76x | `resolved` |

### Q2. What is the total amount of committed funding sources for this project in USD?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.committed_funding_sources_usd` | 510,000,000.00 USD | `resolved` |

### Q3. What is the status of funding reconciliation for this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.funding_reconciliation_status` | reconciled_within_0.1_pct_tolerance | `resolved` |

### Q4. What is the funding scope comparability status for this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.funding_scope_comparability` | comparable | `resolved` |

## 11. Financial sustainability and business model

Section `financial_sustainability_and_business_model` · component `financial_sustainability_and_business_model_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. What is the status of the facility recycling qualification for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.facility_recycling_qualification` | No repayments, released guarantees or capital reuse enter the four-period state chain. | `resolved` |

### Q2. What is the status of the instrument terms qualification for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.instrument_terms_qualification` | Instrument amounts are face-value benchmark allocations, not grant equivalents; pricing, repayment and subsidy values are not inferred. Unused exhaustive instrument categories are reported as not applicable; their zero amounts and zero-percent shares are arithmetic balance placeholders only. | `resolved` |

### Q3. What is the status of the business model, financial model, financial returns, lifecycle operating expenditure, and revenue model for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.business_model` | A complete source-backed business model is not available as atomic evidence. | `resolved` |
| `req.financial_model` | A complete source-backed financial model and its assumptions are not available as atomic evidence. | `resolved` |
| `req.financial_returns` | Comparable project-level financial-return measures are not available as atomic evidence. | `resolved` |
| `req.lifecycle_opex` | Lifecycle operating expenditure is not available as atomic evidence. | `resolved` |

### Q4. What is the status of the revenue model for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.revenue_model` | A complete revenue model is not available as atomic evidence. | `resolved` |

## 12. Impact, ESG, and safeguards

Section `impact_esg_and_safeguards` · component `impact_esg_and_safeguards_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **deterministic fallback**.

### Q1. What is the evidence status or value for project cost per reported tco2e?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.project_cost_per_reported_tco2e` | 2.73 USD/tCO2e | `resolved` |

## 13. Performance indicators and MRV

Section `performance_indicators_and_mrv` · component `performance_indicators_and_mrv_text` · output contract `benchmark.kpi_priority.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. How many indicators were available for prioritization in the KPI selection process?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.available_kpi_priority_count` | 16 indicators | `resolved` |

### Q2. How many indicators remained unranked in the KPI selection process?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.incomplete_kpi_priority_count` | 0 indicators | `resolved` |

### Q3. What was the priority cutoff used to select the KPIs?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.kpi_priority_cutoff` | 4 priority | `resolved` |

### Q4. How many indicators were selected as priority KPIs?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.priority_kpi_count` | 2 indicators | `resolved` |

### Q5. How many indicators were prioritized in the KPI selection process?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.prioritized_kpi_count` | 16 indicators | `resolved` |

### Q6. What are the selected priority KPIs for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.priority_kpis` | Tonnes of carbon dioxide equivalent (t CO2eq) reduced as a result of Fund funded projects/ programmes; MWs of Lowemission energy capacity installed, generated and/or rehabilitated as a result of the GCF support. | `resolved` |

### Q7. What is the total number of MRV-ready KPIs?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.mrv_ready_kpi_count` | 16 indicators | `resolved` |

### Q8. What are the MRV assessments associated with the KPIs?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.kpi_mrv_assessments` | Tonnes of carbon dioxide equivalent (t CO2eq) reduced as a result of Fund funded projects/ programmes; Cost per t CO2eq decreased for all Fund-funded mitigation projects/ programmes; MWs of Lowemission energy capacity installed, generated and/or rehabilitated as a result of the GCF support.; Volume of finance leveraged by Fund funding; Volume of finance leveraged by Fund funding – SubElement 1: Private capital mobilized for investment in geothermal Exploration; Volume of finance leveraged by Fund funding – SubElement 2: Private capital expected to be mobilized for investment in geothermal development over time; Number of projects explored; P… | `resolved` |

### Q9. What are the target delta assessments associated with the KPIs?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.kpi_target_delta_assessments` | Tonnes of carbon dioxide equivalent (t CO2eq) reduced as a result of Fund funded projects/ programmes; Cost per t CO2eq decreased for all Fund-funded mitigation projects/ programmes; MWs of Lowemission energy capacity installed, generated and/or rehabilitated as a result of the GCF support.; Volume of finance leveraged by Fund funding; Volume of finance leveraged by Fund funding – SubElement 1: Private capital mobilized for investment in geothermal Exploration; Volume of finance leveraged by Fund funding – SubElement 2: Private capital expected to be mobilized for investment in geothermal development over time; Number of projects explored; P… | `resolved` |

### Q10. How many KPIs have compatible target delta assessments?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.kpi_compatible_target_delta_count` | 13 indicators | `resolved` |

### Q11. What is the status of the project's monitoring and reporting process?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.monitoring_reporting_process` | No exact resolved state found. | `unresolved` |

### Q12. What is the status of the MRV plan for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.mrv_plan_status` | Formal MRV-plan completion status is not available as atomic evidence. | `resolved` |

## 14. Risk and bankability constraints

Section `risk_and_bankability_constraints` · component `risk_and_bankability_constraints_text` · output contract `benchmark.risk_priority.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. How many risks are scored in the risk and bankability constraints analysis for the Indonesia Geothermal Resource Risk Mitigation Project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.scored_risk_count` | missing | `resolved` |

### Q2. How many risks are unscored in the risk and bankability constraints analysis for the Indonesia Geothermal Resource Risk Mitigation Project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.incomplete_risk_count` | missing | `resolved` |

### Q3. What is the maximum risk priority score used in the risk and bankability constraints analysis for the Indonesia Geothermal Resource Risk Mitigation Project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.maximum_risk_priority_score` | null | `resolved` |

### Q4. How many risks are selected as maximum priority risks in the risk and bankability constraints analysis for the Indonesia Geothermal Resource Risk Mitigation Project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.maximum_priority_risk_count` | null | `resolved` |

### Q5. What is the set of risks tied at the maximum risk priority score in the risk and bankability constraints analysis for the Indonesia Geothermal Resource Risk Mitigation Project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.maximum_priority_risks` | missing | `resolved` |

## 15. Conclusions and evidence requirements

Section `conclusions_and_evidence_requirements` · component `conclusions_and_evidence_requirements_text` · output contract `benchmark.evidence_requirements.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. What is the status of funding reconciliation for the project, and what is the maximum-risk priority score?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.funding_reconciliation_status` | reconciled_within_0.1_pct_tolerance | `resolved` |
| `calc.maximum_risk_priority_score` | missing | `resolved` |

### Q2. What is the priority-KPI cutoff, and what is the status of the financial model?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.kpi_priority_cutoff` | 4 priority | `resolved` |
| `req.financial_model` | A complete source-backed financial model and its assumptions are not available as atomic evidence. | `resolved` |

### Q3. What is the status of technical design maturity and environmental and social safeguards?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.technical_design_maturity` | Technical design maturity is not available as atomic evidence. | `resolved` |
| `req.environmental_social_safeguards` | A complete environmental and social safeguards assessment is not available as atomic evidence. | `resolved` |


# FP019 — Priming Financial and Land-Use Planning Instruments to Reduce Emissions from Deforestation — update

Template `land_use_nature` · condition `fp019.v2.population.mutation.collection_with_dependents_cross_section` · episode `completed`

Executable gold `8032f0622104f7a7006f69545f03ef79f13466c491c67b0693cbe4bf53620ce7` · contract `38afb10b0c6d9f19a7dd76a139ca9ab8e7efba9487425856a7596f8fc41881a5`

## 1. Executive assessment and critical issues

Section `executive_summary` · component `executive_summary_text` · output contract `benchmark.executive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the status of funding reconciliation for this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.funding_reconciliation_status` | reconciled_within_0.1_pct_tolerance | `resolved` |

### Q2. What are the maximum priority risks associated with this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.maximum_priority_risks` | Social and environmental; Social and environmental; Social and environmental | `resolved` |

### Q3. What is the ratio of modelled to reported greenhouse gas emissions for this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.modelled_vs_reported_ghg_ratio` | 0.3038610343333334 x | `resolved` |

### Q4. What are the priority key performance indicators for this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.priority_kpis` | none | `resolved` |

### Q5. How is the funding scope qualified for this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.funding_scope_qualification` | For benchmark arithmetic, the reported aggregate amounts are treated as one committed financing envelope; this is not an audit conclusion. | `resolved` |

### Q6. How is the land accounting qualified for this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.land_accounting_qualification` | The pathway areas, rates, factors, enrolment profile and deductions are deterministic benchmark assumptions. Plantation is not relabelled as restoration, and co-benefits outside the boundary are excluded. | `resolved` |

### Q7. What is the disclosure status of synthetic evidence used in this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.synthetic_evidence_disclosure` | This benchmark instance combines immutable normalized source evidence with visibly labelled deterministic synthetic assumptions. It is not a factual due-diligence record. | `resolved` |

## 2. Project identification and status

Section `project_identification_and_status` · component `project_identification_and_status_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. What is the description of the project and its intended mandate, including the activities it aims to finance and the timeframe for assessing emission reductions?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.description` | Ecuador is finalizing its REDD+1 readiness process. A Forest Reference Emission Level (FREL) was submitted and technically assessed by the UNFCCC in 20153 and a REDD+ Action Plan (REDD+ AP4) has been approved. The Action Plan presents the policies and measures prioritized to address the drivers of deforestation5. It has a national scope and includes the 5 REDD+ activities. It is designed to support the national objective of achieving zero net deforestation by 2020. The GCF project will co-finance the REDD+ AP by providing targeted investment to control agricultural expansion into forest areas; optimize existing financial, economic mechanisms… | `resolved` |

### Q2. What is the current implementation status of the project according to the normalized benchmark source?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.project_status` | Current implementation status is not established by the normalized benchmark source. | `resolved` |

## 3. Promoter and delivery assessment

Section `promoter_and_delivery_arrangements` · component `promoter_and_delivery_arrangements_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the current financial standing of the promoter for the FP019 project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.promoter_financial_standing` | The promoter's current financial standing is not available as atomic evidence. | `resolved` |

### Q2. Is there a comparable source-backed delivery track record for the promoter of the FP019 project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.promoter_track_record` | A comparable source-backed delivery track record for the promoter is not available as atomic evidence. | `resolved` |

## 4. Climate rationale and strategic fit

Section `climate_rationale_and_strategic_fit` · component `climate_rationale_and_strategic_fit_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. What is the climate rationale for the project, and how does the greenhouse gas target horizon constrain the case?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.climate_rationale` | A complete source-backed climate-hazard, exposure and vulnerability rationale is not available as atomic evidence. | `resolved` |
| `req.ghg_target_horizon` | The source GHG point estimate does not consistently expose a separate atomic accounting horizon. | `resolved` |

### Q2. What is the annualised reported greenhouse gas target in tonnes of carbon dioxide equivalent per year?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.annualised_reported_ghg_target_tco2e` | 3,000,000.00 tCO2e/year | `resolved` |

## 5. Land-use baseline and intervention

Section `land_use_baseline_and_intervention` · component `land_use_baseline_and_intervention_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. What is the rate of avoided deforestation and how does it relate to the jurisdictional accounting qualification for this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.avoided_deforestation_rate_pct_per_year` | not applicable | `resolved` |
| `dt.project.jurisdictional_accounting_qualification` | The national accounting area and annual reference/program emissions are independently seeded deterministic benchmark-scenario inputs; the reported GHG target was not an input. They are not source-derived FREL values, observed performance, or validation of the reported target. | `resolved` |

### Q2. What is the annual jurisdictional gross reduction in CO2 equivalent emissions and what is the land carbon pathway boundary for this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.jurisdictional_gross_reduction_tco2e_per_year` | 911,583.10 tCO2e/year | `resolved` |
| `dt.project.land_carbon_pathway_boundary` | The national jurisdictional reference-level pathway is the sole benchmark carbon boundary; activity-area pathways are excluded. | `resolved` |

## 6. Area allocation and enrolment

Section `area_allocation_and_enrolment` · component `area_allocation_and_enrolment_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the status of land area reconciliation for the applicable accounting area in this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.land_area_reconciliation_status` | not_applicable_jurisdictional_boundary | `resolved` |

### Q2. Is there a source-backed dated activity-level critical path available for the detailed implementation schedule?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.detailed_implementation_schedule` | No source-backed dated activity-level critical path is present in the normalized evidence. | `resolved` |

### Q3. Are land tenure, access, and site-control status available as complete atomic evidence?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.land_and_access_status` | Land tenure, access and site-control status are not available as complete atomic evidence. | `resolved` |

## 7. Carbon-accounting consistency

Section `carbon_accounting_consistency` · component `carbon_accounting_consistency_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the modelled net accounting GHG value in tCO2e for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.modelled_net_accounting_ghg_tco2e` | 4,557,915.52 tCO2e | `resolved` |

### Q2. What is the ratio of modelled GHG to reported GHG for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.modelled_vs_reported_ghg_ratio` | 0.30x | `resolved` |

### Q3. What is the jurisdictional accounting qualification for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.jurisdictional_accounting_qualification` | The national accounting area and annual reference/program emissions are independently seeded deterministic benchmark-scenario inputs; the reported GHG target was not an input. They are not source-derived FREL values, observed performance, or validation of the reported target. | `resolved` |

### Q4. What is the GHG comparison status of the project with respect to reported targets?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.reported_ghg_comparison_status` | comparable | `resolved` |

## 8. People and co-benefits

Section `people_and_cobenefits` · component `people_and_cobenefits_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **deterministic fallback**.

### Q1. What is the evidence status or value for beneficiary allocation qualification?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.beneficiary_allocation_qualification` | Input basis: direct=synthetic scenario, women=synthetic scenario, local-community=synthetic scenario, livelihood-enterprise=synthetic scenario. Any synthetic counts are deterministic, project-specific ex-ante allocation scenarios. Women and local-community shares are allocation diagnostics only; they do not evidence delivery, participation, equity, benefit quality, or performance. | `resolved` |

## 9. Technical feasibility and implementation readiness

Section `technical_feasibility_and_readiness` · component `technical_feasibility_and_readiness_text` · output contract `benchmark.interpretive_assessment.v1`

> **Contract coverage gap:** no canonical citation-answer dependencies are bound to this LLM component, so no question can be generated from the specification.

## 10. Costs and financing structure

Section `costs_and_financing_structure` · component `costs_and_financing_structure_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the ratio of cofinance to GCF dollars for this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.cofinance_per_gcf_dollar` | 1.04x | `resolved` |

### Q2. What is the total amount of committed funding sources for this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.committed_funding_sources_usd` | 84,008,647.00 USD | `resolved` |

### Q3. What is the status of the funding reconciliation for this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.funding_reconciliation_status` | reconciled_within_0.1_pct_tolerance | `resolved` |

### Q4. What is the funding scope comparability for this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.funding_scope_comparability` | comparable | `resolved` |

## 11. Financial sustainability and business model

Section `financial_sustainability_and_business_model` · component `financial_sustainability_and_business_model_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. Can recurrent financing, operating sustainability, repayment capacity, or returns be assessed from the business model, financial model, financial returns, lifecycle operating expenditure, and revenue model for this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.business_model` | A complete source-backed business model is not available as atomic evidence. | `resolved` |
| `req.financial_model` | A complete source-backed financial model and its assumptions are not available as atomic evidence. | `resolved` |
| `req.financial_returns` | Comparable project-level financial-return measures are not available as atomic evidence. | `resolved` |
| `req.lifecycle_opex` | Lifecycle operating expenditure is not available as atomic evidence. | `resolved` |

### Q2. Is there evidence of a complete source-backed business model, financial model, financial returns, lifecycle operating expenditure, or revenue model for this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.revenue_model` | A complete revenue model is not available as atomic evidence. | `resolved` |

## 12. Impact, ESG, and safeguards

Section `impact_esg_and_safeguards` · component `impact_esg_and_safeguards_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the cost per unit of reported carbon dioxide equivalent emissions for this project, and what is the qualification for the greenhouse gas accounting?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.project_cost_per_reported_tco2e` | 5.60 USD/tCO2e | `resolved` |

### Q2. What is the qualification for the greenhouse gas accounting in this project, and how is the normalized project value treated in the accounting boundary?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.ghg_accounting_qualification` | The normalized project value remains the reported point target. The lower and upper bounds and the lifespan-anchored accounting horizon are synthetic benchmark assumptions, not proposal claims. | `resolved` |

## 13. Performance indicators and MRV

Section `performance_indicators_and_mrv` · component `performance_indicators_and_mrv_text` · output contract `benchmark.kpi_priority.v1`

Generation: **model generation attempt 2 (seed 17)**.

### Q1. How many indicators were available for prioritization in the KPI selection process?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.available_kpi_priority_count` | 21 indicators | `resolved` |

### Q2. How many indicators remained unranked in the KPI prioritization process?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.incomplete_kpi_priority_count` | 0 indicators | `resolved` |

### Q3. How many of the selected KPIs have compatible target delta assessments?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.kpi_compatible_target_delta_count` | 9 indicators | `resolved` |

### Q4. What are the assessments related to the MRV status of the selected KPIs?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.kpi_mrv_assessments` | emission reduction (tCO2e) as a result of REDD+ AP; cost per tCO2e; Institutional and regulatory systems that improve incentives for low- emission planning and development and their effective implementation; Number and level of effective coordination mechanisms; Hectares of land or forests under improved and effective management that contributes to CO2 emission reductions; Number of strengthened land-use planning instruments and life plans that have included climate change mitigation policies and actions; Provincial PDOT; Cantonal PDOT; Life Plans; Number of legal coordination instruments at a national and territorial level for REDD+; rea (h… | `resolved` |

### Q5. What is the priority cutoff used to select the KPIs?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.kpi_priority_cutoff` | 4 priority | `resolved` |

### Q6. What are the assessments related to the target delta of the KPIs?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.kpi_target_delta_assessments` | emission reduction (tCO2e) as a result of REDD+ AP; cost per tCO2e; Institutional and regulatory systems that improve incentives for low- emission planning and development and their effective implementation; Number and level of effective coordination mechanisms; Hectares of land or forests under improved and effective management that contributes to CO2 emission reductions; Number of strengthened land-use planning instruments and life plans that have included climate change mitigation policies and actions; Provincial PDOT; Cantonal PDOT; Life Plans; Number of legal coordination instruments at a national and territorial level for REDD+; rea (h… | `resolved` |

### Q7. How many of the KPIs are considered MRV-ready?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.mrv_ready_kpi_count` | 18 indicators | `resolved` |

### Q8. How many KPIs were prioritized in the selection process?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.prioritized_kpi_count` | 21 indicators | `resolved` |

### Q9. How many KPIs were selected as priority KPIs?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.priority_kpi_count` | 7 indicators | `resolved` |

### Q10. What are the selected priority KPIs?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.priority_kpis` | emission reduction (tCO2e) as a result of REDD+ AP; Hectares of land or forests under improved and effective management that contributes to CO2 emission reductions; rea (ha) transformed to sustainable production systems in deforested areas; Area (ha) transformed to sustainable production systems in deforested areas; Number of hectares under conservation incentives in priority areas with high threat of deforestation and potential to generate social and environmental cobenefits; Number of hectares under conservation incentives in priority areas with high threat of deforestation and potential to generate social and environmental cobenefi; Numbe… | `resolved` |

### Q11. What is the status of the project's monitoring and reporting process?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.monitoring_reporting_process` | No exact resolved state found. | `unresolved` |

### Q12. What is the status of the MRV plan for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.mrv_plan_status` | Formal MRV-plan completion status is not available as atomic evidence. | `resolved` |

## 14. Risk and bankability constraints

Section `risk_and_bankability_constraints` · component `risk_and_bankability_constraints_text` · output contract `benchmark.risk_priority.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. How many risks are scored in the risk and bankability constraints section of this report?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.scored_risk_count` | 5 risks | `resolved` |

### Q2. How many risks are not scored in the risk and bankability constraints section of this report?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.incomplete_risk_count` | 0 risks | `resolved` |

### Q3. What is the maximum risk priority score used in the risk and bankability constraints section of this report?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.maximum_risk_priority_score` | 2 | `resolved` |

### Q4. How many risks are tied at the maximum risk priority score in the risk and bankability constraints section of this report?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.maximum_priority_risk_count` | 3 risks | `resolved` |

### Q5. What are the names of the risks tied at the maximum risk priority score in the risk and bankability constraints section of this report?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.maximum_priority_risks` | Social and environmental; Social and environmental; Social and environmental | `resolved` |

## 15. Conclusions and evidence requirements

Section `conclusions_and_evidence_requirements` · component `conclusions_and_evidence_requirements_text` · output contract `benchmark.evidence_requirements.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. What is the status of funding reconciliation for the project, and what is the maximum-risk priority score and KPI priority cutoff?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.funding_reconciliation_status` | reconciled_within_0.1_pct_tolerance | `resolved` |
| `calc.maximum_risk_priority_score` | 2 score | `resolved` |
| `calc.kpi_priority_cutoff` | 4 priority | `resolved` |

### Q2. What are the missing evidence requirements for the project's environmental and social safeguards, financial model, and technical design maturity?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.environmental_social_safeguards` | A complete environmental and social safeguards assessment is not available as atomic evidence. | `resolved` |
| `req.financial_model` | A complete source-backed financial model and its assumptions are not available as atomic evidence. | `resolved` |
| `req.technical_design_maturity` | Technical design maturity is not available as atomic evidence. | `resolved` |


# FP033 — Accelerating the Transformational Shift to a Low-Carbon Economy in the Republic of Mauritius — update

Template `asset_delivery` · condition `fp033.v2.population.mutation.collection_with_dependents_cross_section` · episode `completed`

Executable gold `4a6b1d01ee2f4b03632d270a550eb91a6f819c467370aee4b992603788ce48f3` · contract `25caa78a7c2876abce7c06eb27c2232558cd26d26e9c31a4e77724d07a2d5bc0`

## 1. Executive assessment and critical issues

Section `executive_summary` · component `executive_summary_text` · output contract `benchmark.executive_assessment.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. What is the status of funding reconciliation for the project, and how does it relate to the reported financial commitments?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.funding_reconciliation_status` | reconciled_within_0.1_pct_tolerance | `resolved` |
| `dt.project.funding_scope_qualification` | For benchmark arithmetic, the reported aggregate amounts are treated as one committed financing envelope; this is not an audit conclusion. | `resolved` |

### Q2. What are the maximum priority risks associated with the project, and how do they affect the project's implementation?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.maximum_priority_risks` | Delay in procurement of necessary technical assistance for the various components; Duty-bearers may not have the capacity to meet their obligations to the project; Potential for the project to reproduce discrimination against women’s participation; Technical and operational; Technical and operational; Technical and operational | `resolved` |

### Q3. What is the cost of the project per reported tonne of CO2 equivalent, and how is this value used in benchmarking?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.project_cost_per_reported_tco2e` | 44.85587063510663 USD/tCO2e | `resolved` |

### Q4. What are the key performance indicators that the results framework considers most important, and how are they treated in the assessment?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.priority_kpis` | none | `resolved` |

### Q5. How is the greenhouse gas accounting treated in the project, and what assumptions are made in the benchmarking process?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.ghg_accounting_qualification` | The normalized project value remains the reported point target. The lower and upper bounds and the lifespan-anchored accounting horizon are synthetic benchmark assumptions, not proposal claims. | `resolved` |

### Q6. What is the nature of the evidence used in the benchmark instance, and how are synthetic assumptions handled?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.synthetic_evidence_disclosure` | This benchmark instance combines immutable normalized source evidence with visibly labelled deterministic synthetic assumptions. It is not a factual due-diligence record. | `resolved` |

## 2. Project identification and status

Section `project_identification_and_status` · component `project_identification_and_status_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. What is the primary context and rationale for the project's focus on low-carbon development in Mauritius?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.description` | With 84% of its primary energy requirements met from imported fossil fuels, Mauritius, like many Small Island Developing States (SIDS), is extremely vulnerable to energy shocks. The grid emission factor of Mauritius is extremely high at 1.01 tonnes CO2/MWh due to the prevalence of imported coal (39%) and fuel oil (38%) in the electricity generation mix. Net greenhouse gas emissions are increasing at a rapid rate of 3% per year. The pressing need to significantly enhance Mauritius’s energy independence and reduce greenhouse gas emissions is recognised in the country’s Nationally Determined Contribution (2016), its Second National Communicatio… | `resolved` |

### Q2. What is the current implementation status of the project according to the normalized benchmark source?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.project_status` | Current implementation status is not established by the normalized benchmark source. | `resolved` |

## 3. Promoter and delivery assessment

Section `promoter_and_delivery_arrangements` · component `promoter_and_delivery_arrangements_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the current financial standing of the promoter in relation to the project's implementation?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.promoter_financial_standing` | The promoter's current financial standing is not available as atomic evidence. | `resolved` |

### Q2. Is there a comparable source-backed delivery track record available for the promoter?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.promoter_track_record` | A comparable source-backed delivery track record for the promoter is not available as atomic evidence. | `resolved` |

### Q3. How is the benchmark instance constructed in terms of evidence and synthetic assumptions?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.synthetic_evidence_disclosure` | This benchmark instance combines immutable normalized source evidence with visibly labelled deterministic synthetic assumptions. It is not a factual due-diligence record. | `resolved` |

## 4. Climate rationale and strategic fit

Section `climate_rationale_and_strategic_fit` · component `climate_rationale_and_strategic_fit_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. What is the basis for the climate rationale in the project, and how does the greenhouse gas target horizon affect the case?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.climate_rationale` | A complete source-backed climate-hazard, exposure and vulnerability rationale is not available as atomic evidence. | `resolved` |
| `req.ghg_target_horizon` | The source GHG point estimate does not consistently expose a separate atomic accounting horizon. | `resolved` |

### Q2. What is the annualised reported greenhouse gas target in tonnes of CO2 equivalent per year?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.annualised_reported_ghg_target_tco2e` | 213,350.00 tCO2e/year | `resolved` |

## 5. System baseline and policy context

Section `system_baseline_and_policy_context` · component `system_baseline_and_policy_context_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the calculated difference in emission factors between the current and projected scenarios, expressed in tonnes of CO2 equivalent per megawatt-hour?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.emission_factor_delta_tco2e_per_mwh` | 0.97 tCO2e/MWh | `resolved` |

### Q2. What percentage represents the gap in renewable policy implementation compared to the desired level for this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.renewable_policy_gap_pct` | 25.00 pp | `resolved` |

## 6. Capacity and output

Section `capacity_and_output` · component `capacity_and_output_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the relationship between the capacity delivered and the programme-supported investment in this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.capacity_delivery_relationship` | capacity enabled downstream by programme-supported investment | `resolved` |

### Q2. What is the scope of generation accounting for this project's capacity and output analysis?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.generation_accounting_boundary` | Generation from programme-enabled renewable assets only; policy support, storage, reliability and network effects are excluded. | `resolved` |

## 7. Commissioning evidence and dependencies

Section `commissioning_profile` · component `commissioning_profile_text` · output contract `benchmark.interpretive_assessment.v1`

> **Contract coverage gap:** no canonical citation-answer dependencies are bound to this LLM component, so no question can be generated from the specification.

## 8. Operational impact consistency

Section `operational_impact_consistency` · component `operational_impact_consistency_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. What is the status of the reported GHG comparison for the project, and how does this affect the consistency check between the modelled and reported GHG values?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.reported_ghg_comparison_status` | not_comparable | `resolved` |
| `dt.project.reported_ghg_comparison_qualification` | The reported target contains enabled or adjacent effects beyond the restricted generation model; no reported-to-modelled ratio is evaluated. | `resolved` |

### Q2. What is the difference between the reported and modelled GHG values, and what does this indicate about the project's GHG performance?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.reported_minus_modelled_ghg_tco2e` | not applicable | `resolved` |
| `calc.modelled_vs_reported_ghg_ratio` | not applicable | `resolved` |

### Q3. What is the qualification for the asset impact boundary, and how does it affect the interpretation of the modelled GHG values?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.asset_impact_boundary_qualification` | The physical model covers only generation inside the declared boundary; storage, reliability, network and policy effects are not converted to MWh. | `resolved` |

## 9. Technical feasibility and implementation readiness

Section `technical_feasibility_and_readiness` · component `technical_feasibility_and_readiness_text` · output contract `benchmark.interpretive_assessment.v1`

> **Contract coverage gap:** no canonical citation-answer dependencies are bound to this LLM component, so no question can be generated from the specification.

## 10. Costs and financing structure

Section `costs_and_financing_structure` · component `costs_and_financing_structure_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the ratio of cofinancing to GCF dollars in the project's funding structure?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.cofinance_per_gcf_dollar` | 5.78x | `resolved` |

### Q2. What is the total amount of committed funding sources in USD for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.committed_funding_sources_usd` | 191,390,000.00 USD | `resolved` |

### Q3. What is the status of the funding reconciliation for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.funding_reconciliation_status` | reconciled_within_0.1_pct_tolerance | `resolved` |

### Q4. What is the funding scope comparability status for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.funding_scope_comparability` | comparable | `resolved` |

## 11. Financial sustainability and business model

Section `financial_sustainability_and_business_model` · component `financial_sustainability_and_business_model_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. Is there a complete source-backed business model available for assessing operating sustainability, repayment capacity, or returns?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.business_model` | A complete source-backed business model is not available as atomic evidence. | `resolved` |

### Q2. Is there a complete source-backed financial model and its assumptions available for assessing operating sustainability, repayment capacity, or returns?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.financial_model` | A complete source-backed financial model and its assumptions are not available as atomic evidence. | `resolved` |

### Q3. Are comparable project-level financial-return measures available for assessing operating sustainability, repayment capacity, or returns?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.financial_returns` | Comparable project-level financial-return measures are not available as atomic evidence. | `resolved` |

### Q4. Is lifecycle operating expenditure available for assessing operating sustainability, repayment capacity, or returns?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.lifecycle_opex` | Lifecycle operating expenditure is not available as atomic evidence. | `resolved` |

### Q5. Is there a complete revenue model available for assessing operating sustainability, repayment capacity, or returns?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.revenue_model` | A complete revenue model is not available as atomic evidence. | `resolved` |

## 12. Impact, ESG, and safeguards

Section `impact_esg_and_safeguards` · component `impact_esg_and_safeguards_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the cost per reported tonne of CO2 equivalent for the project, and what is the qualification for greenhouse gas accounting?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.project_cost_per_reported_tco2e` | 44.86 USD/tCO2e | `resolved` |

### Q2. What is the qualification for greenhouse gas accounting in the project, and how is the normalized project value treated?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.ghg_accounting_qualification` | The normalized project value remains the reported point target. The lower and upper bounds and the lifespan-anchored accounting horizon are synthetic benchmark assumptions, not proposal claims. | `resolved` |

## 13. Performance indicators and MRV

Section `performance_indicators_and_mrv` · component `performance_indicators_and_mrv_text` · output contract `benchmark.kpi_priority.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. How many indicators were available for prioritization in the project's KPI selection process?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.available_kpi_priority_count` | 17 indicators | `resolved` |

### Q2. How many indicators remained unranked in the project's KPI prioritization process?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.incomplete_kpi_priority_count` | 0 indicators | `resolved` |

### Q3. What is the number of indicators that have compatible target delta assessments in the project's KPI selection?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.kpi_compatible_target_delta_count` | 12 indicators | `resolved` |

### Q4. What are the MRV assessments associated with the KPIs in the project's prioritization process?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.kpi_mrv_assessments` | Institutional and regulatory systems that improve incentives for low-emission planning and development and their effective implementation; Proportion of low- emission power supply in a jurisdiction or market; Number of households, and individuals (males and females) with improved access to low-emission energy sources; Institution staffed by mid-term; Renewable Energy Agency Act in place; Battery energy storage system procured; Software purchased; Smart Grid Strategy; Advanced Distribution Management system; Actual MW installed by category (gender- disaggregated data); Capacity of PV systems installed Number of OIDC staff trained; Number of O… | `resolved` |

### Q5. What is the priority cutoff used to select KPIs in the project's prioritization process?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.kpi_priority_cutoff` | 4 priority | `resolved` |

### Q6. What are the target delta assessments associated with the KPIs in the project's prioritization process?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.kpi_target_delta_assessments` | Institutional and regulatory systems that improve incentives for low-emission planning and development and their effective implementation; Proportion of low- emission power supply in a jurisdiction or market; Number of households, and individuals (males and females) with improved access to low-emission energy sources; Institution staffed by mid-term; Renewable Energy Agency Act in place; Battery energy storage system procured; Software purchased; Smart Grid Strategy; Advanced Distribution Management system; Actual MW installed by category (gender- disaggregated data); Capacity of PV systems installed Number of OIDC staff trained; Number of O… | `resolved` |

### Q7. How many indicators are considered MRV-ready in the project's KPI selection process?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.mrv_ready_kpi_count` | 13 indicators | `resolved` |

### Q8. How many indicators were prioritized in the project's KPI selection process?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.prioritized_kpi_count` | 17 indicators | `resolved` |

### Q9. How many indicators were selected as priority KPIs in the project's prioritization process?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.priority_kpi_count` | 4 indicators | `resolved` |

### Q10. Which specific KPIs were selected as priority indicators in the project's prioritization process?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.priority_kpis` | Battery energy storage system procured; Actual MW installed by category (gender- disaggregated data); Capacity of PV systems installed Number of OIDC staff trained; onnes of carbon dioxide equivalent (tCO2eq) reduced or avoided as a result of Fund funded projects / programmes | `resolved` |

### Q11. What is the status of the project's monitoring and reporting process?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.monitoring_reporting_process` | No exact resolved state found. | `unresolved` |

### Q12. What is the status of the MRV plan for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.mrv_plan_status` | Formal MRV-plan completion status is not available as atomic evidence. | `resolved` |

## 14. Risk and bankability constraints

Section `risk_and_bankability_constraints` · component `risk_and_bankability_constraints_text` · output contract `benchmark.risk_priority.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. How many risks were scored in the risk and bankability constraints analysis for the FP033 project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.scored_risk_count` | 9 risks | `resolved` |

### Q2. How many risks were not scored in the risk and bankability constraints analysis for the FP033 project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.incomplete_risk_count` | 0 risks | `resolved` |

### Q3. What is the maximum risk priority score used in the risk and bankability constraints analysis for the FP033 project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.maximum_risk_priority_score` | 2 | `resolved` |

### Q4. How many risks were selected as having the maximum risk priority score in the risk and bankability constraints analysis for the FP033 project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.maximum_priority_risk_count` | 6 risks | `resolved` |

### Q5. What are the specific risks that were selected as having the maximum risk priority score in the risk and bankability constraints analysis for the FP033 project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.maximum_priority_risks` | Delay in procurement of necessary technical assistance for the various components; Duty-bearers may not have the capacity to meet their obligations to the project; Potential for the project to reproduce discrimination against women’s participation; Technical and operational; Technical and operational; Technical and operational | `resolved` |

## 15. Conclusions and evidence requirements

Section `conclusions_and_evidence_requirements` · component `conclusions_and_evidence_requirements_text` · output contract `benchmark.evidence_requirements.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. What is the status of funding reconciliation for the project, and what is the maximum risk priority score, along with the priority-KPI cutoff value?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.funding_reconciliation_status` | reconciled_within_0.1_pct_tolerance | `resolved` |
| `calc.maximum_risk_priority_score` | 2 score | `resolved` |
| `calc.kpi_priority_cutoff` | 4 priority | `resolved` |

### Q2. What are the specific evidence requirements for the project's financial model, technical design maturity, and environmental and social safeguards?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.financial_model` | A complete source-backed financial model and its assumptions are not available as atomic evidence. | `resolved` |
| `req.technical_design_maturity` | Technical design maturity is not available as atomic evidence. | `resolved` |
| `req.environmental_social_safeguards` | A complete environmental and social safeguards assessment is not available as atomic evidence. | `resolved` |


# FP019 — Priming Financial and Land-Use Planning Instruments to Reduce Emissions from Deforestation — missingness

Template `land_use_nature` · condition `fp019.v2.population.mask.collection_with_dependents_cross_section` · episode `completed`

Executable gold `02993b9da5d930773ec383d5e5af5856caf0b4f41bfb86038cae45a585c0744c` · contract `38afb10b0c6d9f19a7dd76a139ca9ab8e7efba9487425856a7596f8fc41881a5`

## 1. Executive assessment and critical issues

Section `executive_summary` · component `executive_summary_text` · output contract `benchmark.executive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the status of funding reconciliation for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.funding_reconciliation_status` | reconciled_within_0.1_pct_tolerance | `resolved` |

### Q2. What is the maximum priority risk set for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.maximum_priority_risks` | missing | `resolved` |

### Q3. What is the ratio of modelled to reported greenhouse gas emissions for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.modelled_vs_reported_ghg_ratio` | 0.3038610343333334 x | `resolved` |

### Q4. What is the set of priority key performance indicators for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.priority_kpis` | none | `resolved` |

### Q5. How is the funding scope qualification defined for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.funding_scope_qualification` | For benchmark arithmetic, the reported aggregate amounts are treated as one committed financing envelope; this is not an audit conclusion. | `resolved` |

### Q6. How is the land accounting qualification defined for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.land_accounting_qualification` | The pathway areas, rates, factors, enrolment profile and deductions are deterministic benchmark assumptions. Plantation is not relabelled as restoration, and co-benefits outside the boundary are excluded. | `resolved` |

### Q7. What is the disclosure status of synthetic evidence used in the benchmark instance?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.synthetic_evidence_disclosure` | This benchmark instance combines immutable normalized source evidence with visibly labelled deterministic synthetic assumptions. It is not a factual due-diligence record. | `resolved` |

## 2. Project identification and status

Section `project_identification_and_status` · component `project_identification_and_status_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. What is the description of the project and its intended mandate, including the scope, activities, and expected outcomes?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.description` | Ecuador is finalizing its REDD+1 readiness process. A Forest Reference Emission Level (FREL) was submitted and technically assessed by the UNFCCC in 20153 and a REDD+ Action Plan (REDD+ AP4) has been approved. The Action Plan presents the policies and measures prioritized to address the drivers of deforestation5. It has a national scope and includes the 5 REDD+ activities. It is designed to support the national objective of achieving zero net deforestation by 2020. The GCF project will co-finance the REDD+ AP by providing targeted investment to control agricultural expansion into forest areas; optimize existing financial, economic mechanisms… | `resolved` |

### Q2. What is the current implementation status of the project according to the normalized benchmark source?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.project_status` | Current implementation status is not established by the normalized benchmark source. | `resolved` |

## 3. Promoter and delivery assessment

Section `promoter_and_delivery_arrangements` · component `promoter_and_delivery_arrangements_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the current financial standing of the promoter for the FP019 project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.promoter_financial_standing` | The promoter's current financial standing is not available as atomic evidence. | `resolved` |

### Q2. Is there a comparable source-backed delivery track record for the promoter of the FP019 project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.promoter_track_record` | A comparable source-backed delivery track record for the promoter is not available as atomic evidence. | `resolved` |

## 4. Climate rationale and strategic fit

Section `climate_rationale_and_strategic_fit` · component `climate_rationale_and_strategic_fit_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. What is the climate rationale for the project, and how does the greenhouse gas target horizon limit the case?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.climate_rationale` | A complete source-backed climate-hazard, exposure and vulnerability rationale is not available as atomic evidence. | `resolved` |
| `req.ghg_target_horizon` | The source GHG point estimate does not consistently expose a separate atomic accounting horizon. | `resolved` |

### Q2. What is the annualised reported greenhouse gas target in tonnes of carbon dioxide equivalent per year?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.annualised_reported_ghg_target_tco2e` | 3,000,000.00 tCO2e/year | `resolved` |

## 5. Land-use baseline and intervention

Section `land_use_baseline_and_intervention` · component `land_use_baseline_and_intervention_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the rate of avoided deforestation in the project's jurisdictional accounting area, expressed as a percentage per year?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.avoided_deforestation_rate_pct_per_year` | not applicable | `resolved` |

### Q2. What is the annual gross reduction in carbon dioxide equivalent emissions from the jurisdictional accounting area?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.jurisdictional_gross_reduction_tco2e_per_year` | 911,583.10 tCO2e/year | `resolved` |

### Q3. How is the jurisdictional accounting area and annual reference/program emissions defined in the project's context?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.jurisdictional_accounting_qualification` | The national accounting area and annual reference/program emissions are independently seeded deterministic benchmark-scenario inputs; the reported GHG target was not an input. They are not source-derived FREL values, observed performance, or validation of the reported target. | `resolved` |

### Q4. What is the boundary used for the project's land carbon pathway?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.land_carbon_pathway_boundary` | The national jurisdictional reference-level pathway is the sole benchmark carbon boundary; activity-area pathways are excluded. | `resolved` |

## 6. Area allocation and enrolment

Section `area_allocation_and_enrolment` · component `area_allocation_and_enrolment_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the status of land area reconciliation for the applicable accounting area in this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.land_area_reconciliation_status` | not_applicable_jurisdictional_boundary | `resolved` |

### Q2. Is there a source-backed dated activity-level critical path available for the detailed implementation schedule?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.detailed_implementation_schedule` | No source-backed dated activity-level critical path is present in the normalized evidence. | `resolved` |

### Q3. Are land tenure, access, and site-control status available as complete atomic evidence?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.land_and_access_status` | Land tenure, access and site-control status are not available as complete atomic evidence. | `resolved` |

## 7. Carbon-accounting consistency

Section `carbon_accounting_consistency` · component `carbon_accounting_consistency_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the modelled net accounting GHG value in tCO2e for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.modelled_net_accounting_ghg_tco2e` | 4,557,915.52 tCO2e | `resolved` |

### Q2. What is the ratio of modelled versus reported GHG for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.modelled_vs_reported_ghg_ratio` | 0.30x | `resolved` |

### Q3. What is the jurisdictional accounting qualification for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.jurisdictional_accounting_qualification` | The national accounting area and annual reference/program emissions are independently seeded deterministic benchmark-scenario inputs; the reported GHG target was not an input. They are not source-derived FREL values, observed performance, or validation of the reported target. | `resolved` |

### Q4. What is the GHG comparison status of the project with respect to reported targets?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.reported_ghg_comparison_status` | comparable | `resolved` |

## 8. People and co-benefits

Section `people_and_cobenefits` · component `people_and_cobenefits_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **deterministic fallback**.

### Q1. What is the evidence status or value for beneficiary allocation qualification?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.beneficiary_allocation_qualification` | Input basis: direct=synthetic scenario, women=synthetic scenario, local-community=synthetic scenario, livelihood-enterprise=synthetic scenario. Any synthetic counts are deterministic, project-specific ex-ante allocation scenarios. Women and local-community shares are allocation diagnostics only; they do not evidence delivery, participation, equity, benefit quality, or performance. | `resolved` |

## 9. Technical feasibility and implementation readiness

Section `technical_feasibility_and_readiness` · component `technical_feasibility_and_readiness_text` · output contract `benchmark.interpretive_assessment.v1`

> **Contract coverage gap:** no canonical citation-answer dependencies are bound to this LLM component, so no question can be generated from the specification.

## 10. Costs and financing structure

Section `costs_and_financing_structure` · component `costs_and_financing_structure_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. What does the cofinance per GCF dollar indicate about the stated cofinance and what does it not address regarding viability or return?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.cofinance_per_gcf_dollar` | 1.04x | `resolved` |

### Q2. What is the total amount of committed funding sources in USD for this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.committed_funding_sources_usd` | 84,008,647.00 USD | `resolved` |

### Q3. What is the status of the funding reconciliation for this project, and under what condition is it reported?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.funding_reconciliation_status` | reconciled_within_0.1_pct_tolerance | `resolved` |
| `dt.project.funding_scope_comparability` | comparable | `resolved` |

## 11. Financial sustainability and business model

Section `financial_sustainability_and_business_model` · component `financial_sustainability_and_business_model_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. Can recurrent financing, operating sustainability, repayment capacity, or returns be assessed from the business model, financial model, financial returns, lifecycle operating expenditure, and revenue model for this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.business_model` | A complete source-backed business model is not available as atomic evidence. | `resolved` |
| `req.financial_model` | A complete source-backed financial model and its assumptions are not available as atomic evidence. | `resolved` |
| `req.financial_returns` | Comparable project-level financial-return measures are not available as atomic evidence. | `resolved` |
| `req.lifecycle_opex` | Lifecycle operating expenditure is not available as atomic evidence. | `resolved` |

### Q2. Is there evidence of a complete source-backed business model, financial model, financial returns, lifecycle operating expenditure, or revenue model for this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.revenue_model` | A complete revenue model is not available as atomic evidence. | `resolved` |

## 12. Impact, ESG, and safeguards

Section `impact_esg_and_safeguards` · component `impact_esg_and_safeguards_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the cost per tonne of CO2 equivalent reported for this project, and what is the qualification for the greenhouse gas accounting?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.project_cost_per_reported_tco2e` | 5.60 USD/tCO2e | `resolved` |

### Q2. What is the qualification for the greenhouse gas accounting in this project, and what is the cost per tonne of CO2 equivalent reported?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.ghg_accounting_qualification` | The normalized project value remains the reported point target. The lower and upper bounds and the lifespan-anchored accounting horizon are synthetic benchmark assumptions, not proposal claims. | `resolved` |

## 13. Performance indicators and MRV

Section `performance_indicators_and_mrv` · component `performance_indicators_and_mrv_text` · output contract `benchmark.kpi_priority.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. How many indicators were considered for priority ranking in the performance indicators and MRV section?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.available_kpi_priority_count` | 21 indicators | `resolved` |

### Q2. How many indicators remained unranked in the performance indicators and MRV section?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.incomplete_kpi_priority_count` | 0 indicators | `resolved` |

### Q3. How many of the selected KPIs have compatible target delta assessments in the performance indicators and MRV section?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.kpi_compatible_target_delta_count` | 9 indicators | `resolved` |

### Q4. What are the MRV assessments associated with the KPIs in the performance indicators and MRV section?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.kpi_mrv_assessments` | emission reduction (tCO2e) as a result of REDD+ AP; cost per tCO2e; Institutional and regulatory systems that improve incentives for low- emission planning and development and their effective implementation; Number and level of effective coordination mechanisms; Hectares of land or forests under improved and effective management that contributes to CO2 emission reductions; Number of strengthened land-use planning instruments and life plans that have included climate change mitigation policies and actions; Provincial PDOT; Cantonal PDOT; Life Plans; Number of legal coordination instruments at a national and territorial level for REDD+; rea (h… | `resolved` |

### Q5. What is the priority cutoff used to select KPIs in the performance indicators and MRV section?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.kpi_priority_cutoff` | 4 priority | `resolved` |

### Q6. What are the target delta assessments associated with the KPIs in the performance indicators and MRV section?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.kpi_target_delta_assessments` | emission reduction (tCO2e) as a result of REDD+ AP; cost per tCO2e; Institutional and regulatory systems that improve incentives for low- emission planning and development and their effective implementation; Number and level of effective coordination mechanisms; Hectares of land or forests under improved and effective management that contributes to CO2 emission reductions; Number of strengthened land-use planning instruments and life plans that have included climate change mitigation policies and actions; Provincial PDOT; Cantonal PDOT; Life Plans; Number of legal coordination instruments at a national and territorial level for REDD+; rea (h… | `resolved` |

### Q7. How many KPIs are MRV-ready in the performance indicators and MRV section?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.mrv_ready_kpi_count` | 18 indicators | `resolved` |

### Q8. How many KPIs were prioritized in the performance indicators and MRV section?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.prioritized_kpi_count` | 21 indicators | `resolved` |

### Q9. How many KPIs were selected as priority KPIs in the performance indicators and MRV section?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.priority_kpi_count` | 7 indicators | `resolved` |

### Q10. What are the selected priority KPIs in the performance indicators and MRV section?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.priority_kpis` | emission reduction (tCO2e) as a result of REDD+ AP; Hectares of land or forests under improved and effective management that contributes to CO2 emission reductions; rea (ha) transformed to sustainable production systems in deforested areas; Area (ha) transformed to sustainable production systems in deforested areas; Number of hectares under conservation incentives in priority areas with high threat of deforestation and potential to generate social and environmental cobenefits; Number of hectares under conservation incentives in priority areas with high threat of deforestation and potential to generate social and environmental cobenefi; Numbe… | `resolved` |

### Q11. What is the status of the monitoring and reporting process for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.monitoring_reporting_process` | No exact resolved state found. | `unresolved` |

### Q12. What is the status of the MRV plan for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.mrv_plan_status` | Formal MRV-plan completion status is not available as atomic evidence. | `resolved` |

## 14. Risk and bankability constraints

Section `risk_and_bankability_constraints` · component `risk_and_bankability_constraints_text` · output contract `benchmark.risk_priority.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. How many risks are unscored in the risk and bankability constraints section of this report?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.incomplete_risk_count` | missing | `resolved` |

### Q2. How many risks are selected as having the maximum risk priority score in this report?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.maximum_priority_risk_count` | null | `resolved` |

### Q3. What is the maximum risk priority score used to identify the highest priority risks in this report?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.maximum_risk_priority_score` | null | `resolved` |

### Q4. How many risks are scored in the risk and bankability constraints section of this report?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.scored_risk_count` | missing | `resolved` |

### Q5. What is the complete set of risks tied at the maximum risk priority score in this report?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.maximum_priority_risks` | missing | `resolved` |

## 15. Conclusions and evidence requirements

Section `conclusions_and_evidence_requirements` · component `conclusions_and_evidence_requirements_text` · output contract `benchmark.evidence_requirements.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. What is the status of funding reconciliation for the project, and what is the maximum-risk priority score, along with the priority-KPI cutoff?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.funding_reconciliation_status` | reconciled_within_0.1_pct_tolerance | `resolved` |
| `calc.maximum_risk_priority_score` | missing | `resolved` |
| `calc.kpi_priority_cutoff` | 4 priority | `resolved` |

### Q2. What are the statuses of the environmental and social safeguards, financial model, and technical design maturity for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.environmental_social_safeguards` | A complete environmental and social safeguards assessment is not available as atomic evidence. | `resolved` |
| `req.financial_model` | A complete source-backed financial model and its assumptions are not available as atomic evidence. | `resolved` |
| `req.technical_design_maturity` | Technical design maturity is not available as atomic evidence. | `resolved` |


# FP033 — Accelerating the Transformational Shift to a Low-Carbon Economy in the Republic of Mauritius — missingness

Template `asset_delivery` · condition `fp033.v2.population.mask.collection_with_dependents_cross_section` · episode `completed`

Executable gold `9e5cdb044b9887ee09447af8845d153ea22b3262ddb51b41971845a5192d4c1d` · contract `25caa78a7c2876abce7c06eb27c2232558cd26d26e9c31a4e77724d07a2d5bc0`

## 1. Executive assessment and critical issues

Section `executive_summary` · component `executive_summary_text` · output contract `benchmark.executive_assessment.v1`

Generation: **model generation attempt 1 (seed 17)**.

### Q1. What is the status of funding reconciliation for the project, and how are the reported aggregate amounts treated for benchmark arithmetic?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.funding_reconciliation_status` | reconciled_within_0.1_pct_tolerance | `resolved` |
| `dt.project.funding_scope_qualification` | For benchmark arithmetic, the reported aggregate amounts are treated as one committed financing envelope; this is not an audit conclusion. | `resolved` |

### Q2. What is the project cost per reported tCO2e, and how is the greenhouse gas accounting handled in the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.project_cost_per_reported_tco2e` | 44.85587063510663 USD/tCO2e | `resolved` |
| `dt.project.ghg_accounting_qualification` | The normalized project value remains the reported point target. The lower and upper bounds and the lifespan-anchored accounting horizon are synthetic benchmark assumptions, not proposal claims. | `resolved` |

### Q3. What is the status of the maximum priority risks, and what is the set of priority KPIs used in the results framework?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.maximum_priority_risks` | missing | `resolved` |
| `calc.priority_kpis` | none | `resolved` |

### Q4. What is the status of the synthetic evidence disclosure, and what is the nature of the benchmark instance?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.synthetic_evidence_disclosure` | This benchmark instance combines immutable normalized source evidence with visibly labelled deterministic synthetic assumptions. It is not a factual due-diligence record. | `resolved` |

## 2. Project identification and status

Section `project_identification_and_status` · component `project_identification_and_status_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. What is the primary context and rationale for the project's focus on low-carbon development in Mauritius?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.description` | With 84% of its primary energy requirements met from imported fossil fuels, Mauritius, like many Small Island Developing States (SIDS), is extremely vulnerable to energy shocks. The grid emission factor of Mauritius is extremely high at 1.01 tonnes CO2/MWh due to the prevalence of imported coal (39%) and fuel oil (38%) in the electricity generation mix. Net greenhouse gas emissions are increasing at a rapid rate of 3% per year. The pressing need to significantly enhance Mauritius’s energy independence and reduce greenhouse gas emissions is recognised in the country’s Nationally Determined Contribution (2016), its Second National Communicatio… | `resolved` |

### Q2. What is the current implementation status of the project according to the normalized benchmark source?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.project_status` | Current implementation status is not established by the normalized benchmark source. | `resolved` |

## 3. Promoter and delivery assessment

Section `promoter_and_delivery_arrangements` · component `promoter_and_delivery_arrangements_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. What is the status of the promoter's financial standing in relation to the project's evidence requirements?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.promoter_financial_standing` | The promoter's current financial standing is not available as atomic evidence. | `resolved` |

### Q2. Is there a comparable source-backed delivery track record for the promoter that meets the project's evidence requirements?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.promoter_track_record` | A comparable source-backed delivery track record for the promoter is not available as atomic evidence. | `resolved` |

### Q3. How is the benchmark instance for this project characterized in terms of evidence synthesis and synthetic assumptions?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.synthetic_evidence_disclosure` | This benchmark instance combines immutable normalized source evidence with visibly labelled deterministic synthetic assumptions. It is not a factual due-diligence record. | `resolved` |

## 4. Climate rationale and strategic fit

Section `climate_rationale_and_strategic_fit` · component `climate_rationale_and_strategic_fit_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. What is the basis for the climate rationale in the project, and how does the greenhouse gas target horizon affect the case?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.climate_rationale` | A complete source-backed climate-hazard, exposure and vulnerability rationale is not available as atomic evidence. | `resolved` |
| `req.ghg_target_horizon` | The source GHG point estimate does not consistently expose a separate atomic accounting horizon. | `resolved` |

### Q2. What is the annualised reported greenhouse gas target in tonnes of CO2 equivalent per year?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.annualised_reported_ghg_target_tco2e` | 213,350.00 tCO2e/year | `resolved` |

## 5. System baseline and policy context

Section `system_baseline_and_policy_context` · component `system_baseline_and_policy_context_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the calculated difference in emission factors between the current and target scenarios for electricity generation in the project's context?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.emission_factor_delta_tco2e_per_mwh` | 0.97 tCO2e/MWh | `resolved` |

### Q2. What percentage gap exists between the current renewable energy policy and the target policy in the project's context?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.renewable_policy_gap_pct` | 25.00 pp | `resolved` |

## 6. Capacity and output

Section `capacity_and_output` · component `capacity_and_output_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the relationship between the capacity delivered and the programme-supported investment in this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.capacity_delivery_relationship` | capacity enabled downstream by programme-supported investment | `resolved` |

### Q2. What is the scope of generation accounting for this project's capacity and output assessment?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.generation_accounting_boundary` | Generation from programme-enabled renewable assets only; policy support, storage, reliability and network effects are excluded. | `resolved` |

## 7. Commissioning evidence and dependencies

Section `commissioning_profile` · component `commissioning_profile_text` · output contract `benchmark.interpretive_assessment.v1`

> **Contract coverage gap:** no canonical citation-answer dependencies are bound to this LLM component, so no question can be generated from the specification.

## 8. Operational impact consistency

Section `operational_impact_consistency` · component `operational_impact_consistency_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the status of the reported GHG comparison for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.reported_ghg_comparison_status` | not_comparable | `resolved` |

### Q2. What qualification explains the reported GHG comparison for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.reported_ghg_comparison_qualification` | The reported target contains enabled or adjacent effects beyond the restricted generation model; no reported-to-modelled ratio is evaluated. | `resolved` |

### Q3. What is the ratio of modelled to reported GHG for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.modelled_vs_reported_ghg_ratio` | not applicable | `resolved` |

### Q4. What is the difference between reported and modelled GHG in tonnes of CO2e for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.reported_minus_modelled_ghg_tco2e` | not applicable | `resolved` |

### Q5. What qualification explains the asset impact boundary for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.asset_impact_boundary_qualification` | The physical model covers only generation inside the declared boundary; storage, reliability, network and policy effects are not converted to MWh. | `resolved` |

## 9. Technical feasibility and implementation readiness

Section `technical_feasibility_and_readiness` · component `technical_feasibility_and_readiness_text` · output contract `benchmark.interpretive_assessment.v1`

> **Contract coverage gap:** no canonical citation-answer dependencies are bound to this LLM component, so no question can be generated from the specification.

## 10. Costs and financing structure

Section `costs_and_financing_structure` · component `costs_and_financing_structure_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. What does the cofinance per GCF dollar metric indicate about the mobilisation of funds for this project, and what is the status of the funding reconciliation?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.cofinance_per_gcf_dollar` | 5.78x | `resolved` |
| `calc.funding_reconciliation_status` | reconciled_within_0.1_pct_tolerance | `resolved` |

### Q2. What is the total amount of committed funding sources for the project, and how does the funding scope comparability affect the interpretation of these figures?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.committed_funding_sources_usd` | 191,390,000.00 USD | `resolved` |
| `dt.project.funding_scope_comparability` | comparable | `resolved` |

## 11. Financial sustainability and business model

Section `financial_sustainability_and_business_model` · component `financial_sustainability_and_business_model_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. Is there a complete source-backed business model available for assessing operating sustainability, repayment capacity, or returns?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.business_model` | A complete source-backed business model is not available as atomic evidence. | `resolved` |

### Q2. Is there a complete source-backed financial model and its assumptions available for assessing operating sustainability, repayment capacity, or returns?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.financial_model` | A complete source-backed financial model and its assumptions are not available as atomic evidence. | `resolved` |

### Q3. Are comparable project-level financial-return measures available for assessing operating sustainability, repayment capacity, or returns?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.financial_returns` | Comparable project-level financial-return measures are not available as atomic evidence. | `resolved` |

### Q4. Is lifecycle operating expenditure available for assessing operating sustainability, repayment capacity, or returns?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.lifecycle_opex` | Lifecycle operating expenditure is not available as atomic evidence. | `resolved` |

### Q5. Is there a complete revenue model available for assessing operating sustainability, repayment capacity, or returns?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.revenue_model` | A complete revenue model is not available as atomic evidence. | `resolved` |

## 12. Impact, ESG, and safeguards

Section `impact_esg_and_safeguards` · component `impact_esg_and_safeguards_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the cost per reported tonne of carbon dioxide equivalent for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.project_cost_per_reported_tco2e` | 44.86 USD/tCO2e | `resolved` |

### Q2. What is the qualification for the greenhouse gas accounting approach used in the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.ghg_accounting_qualification` | The normalized project value remains the reported point target. The lower and upper bounds and the lifespan-anchored accounting horizon are synthetic benchmark assumptions, not proposal claims. | `resolved` |

## 13. Performance indicators and MRV

Section `performance_indicators_and_mrv` · component `performance_indicators_and_mrv_text` · output contract `benchmark.kpi_priority.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. How many indicators were available for prioritization in the performance indicators and MRV section?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.available_kpi_priority_count` | 17 indicators | `resolved` |

### Q2. How many indicators remained unranked in the performance indicators and MRV section?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.incomplete_kpi_priority_count` | 0 indicators | `resolved` |

### Q3. How many indicators have compatible target delta assessments in the performance indicators and MRV section?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.kpi_compatible_target_delta_count` | 12 indicators | `resolved` |

### Q4. What are the MRV assessments for the performance indicators in the performance indicators and MRV section?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.kpi_mrv_assessments` | Institutional and regulatory systems that improve incentives for low-emission planning and development and their effective implementation; Proportion of low- emission power supply in a jurisdiction or market; Number of households, and individuals (males and females) with improved access to low-emission energy sources; Institution staffed by mid-term; Renewable Energy Agency Act in place; Battery energy storage system procured; Software purchased; Smart Grid Strategy; Advanced Distribution Management system; Actual MW installed by category (gender- disaggregated data); Capacity of PV systems installed Number of OIDC staff trained; Number of O… | `resolved` |

### Q5. What is the priority cutoff used for selecting performance indicators in the performance indicators and MRV section?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.kpi_priority_cutoff` | 4 priority | `resolved` |

### Q6. What are the target delta assessments for the performance indicators in the performance indicators and MRV section?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.kpi_target_delta_assessments` | Institutional and regulatory systems that improve incentives for low-emission planning and development and their effective implementation; Proportion of low- emission power supply in a jurisdiction or market; Number of households, and individuals (males and females) with improved access to low-emission energy sources; Institution staffed by mid-term; Renewable Energy Agency Act in place; Battery energy storage system procured; Software purchased; Smart Grid Strategy; Advanced Distribution Management system; Actual MW installed by category (gender- disaggregated data); Capacity of PV systems installed Number of OIDC staff trained; Number of O… | `resolved` |

### Q7. How many indicators are MRV-ready in the performance indicators and MRV section?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.mrv_ready_kpi_count` | 13 indicators | `resolved` |

### Q8. How many indicators were considered for prioritization in the performance indicators and MRV section?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.prioritized_kpi_count` | 17 indicators | `resolved` |

### Q9. How many indicators were selected as priority indicators in the performance indicators and MRV section?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.priority_kpi_count` | 4 indicators | `resolved` |

### Q10. Which indicators were selected as priority indicators in the performance indicators and MRV section?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.priority_kpis` | Battery energy storage system procured; Actual MW installed by category (gender- disaggregated data); Capacity of PV systems installed Number of OIDC staff trained; onnes of carbon dioxide equivalent (tCO2eq) reduced or avoided as a result of Fund funded projects / programmes | `resolved` |

### Q11. What is the status of the monitoring and reporting process for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.monitoring_reporting_process` | No exact resolved state found. | `unresolved` |

### Q12. What is the status of the MRV plan for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.mrv_plan_status` | Formal MRV-plan completion status is not available as atomic evidence. | `resolved` |

## 14. Risk and bankability constraints

Section `risk_and_bankability_constraints` · component `risk_and_bankability_constraints_text` · output contract `benchmark.risk_priority.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. How many risks are scored in the risk and bankability constraints analysis for the FP033 project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.scored_risk_count` | missing | `resolved` |

### Q2. How many risks are unscored in the risk and bankability constraints analysis for the FP033 project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.incomplete_risk_count` | missing | `resolved` |

### Q3. What is the maximum risk priority score used in the risk and bankability constraints analysis for the FP033 project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.maximum_risk_priority_score` | null | `resolved` |

### Q4. How many risks are selected as maximum priority risks in the risk and bankability constraints analysis for the FP033 project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.maximum_priority_risk_count` | null | `resolved` |

### Q5. What is the list of risks tied to the maximum risk priority score in the risk and bankability constraints analysis for the FP033 project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.maximum_priority_risks` | missing | `resolved` |

## 15. Conclusions and evidence requirements

Section `conclusions_and_evidence_requirements` · component `conclusions_and_evidence_requirements_text` · output contract `benchmark.evidence_requirements.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. What is the status of funding reconciliation for the project, and what is the priority cutoff for KPIs?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.funding_reconciliation_status` | reconciled_within_0.1_pct_tolerance | `resolved` |
| `calc.kpi_priority_cutoff` | 4 priority | `resolved` |

### Q2. What is the maximum risk priority score for the project, and what is the status of the financial model?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.maximum_risk_priority_score` | missing | `resolved` |
| `req.financial_model` | A complete source-backed financial model and its assumptions are not available as atomic evidence. | `resolved` |

### Q3. What is the status of the technical design maturity and the environmental and social safeguards assessment?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.technical_design_maturity` | Technical design maturity is not available as atomic evidence. | `resolved` |
| `req.environmental_social_safeguards` | A complete environmental and social safeguards assessment is not available as atomic evidence. | `resolved` |


# FP083 — Indonesia Geothermal Resource Risk Mitigation Project — update

Template `financing_facility` · condition `fp083.v2.population.mutation.collection_with_dependents_cross_section` · episode `completed`

Executable gold `a4df69f0913cf1542cb82914d04da4f33fadd80a7d13288d1288e7435a7a88b2` · contract `d5098ba0ebfc7d33eb43ec844f6111611e9f8c2c5947902d55028fe367a49baa`

## 1. Executive assessment and critical issues

Section `executive_summary` · component `executive_summary_text` · output contract `benchmark.executive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the status of funding reconciliation for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.funding_reconciliation_status` | reconciled_within_0.1_pct_tolerance | `resolved` |

### Q2. What are the maximum priority risks associated with the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.maximum_priority_risks` | Technical and operational | `resolved` |

### Q3. What are the priority KPIs for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.priority_kpis` | none | `resolved` |

### Q4. How is the funding scope qualification described for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.funding_scope_qualification` | For benchmark arithmetic, the reported aggregate amounts are treated as one committed financing envelope; this is not an audit conclusion. | `resolved` |

### Q5. How are instrument terms qualified for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.instrument_terms_qualification` | Instrument amounts are face-value benchmark allocations, not grant equivalents; pricing, repayment and subsidy values are not inferred. Unused exhaustive instrument categories are reported as not applicable; their zero amounts and zero-percent shares are arithmetic balance placeholders only. | `resolved` |

### Q6. How is the mobilization qualification described for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.mobilization_qualification` | The range is a deterministic benchmark objective for incremental capital outside the deployment envelope; it is not committed or realized finance and is not a return. | `resolved` |

### Q7. What is the disclosure status of synthetic evidence used in the benchmark?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.synthetic_evidence_disclosure` | This benchmark instance combines immutable normalized source evidence with visibly labelled deterministic synthetic assumptions. It is not a factual due-diligence record. | `resolved` |

## 2. Project identification and status

Section `project_identification_and_status` · component `project_identification_and_status_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. What is the description of the project's objectives and expected outcomes?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.description` | The national grid in Indonesia has been dominated by fossil-fueled generation. Based on PLN’s RUPTL 2018, the 2017 generation mix was 58.3 percent coal, 23.2 percent gas, 6 percent diesel, 12.5 percent renewables. At the 2015 COP21 in Paris, Indonesia committed to a Nationally Determined Contribution (NDC) at 29 percent reduction of GHG emissions by 2030. In support of the Indonesian Government’s NDC and plan to increase the share of renewable energy in the power generation mix to 23 percent by 2026, the proposed Project aims to support a scale-up of investment in geothermal energy development. As a result, the Project is expected to contrib… | `resolved` |

### Q2. What is the current implementation status of the project according to the normalized benchmark source?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.project_status` | Current implementation status is not established by the normalized benchmark source. | `resolved` |

## 3. Promoter and delivery assessment

Section `promoter_and_delivery_arrangements` · component `promoter_and_delivery_arrangements_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. What is the current financial standing of the promoter for the Indonesia Geothermal Resource Risk Mitigation Project, and is there a comparable source-backed delivery track record available?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.promoter_financial_standing` | The promoter's current financial standing is not available as atomic evidence. | `resolved` |
| `req.promoter_track_record` | A comparable source-backed delivery track record for the promoter is not available as atomic evidence. | `resolved` |

## 4. Climate rationale and strategic fit

Section `climate_rationale_and_strategic_fit` · component `climate_rationale_and_strategic_fit_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the annualised reported GHG target for the project in tonnes of CO2 equivalent per year?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.annualised_reported_ghg_target_tco2e` | 18,700,000.00 tCO2e/year | `resolved` |

### Q2. What is the climate rationale for the project's intervention in relation to its target market and financing barrier?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.climate_rationale` | A complete source-backed climate-hazard, exposure and vulnerability rationale is not available as atomic evidence. | `resolved` |

### Q3. What is the GHG target horizon for the project's accounting and how does it affect the climate rationale?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.ghg_target_horizon` | The source GHG point estimate does not consistently expose a separate atomic accounting horizon. | `resolved` |

## 5. Market rationale and financial additionality

Section `market_rationale_and_additionality` · component `market_rationale_and_additionality_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. What is the scope of the facility's deployment profile, and how does it ensure that the facility does not include recycling or released-capacity reuse?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.facility_profile_scope` | full configured deployment profile without recycling or released-capacity reuse | `resolved` |

### Q2. What is the identified financing barrier that the facility mechanism is intended to address, and how does it relate to the project's target segment and eligibility criteria?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.market_financing_barrier` | Insufficient tenor, risk appetite or affordable liquidity for otherwise eligible climate investments. | `resolved` |

## 6. Instrument structure and terms

Section `instrument_structure_and_terms` · component `instrument_structure_and_terms_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the status of the reconciliation of instrument amounts to the project's benchmark allocations, and how are instrument terms qualified for this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.gcf_instrument_reconciliation_status` | reconciled_within_0.1_pct_tolerance | `resolved` |

### Q2. How are instrument amounts and shares treated in the context of risk allocation, and what is the qualification for instrument terms in this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.instrument_terms_qualification` | Instrument amounts are face-value benchmark allocations, not grant equivalents; pricing, repayment and subsidy values are not inferred. Unused exhaustive instrument categories are reported as not applicable; their zero amounts and zero-percent shares are arithmetic balance placeholders only. | `resolved` |

## 7. Allocation and utilisation profile

Section `allocation_and_utilisation_profile` · component `allocation_and_utilisation_profile_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. What is the deployment envelope per GCF dollar declared for this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.deployment_envelope_per_gcf_dollar` | 0.95x | `resolved` |

### Q2. Is there a source-backed dated activity-level critical path present in the normalized evidence for this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.detailed_implementation_schedule` | No source-backed dated activity-level critical path is present in the normalized evidence. | `resolved` |

### Q3. Is the formal MRV-plan completion status available as atomic evidence for this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.mrv_plan_status` | Formal MRV-plan completion status is not available as atomic evidence. | `resolved` |

### Q4. Are a source-backed procurement plan and procurement status available as atomic evidence for this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.procurement_plan` | A source-backed procurement plan and procurement status are not available as atomic evidence. | `resolved` |

## 8. Portfolio scale and mobilisation

Section `portfolio_scale_and_mobilisation` · component `portfolio_scale_and_mobilisation_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. Under what condition should the expected scale and mobilisation range be interpreted for this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.mobilization_applicability` | No exact resolved state found. | `unresolved` |

### Q2. What is the nature of the range provided for mobilisation in this project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.mobilization_qualification` | The range is a deterministic benchmark objective for incremental capital outside the deployment envelope; it is not committed or realized finance and is not a return. | `resolved` |

### Q3. What does the portfolio-unit denominator represent in this context?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.portfolio_unit_count_basis` | synthetic expected final portfolio for benchmark arithmetic | `resolved` |
| `dt.project.portfolio_unit_count_qualification` | The count retains its stated type and basis; per-unit amounts are allocation intensities, not universal ticket sizes. | `resolved` |

## 9. Technical feasibility and implementation readiness

Section `technical_feasibility_and_readiness` · component `technical_feasibility_and_readiness_text` · output contract `benchmark.interpretive_assessment.v1`

> **Contract coverage gap:** no canonical citation-answer dependencies are bound to this LLM component, so no question can be generated from the specification.

## 10. Costs and financing structure

Section `costs_and_financing_structure` · component `costs_and_financing_structure_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. What does the cofinance per GCF dollar indicate about the relationship between cofinance and GCF funding for this project, and how does it relate to additionality, viability, or return?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.cofinance_per_gcf_dollar` | 1.76x | `resolved` |

### Q2. What is the total amount of committed funding sources for this project, and how is it presented in the report?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.committed_funding_sources_usd` | 510,000,000.00 USD | `resolved` |

### Q3. What is the status of the funding reconciliation for this project, and under what condition is it reported?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.funding_reconciliation_status` | reconciled_within_0.1_pct_tolerance | `resolved` |
| `dt.project.funding_scope_comparability` | comparable | `resolved` |

## 11. Financial sustainability and business model

Section `financial_sustainability_and_business_model` · component `financial_sustainability_and_business_model_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. What is the status of the facility recycling qualification for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.facility_recycling_qualification` | No repayments, released guarantees or capital reuse enter the four-period state chain. | `resolved` |

### Q2. What is the status of the instrument terms qualification for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.instrument_terms_qualification` | Instrument amounts are face-value benchmark allocations, not grant equivalents; pricing, repayment and subsidy values are not inferred. Unused exhaustive instrument categories are reported as not applicable; their zero amounts and zero-percent shares are arithmetic balance placeholders only. | `resolved` |

### Q3. Is there a complete source-backed business model available for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.business_model` | A complete source-backed business model is not available as atomic evidence. | `resolved` |

### Q4. Is there a complete source-backed financial model and its assumptions available for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.financial_model` | A complete source-backed financial model and its assumptions are not available as atomic evidence. | `resolved` |

### Q5. Are comparable project-level financial-return measures available for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.financial_returns` | Comparable project-level financial-return measures are not available as atomic evidence. | `resolved` |

### Q6. Is lifecycle operating expenditure available for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.lifecycle_opex` | Lifecycle operating expenditure is not available as atomic evidence. | `resolved` |

### Q7. Is there a complete revenue model available for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.revenue_model` | A complete revenue model is not available as atomic evidence. | `resolved` |

## 12. Impact, ESG, and safeguards

Section `impact_esg_and_safeguards` · component `impact_esg_and_safeguards_text` · output contract `benchmark.interpretive_assessment.v1`

Generation: **deterministic fallback**.

### Q1. What is the evidence status or value for project cost per reported tco2e?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.project_cost_per_reported_tco2e` | 2.73 USD/tCO2e | `resolved` |

## 13. Performance indicators and MRV

Section `performance_indicators_and_mrv` · component `performance_indicators_and_mrv_text` · output contract `benchmark.kpi_priority.v1`

Generation: **model generation attempt 2 (seed 7)**.

### Q1. How many indicators were available for prioritization in the KPI selection process?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.available_kpi_priority_count` | 16 indicators | `resolved` |

### Q2. How many indicators remained unranked in the KPI prioritization process?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.incomplete_kpi_priority_count` | 0 indicators | `resolved` |

### Q3. What was the cutoff used to select priority KPIs in the prioritization process?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.kpi_priority_cutoff` | 4 priority | `resolved` |

### Q4. How many KPIs were selected as priority indicators in the prioritization process?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.priority_kpi_count` | 2 indicators | `resolved` |

### Q5. Which specific KPIs were selected as priority indicators in the prioritization process?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.priority_kpis` | Tonnes of carbon dioxide equivalent (t CO2eq) reduced as a result of Fund funded projects/ programmes; MWs of Lowemission energy capacity installed, generated and/or rehabilitated as a result of the GCF support. | `resolved` |

### Q6. How many KPIs were fully ready for MRV in the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.mrv_ready_kpi_count` | 16 indicators | `resolved` |

### Q7. What are the MRV assessments associated with the KPIs?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.kpi_mrv_assessments` | Tonnes of carbon dioxide equivalent (t CO2eq) reduced as a result of Fund funded projects/ programmes; Cost per t CO2eq decreased for all Fund-funded mitigation projects/ programmes; MWs of Lowemission energy capacity installed, generated and/or rehabilitated as a result of the GCF support.; Volume of finance leveraged by Fund funding; Volume of finance leveraged by Fund funding – SubElement 1: Private capital mobilized for investment in geothermal Exploration; Volume of finance leveraged by Fund funding – SubElement 2: Private capital expected to be mobilized for investment in geothermal development over time; Number of projects explored; P… | `resolved` |

### Q8. How many KPIs have compatible target delta assessments?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.kpi_compatible_target_delta_count` | 13 indicators | `resolved` |

### Q9. What are the target delta assessments associated with the KPIs?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.kpi_target_delta_assessments` | Tonnes of carbon dioxide equivalent (t CO2eq) reduced as a result of Fund funded projects/ programmes; Cost per t CO2eq decreased for all Fund-funded mitigation projects/ programmes; MWs of Lowemission energy capacity installed, generated and/or rehabilitated as a result of the GCF support.; Volume of finance leveraged by Fund funding; Volume of finance leveraged by Fund funding – SubElement 1: Private capital mobilized for investment in geothermal Exploration; Volume of finance leveraged by Fund funding – SubElement 2: Private capital expected to be mobilized for investment in geothermal development over time; Number of projects explored; P… | `resolved` |

### Q10. How many KPIs were prioritized in the overall prioritization process?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.prioritized_kpi_count` | 16 indicators | `resolved` |

### Q11. What is the status of the project's monitoring and reporting process?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `dt.project.monitoring_reporting_process` | No exact resolved state found. | `unresolved` |

### Q12. What is the status of the MRV plan for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.mrv_plan_status` | Formal MRV-plan completion status is not available as atomic evidence. | `resolved` |

## 14. Risk and bankability constraints

Section `risk_and_bankability_constraints` · component `risk_and_bankability_constraints_text` · output contract `benchmark.risk_priority.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. How many risks are scored in the risk and bankability constraints section of this report?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.scored_risk_count` | 4 risks | `resolved` |

### Q2. How many risks are not scored in the risk and bankability constraints section of this report?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.incomplete_risk_count` | 0 risks | `resolved` |

### Q3. What is the highest risk priority score assigned to any risk in the risk and bankability constraints section of this report?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.maximum_risk_priority_score` | 4 | `resolved` |

### Q4. What is the name of the risk that is tied for the highest risk priority score in the risk and bankability constraints section of this report?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.maximum_priority_risks` | Technical and operational | `resolved` |

### Q5. How many risks are tied for the highest risk priority score in the risk and bankability constraints section of this report?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.maximum_priority_risk_count` | 1 risks | `resolved` |

## 15. Conclusions and evidence requirements

Section `conclusions_and_evidence_requirements` · component `conclusions_and_evidence_requirements_text` · output contract `benchmark.evidence_requirements.v1`

Generation: **model generation attempt 1 (seed 7)**.

### Q1. What is the status of funding reconciliation for the project, and what is the maximum-risk priority score, along with the priority-KPI cutoff?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `calc.funding_reconciliation_status` | reconciled_within_0.1_pct_tolerance | `resolved` |
| `calc.maximum_risk_priority_score` | 4 score | `resolved` |
| `calc.kpi_priority_cutoff` | 4 priority | `resolved` |

### Q2. What are the current evidence gaps related to the financial model, technical design maturity, and environmental and social safeguards for the project?

Aggregation: **AND**

| Answer citation | Condition-specific authoritative answer | Resolution |
|---|---|---|
| `req.financial_model` | A complete source-backed financial model and its assumptions are not available as atomic evidence. | `resolved` |
| `req.technical_design_maturity` | Technical design maturity is not available as atomic evidence. | `resolved` |
| `req.environmental_social_safeguards` | A complete environmental and social safeguards assessment is not available as atomic evidence. | `resolved` |

## Review checklist

For each question, check that it is natural for the named project and condition, does not leak the answer, groups only inseparable answer slots, preserves missingness and qualifications, and can be answered completely from the listed citation evidence. Mark unresolved slots for gold repair rather than approving them for scoring.
