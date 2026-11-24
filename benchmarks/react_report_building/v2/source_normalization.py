from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..paths import NORMALIZED_ROOT
from ..util import read_json, sha256_json, write_json


V2_ROOT = Path(__file__).resolve().parent

# Keep the original path stable while FP083's compiled pilot and enrichment
# contract still pin it. The complete population is materialised separately so
# later all-project work does not need to special-case or overwrite that pilot.
OUTPUT_PATH = V2_ROOT / "data" / "evidence" / "fp083.source-normalized.json"
PROJECTS_OUTPUT_ROOT = V2_ROOT / "data" / "evidence" / "projects"


@dataclass(frozen=True)
class SourceFact:
    node_id: str
    description: str
    value: Any
    unit: str | None
    support_fragment: str


F = SourceFact


# These are deliberately modest manual extractions, not an attempt to turn
# prose into a complete synthetic template input. Every value below is guarded
# by an exact fragment from the same project's pinned description. Facts which
# require arithmetic, cross-project transfer, or substantive interpretation are
# left for the separately disclosed enrichment stage.
_SOURCE_FACTS: dict[str, tuple[SourceFact, ...]] = {
    "FP019": (
        F(
            "dt.project.redd_activity_count",
            "Number of REDD+ activities included in the national action plan",
            5,
            "activities",
            "includes the 5 REDD+ activities",
        ),
        F(
            "dt.project.zero_net_deforestation_target_year",
            "National zero-net-deforestation objective year",
            "2020",
            None,
            "zero net deforestation by 2020",
        ),
    ),
    "FP033": (
        F(
            "dt.project.baseline_imported_fossil_energy_pct",
            "Share of primary energy requirements met by imported fossil fuels",
            84.0,
            "%",
            "84% of its primary energy requirements met from imported fossil fuels",
        ),
        F(
            "dt.project.baseline_grid_emission_factor_tco2e_per_mwh",
            "Mauritius grid emission factor stated in the project description",
            1.01,
            "tCO2e/MWh",
            "grid emission factor of Mauritius is extremely high at 1.01 tonnes CO2/MWh",
        ),
        F(
            "dt.project.baseline_generation_coal_pct",
            "Coal share of the electricity generation mix",
            39.0,
            "%",
            "imported coal (39%)",
        ),
        F(
            "dt.project.baseline_generation_fuel_oil_pct",
            "Fuel-oil share of the electricity generation mix",
            38.0,
            "%",
            "fuel oil (38%)",
        ),
        F(
            "dt.project.net_ghg_emissions_growth_pct_per_year",
            "Reported annual growth in net greenhouse-gas emissions",
            3.0,
            "%/year",
            "Net greenhouse gas emissions are increasing at a rapid rate of 3% per year",
        ),
        F(
            "dt.project.gcf_phase_1_grant_usd",
            "GCF grant resources assigned to project phase 1",
            12_000_000,
            "USD",
            "phase 1 (US$ 12 million)",
        ),
        F(
            "dt.project.gcf_phase_2_grant_usd",
            "GCF grant resources assigned to project phase 2",
            16_210_000,
            "USD",
            "phase 2 (US$ 16.21 million)",
        ),
    ),
    "FP039": (
        F(
            "dt.project.baseline_hydropower_capacity_mw",
            "Hydropower capacity reported in the Egypt energy baseline",
            2_300,
            "MW",
            "hydro power (2,300 MW – c. 7%)",
        ),
        F(
            "dt.project.baseline_hydropower_generation_share_pct",
            "Approximate hydropower share reported in the Egypt energy baseline",
            7.0,
            "%",
            "hydro power (2,300 MW – c. 7%)",
        ),
        F(
            "dt.project.policy_renewable_target_pct",
            "Renewable share policy target",
            20.0,
            "%",
            "renewable sources to provide 20% of electricity generation by 2022",
        ),
        F(
            "dt.project.policy_target_year",
            "Renewable share policy target year",
            "2022",
            None,
            "renewable sources to provide 20% of electricity generation by 2022",
        ),
        F(
            "dt.project.expected_annual_generation_mwh",
            "Expected annual electricity generation once all projects are operational",
            1_400_000,
            "MWh/year",
            "generate around 1,400 GWh electricity annually",
        ),
        F(
            "dt.project.expected_annual_avoided_ghg_tco2e",
            "Expected annual avoided emissions once all projects are operational",
            800_000,
            "tCO2e/year",
            "avoided GHG emissions of about 800,000 tCO2e annually",
        ),
    ),
    "FP063": (
        F(
            "dt.project.economic_rate_of_return_pct",
            "Reported project economic rate of return",
            136.0,
            "%",
            "economic rate of return of 136%",
        ),
        F(
            "dt.project.social_cost_of_carbon_usd_per_tco2e",
            "Social cost of carbon used in the economic analysis",
            62.0,
            "USD/tCO2e",
            "social cost of carbon of USD 62/tCO2",
        ),
        F(
            "dt.project.financial_rate_of_return_pct",
            "Reported project financial return",
            74.0,
            "%",
            "financial return of 74%",
        ),
    ),
    "FP064": (
        F(
            "dt.project.gcf_grant_usd",
            "Non-reimbursable GCF grant resources for technical assistance",
            3_000_000,
            "USD",
            "Non-reimbursable GCF grant resources (USD 3 million)",
        ),
        F(
            "dt.project.bice_in_kind_resources_usd",
            "BICE in-kind resources complementing the GCF grant",
            600_000,
            "USD",
            "in-kind resources from BICE (USD 600,000)",
        ),
        F(
            "dt.project.idb_additional_grant_usd",
            "Additional IDB grant resources",
            250_000,
            "USD",
            "additional IDB grant resources (USD 250,000)",
        ),
        F(
            "dt.project.expected_energy_consumption_reduction_gwh",
            "Expected energy-consumption reduction including the revolving account",
            229.0,
            "GWh",
            "could reduce energy consumption by 229 GWh",
        ),
        F(
            "dt.project.expected_energy_generation_gwh",
            "Expected energy generation including the revolving account",
            8_842.0,
            "GWh",
            "generate 8,842 GWh",
        ),
        F(
            "dt.project.policy_renewable_target_pct",
            "Argentina renewable-energy share target",
            20.0,
            "%",
            "increase RE share in the energy matrix to 20%",
        ),
        F(
            "dt.project.policy_target_year",
            "Target year for the renewable-energy and consumption objectives",
            "2025",
            None,
            "reduce energy consumption in 5.9% by 2025",
        ),
        F(
            "dt.project.revolving_account_tenor_years",
            "Maximum stated tenor for recycling sub-loan returns",
            20.0,
            "years",
            "up to the tenor of 20 years",
        ),
    ),
    "FP071": (
        F(
            "dt.project.gcf_risk_sharing_facility_usd",
            "Amount of the GCF risk-sharing facility component",
            78_000_000,
            "USD",
            "US$78 million GCF Risk Sharing Facility",
        ),
        F(
            "dt.project.world_bank_gcf_technical_assistance_usd",
            "Combined World Bank and GCF technical-assistance component",
            10_000_000,
            "USD",
            "US$10 million World Bank and GCF Technical Assistance",
        ),
        F(
            "dt.project.ibrd_credit_line_usd",
            "Complementary World Bank energy-efficiency credit line",
            100_000_000,
            "USD",
            "US$100 million World Bank Energy Efficiency Credit Line",
        ),
        F(
            "dt.project.expected_ee_investment_mobilization_usd",
            "Approximate energy-efficiency investment mobilisation",
            407_300_000,
            "USD",
            "mobilize approximately US$ 407.3 million of EE investments",
        ),
        F(
            "dt.project.portfolio_unit_type",
            "Type of portfolio unit in the stated support target",
            "industrial company",
            None,
            "supporting over 100 industrial companies",
        ),
        F(
            "dt.project.portfolio_unit_count",
            "Reported lower bound on industrial companies supported",
            100,
            "companies",
            "supporting over 100 industrial companies",
        ),
        F(
            "dt.project.portfolio_unit_count_basis",
            "Basis of the portfolio-unit count",
            "support target",
            None,
            "supporting over 100 industrial companies",
        ),
        F(
            "dt.project.portfolio_unit_count_qualification",
            "Qualification attached to the portfolio-unit count",
            "The source states over 100 industrial companies; 100 is the stated lower bound.",
            None,
            "supporting over 100 industrial companies",
        ),
    ),
    "FP080": (
        F(
            "dt.project.baseline_installed_generation_capacity_mw",
            "Total installed generation capacity in the stated Zambia baseline",
            2_826.9,
            "MW",
            "total installed generation capacity of 2,826.9 MW",
        ),
        F(
            "dt.project.baseline_hydropower_generation_pct",
            "Approximate hydropower share in the stated Zambia baseline",
            90.0,
            "%",
            "nearly 90% of the total installed generation capacity",
        ),
        F(
            "dt.project.baseline_electricity_access_pct",
            "National electrification rate in the stated baseline",
            27.9,
            "%",
            "electrification rate stands at approximately 27.9%",
        ),
        F(
            "dt.project.refit_initial_capacity_target_mw",
            "Initial renewable capacity objective under the REFiT strategy",
            200.0,
            "MW",
            "bring initially 200 megawatts (MW) of renewable energy onto the grid",
        ),
        F(
            "dt.project.refit_solar_capacity_target_mw",
            "Solar-PV share of the initial REFiT capacity objective",
            100.0,
            "MW",
            "divided into 100 MW solar PV and 100 MW small-hydropower",
        ),
        F(
            "dt.project.refit_small_hydro_capacity_target_mw",
            "Small-hydropower share of the initial REFiT capacity objective",
            100.0,
            "MW",
            "divided into 100 MW solar PV and 100 MW small-hydropower",
        ),
        F(
            "dt.project.refit_subproject_capacity_max_mw",
            "Maximum stated capacity of REFiT small and medium projects",
            20.0,
            "MW",
            "renewable energy projects of up to 20 MW",
        ),
        F(
            "dt.project.senior_debt_and_standby_loan_envelope_usd",
            "AfDB-GCF senior-debt and standby-loan financing envelope",
            100_000_000,
            "USD",
            "provide USD 100 million of senior debt and standby loans",
        ),
        F(
            "dt.project.technical_assistance_grants_max_usd",
            "Maximum technical-assistance grants from GCF and AfDB",
            4_000_000,
            "USD",
            "technical assistance (TA) grants of up to USD 4 million",
        ),
    ),
    "FP081": (
        F(
            "dt.project.policy_non_fossil_capacity_target_pct",
            "Non-fossil electric-power capacity target",
            40.0,
            "%",
            "40% cumulative Electric power capacity from non-fossil fuel based energy resources by 2030",
        ),
        F(
            "dt.project.policy_non_fossil_capacity_target_year",
            "Target year for the non-fossil electric-power capacity objective",
            "2030",
            None,
            "40% cumulative Electric power capacity from non-fossil fuel based energy resources by 2030",
        ),
        F(
            "dt.project.policy_rooftop_solar_capacity_target_mw",
            "National rooftop-solar capacity target",
            40_000.0,
            "MW",
            "target of 40 GW of rooftop solar power by 2022",
        ),
        F(
            "dt.project.baseline_rooftop_solar_capacity_mw",
            "Installed rooftop-solar capacity as of March 2017",
            1_400.0,
            "MW",
            "installed capacity stood at 1.4 GW as on March 2017",
        ),
        F(
            "dt.project.rooftop_solar_market_cagr_pct",
            "Reported four-year rooftop-solar market compound annual growth rate",
            98.0,
            "%",
            "solar rooftop market has grown at a CAGR of 98%",
        ),
        F(
            "dt.project.commercial_industrial_capacity_share_pct",
            "Commercial and industrial share of installed rooftop capacity",
            65.0,
            "%",
            "With 65% of total installed capacity, Commercial & Industrial",
        ),
        F(
            "dt.project.gcf_concessional_loan_usd",
            "GCF resources provided in the form of senior loans",
            100_000_000,
            "USD",
            "USD 100 million of GCF resources in the form of Senior Loans",
        ),
        F(
            "dt.project.installed_capacity_target_mw",
            "Solar-rooftop capacity targeted in the programme's initial phase",
            250.0,
            "MW",
            "tap around 250 MW of solar rooftop capacity in the initial phase",
        ),
    ),
    "FP090": (
        F(
            "dt.project.baseline_fossil_generation_pct",
            "Approximate imported-diesel share in historical electricity generation",
            90.0,
            "%",
            "depended almost entirely on imported diesel (around 90%) to generate its electricity",
        ),
        F(
            "dt.project.policy_renewable_target_pct",
            "Final renewable-electricity generation target stated in Tonga's NDC",
            70.0,
            "%",
            "by 2030, 70% of all electricity to be generated from renewables",
        ),
        F(
            "dt.project.policy_target_year",
            "Year of the final renewable-electricity generation target",
            "2030",
            None,
            "by 2030, 70% of all electricity to be generated from renewables",
        ),
        F(
            "dt.project.interim_renewable_target_pct",
            "Interim renewable-electricity generation target stated in Tonga's NDC",
            50.0,
            "%",
            "by 2020, 50% of all electricity to be generated from renewables",
        ),
        F(
            "dt.project.pre_project_renewable_generation_pct",
            "Expected renewable generation share after completion of TERM phases 1 and 2",
            27.0,
            "%",
            "approximately 27% of Tonga’s electricity will be generated from renewable energies",
        ),
        F(
            "dt.project.baseline_grid_loss_pct",
            "Electricity line-loss baseline for the NDC efficiency target",
            18.0,
            "%",
            "from a baseline of 18 percent in 2010",
        ),
        F(
            "dt.project.grid_loss_target_pct",
            "Electricity line-loss target",
            9.0,
            "%",
            "reduction of electricity line losses to 9 percent by 2020",
        ),
    ),
    "FP102": (
        F(
            "dt.project.installed_capacity_target_mw",
            "Total capacity of isolated solar photovoltaic mini-grid systems",
            4.83,
            "MW",
            "total capacity of 4.83 MW",
        ),
        F(
            "dt.project.target_community_count",
            "Communities targeted for isolated solar mini-grid installation",
            70,
            "communities",
            "access to electricity in 70 communities",
        ),
        F(
            "dt.project.expected_annual_avoided_ghg_tco2e",
            "Expected annual avoided greenhouse-gas emissions",
            41_049,
            "tCO2e/year",
            "avoid 41 049 tCO2 / year",
        ),
        F(
            "dt.project.operating_horizon_years",
            "Stated equipment life",
            25.0,
            "years",
            "entire life of the equipment (25 years)",
        ),
        F(
            "dt.project.direct_beneficiaries_target",
            "Estimated direct beneficiaries in the project area",
            310_698,
            "people",
            "Direct beneficiaries are estimated at 310 698 inhabitants",
        ),
        F(
            "dt.project.women_beneficiary_share_pct",
            "Women share of estimated direct beneficiaries",
            50.0,
            "%",
            "50% of whom are women in the project area",
        ),
        F(
            "dt.project.service_connections_target",
            "Approximate new rural household electricity connections",
            31_000,
            "households",
            "Around 31,000 new households will have access to electrification",
        ),
        F(
            "dt.project.first_tranche_impact_share_pct",
            "Share of impact attributed to the first tranche",
            80.0,
            "%",
            "First Tranche will achieve 80% of the impact",
        ),
    ),
    "FP106": (
        F(
            "dt.project.baseline_energy_sector_ghg_share_pct",
            "Energy-sector share of South Africa greenhouse-gas emissions in 2012",
            82.7,
            "%",
            "energy sector remains the single largest contributor to the country’s total GHG emissions (82.7% in 2012)",
        ),
        F(
            "dt.project.baseline_coal_electricity_share_min_pct",
            "Lower bound stated for coal's share of electricity production",
            90.0,
            "%",
            "more than 90% of electricity being produced mainly from this source",
        ),
        F(
            "dt.project.reipppp_procured_capacity_mw",
            "Renewable-energy capacity historically procured by REIPPPP",
            6_422.0,
            "MW",
            "procured renewable energy capacity of ca. 6,422 MW",
        ),
        F(
            "dt.project.developed_renewable_pipeline_capacity_gw",
            "Fully developed viable renewable-energy project pipeline",
            11.2,
            "GW",
            "There remains ca 11.2 GW of fully developed and viable renewable energy projects",
        ),
        F(
            "dt.project.policy_embedded_generation_capacity_mw",
            "Embedded-generation allocation through 2030",
            2_600.0,
            "MW",
            "2,600 MW allocated up to 2030",
        ),
        F(
            "dt.project.expected_annual_avoided_ghg_tco2e",
            "Expected direct annual emissions reduction once all subprojects operate",
            717_794,
            "tCO2e/year",
            "ca. 717,794 tons CO2 eq per year once all the sub-projects are operational",
        ),
    ),
    "FP128": (
        F(
            "dt.project.average_investment_size_min_usd",
            "Lower end of Arbaro's stated average investment-size range",
            10_000_000,
            "USD/investment",
            "average investment size will be between USD 10 to 25 million per project",
        ),
        F(
            "dt.project.average_investment_size_max_usd",
            "Upper end of Arbaro's stated average investment-size range",
            25_000_000,
            "USD/investment",
            "average investment size will be between USD 10 to 25 million per project",
        ),
        F(
            "dt.project.underlying_investment_count_min",
            "Lower end of the stated final portfolio-size range",
            8,
            "investments",
            "final portfolio of 8 to 12 underlying investments",
        ),
        F(
            "dt.project.underlying_investment_count_max",
            "Upper end of the stated final portfolio-size range",
            12,
            "investments",
            "final portfolio of 8 to 12 underlying investments",
        ),
        F(
            "dt.project.conservation_set_aside_pct",
            "Average share of plantation-project land set aside for conservation",
            20.0,
            "%",
            "set aside 20% of its total land area for conservation purposes",
        ),
        F(
            "dt.project.direct_beneficiaries_target",
            "Maximum rural people expected to benefit from Arbaro investments",
            200_000,
            "people",
            "Up to 200 000 rural people are expected to benefit",
        ),
        F(
            "dt.project.direct_jobs_target",
            "Estimated direct employment from Arbaro investments",
            5_000,
            "jobs",
            "estimated to provide direct employment to ca 5 000 people",
        ),
        F(
            "dt.project.indirect_jobs_target",
            "Estimated indirect employment from Arbaro investee projects",
            15_000,
            "jobs",
            "indirectly Arbaro’s investee projects will employ another 15 000 people",
        ),
    ),
    "FP138": (
        F(
            "dt.project.baseline_electricity_access_pct",
            "Rural electricity-access rate in the stated baseline",
            42.0,
            "%",
            "only 42% of Senegal’s rural population has access to electricity",
        ),
        F(
            "dt.project.baseline_renewable_generation_pct",
            "Clean-energy share of the stated energy mix",
            20.0,
            "%",
            "20% of the energy mix derived from clean energy sources",
        ),
        F(
            "dt.project.universal_access_target_year",
            "Government target year for universal energy access",
            "2025",
            None,
            "pledged to reach universal energy access by 2025",
        ),
        F(
            "dt.project.target_community_count",
            "Isolated villages targeted for solar mini-grid deployment",
            1_000,
            "villages",
            "deploying 100% solar mini-grids in a thousand (1,000) isolated villages",
        ),
        F(
            "dt.project.service_connections_target",
            "Newly electrified rural households targeted within five years",
            38_917,
            "households",
            "benefitting 38,917 newly electrified rural households within 5 years",
        ),
        F(
            "dt.project.installed_capacity_target_mw",
            "Ultimate total solar-PV mini-grid capacity",
            32.0,
            "MW",
            "32 MW total solar PV mini-grids ultimate capacity",
        ),
        F(
            "dt.project.expected_annual_avoided_ghg_tco2e",
            "Estimated annual emissions reduction",
            45_098,
            "tCO2e/year",
            "estimated 45,098 tCO2 annual emission reductions impact",
        ),
    ),
    "FP140": (
        F(
            "dt.project.gcf_concessional_loan_usd",
            "GCF concessional-finance component",
            252_500_000,
            "USD",
            "USD 252.500 million concessional finance",
        ),
        F(
            "dt.project.gcf_grant_usd",
            "GCF grant component",
            5_530_000,
            "USD",
            "USD 5.530 million grant from the GCF",
        ),
        F(
            "dt.project.ebrd_and_other_cofinancing_loans_usd",
            "Loans offered by EBRD and other co-financing",
            757_500_000,
            "USD",
            "EBRD and other co-financing will offer USD 757.500 million",
        ),
        F(
            "dt.project.ebrd_technical_assistance_grant_usd",
            "EBRD technical-assistance grant",
            1_360_000,
            "USD",
            "technical assistance grant from the EBRD of USD 1.360 million",
        ),
        F(
            "dt.project.buildings_industry_ghg_reduction_tco2e",
            "Reported mitigation in the buildings, cities, industries and appliances result area",
            15_498_000,
            "tCO2e",
            "buildings, cities, industries and appliances” by 15.498M tCO2",
        ),
        F(
            "dt.project.energy_access_ghg_reduction_tco2e",
            "Reported mitigation in the energy access and power generation result area",
            1_722_000,
            "tCO2e",
            "energy access and power generation” by 1.722M tCO2",
        ),
        F(
            "dt.project.expected_energy_savings_tj",
            "Expected energy savings over investment lifetimes",
            111_400.0,
            "TJ",
            "over 111,400 TJ in energy savings",
        ),
    ),
    "FP148": (
        F(
            "dt.project.no_objection_country_count",
            "Countries from which the accredited entity secured letters of no objection",
            9,
            "countries",
            "secured Letters of No Objection from 9 countries",
        ),
        F(
            "dt.project.portfolio_unit_type",
            "Type of unit in the identified demand pipeline",
            "borrower/company",
            None,
            "308 companies have expressed a need for relief funding",
        ),
        F(
            "dt.project.portfolio_unit_count",
            "Companies in the identified relief-funding demand pipeline",
            308,
            "companies",
            "308 companies have expressed a need for relief funding",
        ),
        F(
            "dt.project.portfolio_unit_count_basis",
            "Basis of the company count",
            "identified demand pipeline",
            None,
            "308 companies have expressed a need for relief funding",
        ),
        F(
            "dt.project.portfolio_unit_count_qualification",
            "Qualification attached to the company count",
            "Companies expressed a financing need; the count is not a final borrower target.",
            None,
            "308 companies have expressed a need for relief funding",
        ),
        F(
            "dt.project.identified_financing_requests_usd",
            "Total indicative financing requests in the identified pipeline",
            79_560_000,
            "USD",
            "indicative requests totaling ~$79.56 million",
        ),
        F(
            "dt.project.identified_request_min_usd",
            "Minimum indicative company request",
            8_000,
            "USD",
            "ranging from $8,000 to $3 million in size",
        ),
        F(
            "dt.project.identified_request_max_usd",
            "Maximum indicative company request",
            3_000_000,
            "USD",
            "ranging from $8,000 to $3 million in size",
        ),
        F(
            "dt.project.people_reached_count",
            "Customers currently served by firms in the identified demand pipeline",
            85_000_000,
            "people",
            "these firms serve over 85 million customers",
        ),
        F(
            "dt.project.people_reach_basis",
            "Basis of the reported people-reach count",
            "current customers of companies in the identified demand pipeline",
            None,
            "these firms serve over 85 million customers",
        ),
        F(
            "dt.project.people_reach_qualification",
            "Qualification attached to the reported people-reach count",
            "The source states over 85 million current customers; this is not a new-beneficiary target.",
            None,
            "these firms serve over 85 million customers",
        ),
        F(
            "dt.project.people_at_risk_of_lost_access",
            "People estimated to be prevented from accessing renewable household energy without relief",
            16_300_000,
            "people",
            "16.3 million people may be prevented from accessing renewable household energy",
        ),
    ),
    "FP163": (
        F(
            "dt.project.initial_phase_country_count",
            "Countries included in the facility's initial phase",
            7,
            "countries",
            "technical and financial support to seven initial countries (Phase 1)",
        ),
    ),
    "FP178": (
        F(
            "dt.project.afdb_cofinancing_usd",
            "AfDB portion of stated co-financing",
            379_600_000,
            "USD",
            "US$ 379.6 million from the AfDB",
        ),
        F(
            "dt.project.private_sector_cofinancing_usd",
            "Private-sector portion of stated co-financing",
            437_000_000,
            "USD",
            "US$ 437 million of private sector co-financing",
        ),
        F(
            "dt.project.enabled_capacity_min_mw",
            "Lower bound stated for additional solar-generation capacity",
            500.0,
            "MW",
            "adding over 500 MW of solar energy generation capacity",
        ),
        F(
            "dt.project.expected_ipp_equity_usd",
            "Equity expected to be mobilized by independent power producers",
            141_700_000,
            "USD",
            "mobilize US$ 141.7 million in equity",
        ),
        F(
            "dt.project.expected_ipp_debt_usd",
            "Debt financing expected to be mobilized by independent power producers",
            566_900_000,
            "USD",
            "US$ 566.9 million in debt financing",
        ),
        F(
            "dt.project.partial_risk_guarantee_usd",
            "Partial risk guarantee introduced by the facility",
            40_000_000,
            "USD",
            "partial risk guarantee of US$ 40 million",
        ),
        F(
            "dt.project.direct_beneficiaries_target",
            "Expected direct beneficiaries",
            3_500_000,
            "people",
            "directly benefit 3.5 million people",
        ),
        F(
            "dt.project.women_beneficiaries_target",
            "Expected women direct beneficiaries",
            1_750_000,
            "people",
            "out of which 1.75 million are women",
        ),
        F(
            "dt.project.indirect_beneficiaries_target",
            "Expected indirect beneficiaries",
            700_000,
            "people",
            "indirect beneficiaries are estimated at 700,000 people",
        ),
        F(
            "dt.project.construction_jobs_target",
            "Estimated jobs created during construction",
            1_250,
            "jobs",
            "1250 jobs will be created during construction",
        ),
        F(
            "dt.project.permanent_jobs_target",
            "Estimated permanent jobs",
            450,
            "jobs",
            "450 permanent jobs",
        ),
    ),
    "FP193": (
        F(
            "dt.project.livelihood_enterprises_target",
            "Eco bio businesses targeted for repayable seed-funding grants",
            55,
            "businesses",
            "provide seed funding in the form of repayable grants to 55 EBBs",
        ),
        F(
            "dt.project.forest_protection_area_target_ha",
            "Forest area targeted to be prevented from deforestation",
            8_602.0,
            "ha",
            "prevent 8,602 hectares of forest from being deforested",
        ),
        F(
            "dt.project.formal_jobs_target",
            "Estimated formal jobs created",
            550,
            "jobs",
            "creation of 550 formal jobs",
        ),
        F(
            "dt.project.indirect_people_supported_target",
            "People estimated to be supported indirectly",
            2_200,
            "people",
            "an additional 2,200 people will indirectly be supported",
        ),
    ),
    "FP196": (
        F(
            "dt.project.baseline_energy_sector_ghg_share_pct",
            "Energy-sector share of Indonesia greenhouse-gas emissions",
            65.43,
            "%",
            "attributes 65.43% of the total greenhouse gas (GHG) emissions to the energy sector",
        ),
        F(
            "dt.project.programme_component_count",
            "Number of programme components designed around the stated barriers",
            3,
            "components",
            "designing three components accordingly",
        ),
    ),
}


def available_project_ids() -> tuple[str, ...]:
    """Return the complete deterministic normalized-twin population."""

    return tuple(path.stem.upper() for path in sorted(NORMALIZED_ROOT.glob("*.json")))


def project_output_path(project_id: str) -> Path:
    canonical_id = _canonical_project_id(project_id)
    return PROJECTS_OUTPUT_ROOT / f"{canonical_id.lower()}.source-normalized.json"


def build_source_normalization(project_id: str = "FP083") -> dict[str, Any]:
    """Atomize facts explicitly stated in one pinned normalized project twin."""

    canonical_id = _canonical_project_id(project_id)
    twin = read_json(NORMALIZED_ROOT / f"{canonical_id.lower()}.json")
    if twin.get("project_id") != canonical_id:
        raise ValueError(
            f"{canonical_id}: normalized twin contains project_id "
            f"{twin.get('project_id')!r}"
        )
    if canonical_id == "FP083":
        return _build_fp083_source_normalization(twin)

    description_node = twin["nodes"]["dt.project.description"]
    description = str(description_node.get("value") or "")
    definitions = _SOURCE_FACTS.get(canonical_id, ())
    missing = [
        fact.support_fragment
        for fact in definitions
        if fact.support_fragment not in description
    ]
    if missing:
        raise ValueError(
            f"{canonical_id} description no longer supports the reviewed extraction: "
            + ", ".join(missing)
        )

    project_url = description_node.get("provenance", {}).get("url")
    document_id = description_node.get("provenance", {}).get(
        "document_id", f"proposal.{canonical_id.lower()}"
    )
    nodes = {
        fact.node_id: _node(
            fact.node_id,
            fact.description,
            fact.value,
            fact.unit,
            "basic_info.description",
            document_id=document_id,
            url=project_url,
            support_fragment=fact.support_fragment,
        )
        for fact in definitions
    }
    _validate_no_collisions(canonical_id, twin, nodes)
    return {
        "schema_version": "react_report.source_normalization/v2",
        "project_id": canonical_id,
        "method": (
            "Manual atomic extraction of values explicitly present in the pinned "
            "same-project description; every extracted node is exact-fragment "
            "validated, with no inference, cross-project imputation, or external "
            "supplementation."
        ),
        "input": {
            "path": f"data/normalized/projects/{canonical_id.lower()}.json",
            "sha256": sha256_json(twin),
            "source_node": "dt.project.description",
        },
        "nodes": nodes,
    }


def build_all_source_normalizations() -> dict[str, dict[str, Any]]:
    """Build all source-normalized bundles without writing to disk."""

    return {
        project_id: build_source_normalization(project_id)
        for project_id in available_project_ids()
    }


def write_source_normalization(
    path: Path | None = None,
    *,
    project_id: str = "FP083",
) -> dict[str, Any]:
    payload = build_source_normalization(project_id)
    destination = path or (
        OUTPUT_PATH
        if payload["project_id"] == "FP083"
        else project_output_path(payload["project_id"])
    )
    write_json(destination, payload)
    return payload


def write_all_source_normalizations(
    output_root: Path = PROJECTS_OUTPUT_ROOT,
) -> dict[str, dict[str, Any]]:
    payloads = build_all_source_normalizations()
    for project_id, payload in payloads.items():
        write_json(
            output_root / f"{project_id.lower()}.source-normalized.json",
            payload,
        )
    return payloads


def _canonical_project_id(project_id: str) -> str:
    canonical_id = str(project_id).upper()
    if canonical_id not in available_project_ids():
        raise ValueError(f"unknown normalized project {project_id!r}")
    return canonical_id


def _validate_no_collisions(
    project_id: str,
    twin: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
) -> None:
    baseline_ids = set(twin.get("nodes", {})) | set(twin.get("collections", {}))
    collisions = sorted(baseline_ids.intersection(nodes))
    if collisions:
        raise ValueError(
            f"{project_id}: source normalization would overwrite baseline IDs: "
            + ", ".join(collisions)
        )


def _build_fp083_source_normalization(twin: dict[str, Any]) -> dict[str, Any]:
    """Preserve the original 19 manually reviewed FP083 source extractions."""

    description_node = twin["nodes"]["dt.project.description"]
    description = str(description_node.get("value") or "")
    required_fragments = (
        "58.3 percent coal",
        "23.2 percent gas",
        "6 percent diesel",
        "12.5 percent renewables",
        "29 percent reduction of GHG emissions by 2030",
        "23 percent by 2026",
        "US$325 million loan",
        "US$25 million soft loan",
        "US$150 million reimbursable grant",
        "US$10 million grant",
        "187 – 281 MtCO2e",
        "1 – 1.5 GW",
        "US$4 – 5.5 billion",
        "US100 million from GCF",
        "around 60% of the impact",
    )
    missing = [fragment for fragment in required_fragments if fragment not in description]
    if missing:
        raise ValueError(
            "FP083 description no longer supports the reviewed extraction: "
            + ", ".join(missing)
        )

    facts = {
        "dt.project.energy_mix_coal_pct": (
            "2017 coal generation share",
            58.3,
            "%",
            "basic_info.description: 2017 generation mix, coal",
        ),
        "dt.project.energy_mix_gas_pct": (
            "2017 gas generation share",
            23.2,
            "%",
            "basic_info.description: 2017 generation mix, gas",
        ),
        "dt.project.energy_mix_diesel_pct": (
            "2017 diesel generation share",
            6.0,
            "%",
            "basic_info.description: 2017 generation mix, diesel",
        ),
        "dt.project.energy_mix_renewables_pct": (
            "2017 renewables generation share",
            12.5,
            "%",
            "basic_info.description: 2017 generation mix, renewables",
        ),
        "dt.project.renewables_policy_target_pct": (
            "Renewables generation policy target for 2026",
            23.0,
            "%",
            "basic_info.description: renewable energy target for 2026",
        ),
        "dt.project.ndc_reduction_target_pct": (
            "Indonesia NDC reduction commitment for 2030",
            29.0,
            "%",
            "basic_info.description: NDC commitment for 2030",
        ),
        "dt.project.ndc_target_year": (
            "Indonesia NDC target year",
            "2030",
            None,
            "basic_info.description: NDC commitment for 2030",
        ),
        "dt.project.gcf_soft_loan_usd": (
            "GCF soft loan financing amount",
            25_000_000,
            "USD",
            "basic_info.description: GCF US$25 million soft loan",
        ),
        "dt.project.gcf_reimbursable_grant_usd": (
            "GCF reimbursable grant financing amount",
            150_000_000,
            "USD",
            "basic_info.description: GCF US$150 million reimbursable grant",
        ),
        "dt.project.gcf_grant_usd": (
            "GCF grant financing amount",
            10_000_000,
            "USD",
            "basic_info.description: GCF US$10 million grant",
        ),
        "dt.project.ghg_reduction_min_tco2e": (
            "Expected lifetime GHG reduction lower estimate",
            187_000_000,
            "tCO2e",
            "basic_info.description: 187–281 MtCO2e expected lifetime range",
        ),
        "dt.project.ghg_reduction_max_tco2e": (
            "Expected lifetime GHG reduction upper estimate",
            281_000_000,
            "tCO2e",
            "basic_info.description: 187–281 MtCO2e expected lifetime range",
        ),
        "dt.project.enabled_capacity_min_mw": (
            "Enabled geothermal capacity lower estimate",
            1_000,
            "MW",
            "basic_info.description: 1–1.5 GW additional capacity range",
        ),
        "dt.project.enabled_capacity_max_mw": (
            "Enabled geothermal capacity upper estimate",
            1_500,
            "MW",
            "basic_info.description: 1–1.5 GW additional capacity range",
        ),
        "dt.project.mobilized_capital_min_usd": (
            "Expected mostly private capital mobilized lower estimate",
            4_000_000_000,
            "USD",
            "basic_info.description: US$4–5.5 billion expected mobilization range",
        ),
        "dt.project.mobilized_capital_max_usd": (
            "Expected mostly private capital mobilized upper estimate",
            5_500_000_000,
            "USD",
            "basic_info.description: US$4–5.5 billion expected mobilization range",
        ),
        "dt.project.first_tranche_gcf_usd": (
            "First-tranche GCF financing amount",
            100_000_000,
            "USD",
            "basic_info.description: first tranche total from GCF",
        ),
        "dt.project.first_tranche_impact_share_pct": (
            "Approximate first-tranche share of total project impact",
            60.0,
            "%",
            "basic_info.description: first tranche around 60% of total impact",
        ),
        "dt.project.ghg_accounting_qualification": (
            "GHG accounting qualification",
            (
                "The expected 187–281 MtCO2e range is stated over generating "
                "assets' lifetime and is to be cross-checked after drilling using "
                "a two-step GHG accounting approach."
            ),
            None,
            "basic_info.description: lifetime and post-drilling accounting qualification",
        ),
    }
    project_url = description_node.get("provenance", {}).get("url")
    document_id = description_node.get("provenance", {}).get(
        "document_id", "proposal.fp083"
    )
    nodes = {
        node_id: _node(
            node_id,
            description,
            value,
            unit,
            locator,
            document_id=document_id,
            url=project_url,
        )
        for node_id, (description, value, unit, locator) in facts.items()
    }
    _validate_no_collisions("FP083", twin, nodes)
    return {
        "schema_version": "react_report.source_normalization/v2",
        "project_id": "FP083",
        "method": (
            "Manual atomic extraction of values explicitly present in the pinned "
            "project twin; no cross-project imputation or external supplementation."
        ),
        "input": {
            "path": "data/normalized/projects/fp083.json",
            "sha256": sha256_json(twin),
            "source_node": "dt.project.description",
        },
        "nodes": nodes,
    }


def _node(
    node_id: str,
    description: str,
    value: Any,
    unit: str | None,
    locator: str,
    *,
    document_id: str,
    url: str | None,
    support_fragment: str | None = None,
) -> dict[str, Any]:
    provenance: dict[str, Any] = {
        "source_kind": "same_project_source_extraction",
        "document_id": document_id,
        "url": url,
        "locator": locator,
    }
    normalization: dict[str, Any] = {
        "method": "manual atomic extraction",
        "imputed": False,
        "overwrites_source_node": False,
    }
    if support_fragment is not None:
        provenance["support_fragment"] = support_fragment
        normalization["support_validation"] = "exact_fragment"
    return {
        "id": node_id,
        "kind": "scalar",
        "description": description,
        "status": "available",
        "value": value,
        "unit": unit,
        "evidence_class": "same_project_source_extraction",
        "provenance": provenance,
        "normalization": normalization,
    }


def main() -> None:
    payloads = write_all_source_normalizations()
    # Keep the existing FP083 pilot file synchronized without changing its
    # content or the paths pinned by the current enrichment/compiled contract.
    write_json(OUTPUT_PATH, payloads["FP083"])
    node_count = sum(len(payload["nodes"]) for payload in payloads.values())
    print(
        f"{PROJECTS_OUTPUT_ROOT} "
        f"({len(payloads)} projects, {node_count} source-normalized nodes)"
    )


if __name__ == "__main__":
    main()
