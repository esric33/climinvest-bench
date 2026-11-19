(function attachReportIr(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.CliminvestReportIR = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function createReportIrApi() {
  "use strict";

  const IR_VERSION = 1;
  const OUTPUT_TYPES = new Set([
    "number",
    "text",
    "quantity",
    "dataset",
    "rank",
    "schedule",
    "markdown_inline",
    "markdown_block",
    "artifact",
    "section",
    "report"
  ]);

  function sourceRange(value = {}) {
    const start = Math.max(0, Number(value.start || 0));
    const end = Math.max(start, Number(value.end ?? start));
    return { start, end };
  }

  function nodeDefinition(value) {
    if (!value?.id) throw new Error("IR nodes require an id");
    const outputType = String(value.outputType || value.valueType || "text");
    if (!OUTPUT_TYPES.has(outputType)) throw new Error(`Unsupported IR output type '${outputType}'`);
    return {
      id: String(value.id),
      symbol: String(value.symbol || value.name || value.id),
      kind: String(value.kind || "computed"),
      toolId: String(value.toolId || value.tool || ""),
      outputType,
      dependencies: [...new Set(value.dependencies || value.deps || [])].map(String),
      config: value.config && typeof value.config === "object" ? { ...value.config } : {},
      sourceRange: sourceRange(value.sourceRange || value),
      sectionId: String(value.sectionId || "front_matter"),
      subsectionId: String(value.subsectionId || "front_matter__intro")
    };
  }

  function placement(value) {
    if (!value?.id) throw new Error("IR placements require an id");
    return {
      id: String(value.id),
      nodeId: value.nodeId ? String(value.nodeId) : "",
      kind: String(value.kind || "markdown"),
      renderMode: String(value.renderMode || "block"),
      config: value.config && typeof value.config === "object" ? { ...value.config } : {},
      dependencies: [...new Set(value.dependencies || value.deps || [])].map(String),
      sourceRange: sourceRange(value.sourceRange || value),
      sectionId: String(value.sectionId || "front_matter"),
      subsectionId: String(value.subsectionId || "front_matter__intro")
    };
  }

  function sectionExport(value) {
    if (!value?.id) throw new Error("IR section exports require an id");
    return {
      id: String(value.id),
      name: String(value.name || value.id),
      nodeIds: [...new Set(value.nodeIds || value.dependencies || [])].map(String),
      sourceRange: sourceRange(value.sourceRange || value),
      sectionId: String(value.sectionId || "front_matter"),
      subsectionId: String(value.subsectionId || "front_matter__intro")
    };
  }

  function createReportIR(value = {}) {
    const diagnostics = [...(value.diagnostics || [])];
    const nodes = (value.nodes || []).map(nodeDefinition);
    const placements = (value.placements || []).map(placement);
    const sectionExports = (value.exports || []).map(sectionExport);
    const nodeIds = new Set();
    const placementIds = new Set();
    const exportIds = new Set();

    for (const node of nodes) {
      if (nodeIds.has(node.id)) diagnostics.push({ severity: "error", code: "duplicate-ir-node", message: `Duplicate IR node '${node.id}'`, ...node.sourceRange });
      nodeIds.add(node.id);
    }
    for (const item of placements) {
      if (placementIds.has(item.id)) diagnostics.push({ severity: "error", code: "duplicate-ir-placement", message: `Duplicate IR placement '${item.id}'`, ...item.sourceRange });
      placementIds.add(item.id);
      if (item.nodeId && !nodeIds.has(item.nodeId) && !(value.externalNodeIds || []).includes(item.nodeId)) {
        diagnostics.push({ severity: "error", code: "unknown-placement-node", message: `Placement references unknown node '${item.nodeId}'`, ...item.sourceRange });
      }
    }
    for (const item of sectionExports) {
      if (exportIds.has(item.id)) diagnostics.push({ severity: "error", code: "duplicate-ir-export", message: `Duplicate IR section export '${item.id}'`, ...item.sourceRange });
      exportIds.add(item.id);
      for (const nodeId of item.nodeIds) {
        if (!nodeIds.has(nodeId)) diagnostics.push({ severity: "error", code: "unknown-export-node", message: `Section export references unknown node '${nodeId}'`, ...item.sourceRange });
      }
    }

    return {
      version: IR_VERSION,
      source: String(value.source || ""),
      sourceHash: String(value.sourceHash || ""),
      structure: value.structure && typeof value.structure === "object" ? value.structure : { headings: [], sections: [] },
      nodes,
      placements,
      exports: sectionExports,
      externalNodeIds: [...new Set(value.externalNodeIds || [])].map(String),
      diagnostics
    };
  }

  return {
    IR_VERSION,
    OUTPUT_TYPES,
    sourceRange,
    nodeDefinition,
    placement,
    sectionExport,
    createReportIR
  };
});
