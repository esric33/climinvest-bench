"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const documentEngine = require("./vendor/tracemark-core/document-engine.js");

const PACKAGE_ROOT = path.resolve(__dirname, "..");
const V2_ROOT = __dirname;
const outputPath = path.join(V2_ROOT, "data", "compiled_contract.json");
const familyOutputRoot = path.join(V2_ROOT, "data", "contracts");
const populationRelativePath = "v2/data/study/twenty-project-study-population.json";
const populationPath = path.join(PACKAGE_ROOT, populationRelativePath);
const semanticCalculationsPath = path.join(V2_ROOT, "data", "semantic_calculations.json");

const COMMON_SECTION_IDS = [
  "executive_summary",
  "project_identification_and_status",
  "promoter_and_delivery_arrangements",
  "climate_rationale_and_strategic_fit",
  "technical_feasibility_and_readiness",
  "costs_and_financing_structure",
  "financial_sustainability_and_business_model",
  "impact_esg_and_safeguards",
  "performance_indicators_and_mrv",
  "risk_and_bankability_constraints",
  "conclusions_and_evidence_requirements"
];

const LEADING_COMMON_SECTION_IDS = COMMON_SECTION_IDS.slice(0, 4);
const TRAILING_COMMON_SECTION_IDS = COMMON_SECTION_IDS.slice(4);
const OUTPUT_CONTRACT_IDS = new Set([
  "benchmark.executive_assessment.v1",
  "benchmark.interpretive_assessment.v1",
  "benchmark.kpi_priority.v1",
  "benchmark.risk_priority.v1",
  "benchmark.evidence_requirements.v1"
]);

const FAMILY_TEMPLATES = {
  asset_delivery: {
    label: "Asset and physical delivery",
    template: "v2/templates/asset_delivery.tracemark.md",
    specialistSections: [
      "system_baseline_and_policy_context",
      "capacity_and_output",
      "commissioning_profile",
      "operational_impact_consistency"
    ],
    applicability: {
      accounting_boundary_field: "dt.project.generation_accounting_boundary",
      comparison_gate: "dt.project.reported_ghg_comparison_status",
      comparison_allowed_value: "comparable",
      qualifications: [
        "dt.project.capacity_delivery_relationship",
        "dt.project.asset_impact_boundary_qualification",
        "dt.project.reported_ghg_comparison_qualification"
      ]
    }
  },
  financing_facility: {
    label: "Financing facility or investment programme",
    template: "v2/templates/financing_facility.tracemark.md",
    specialistSections: [
      "market_rationale_and_additionality",
      "instrument_structure_and_terms",
      "allocation_and_utilisation_profile",
      "portfolio_scale_and_mobilisation"
    ],
    applicability: {
      facility_archetype_field: "dt.project.facility_archetype",
      deployment_basis_field: "dt.project.facility_deployment_basis",
      mobilisation_gate: "dt.project.mobilization_applicability",
      mobilisation_allowed_value: "applicable",
      qualifications: [
        "dt.project.instrument_terms_qualification",
        "dt.project.facility_profile_scope",
        "dt.project.facility_recycling_qualification",
        "dt.project.portfolio_unit_count_basis",
        "dt.project.mobilization_qualification"
      ]
    }
  },
  land_use_nature: {
    label: "Land-use and nature programme",
    template: "v2/templates/land_use_nature.tracemark.md",
    specialistSections: [
      "land_use_baseline_and_intervention",
      "area_allocation_and_enrolment",
      "carbon_accounting_consistency",
      "people_and_cobenefits"
    ],
    applicability: {
      accounting_mode_field: "dt.project.land_accounting_mode",
      accounting_modes: ["activity_area", "jurisdictional", "investment_portfolio"],
      pathway_registry: "dt.project.land_pathway_applicability",
      pathway_gate_fields: [
        "dt.project.protection_pathway_applicability",
        "dt.project.restoration_pathway_applicability",
        "dt.project.plantation_afforestation_pathway_applicability",
        "dt.project.sustainable_management_pathway_applicability",
        "dt.project.jurisdictional_pathway_applicability"
      ],
      adjustment_gate_fields: [
        "dt.project.implementation_effectiveness_adjustment_applicability",
        "dt.project.leakage_adjustment_applicability",
        "dt.project.permanence_buffer_adjustment_applicability"
      ],
      adjustment_active_value: "apply",
      adjustment_already_embedded_value: "already_embedded",
      comparison_gate: "dt.project.reported_ghg_comparison_status",
      comparison_allowed_value: "comparable",
      qualifications: [
        "dt.project.land_carbon_pathway_boundary",
        "dt.project.land_adjustment_scope_qualification",
        "dt.project.land_accounting_qualification",
        "dt.project.reported_ghg_comparison_qualification"
      ]
    }
  }
};

const compilerPin = {
  source_repository: "climinvest-studio",
  source_commit: "28b49429da5befbe22d9debd1f72ac7e3c10b2c0",
  files: {
    "document-engine.js": "eb2f4855dcdcab76d951e43b8f40ababe4584423856e0f494ef7b1131263d655",
    "report-ir.js": "ef4c791b8ce41bce0e6bbf63e098fa79c16dea6681bd5b1b0063ba39128ba6db"
  }
};

function semanticCalculationRegistry() {
  const payload = JSON.parse(fs.readFileSync(semanticCalculationsPath, "utf8"));
  if (payload.schema_version !== "react_report.semantic_calculations/v1") {
    throw new Error("Unexpected semantic-calculation specification schema");
  }
  return Object.fromEntries((payload.calculations || []).map(item => [item.id, item]));
}

function semanticCalculationsForSource(source) {
  const registry = semanticCalculationRegistry();
  const direct = new Set(
    (source.match(/\bcalc\.[A-Za-z0-9_.]+\b/g) || []).filter(id => registry[id])
  );
  const selected = new Set();
  const visit = id => {
    if (!registry[id] || selected.has(id)) return;
    selected.add(id);
    for (const dependency of Object.values(registry[id].input_ids || {})) {
      if (String(dependency).startsWith("calc.")) visit(dependency);
    }
  };
  for (const id of direct) visit(id);
  return [...selected].map(id => registry[id]);
}

function semanticGlobalDefinitions(calculations) {
  return Object.fromEntries(calculations.map(item => [item.id, {
    id: item.id,
    label: item.description || item.id,
    // The pinned document compiler only needs a typed external node. Runtime
    // execution remains the public calculate tool defined by the shared spec.
    tool: "GET_DATA",
    valueType: item.value_type,
    unit: item.unit || null
  }]));
}

function semanticSourceIds(calculations) {
  return [...new Set(calculations.flatMap(item =>
    Object.values(item.input_ids || {})
      .filter(dependency => !String(dependency).startsWith("calc."))
      .map(String)
  ))].sort();
}

function semanticDepths(calculations) {
  const byId = new Map(calculations.map(item => [item.id, item]));
  const memo = new Map();
  const depth = (id, active = new Set()) => {
    if (memo.has(id)) return memo.get(id);
    if (active.has(id)) throw new Error(`Semantic calculation cycle at ${id}`);
    const next = new Set(active).add(id);
    const value = 1 + Math.max(0, ...Object.values(byId.get(id).input_ids || {})
      .filter(dependency => byId.has(dependency))
      .map(dependency => depth(dependency, next)));
    memo.set(id, value);
    return value;
  };
  return Object.fromEntries(calculations.map(item => [item.id, depth(item.id)]));
}

function semanticGeneratedNodes(calculations) {
  const depths = semanticDepths(calculations);
  return calculations.map(item => ({
    id: item.id,
    canonical_id: item.id,
    name: item.id.replace(/^calc\./, ""),
    tool: "BENCHMARK_CALCULATION",
    value_type: item.value_type,
    unit: item.unit || null,
    label: item.description,
    expression: null,
    expression_ast: null,
    operation_id: item.operation_id,
    parameters: item.parameters || {},
    input_ids: item.input_ids || {},
    dependencies: Object.values(item.input_ids || {}),
    canonical_dependencies: Object.values(item.input_ids || {}),
    calculation_depth: depths[item.id],
    section_id: null,
    subsection_id: null
  }));
}

function addSemanticGraph(graph, calculations) {
  if (!calculations.length) return graph;
  const depths = semanticDepths(calculations);
  const deepest = [...calculations]
    .sort((left, right) => depths[right.id] - depths[left.id])[0];
  return {
    ...graph,
    calculation_count: graph.calculation_count + calculations.length,
    semantic_calculation_count: calculations.length,
    edge_count: graph.edge_count + calculations.reduce(
      (total, item) => total + Object.keys(item.input_ids || {}).length,
      0
    ),
    max_calculation_depth: Math.max(
      graph.max_calculation_depth,
      deepest ? depths[deepest.id] : 0
    ),
    calculation_depths: {...graph.calculation_depths, ...depths}
  };
}

function sha256(filePath) {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

function verifyCompilerPin() {
  for (const [filename, expected] of Object.entries(compilerPin.files)) {
    const actual = sha256(path.join(V2_ROOT, "vendor", "tracemark-core", filename));
    if (actual !== expected) {
      throw new Error(`TraceMark pin mismatch for ${filename}: expected ${expected}, received ${actual}`);
    }
  }
}

function expressionIdentifiers(ast, output = []) {
  if (!ast || typeof ast !== "object") return output;
  if (ast.type === "identifier") output.push(ast.name);
  if (ast.argument) expressionIdentifiers(ast.argument, output);
  if (ast.left) expressionIdentifiers(ast.left, output);
  if (ast.right) expressionIdentifiers(ast.right, output);
  for (const item of ast.args || ast.elements || []) expressionIdentifiers(item, output);
  return output;
}

function canonicalMappings(compiled) {
  const calculationByRuntimeId = new Map(
    compiled.generatedNodes
      .filter(node => node.tool === "DOC_EXPRESSION")
      .map(node => [node.id, `calc.${node.name}`])
  );
  const canonicalId = id => calculationByRuntimeId.get(id) || id;
  const canonicalize = ast => {
    if (!ast || typeof ast !== "object") return ast;
    if (Array.isArray(ast)) return ast.map(canonicalize);
    const output = Object.fromEntries(
      Object.entries(ast).map(([key, value]) => [key, canonicalize(value)])
    );
    if (output.type === "identifier") output.name = canonicalId(output.name);
    return output;
  };
  const canonicalExpressionAst = node => canonicalize(node.ast);
  const inputIds = node => Object.fromEntries(
    [...new Set(expressionIdentifiers(canonicalExpressionAst(node)))]
      .map(name => [name, name])
  );
  return { canonicalId, canonicalExpressionAst, inputIds };
}

function buildGraph(compiled) {
  const generated = new Map(compiled.generatedNodes.map(node => [node.id, node]));
  const depthMemo = new Map();
  const chainMemo = new Map();
  const sourcesMemo = new Map();

  function depth(id, visiting = new Set()) {
    if (!generated.has(id)) return 0;
    if (depthMemo.has(id)) return depthMemo.get(id);
    if (visiting.has(id)) throw new Error(`Cycle while measuring dependency depth at ${id}`);
    const next = new Set(visiting).add(id);
    const value = 1 + Math.max(0, ...(generated.get(id).deps || []).map(dep => depth(dep, next)));
    depthMemo.set(id, value);
    return value;
  }

  function longestChain(id) {
    if (!generated.has(id)) return [];
    if (chainMemo.has(id)) return chainMemo.get(id);
    const upstream = (generated.get(id).deps || [])
      .map(longestChain)
      .sort((left, right) => right.length - left.length)[0] || [];
    const value = [...upstream, id];
    chainMemo.set(id, value);
    return value;
  }

  function sourceIds(id, visiting = new Set()) {
    if (!generated.has(id)) return [id];
    if (sourcesMemo.has(id)) return sourcesMemo.get(id);
    if (visiting.has(id)) throw new Error(`Cycle while resolving source dependencies at ${id}`);
    const next = new Set(visiting).add(id);
    const value = [...new Set((generated.get(id).deps || []).flatMap(dep => sourceIds(dep, next)))].sort();
    sourcesMemo.set(id, value);
    return value;
  }

  const calculations = compiled.generatedNodes.filter(node => node.tool === "DOC_EXPRESSION");
  const depths = Object.fromEntries(calculations.map(node => [node.id, depth(node.id)]));
  const deepest = [...calculations].sort((left, right) => depth(right.id) - depth(left.id))[0];
  const longest = deepest ? longestChain(deepest.id) : [];
  const nameById = new Map(calculations.map(node => [node.id, node.name]));
  const sourceSectionFanout = {};

  for (const artifact of compiled.artifacts.filter(item => !["calculation", "markdown"].includes(item.type))) {
    for (const sourceId of [...new Set((artifact.deps || []).flatMap(id => sourceIds(id)))]) {
      sourceSectionFanout[sourceId] ||= [];
      if (artifact.sectionId && !sourceSectionFanout[sourceId].includes(artifact.sectionId)) {
        sourceSectionFanout[sourceId].push(artifact.sectionId);
      }
    }
  }
  for (const sectionIds of Object.values(sourceSectionFanout)) sectionIds.sort();

  const edgeCount = calculations.reduce((total, node) => total + (node.deps || []).length, 0)
    + compiled.artifacts.reduce((total, artifact) => total + (artifact.deps || []).length, 0);

  return {
    calculation_count: calculations.length,
    artifact_count: compiled.artifacts.length,
    llm_component_count: compiled.artifacts.filter(item => item.type === "llm").length,
    edge_count: edgeCount,
    max_calculation_depth: deepest ? depth(deepest.id) : 0,
    calculation_depths: depths,
    longest_calculation_chain: longest,
    longest_calculation_chain_names: longest.map(id => nameById.get(id) || id),
    source_section_fanout: Object.fromEntries(Object.entries(sourceSectionFanout).sort(([left], [right]) => left.localeCompare(right)))
  };
}

const COLLECTION_SOURCE_IDS = new Set([
  "dt.project.countries",
  "dt.project.mitigation_areas",
  "dt.project.adaptation_areas",
  "dt.project.energy_technologies",
  "dt.kpis",
  "dt.kpi_reporting_priorities",
  "dt.risks",
  "dt.project.facility_reach",
  "dt.project.land_pathway_applicability"
]);

function directSourceIds(source) {
  return [...new Set(source.match(/\b(?:dt|reference|req)\.[A-Za-z0-9_.]+\b/g) || [])].sort();
}

function numericSource(id) {
  return /(?:_usd|_pct|_share|_years|_year|_tco2e|_mw|_mwh|_ha|_count|_factor_tco2e_per_mwh|_tco2e_per_ha|_tco2e_per_ha_year|_tco2e_per_year)$/.test(id)
    || /(?:median|q1|q3|sample_count|beneficiaries_target|connections_target|enterprises_target)$/.test(id);
}

function inferredUnit(id) {
  if (/(?:project_cost|gcf_financing)_per_reported_tco2e$/.test(id)) return "USD/tCO2e";
  if (/^annualised_reported_ghg_target_tco2e$/.test(id)) return "tCO2e/year";
  if (/(?:project_cost|gcf_financing)_per_tco2e_(?:low|mid|high)$/.test(id)) return "USD/tCO2e";
  if (/_per_modelled_tco2e$/.test(id)) return "USD/tCO2e";
  if (/_per_installed_mw$/.test(id)) return id.startsWith("beneficiaries_") ? "people/MW" : "USD/MW";
  if (/_per_intervention_hectare$/.test(id)) return "USD/ha";
  if (/_per_direct_beneficiary$/.test(id)) return "USD/person";
  if (/_per_livelihood_enterprise$/.test(id)) return "USD/enterprise";
  if (/_per_service_connection$/.test(id)) return id.startsWith("direct_beneficiaries_") ? "people/connection" : "USD/connection";
  if (/_per_portfolio_unit(?:_(?:low|high))?$/.test(id)) return "USD/portfolio unit";
  if (/_generation_mwh_per_year$/.test(id)) return "MWh/year";
  if (/_tco2e_per_ha_year$/.test(id)) return "tCO2e/ha/year";
  if (/_tco2e_per_mwh$/.test(id)) return "tCO2e/MWh";
  if (/_tco2e_per_ha$/.test(id)) return "tCO2e/ha";
  if (/_tco2e_per_year$/.test(id)) return "tCO2e/year";
  if (/_tco2e$/.test(id)) return "tCO2e";
  if (/_mwh$/.test(id)) return "MWh";
  if (/_mw$/.test(id)) return "MW";
  if (/_usd$/.test(id)) return "USD";
  if (/_ha$/.test(id)) return "ha";
  if (/_pct/.test(id)) return "%";
  if (/_share$/.test(id)) return "x";
  if (/_share_total$/.test(id)) return "x";
  if (/_ratio$/.test(id)) return "x";
  if (/_per_gcf_dollar$/.test(id)) return "x";
  if (/_per_gcf_dollar_(?:low|high)$/.test(id)) return "x";
  if (/_per_deployment_envelope_dollar_(?:low|high)$/.test(id)) return "x";
  if (/_years$/.test(id)) return "years";
  if (/_year$/.test(id)) return "year";
  if (/(?:_count|sample_count|beneficiaries_target|connections_target|enterprises_target)$/.test(id)) return "#";
  if (/project_cost_per_tco2e$/.test(id)) return "USD/tCO2e";
  return null;
}

function projectNeutralSourceDefinitions(source, semanticCalculations = []) {
  const sourceDefinitions = Object.fromEntries(directSourceIds(source).map(id => {
    const collection = COLLECTION_SOURCE_IDS.has(id);
    const numeric = !collection && numericSource(id);
    return [id, {
      id,
      label: id,
      tool: "GET_DATA",
      valueType: collection ? "dataset" : numeric ? "number" : "text",
      // Project-neutral compilation validates expression topology without
      // pretending every future normalized/enriched bundle has already fixed
      // identical source-unit metadata. Public units are inferred below from
      // stable canonical suffixes and are checked again against each bundle at
      // preflight.
      unit: null
    }];
  }));
  return {
    ...sourceDefinitions,
    ...semanticGlobalDefinitions(semanticCalculations)
  };
}

function familyAssignments(population, templateId) {
  return (population.projects || [])
    .filter(item => item.template_id === templateId)
    .map(item => item.project_id);
}

function familyAllowedNotApplicableIds(templateId) {
  if (templateId === "financing_facility") {
    return [
      "dt.project.additional_capital_mobilized_min_usd",
      "dt.project.additional_capital_mobilized_max_usd",
      "dt.project.facility_reach"
    ];
  }
  if (templateId === "land_use_nature") {
    return [
      "dt.project.intervention_area_target_ha",
      "dt.project.forest_protection_area_target_ha",
      "dt.project.restoration_area_target_ha",
      "dt.project.plantation_afforestation_area_target_ha",
      "dt.project.sustainable_management_area_target_ha",
      "dt.project.baseline_deforestation_rate_pct_per_year",
      "dt.project.project_deforestation_rate_pct_per_year",
      "dt.project.forest_carbon_stock_tco2e_per_ha",
      "dt.project.restoration_sequestration_tco2e_per_ha_year",
      "dt.project.plantation_afforestation_sequestration_tco2e_per_ha_year",
      "dt.project.sustainable_management_mitigation_tco2e_per_ha_year",
      "dt.project.jurisdictional_accounting_area_ha",
      "dt.project.jurisdictional_reference_emissions_tco2e_per_year",
      "dt.project.jurisdictional_program_emissions_tco2e_per_year",
      "dt.project.jurisdictional_accounting_qualification",
      "dt.project.implementation_effectiveness_pct",
      "dt.project.leakage_deduction_pct",
      "dt.project.permanence_buffer_pct"
    ];
  }
  return [];
}

function familyConditionalGroups(templateId) {
  if (templateId === "asset_delivery") {
    return [{
      id: "reported_ghg_comparison",
      gate_id: "dt.project.reported_ghg_comparison_status",
      active_value: "comparable",
      calculation_ids: [
        "calc.modelled_vs_reported_ghg_ratio",
        "calc.reported_minus_modelled_ghg_tco2e"
      ]
    }];
  }
  if (templateId === "financing_facility") {
    return [{
      id: "additional_capital_mobilisation",
      gate_id: "dt.project.mobilization_applicability",
      active_value: "applicable",
      direct_evidence_ids: [
        "dt.project.additional_capital_mobilized_min_usd",
        "dt.project.additional_capital_mobilized_max_usd"
      ],
      calculation_id_prefixes: [
        "calc.additional_capital_",
        "calc.total_enabled_capital_",
        "calc.enabled_capital_per_portfolio_unit_"
      ]
    }];
  }
  return [
    {
      id: "land_accounting_mode",
      gate_id: "dt.project.land_accounting_mode",
      active_values: ["activity_area", "jurisdictional", "investment_portfolio"],
      note: "Area reconciliation is not applicable to a purely jurisdictional boundary. Carbon pathways are selected by the separately declared pathway gates."
    },
    {
      id: "land_accounting_adjustments",
      gate_ids: [
        "dt.project.implementation_effectiveness_adjustment_applicability",
        "dt.project.leakage_adjustment_applicability",
        "dt.project.permanence_buffer_adjustment_applicability"
      ],
      active_value: "apply",
      already_embedded_value: "already_embedded",
      optional_direct_evidence_ids: [
        "dt.project.implementation_effectiveness_pct",
        "dt.project.leakage_deduction_pct",
        "dt.project.permanence_buffer_pct"
      ],
      note: "When an adjustment is already embedded in a jurisdictional reference-minus-program value, its factor remains N/A and the calculation carries the value forward without a second deduction."
    },
    {
      id: "reported_ghg_comparison",
      gate_id: "dt.project.reported_ghg_comparison_status",
      active_value: "comparable",
      calculation_ids: [
        "calc.modelled_vs_reported_ghg_ratio",
        "calc.reported_minus_modelled_ghg_tco2e"
      ]
    }
  ];
}

function familyComponentCounts(compiled, visibleSectionIds) {
  const visible = compiled.artifacts.filter(item => visibleSectionIds.includes(item.sectionId));
  const bySection = Object.fromEntries(visibleSectionIds.map(sectionId => {
    const artifacts = visible.filter(item => item.sectionId === sectionId);
    return [sectionId, {
      tables: artifacts.filter(item => item.type === "table").length,
      llm: artifacts.filter(item => item.type === "llm").length
    }];
  }));
  return {
    visible_sections: visibleSectionIds.length,
    tables: visible.filter(item => item.type === "table").length,
    llm: visible.filter(item => item.type === "llm").length,
    by_section: bySection
  };
}

function calculationUsage(compiled, semanticCalculations) {
  const canonical = canonicalMappings(compiled);
  const dependencies = new Map();
  for (const node of compiled.generatedNodes.filter(item => item.tool === "DOC_EXPRESSION")) {
    dependencies.set(
      `calc.${node.name}`,
      (node.deps || []).map(canonical.canonicalId)
    );
  }
  for (const item of semanticCalculations) {
    dependencies.set(item.id, Object.values(item.input_ids || {}).map(String));
  }

  const visibleArtifacts = compiled.artifacts.filter(item =>
    ["table", "llm"].includes(item.type)
  );
  const visibleRoots = [...new Set(visibleArtifacts.flatMap(artifact => [
    ...(artifact.deps || []),
    ...(artifact.dataIds || []),
    ...(artifact.instructionDependencyIds || [])
  ]).map(canonical.canonicalId))].sort();
  const consumed = new Set();
  const visit = id => {
    if (!dependencies.has(id) || consumed.has(id)) return;
    consumed.add(id);
    for (const dependency of dependencies.get(id) || []) visit(dependency);
  };
  for (const id of visibleRoots) visit(id);
  const calculationIds = [...dependencies.keys()].sort();
  const unused = calculationIds.filter(id => !consumed.has(id));
  return {
    calculation_count: calculationIds.length,
    consumed_calculation_count: consumed.size,
    visible_root_ids: visibleRoots,
    consumed_calculation_ids: [...consumed].sort(),
    unused_calculation_ids: unused
  };
}

function compileFamilyContract(templateId, specification, population) {
  verifyCompilerPin();
  const templatePath = path.join(PACKAGE_ROOT, specification.template);
  const source = fs.readFileSync(templatePath, "utf8");
  const semanticCalculations = semanticCalculationsForSource(source);
  const scopeId = `react_report_v2_${templateId}`;
  const compiled = documentEngine.compileDocument(source, {
    scopeId,
    globalNodes: projectNeutralSourceDefinitions(source, semanticCalculations)
  });
  const errors = compiled.diagnostics.filter(item => item.severity === "error");
  if (errors.length) throw new Error(`${templateId} TraceMark compilation failed: ${JSON.stringify(errors)}`);

  const visibleSections = (compiled.structure.sections || []).filter(section => section.id !== "front_matter");
  const visibleSectionIds = visibleSections.map(section => section.id);
  const expectedSectionIds = [
    ...LEADING_COMMON_SECTION_IDS,
    ...specification.specialistSections,
    ...TRAILING_COMMON_SECTION_IDS
  ];
  if (JSON.stringify(visibleSectionIds) !== JSON.stringify(expectedSectionIds)) {
    throw new Error(`${templateId} section contract mismatch: received ${visibleSectionIds.join(", ")}`);
  }

  const forbiddenGenerationSyntax = [...source.matchAll(/:::(text|prose|distill|conclusion)\b/gi)]
    .map(match => match[1].toLowerCase());
  if (forbiddenGenerationSyntax.length) {
    throw new Error(`${templateId} uses forbidden generation recipes: ${forbiddenGenerationSyntax.join(", ")}`);
  }
  if (/\bFP\d{3}\b/i.test(source)) {
    throw new Error(`${templateId} must not contain a project-specific FP identifier`);
  }
  const sourceIds = [...new Set([
    ...directSourceIds(source),
    ...semanticSourceIds(semanticCalculations)
  ])].sort();
  const invalidReferenceIds = sourceIds.filter(id => id.startsWith("reference."));
  if (invalidReferenceIds.length) {
    throw new Error(`${templateId} uses out-of-scope cross-project reference IDs: ${invalidReferenceIds.join(", ")}`);
  }

  const graph = addSemanticGraph(buildGraph(compiled), semanticCalculations);
  const usage = calculationUsage(compiled, semanticCalculations);
  if (usage.unused_calculation_ids.length) {
    throw new Error(
      `${templateId} contains calculations that are not consumed by a visible component: `
      + usage.unused_calculation_ids.join(", ")
    );
  }

  const components = familyComponentCounts(compiled, visibleSectionIds);
  const invalidComponents = Object.entries(components.by_section)
    .filter(([, counts]) => counts.tables < 1 || counts.llm !== 1)
    .map(([sectionId]) => sectionId);
  if (invalidComponents.length) {
    throw new Error(`${templateId} sections must each contain at least one deterministic table and exactly one llm: ${invalidComponents.join(", ")}`);
  }
  const generationRecipes = [...new Set(compiled.artifacts
    .filter(item => item.type === "llm")
    .map(item => item.recipe))].sort();
  if (generationRecipes.length !== 1 || generationRecipes[0] !== "llm") {
    throw new Error(`${templateId} must use only neutral llm generation`);
  }

  const invalidOutputContracts = compiled.artifacts
    .filter(item => item.type === "llm")
    .filter(item => !OUTPUT_CONTRACT_IDS.has(item.outputContractId))
    .map(item => `${item.id}:${item.outputContractId || "missing"}`);
  if (invalidOutputContracts.length) {
    throw new Error(`${templateId} has invalid llm output contracts: ${invalidOutputContracts.join(", ")}`);
  }

  const assignments = familyAssignments(population, templateId);
  if (!assignments.length) throw new Error(`${templateId} has no projects in the frozen population`);
  const canonical = canonicalMappings(compiled);
  const namespaceCounts = sourceIds.reduce((counts, id) => {
    const namespace = id.startsWith("reference.") ? "reference" : id.startsWith("req.") ? "requirement" : "project";
    counts[namespace] += 1;
    return counts;
  }, { project: 0, reference: 0, requirement: 0 });

  return {
    schema_version: "react_report.compiled_contract/v2",
    benchmark_version: "2.2.0-bankability-executable-gold",
    contract_id: templateId,
    template_id: templateId,
    template_label: specification.label,
    project_neutral: true,
    project_code: null,
    scope_id: scopeId,
    template_path: specification.template,
    template_sha256: sha256(templatePath),
    compiler_pin: compilerPin,
    generation_contract: {
      component_type: "llm",
      source_directive: ":::llm",
      prompt_field: "instructions",
      recipes: generationRecipes,
      llm_components_per_section: 1,
      agent_tools_added: []
    },
    template_family: {
      shared_core_section_ids: COMMON_SECTION_IDS,
      specialist_section_ids: specification.specialistSections,
      section_order: expectedSectionIds,
      shared_core_section_count: COMMON_SECTION_IDS.length,
      specialist_section_count: specification.specialistSections.length,
      visible_section_count: visibleSectionIds.length
    },
    population_binding: {
      manifest_path: populationRelativePath,
      manifest_sha256: sha256(populationPath),
      assigned_project_ids: assignments,
      assigned_project_count: assignments.length,
      template_is_experimental_condition: false
    },
    applicability_contract: {
      ...specification.applicability,
      common_scope_gates: {
        funding_reconciliation: {
          gate_id: "dt.project.funding_scope_comparability",
          active_value: "comparable"
        },
        whole_project_cost_intensity: {
          gate_id: "dt.project.total_cost_scope",
          active_value: "whole_project"
        }
      },
      conditional_groups: familyConditionalGroups(templateId),
      allowed_not_applicable_ids: familyAllowedNotApplicableIds(templateId)
    },
    source_contract: {
      required_source_ids: sourceIds,
      required_source_count: sourceIds.length,
      namespace_counts: namespaceCounts,
      project_specific_reference_ids: []
    },
    component_counts: components,
    diagnostics: compiled.diagnostics,
    structure: compiled.structure,
    dependency_ids: compiled.dependencyIds,
    semantic_calculation_ids: semanticCalculations.map(item => item.id),
    graph,
    calculation_usage: usage,
    execution_validation: {
      status: "compile_graph_validated_population_preflight_separate",
      compile_graph_validated: true,
      representative_probe_project_id: null,
      population_preflight_required_before_provider_calls: true,
      population_preflight_command: "python3 -m benchmarks.react_report_building preflight-v2",
      qualification: "Compilation does not fabricate evidence or invoke providers; the committed population evidence is validated by the separate zero-provider preflight."
    },
    generated_nodes: [...compiled.generatedNodes.map(node => ({
      id: node.id,
      canonical_id: node.tool === "DOC_EXPRESSION" ? `calc.${node.name}` : node.id,
      name: node.name,
      tool: node.tool,
      value_type: node.valueType || null,
      // TraceMark's generic arithmetic inference treats some domain ratios as
      // unitless. Stable canonical-name rules carry the report's compound units
      // and therefore take precedence when one is defined.
      unit: inferredUnit(node.name) || node.unit || null,
      label: node.label || node.name,
      expression: node.expression || null,
      expression_ast: node.tool === "DOC_EXPRESSION" ? canonical.canonicalExpressionAst(node) : null,
      input_ids: node.tool === "DOC_EXPRESSION" ? canonical.inputIds(node) : {},
      dependencies: node.deps || [],
      canonical_dependencies: (node.deps || []).map(canonical.canonicalId),
      calculation_depth: node.tool === "DOC_EXPRESSION" ? graph.calculation_depths[node.id] : null,
      section_id: node.sectionId || null,
      subsection_id: node.subsectionId || null
    })), ...semanticGeneratedNodes(semanticCalculations)],
    artifacts: compiled.artifacts.map(artifact => ({
      id: artifact.id,
      type: artifact.type,
      recipe: artifact.recipe || null,
      title: artifact.title || null,
      prompt: artifact.type === "llm" ? artifact.prompt : null,
      estimated_max_words: artifact.type === "llm" ? artifact.estimatedMaxWords || 0 : null,
      profile: artifact.type === "llm" ? artifact.profile || null : null,
      output_contract_id: artifact.type === "llm" ? artifact.outputContractId || null : null,
      output_contract_version: artifact.type === "llm" ? artifact.outputContractVersion || null : null,
      dependencies: artifact.deps || [],
      canonical_dependencies: (artifact.deps || []).map(canonical.canonicalId),
      data_ids: (artifact.dataIds || []).map(canonical.canonicalId),
      instruction_dependency_ids: (artifact.instructionDependencyIds || []).map(canonical.canonicalId),
      table_type: artifact.type === "table" ? artifact.tableType : null,
      headers: artifact.type === "table" ? artifact.headers || [] : [],
      start: artifact.start,
      section_id: artifact.sectionId || null,
      subsection_id: artifact.subsectionId || null
    }))
  };
}

function compiledFamilyContracts() {
  const population = JSON.parse(fs.readFileSync(populationPath, "utf8"));
  const contracts = Object.fromEntries(Object.entries(FAMILY_TEMPLATES)
    .map(([templateId, specification]) => [
      templateId,
      compileFamilyContract(templateId, specification, population)
    ]));
  const assigned = Object.values(contracts)
    .flatMap(contract => contract.population_binding.assigned_project_ids);
  const expected = (population.projects || []).map(item => item.project_id);
  if (assigned.length !== expected.length || new Set(assigned).size !== expected.length) {
    throw new Error("Three-specialisation bindings must cover every frozen project exactly once");
  }
  if (expected.some(projectId => !assigned.includes(projectId))) {
    throw new Error("Three-specialisation bindings omit one or more frozen projects");
  }
  return contracts;
}

function familyOutputPath(templateId) {
  return path.join(familyOutputRoot, `${templateId}.compiled.json`);
}

function main() {
  const mode = process.argv[2] || "--stdout";
  const families = compiledFamilyContracts();
  const serializedFamilies = Object.fromEntries(Object.entries(families)
    .map(([templateId, payload]) => [templateId, `${JSON.stringify(payload, null, 2)}\n`]));
  // The default file remains as a compatibility alias for callers that do not
  // yet select a family explicitly. FP083 belongs to the financing-facility
  // family, so the alias is the exact family contract rather than a fourth,
  // project-specific synthetic template.
  const serialized = serializedFamilies.financing_facility;
  if (mode === "--write") {
    fs.writeFileSync(outputPath, serialized);
    fs.mkdirSync(familyOutputRoot, { recursive: true });
    for (const [templateId, payload] of Object.entries(serializedFamilies)) {
      fs.writeFileSync(familyOutputPath(templateId), payload);
    }
    process.stdout.write([
      path.relative(process.cwd(), outputPath),
      ...Object.keys(serializedFamilies).map(templateId => path.relative(process.cwd(), familyOutputPath(templateId)))
    ].join("\n") + "\n");
    return;
  }
  if (mode === "--check") {
    if (!fs.existsSync(outputPath) || fs.readFileSync(outputPath, "utf8") !== serialized) {
      process.stderr.write("Committed v2 compiled contract is stale; run compile_contract.js --write\n");
      process.exitCode = 1;
    }
    for (const [templateId, payload] of Object.entries(serializedFamilies)) {
      const target = familyOutputPath(templateId);
      if (!fs.existsSync(target) || fs.readFileSync(target, "utf8") !== payload) {
        process.stderr.write(`Committed ${templateId} compiled contract is stale; run compile_contract.js --write\n`);
        process.exitCode = 1;
      }
    }
    return;
  }
  if (mode === "--stdout-family") {
    const templateId = process.argv[3];
    if (!serializedFamilies[templateId]) throw new Error(`Unknown template '${templateId}'`);
    process.stdout.write(serializedFamilies[templateId]);
    return;
  }
  if (mode === "--stdout-families") {
    process.stdout.write(`${JSON.stringify(families, null, 2)}\n`);
    return;
  }
  if (mode !== "--stdout") throw new Error(`Unknown mode '${mode}'`);
  process.stdout.write(serialized);
}

main();
