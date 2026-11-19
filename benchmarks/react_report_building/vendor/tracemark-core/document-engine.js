(function attachDocumentEngine(root, factory) {
  const reportIr = typeof module === "object" && module.exports
    ? require("./report-ir.js")
    : root?.CliminvestReportIR;
  const api = factory(reportIr);
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.CliminvestDocumentEngine = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function createDocumentEngine(reportIr) {
  "use strict";

  const IDENTIFIER_PATTERN = /^[A-Za-z_][A-Za-z0-9_.:-]*$/;
  const LOCAL_NAME_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;
  const GENERATED_OUTPUT_CONTRACT_VERSION = 3;
  const GENERATED_OUTPUT_RULES_VERSION = 4;
  const GENERATED_RECIPE_CONFIG = Object.freeze({
    text: {
      tool: "GENERATE_MARKDOWN",
      profile: "short_text",
      outputType: "markdown_inline",
      outputContractId: "climinvest.generate_markdown.short_text"
    },
    prose: {
      tool: "GENERATE_MARKDOWN",
      profile: "prose",
      outputType: "markdown_block",
      outputContractId: "climinvest.generate_markdown.prose"
    },
    "rules-text": {
      tool: "GENERATE_MARKDOWN",
      profile: "rules_text",
      outputType: "markdown_block",
      outputContractId: "rules.generate_markdown.text"
    },
    caption: {
      tool: "GENERATE_MARKDOWN",
      profile: "rules_caption",
      outputType: "markdown_inline",
      outputContractId: "rules.generate_markdown.caption",
      defaultEstimatedMaxWords: 55
    },
    llm: {
      tool: "GENERATE_MARKDOWN",
      profile: "neutral",
      outputType: "markdown_block",
      outputContractId: "climinvest.generate_markdown.neutral"
    },
    distill: {
      tool: "SUMMARISE_EVIDENCE",
      profile: "evidence_summary",
      outputType: "markdown_block",
      outputContractId: "climinvest.summarise_evidence",
      defaultEstimatedMaxWords: 120
    },
    conclusion: {
      tool: "GENERATE_CONCLUSION",
      profile: "conclusion",
      outputType: "markdown_block",
      outputContractId: "climinvest.generate_conclusion"
    }
  });
  const GENERATED_TOOL_IDS = new Set(Object.values(GENERATED_RECIPE_CONFIG).map(config => config.tool));
  const RULE_DIRECTIVE_KINDS = new Set([
    "warning",
    "entity-summary",
    "collection",
    "review-queue",
    "conflict-table",
    "source-register",
    "dataset",
    "validation-result",
    "mission-card",
    "asset-gallery",
    "operation-result",
    "procedure",
    "unit-card",
    "rule-usage-index",
    "supporting-image"
  ]);

  function generatedRecipeConfig(kind) {
    return GENERATED_RECIPE_CONFIG[String(kind || "").toLowerCase()] || null;
  }

  function isGeneratedTool(tool) {
    return GENERATED_TOOL_IDS.has(String(tool || ""));
  }

  function hashText(value) {
    let hash = 2166136261;
    const text = String(value || "");
    for (let index = 0; index < text.length; index += 1) {
      hash ^= text.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(36);
  }

  function slug(value) {
    return String(value || "item")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "") || "item";
  }

  function markdownTableCells(rawLine) {
    let line = String(rawLine || "").trim();
    if (!line.includes("|")) return null;
    if (line.startsWith("|")) line = line.slice(1);
    if (line.endsWith("|")) line = line.slice(0, -1);
    const cells = [];
    let current = "";
    let inCode = false;
    for (let index = 0; index < line.length; index += 1) {
      const character = line[index];
      if (character === "\\" && line[index + 1] === "|") {
        current += "|";
        index += 1;
        continue;
      }
      if (character === "`") inCode = !inCode;
      if (character === "|" && !inCode) {
        cells.push(current.trim());
        current = "";
        continue;
      }
      current += character;
    }
    cells.push(current.trim());
    return cells.length > 1 ? cells : null;
  }

  function markdownTableAlignment(marker) {
    const value = String(marker || "").trim();
    if (!/^:?-{3,}:?$/.test(value)) return "";
    if (value.startsWith(":") && value.endsWith(":")) return "center";
    if (value.endsWith(":")) return "right";
    return "left";
  }

  function parseMarkdownTableAt(lines, startIndex) {
    const headers = markdownTableCells(lines?.[startIndex]);
    const markers = markdownTableCells(lines?.[startIndex + 1]);
    if (!headers || !markers || headers.length !== markers.length) return null;
    const alignments = markers.map(markdownTableAlignment);
    if (alignments.some(alignment => !alignment)) return null;
    const rows = [];
    let endIndex = startIndex + 2;
    while (endIndex < lines.length) {
      const cells = markdownTableCells(lines[endIndex]);
      if (!cells) break;
      rows.push(headers.map((_header, cellIndex) => cells[cellIndex] || ""));
      endIndex += 1;
    }
    return { headers, alignments, rows, endIndex };
  }

  function tokenizeExpression(expression) {
    const tokens = [];
    let cursor = 0;
    const source = String(expression || "");
    while (cursor < source.length) {
      const rest = source.slice(cursor);
      const whitespace = rest.match(/^\s+/);
      if (whitespace) {
        cursor += whitespace[0].length;
        continue;
      }
      const number = rest.match(/^(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?/i);
      if (number) {
        tokens.push({ type: "number", value: Number(number[0]), start: cursor, end: cursor + number[0].length });
        cursor += number[0].length;
        continue;
      }
      const string = rest.match(/^"(?:\\.|[^"\\])*"|^'(?:\\.|[^'\\])*'/);
      if (string) {
        const raw = string[0];
        tokens.push({
          type: "string",
          value: raw.slice(1, -1).replace(/\\([\\"'])/g, "$1"),
          start: cursor,
          end: cursor + raw.length
        });
        cursor += raw.length;
        continue;
      }
      const identifier = rest.match(/^[A-Za-z_][A-Za-z0-9_.:]*/);
      if (identifier) {
        const value = identifier[0];
        const type = ["true", "false", "null"].includes(value.toLowerCase()) ? "literal" : "identifier";
        tokens.push({ type, value, start: cursor, end: cursor + value.length });
        cursor += value.length;
        continue;
      }
      const doubleOperator = rest.match(/^(<=|>=|==|!=|&&|\|\|)/);
      if (doubleOperator) {
        tokens.push({ type: "operator", value: doubleOperator[0], start: cursor, end: cursor + 2 });
        cursor += 2;
        continue;
      }
      const character = rest[0];
      if ("+-*/%^<>!".includes(character)) tokens.push({ type: "operator", value: character, start: cursor, end: cursor + 1 });
      else if ("()[]".includes(character)) tokens.push({ type: "punctuation", value: character, start: cursor, end: cursor + 1 });
      else if (character === ",") tokens.push({ type: "comma", value: character, start: cursor, end: cursor + 1 });
      else throw new Error(`Unsupported character '${character}' at column ${cursor + 1}`);
      cursor += 1;
    }
    tokens.push({ type: "eof", value: "", start: cursor, end: cursor });
    return tokens;
  }

  function parseExpression(expression) {
    const tokens = tokenizeExpression(expression);
    let cursor = 0;
    const peek = () => tokens[cursor];
    const take = (type, value) => {
      const token = peek();
      if (!token || token.type !== type || (value !== undefined && token.value !== value)) {
        throw new Error(`Expected ${value !== undefined ? `'${value}'` : type}`);
      }
      cursor += 1;
      return token;
    };
    const binary = (next, operators) => {
      let node = next();
      while (peek().type === "operator" && operators.includes(peek().value)) {
        const operator = take("operator").value;
        node = { type: "binary", operator, left: node, right: next() };
      }
      return node;
    };
    const parsePrimary = () => {
      const token = peek();
      if (token.type === "number") return { type: "literal", value: take("number").value };
      if (token.type === "string") return { type: "literal", value: take("string").value };
      if (token.type === "literal") {
        const value = take("literal").value.toLowerCase();
        return { type: "literal", value: value === "true" ? true : value === "false" ? false : null };
      }
      if (token.type === "identifier") {
        const name = take("identifier").value;
        if (peek().type === "punctuation" && peek().value === "(") {
          take("punctuation", "(");
          const args = [];
          if (!(peek().type === "punctuation" && peek().value === ")")) {
            args.push(parseOr());
            while (peek().type === "comma") {
              take("comma");
              args.push(parseOr());
            }
          }
          take("punctuation", ")");
          return { type: "call", name, args };
        }
        return { type: "identifier", name };
      }
      if (token.type === "punctuation" && token.value === "(") {
        take("punctuation", "(");
        const node = parseOr();
        take("punctuation", ")");
        return node;
      }
      if (token.type === "punctuation" && token.value === "[") {
        take("punctuation", "[");
        const elements = [];
        if (!(peek().type === "punctuation" && peek().value === "]")) {
          elements.push(parseOr());
          while (peek().type === "comma") {
            take("comma");
            elements.push(parseOr());
          }
        }
        take("punctuation", "]");
        return { type: "array", elements };
      }
      throw new Error(`Expected a value at column ${token.start + 1}`);
    };
    const parseUnary = () => {
      if (peek().type === "operator" && ["+", "-", "!"].includes(peek().value)) {
        return { type: "unary", operator: take("operator").value, argument: parseUnary() };
      }
      return parsePrimary();
    };
    const parsePower = () => {
      let node = parseUnary();
      if (peek().type === "operator" && peek().value === "^") {
        take("operator", "^");
        node = { type: "binary", operator: "^", left: node, right: parsePower() };
      }
      return node;
    };
    const parseProduct = () => binary(parsePower, ["*", "/", "%"]);
    const parseSum = () => binary(parseProduct, ["+", "-"]);
    const parseComparison = () => binary(parseSum, ["<", "<=", ">", ">="]);
    const parseEquality = () => binary(parseComparison, ["==", "!="]);
    const parseAnd = () => binary(parseEquality, ["&&"]);
    function parseOr() { return binary(parseAnd, ["||"]); }
    const ast = parseOr();
    if (peek().type !== "eof") throw new Error(`Unexpected token '${peek().value}' at column ${peek().start + 1}`);
    return ast;
  }

  function flattenNumeric(values) {
    return values.flatMap(value => Array.isArray(value) ? flattenNumeric(value) : [Number(value)]).filter(Number.isFinite);
  }

  function applyFunction(name, args) {
    const key = String(name || "").toLowerCase();
    const numbers = flattenNumeric(args);
    if (key === "sum") return numbers.reduce((total, value) => total + value, 0);
    if (key === "avg" || key === "mean") return numbers.length ? numbers.reduce((total, value) => total + value, 0) / numbers.length : 0;
    if (key === "min") return numbers.length ? Math.min(...numbers) : 0;
    if (key === "max") return numbers.length ? Math.max(...numbers) : 0;
    if (key === "abs" && args.length === 1) return Math.abs(Number(args[0]));
    if (key === "round" && args.length >= 1) {
      const digits = Math.max(0, Number(args[1] || 0));
      const factor = 10 ** digits;
      return Math.round(Number(args[0]) * factor) / factor;
    }
    if (key === "floor" && args.length === 1) return Math.floor(Number(args[0]));
    if (key === "ceil" && args.length === 1) return Math.ceil(Number(args[0]));
    if (key === "pow" && args.length === 2) return Math.pow(Number(args[0]), Number(args[1]));
    if (key === "sqrt" && args.length === 1) return Math.sqrt(Number(args[0]));
    if (key === "log" && args.length === 1) return Math.log(Number(args[0]));
    if (key === "exp" && args.length === 1) return Math.exp(Number(args[0]));
    if (key === "clamp" && args.length === 3) return Math.min(Number(args[2]), Math.max(Number(args[1]), Number(args[0])));
    if (key === "count") return args.flat(Infinity).length;
    if (key === "percentage" && args.length === 2) return Number(args[1]) === 0 ? 0 : Number(args[0]) / Number(args[1]) * 100;
    if (key === "ratio" && args.length === 2) return Number(args[1]) === 0 ? 0 : Number(args[0]) / Number(args[1]);
    if (key === "if" && args.length === 3) return args[0] ? args[1] : args[2];
    if (key === "coalesce") return args.find(value => value !== null && value !== undefined && value !== "") ?? null;
    if (key === "series" || key === "dataset") return args.flat();
    throw new Error(`Unsupported function '${name}'`);
  }

  function evaluateExpression(ast, resolver, metadataResolver = () => ({})) {
    if (!ast) return null;
    if (ast.type === "literal") return ast.value;
    if (ast.type === "identifier") return resolver(ast.name);
    if (ast.type === "array") return ast.elements.map(element => evaluateExpression(element, resolver, metadataResolver));
    if (ast.type === "call") return applyFunction(ast.name, ast.args.map(argument => evaluateExpression(argument, resolver, metadataResolver)));
    if (ast.type === "unary") {
      const value = evaluateExpression(ast.argument, resolver, metadataResolver);
      if (ast.operator === "+") return Number(value);
      if (ast.operator === "-") return -Number(value);
      if (ast.operator === "!") return !value;
    }
    if (ast.type === "binary") {
      const left = evaluateExpression(ast.left, resolver, metadataResolver);
      if (ast.operator === "&&") return left && evaluateExpression(ast.right, resolver, metadataResolver);
      if (ast.operator === "||") return left || evaluateExpression(ast.right, resolver, metadataResolver);
      const right = evaluateExpression(ast.right, resolver, metadataResolver);
      const leftMetadata = inferExpressionMetadata(ast.left, metadataResolver);
      const rightMetadata = inferExpressionMetadata(ast.right, metadataResolver);
      const leftIsPercentage = leftMetadata.unit === "%";
      const rightIsPercentage = rightMetadata.unit === "%";
      if (ast.operator === "+") return Number(left) + Number(right);
      if (ast.operator === "-") return Number(left) - Number(right);
      if (ast.operator === "*") {
        const percentageScalesUnit = (
          (leftIsPercentage && rightIsPercentage)
          || (leftIsPercentage && !isDimensionlessMetadata(rightMetadata))
          || (rightIsPercentage && !isDimensionlessMetadata(leftMetadata))
        );
        if (percentageScalesUnit) return Number(left) * Number(right) / 100;
        return Number(left) * Number(right);
      }
      if (ast.operator === "/") {
        if (Number(right) === 0) throw new Error("Division by zero");
        if (rightIsPercentage && !leftIsPercentage) return Number(left) / (Number(right) / 100);
        return Number(left) / Number(right);
      }
      if (ast.operator === "%") {
        if (Number(right) === 0) throw new Error("Division by zero");
        return Number(left) % Number(right);
      }
      if (ast.operator === "^") return Math.pow(Number(left), Number(right));
      if (ast.operator === "<") return left < right;
      if (ast.operator === "<=") return left <= right;
      if (ast.operator === ">") return left > right;
      if (ast.operator === ">=") return left >= right;
      if (ast.operator === "==") return left === right;
      if (ast.operator === "!=") return left !== right;
    }
    throw new Error(`Unsupported expression node '${ast.type}'`);
  }

  function collectIdentifiers(ast, output = []) {
    if (!ast) return output;
    if (ast.type === "identifier") output.push(ast.name);
    if (ast.type === "unary") collectIdentifiers(ast.argument, output);
    if (ast.type === "binary") {
      collectIdentifiers(ast.left, output);
      collectIdentifiers(ast.right, output);
    }
    if (ast.type === "array") ast.elements.forEach(element => collectIdentifiers(element, output));
    if (ast.type === "call") ast.args.forEach(argument => collectIdentifiers(argument, output));
    return [...new Set(output)];
  }

  function rewriteIdentifiers(ast, resolver) {
    if (!ast || typeof ast !== "object") return ast;
    if (ast.type === "identifier") return { ...ast, name: resolver(ast.name) || ast.name };
    if (ast.type === "unary") return { ...ast, argument: rewriteIdentifiers(ast.argument, resolver) };
    if (ast.type === "binary") return { ...ast, left: rewriteIdentifiers(ast.left, resolver), right: rewriteIdentifiers(ast.right, resolver) };
    if (ast.type === "array") return { ...ast, elements: ast.elements.map(element => rewriteIdentifiers(element, resolver)) };
    if (ast.type === "call") return { ...ast, args: ast.args.map(argument => rewriteIdentifiers(argument, resolver)) };
    return { ...ast };
  }

  function normalizeMetadata(metadata = {}) {
    return {
      valueType: metadata.valueType || "number",
      unit: metadata.unit || "",
      scaleFactor: Number(metadata.scaleFactor || 1),
      scaleLabel: metadata.scaleLabel || "",
      digits: Number.isFinite(Number(metadata.digits)) ? Number(metadata.digits) : undefined
    };
  }

  function compatibleMetadata(items) {
    const candidates = items.filter(Boolean).map(normalizeMetadata);
    if (!candidates.length) return normalizeMetadata();
    const first = candidates[0];
    if (candidates.every(item => item.valueType === first.valueType && item.unit === first.unit)) return first;
    if (candidates.some(item => item.valueType === "text")) return normalizeMetadata({ valueType: "text" });
    return normalizeMetadata({ valueType: "number" });
  }

  function isDimensionlessMetadata(metadata) {
    return !metadata.unit || metadata.unit === "x" || metadata.unit === "#";
  }

  function derivedUnitMetadata(operator, left, right) {
    const leftUnit = String(left.unit || "");
    const rightUnit = String(right.unit || "");
    if (operator === "*") {
      const units = new Set([leftUnit, rightUnit]);
      if (units.has("MWh/year") && units.has("tCO2e/MWh")) {
        return normalizeMetadata({ valueType: "number", unit: "tCO2e/year", digits: 0 });
      }
      if (units.has("tCO2e/year") && units.has("years")) {
        return normalizeMetadata({ valueType: "number", unit: "tCO2e", digits: 0 });
      }
    }
    if (operator === "/" && leftUnit === "EUR" && rightUnit === "tCO2e") {
      return normalizeMetadata({ valueType: "number", unit: "EUR/tCO2e", digits: 2 });
    }
    return null;
  }

  function inferExpressionMetadata(ast, resolver) {
    if (!ast) return normalizeMetadata();
    if (ast.type === "literal") {
      return normalizeMetadata({
        valueType: typeof ast.value === "number" ? "number" : typeof ast.value === "boolean" ? "boolean" : "text"
      });
    }
    if (ast.type === "identifier") return normalizeMetadata(resolver(ast.name) || {});
    if (ast.type === "array") return normalizeMetadata({ valueType: "dataset" });
    if (ast.type === "unary") {
      if (ast.operator === "!") return normalizeMetadata({ valueType: "boolean" });
      return inferExpressionMetadata(ast.argument, resolver);
    }
    if (ast.type === "binary") {
      if (["<", "<=", ">", ">=", "==", "!=", "&&", "||"].includes(ast.operator)) {
        return normalizeMetadata({ valueType: "boolean" });
      }
      const left = inferExpressionMetadata(ast.left, resolver);
      const right = inferExpressionMetadata(ast.right, resolver);
      if (["+", "-"].includes(ast.operator)) return compatibleMetadata([left, right]);
      if (ast.operator === "/" && left.unit && left.unit === right.unit) return normalizeMetadata({ valueType: "number", unit: "x" });
      const derived = derivedUnitMetadata(ast.operator, left, right);
      if (derived) return derived;
      if (ast.operator === "*" && left.unit === "%" && right.unit === "%") return left;
      if (ast.operator === "*" && left.unit === "%") return isDimensionlessMetadata(right) ? left : right;
      if (ast.operator === "*" && right.unit === "%") return isDimensionlessMetadata(left) ? right : left;
      if (ast.operator === "/" && right.unit === "%" && left.unit) return left;
      if (["*", "/"].includes(ast.operator)) {
        if (left.unit && isDimensionlessMetadata(right)) return left;
        if (isDimensionlessMetadata(left) && right.unit && ast.operator === "*") return right;
      }
      return normalizeMetadata({ valueType: "number" });
    }
    if (ast.type === "call") {
      const key = String(ast.name || "").toLowerCase();
      const args = ast.args.map(argument => inferExpressionMetadata(argument, resolver));
      if (["series", "dataset"].includes(key)) return normalizeMetadata({ valueType: "dataset" });
      if (key === "percentage") return normalizeMetadata({ valueType: "number", unit: "%", digits: 1 });
      if (key === "ratio") return normalizeMetadata({ valueType: "number", unit: "x", digits: 2 });
      if (key === "count") return normalizeMetadata({ valueType: "number", unit: "#", digits: 0 });
      if (["if", "coalesce"].includes(key)) return compatibleMetadata(key === "if" ? args.slice(1) : args);
      if (["sum", "avg", "mean", "min", "max", "abs", "round", "floor", "ceil", "clamp"].includes(key)) {
        return compatibleMetadata(key === "clamp" ? args.slice(0, 1) : args);
      }
      return normalizeMetadata({ valueType: "number" });
    }
    return normalizeMetadata();
  }

  function expressionUnitMismatches(ast, resolver, output = []) {
    if (!ast) return output;
    if (ast.type === "binary") {
      expressionUnitMismatches(ast.left, resolver, output);
      expressionUnitMismatches(ast.right, resolver, output);
      if (["+", "-"].includes(ast.operator)) {
        const left = inferExpressionMetadata(ast.left, resolver);
        const right = inferExpressionMetadata(ast.right, resolver);
        if (left.unit && right.unit && left.unit !== right.unit) output.push(`${left.unit} ${ast.operator} ${right.unit}`);
      }
    }
    if (ast.type === "unary") expressionUnitMismatches(ast.argument, resolver, output);
    if (ast.type === "array") ast.elements.forEach(element => expressionUnitMismatches(element, resolver, output));
    if (ast.type === "call") {
      ast.args.forEach(argument => expressionUnitMismatches(argument, resolver, output));
      const key = String(ast.name || "").toLowerCase();
      if (["sum", "avg", "mean", "min", "max"].includes(key)) {
        const units = [...new Set(ast.args.map(argument => inferExpressionMetadata(argument, resolver).unit).filter(Boolean))];
        if (units.length > 1) output.push(`${key}(${units.join(", ")})`);
      }
    }
    return [...new Set(output)];
  }

  function braceBalance(text) {
    let balance = 0;
    let quote = "";
    let escaped = false;
    for (const character of String(text || "")) {
      if (escaped) {
        escaped = false;
        continue;
      }
      if (character === "\\") {
        escaped = true;
        continue;
      }
      if (quote) {
        if (character === quote) quote = "";
        continue;
      }
      if (character === "'" || character === '"') {
        quote = character;
        continue;
      }
      if (character === "{") balance += 1;
      if (character === "}") balance -= 1;
    }
    return balance;
  }

  function scanInlineTokens(text, baseOffset = 0) {
    const source = String(text || "");
    const tokens = [];
    let cursor = 0;
    let codeDelimiter = 0;
    while (cursor < source.length) {
      if (source[cursor] === "`" && source[cursor - 1] !== "\\") {
        let width = 1;
        while (source[cursor + width] === "`") width += 1;
        if (!codeDelimiter) codeDelimiter = width;
        else if (codeDelimiter === width) codeDelimiter = 0;
        cursor += width;
        continue;
      }
      if (!codeDelimiter && source[cursor] === "{" && source[cursor - 1] !== "\\") {
        let end = cursor + 1;
        let depth = 1;
        let quote = "";
        while (end < source.length && depth > 0) {
          const character = source[end];
          if (quote) {
            if (character === quote && source[end - 1] !== "\\") quote = "";
          } else if (character === "'" || character === '"') quote = character;
          else if (character === "{") depth += 1;
          else if (character === "}") depth -= 1;
          end += 1;
        }
        if (depth === 0) {
          const raw = source.slice(cursor, end);
          const content = raw.slice(1, -1).trim();
          if (!content.startsWith("#")) {
            tokens.push({
              type: content.startsWith("=") ? "expression" : "reference",
              raw,
              content: content.startsWith("=") ? content.slice(1).trim() : content,
              start: baseOffset + cursor,
              end: baseOffset + end
            });
          }
          cursor = end;
          continue;
        }
      }
      cursor += 1;
    }
    return tokens;
  }

  function parseDirectiveBody(lines) {
    const attributes = {};
    for (let index = 0; index < lines.length; index += 1) {
      const match = lines[index].match(/^\s*([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$/);
      if (!match) continue;
      const key = match[1];
      const initial = match[2];
      if (initial === "|") {
        const content = [];
        index += 1;
        while (index < lines.length && (lines[index].match(/^\s+/) || !lines[index].trim())) {
          content.push(lines[index].replace(/^\s{2}/, ""));
          index += 1;
        }
        index -= 1;
        attributes[key] = content.join("\n").trimEnd();
      } else if (!initial.trim() && /^\s+-\s+/.test(lines[index + 1] || "")) {
        const items = [];
        index += 1;
        while (index < lines.length) {
          const item = lines[index].match(/^\s+-\s+(.+?)\s*$/);
          if (!item) break;
          items.push(item[1].replace(/^['"]|['"]$/g, ""));
          index += 1;
        }
        index -= 1;
        attributes[key] = `[${items.join(", ")}]`;
      } else {
        attributes[key] = initial.trim().replace(/^['"]|['"]$/g, "");
      }
    }
    return attributes;
  }

  function parseDirectiveAttributeRanges(bodyLines, firstLineIndex, documentLines, offsets) {
    const ranges = {};
    for (let index = 0; index < bodyLines.length; index += 1) {
      const match = bodyLines[index].match(/^(\s*)([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$/);
      if (!match) continue;
      const attributeIndex = index;
      const key = match[2];
      let endIndex = index;
      if (match[3] === "|") {
        let cursor = index + 1;
        while (cursor < bodyLines.length && (bodyLines[cursor].match(/^\s+/) || !bodyLines[cursor].trim())) cursor += 1;
        endIndex = Math.max(index, cursor - 1);
        index = cursor - 1;
      }
      const attributeLineIndex = firstLineIndex + attributeIndex;
      const documentEndLine = firstLineIndex + endIndex;
      ranges[key] = {
        key,
        indent: match[1],
        start: offsets[attributeLineIndex] ?? 0,
        end: (offsets[documentEndLine] ?? 0) + String(documentLines[documentEndLine] || "").length
      };
    }
    return ranges;
  }

  function parseDocument(source) {
    const text = String(source || "").replace(/\r\n?/g, "\n");
    const lines = text.split("\n");
    const offsets = [];
    let offset = 0;
    for (const line of lines) {
      offsets.push(offset);
      offset += line.length + 1;
    }
    const nodes = [];
    const diagnostics = [];
    let markdownStart = 0;
    let markdownLines = [];
    let inFence = false;
    const flushMarkdown = endLine => {
      if (!markdownLines.length) return;
      const blockSource = markdownLines.join("\n");
      const start = offsets[markdownStart] || 0;
      nodes.push({ type: "markdown", source: blockSource, start, end: start + blockSource.length, tokens: scanInlineTokens(blockSource, start) });
      markdownLines = [];
      markdownStart = endLine;
    };

    for (let index = 0; index < lines.length; index += 1) {
      const line = lines[index];
      const executableFence = line.match(/^\s*(`{3,}|~{3,})\s*code\s*$/i);
      if (!inFence && executableFence) {
        flushMarkdown(index);
        const startLine = index;
        const marker = executableFence[1];
        let endLine = index + 1;
        while (endLine < lines.length) {
          const closing = lines[endLine].match(/^\s*(`{3,}|~{3,})\s*$/);
          if (closing && closing[1][0] === marker[0] && closing[1].length >= marker.length) break;
          endLine += 1;
        }
        const closed = endLine < lines.length;
        const contentStartLine = startLine + 1;
        const contentLines = lines.slice(contentStartLine, closed ? endLine : lines.length);
        const codeSource = contentLines.join("\n");
        const codeOffset = offsets[contentStartLine] ?? (offsets[startLine] + line.length + 1);
        const nested = parseDocument(codeSource);
        const shiftedNodes = nested.nodes
          .filter(item => item.type !== "markdown")
          .map(item => ({
            ...item,
            start: item.start + codeOffset,
            end: item.end + codeOffset,
            ...(item.attributeRanges ? {
              attributeRanges: Object.fromEntries(Object.entries(item.attributeRanges).map(([key, range]) => [key, {
                ...range,
                start: range.start + codeOffset,
                end: range.end + codeOffset
              }]))
            } : {})
          }));
        const declaredNames = shiftedNodes
          .filter(item => ["definition", "literal_definition", "record_definition", "generated_definition", "invalid_definition"].includes(item.type))
          .map(item => item.name);
        nodes.push({
          type: "executable_code",
          language: "code",
          source: codeSource,
          declaredNames,
          start: offsets[startLine],
          end: closed ? offsets[endLine] + lines[endLine].length : text.length
        });
        nodes.push(...shiftedNodes);
        diagnostics.push(...nested.diagnostics.map(item => ({
          ...item,
          start: item.start + codeOffset,
          end: item.end + codeOffset
        })));
        if (!closed) diagnostics.push({
          severity: "error",
          code: "unclosed-executable-code",
          message: "Unclosed executable code fence",
          start: offsets[startLine],
          end: text.length
        });
        index = closed ? endLine : lines.length;
        markdownStart = index + 1;
        continue;
      }
      if (/^\s*```/.test(line)) {
        if (!markdownLines.length) markdownStart = index;
        markdownLines.push(line);
        inFence = !inFence;
        continue;
      }
      if (inFence) {
        if (!markdownLines.length) markdownStart = index;
        markdownLines.push(line);
        continue;
      }
      const literalDefinition = line.match(/^(\s*)([A-Za-z_][A-Za-z0-9_]*)\s*::=\s*\|\s*$/);
      if (literalDefinition) {
        flushMarkdown(index);
        const startLine = index;
        const body = [];
        while (index + 1 < lines.length) {
          const candidate = lines[index + 1];
          const indentation = candidate.match(/^\s*/)?.[0].length || 0;
          if (candidate.trim() && indentation <= literalDefinition[1].length) break;
          index += 1;
          body.push(candidate);
        }
        const value = dedentLiteralLines(body, literalDefinition[1].length);
        if (!value.trim()) diagnostics.push({ severity: "error", code: "empty-literal-definition", message: `Literal definition '${literalDefinition[2]}' requires indented text`, start: offsets[startLine], end: offsets[index] + lines[index].length });
        nodes.push({
          type: "literal_definition",
          name: literalDefinition[2],
          value,
          start: offsets[startLine],
          end: offsets[index] + lines[index].length
        });
        markdownStart = index + 1;
        continue;
      }
      const recordDefinition = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*::=\s*(record\s*\{.*)$/i);
      if (recordDefinition) {
        flushMarkdown(index);
        const startLine = index;
        const rhsLines = [recordDefinition[2]];
        let balance = braceBalance(recordDefinition[2]);
        while (balance > 0 && index + 1 < lines.length) {
          index += 1;
          rhsLines.push(lines[index]);
          balance += braceBalance(lines[index]);
        }
        const rhs = rhsLines.join("\n").trim();
        if (balance !== 0 || !rhs.endsWith("}")) diagnostics.push({ severity: "error", code: "unclosed-record-definition", message: `Unclosed record definition '${recordDefinition[1]}'`, start: offsets[startLine], end: offsets[index] + lines[index].length });
        nodes.push({ type: "record_definition", name: recordDefinition[1], rhs, start: offsets[startLine], end: offsets[index] + lines[index].length });
        markdownStart = index + 1;
        continue;
      }
      const generatedDefinition = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*::=\s*:::(llm|prose|text|rules-text|caption|distill|conclusion)\b(?:\s*\{#([^}]+)\})?\s*$/i);
      if (generatedDefinition) {
        flushMarkdown(index);
        const startLine = index;
        const body = [];
        index += 1;
        while (index < lines.length && !/^\s*:::\s*$/.test(lines[index])) {
          body.push(lines[index]);
          index += 1;
        }
        if (index >= lines.length) diagnostics.push({ severity: "error", code: "unclosed-generated-definition", message: `Unclosed ${generatedDefinition[2]} definition '${generatedDefinition[1]}'`, start: offsets[startLine], end: text.length });
        nodes.push({
          type: "generated_definition",
          name: generatedDefinition[1],
          kind: generatedDefinition[2].toLowerCase(),
          id: generatedDefinition[3] || "",
          attributes: parseDirectiveBody(body),
          attributeRanges: parseDirectiveAttributeRanges(body, startLine + 1, lines, offsets),
          start: offsets[startLine],
          end: index < lines.length ? offsets[index] + lines[index].length : text.length
        });
        markdownStart = index + 1;
        continue;
      }
      const directive = line.match(/^\s*:::(artifact|table|chart|text|prose|rules-text|caption|distill|conclusion|llm|include|pagebreak|export|warning|entity-summary|collection|review-queue|conflict-table|source-register|dataset|validation-result|mission-card|asset-gallery|operation-result|procedure|unit-card|rule-usage-index|supporting-image)\b(?:\s*\{#([^}]+)\})?\s*$/i);
      if (directive) {
        flushMarkdown(index);
        const startLine = index;
        const body = [];
        index += 1;
        while (index < lines.length && !/^\s*:::\s*$/.test(lines[index])) {
          body.push(lines[index]);
          index += 1;
        }
        if (index >= lines.length) diagnostics.push({ severity: "error", code: "unclosed-directive", message: `Unclosed ${directive[1]} directive`, start: offsets[startLine], end: text.length });
        const attributes = parseDirectiveBody(body);
        nodes.push({
          type: "directive",
          kind: directive[1].toLowerCase(),
          id: directive[2] || attributes.id || "",
          attributes,
          attributeRanges: parseDirectiveAttributeRanges(body, startLine + 1, lines, offsets),
          start: offsets[startLine],
          end: index < lines.length ? offsets[index] + lines[index].length : text.length
        });
        markdownStart = index + 1;
        continue;
      }
      const definition = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*::=\s*(\{.*)$/);
      if (definition) {
        flushMarkdown(index);
        const startLine = index;
        const rhsLines = [definition[2]];
        let balance = braceBalance(definition[2]);
        while (balance > 0 && index + 1 < lines.length) {
          index += 1;
          rhsLines.push(lines[index]);
          balance += braceBalance(lines[index]);
        }
        const rhs = rhsLines.join("\n").trim();
        if (balance !== 0 || !rhs.endsWith("}")) diagnostics.push({ severity: "error", code: "unclosed-definition", message: `Unclosed definition '${definition[1]}'`, start: offsets[startLine], end: offsets[index] + lines[index].length });
        nodes.push({ type: "definition", name: definition[1], rhs, start: offsets[startLine], end: offsets[index] + lines[index].length });
        markdownStart = index + 1;
        continue;
      }
      const missingGeneratedOperator = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s+(:::(?:llm|prose|text|rules-text|caption|distill|conclusion)\b.*)$/i);
      const malformedDeclaration = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s+(::=?|::\|)\s*(.*)$/);
      if (missingGeneratedOperator || malformedDeclaration) {
        flushMarkdown(index);
        const startLine = index;
        const name = (missingGeneratedOperator || malformedDeclaration)[1];
        const operator = missingGeneratedOperator ? "" : malformedDeclaration[2];
        const rhs = (missingGeneratedOperator ? missingGeneratedOperator[2] : malformedDeclaration[3]).trim();
        const generatedKind = rhs.match(/^:::(llm|prose|text|rules-text|caption|distill|conclusion)\b/i)?.[1]?.toLowerCase() || "";
        if (generatedKind) {
          index += 1;
          while (index < lines.length && !/^\s*:::\s*$/.test(lines[index])) index += 1;
        }
        const end = index < lines.length ? offsets[index] + lines[index].length : text.length;
        const message = generatedKind && operator !== "::="
          ? `Generated definition '${name}' requires '::=' before :::${generatedKind}`
          : `Malformed declaration '${name}'. Expected '${name} ::= { ... }', '${name} ::= |', or '${name} ::= :::llm'.`;
        diagnostics.push({
          severity: "error",
          code: "malformed-declaration",
          message,
          start: offsets[startLine],
          end
        });
        nodes.push({
          type: "invalid_definition",
          name,
          kind: generatedKind,
          source: text.slice(offsets[startLine], end),
          start: offsets[startLine],
          end
        });
        markdownStart = index + 1;
        continue;
      }
      const placementReference = line.match(/^\s*\{([A-Za-z_][A-Za-z0-9_.:-]*)\}\s*$/);
      if (placementReference) {
        flushMarkdown(index);
        nodes.push({
          type: "placement_reference",
          name: placementReference[1],
          source: line,
          start: offsets[index],
          end: offsets[index] + line.length
        });
        markdownStart = index + 1;
        continue;
      }
      if (!markdownLines.length) markdownStart = index;
      markdownLines.push(line);
    }
    flushMarkdown(lines.length);
    return { type: "document", source: text, nodes, diagnostics };
  }

  function unwrapDefinition(rhs) {
    const value = String(rhs || "").trim();
    if (!value.startsWith("{") || !value.endsWith("}")) throw new Error("Definitions must use {...}");
    const content = value.slice(1, -1).trim();
    return content.startsWith("=") ? content.slice(1).trim() : content;
  }

  function splitSemicolonDataset(expression) {
    const source = String(expression || "");
    const parts = [];
    let cursor = 0;
    let start = 0;
    let quote = "";
    let depth = 0;
    let found = false;
    while (cursor < source.length) {
      const character = source[cursor];
      if (quote) {
        if (character === quote && source[cursor - 1] !== "\\") quote = "";
      } else if (character === "'" || character === '"') {
        quote = character;
      } else if (["(", "["].includes(character)) {
        depth += 1;
      } else if ([")", "]"].includes(character)) {
        depth = Math.max(0, depth - 1);
      } else if (character === ";" && depth === 0) {
        found = true;
        parts.push(source.slice(start, cursor).trim());
        start = cursor + 1;
      }
      cursor += 1;
    }
    if (!found) return null;
    parts.push(source.slice(start).trim());
    const names = parts.filter(Boolean);
    if (!names.length || names.some(name => !IDENTIFIER_PATTERN.test(name))) {
      throw new Error("Semicolon datasets may contain only data-node or variable identifiers");
    }
    return {
      type: "call",
      name: "series",
      args: names.map(name => ({ type: "identifier", name }))
    };
  }

  function parseDocumentExpression(expression) {
    return splitSemicolonDataset(expression) || parseExpression(expression);
  }

  function dedentLiteralLines(lines, baseIndent = 0) {
    const content = [...lines];
    while (content.length && !content[content.length - 1].trim()) content.pop();
    const indents = content
      .filter(line => line.trim())
      .map(line => (line.match(/^\s*/)?.[0].length || 0));
    const indent = indents.length ? Math.max(baseIndent + 1, Math.min(...indents)) : baseIndent + 1;
    return content.map(line => line.trim() ? line.slice(Math.min(indent, line.length)) : "").join("\n");
  }

  function splitRecordEntries(source) {
    const entries = [];
    let start = 0;
    let quote = "";
    let escaped = false;
    let depth = 0;
    const text = String(source || "");
    for (let index = 0; index < text.length; index += 1) {
      const character = text[index];
      if (escaped) {
        escaped = false;
        continue;
      }
      if (character === "\\") {
        escaped = true;
        continue;
      }
      if (quote) {
        if (character === quote) quote = "";
        continue;
      }
      if (character === "'" || character === '"') {
        quote = character;
        continue;
      }
      if (["(", "[", "{"].includes(character)) depth += 1;
      else if ([")", "]", "}"].includes(character)) depth = Math.max(0, depth - 1);
      else if (character === ";" && depth === 0) {
        entries.push(text.slice(start, index).trim());
        start = index + 1;
      }
    }
    entries.push(text.slice(start).trim());
    return entries.filter(Boolean);
  }

  function recordFieldSeparator(source) {
    let quote = "";
    let escaped = false;
    for (let index = 0; index < source.length; index += 1) {
      const character = source[index];
      if (escaped) {
        escaped = false;
        continue;
      }
      if (character === "\\") {
        escaped = true;
        continue;
      }
      if (quote) {
        if (character === quote) quote = "";
        continue;
      }
      if (character === "'" || character === '"') quote = character;
      else if (character === ":") return index;
    }
    return -1;
  }

  function parseRecordDefinition(rhs) {
    const match = String(rhs || "").trim().match(/^record\s*\{([\s\S]*)\}$/i);
    if (!match) throw new Error("Records must use record { \"Label\": value; ... }");
    const entries = splitRecordEntries(match[1]);
    if (!entries.length) throw new Error("Records require at least one labelled field");
    const labels = new Set();
    return entries.map(entry => {
      const separator = recordFieldSeparator(entry);
      if (separator < 0) throw new Error(`Record field '${entry}' requires a ':' separator`);
      const rawLabel = entry.slice(0, separator).trim();
      const valueSource = entry.slice(separator + 1).trim();
      if (!rawLabel || !valueSource) throw new Error(`Record field '${entry}' requires both a label and value`);
      let label = rawLabel;
      if (/^(['"])[\s\S]*\1$/.test(rawLabel)) {
        const labelAst = parseExpression(rawLabel);
        if (labelAst.type !== "literal" || typeof labelAst.value !== "string") throw new Error(`Invalid record label ${rawLabel}`);
        label = labelAst.value;
      } else if (!/^[A-Za-z_][A-Za-z0-9_-]*$/.test(rawLabel)) {
        throw new Error(`Record label '${rawLabel}' must be quoted when it contains spaces`);
      }
      if (!String(label).trim()) throw new Error("Record labels cannot be empty");
      if (labels.has(label)) throw new Error(`Duplicate record label '${label}'`);
      labels.add(label);
      return { label, valueSource, ast: parseExpression(valueSource) };
    });
  }

  function stripHeadingAnchor(line) {
    return String(line || "").replace(/\s+\{#[A-Za-z_][A-Za-z0-9_.:-]*\}\s*$/, "");
  }

  function headingIdFromTitle(level, title, parentIds) {
    let ownId = slug(String(title || "").replace(/\s+#+\s*$/, "").trim());
    if (!/^[A-Za-z_]/.test(ownId)) ownId = `heading_${ownId}`;
    if (level <= 2) return ownId;
    for (let parentLevel = level - 1; parentLevel >= 2; parentLevel -= 1) {
      if (parentIds.has(parentLevel)) return `${parentIds.get(parentLevel)}_${ownId}`;
    }
    return ownId;
  }

  function headingCompletionContext(source, lineStart) {
    const parentIds = new Map();
    const usedIds = new Set([...String(source || "").matchAll(/\{#([A-Za-z_][A-Za-z0-9_.:-]*)\}/g)].map(match => match[1]));
    const lines = String(source || "").slice(0, lineStart).split("\n");
    let fence = null;
    let inDirective = false;

    for (const line of lines) {
      if (!inDirective) {
        const marker = line.match(/^\s*(`{3,}|~{3,})/);
        if (marker) {
          if (!fence) fence = { character: marker[1][0], length: marker[1].length };
          else if (marker[1][0] === fence.character && marker[1].length >= fence.length) fence = null;
          continue;
        }
      }
      if (fence) continue;
      if (inDirective) {
        if (/^\s*:::\s*$/.test(line)) inDirective = false;
        continue;
      }
      if (/^\s*:::[A-Za-z]/.test(line) || /^\s*[A-Za-z_][A-Za-z0-9_]*\s*::=\s*:::(llm|prose|text|distill|conclusion)\b/i.test(line)) {
        inDirective = true;
        continue;
      }

      const heading = line.match(/^\s{0,3}(#{1,6})[ \t]+(.+?)\s*$/);
      if (!heading) continue;
      const anchor = heading[2].match(/\s+\{#([A-Za-z_][A-Za-z0-9_.:-]*)\}\s*$/);
      const level = heading[1].length;
      const title = stripHeadingAnchor(heading[2]).trim();
      const id = anchor?.[1] || headingIdFromTitle(level, title, parentIds);
      parentIds.set(level, id);
      for (let deeper = level + 1; deeper <= 6; deeper += 1) parentIds.delete(deeper);
      usedIds.add(id);
    }

    return { allowed: !fence && !inDirective, parentIds, usedIds };
  }

  function completeMarkdownHeading(source, selectionStart, selectionEnd = selectionStart) {
    const text = String(source || "");
    const start = Math.max(0, Math.min(text.length, Number(selectionStart) || 0));
    const end = Math.max(0, Math.min(text.length, Number(selectionEnd) || 0));
    if (start !== end) return null;

    const lineStart = text.lastIndexOf("\n", start - 1) + 1;
    const nextBreak = text.indexOf("\n", start);
    const lineEnd = nextBreak < 0 ? text.length : nextBreak;
    if (text.slice(start, lineEnd).trim()) return null;

    const line = text.slice(lineStart, lineEnd);
    const heading = line.match(/^(\s{0,3})(#{1,6})([ \t]+)(.+?)\s*$/);
    if (!heading) return null;
    const title = heading[4].trim();
    if (!title || /^#+$/.test(title) || /\s+\{#[^}]+\}\s*$/.test(title)) return null;

    const context = headingCompletionContext(text, lineStart);
    if (!context.allowed) return null;
    const level = heading[2].length;
    const rootId = headingIdFromTitle(level, title, context.parentIds);
    let id = rootId;
    let suffix = 2;
    while (context.usedIds.has(id)) {
      id = `${rootId}_${suffix}`;
      suffix += 1;
    }

    return {
      id,
      level,
      replaceStart: lineStart,
      replaceEnd: lineEnd,
      text: `${line.trimEnd()} {#${id}}\n`
    };
  }

  function scanDocumentStructure(source) {
    const text = String(source || "").replace(/\r\n?/g, "\n");
    const lines = text.split("\n");
    const offsets = [];
    let offset = 0;
    for (const line of lines) {
      offsets.push(offset);
      offset += line.length + 1;
    }
    const headings = [];
    const diagnostics = [];
    let inFence = false;
    let inDirective = false;
    for (let index = 0; index < lines.length; index += 1) {
      const line = lines[index];
      if (/^\s*```/.test(line) && !inDirective) {
        inFence = !inFence;
        continue;
      }
      if (inFence) continue;
      if (inDirective) {
        if (/^\s*:::\s*$/.test(line)) inDirective = false;
        continue;
      }
      if (/^\s*:::[A-Za-z]/.test(line) || /^\s*[A-Za-z_][A-Za-z0-9_]*\s*::=\s*:::(llm|prose|text|distill|conclusion)\b/i.test(line)) {
        inDirective = true;
        continue;
      }
      const match = line.match(/^(#{1,3})\s+(.+?)\s*$/);
      if (!match) continue;
      const anchor = match[2].match(/\s+\{#([A-Za-z_][A-Za-z0-9_.:-]*)\}\s*$/);
      const title = stripHeadingAnchor(match[2]).trim();
      const level = match[1].length;
      headings.push({
        level,
        title,
        id: anchor ? anchor[1] : "",
        explicitId: Boolean(anchor),
        line: index,
        start: offsets[index],
        end: offsets[index] + line.length
      });
    }

    const idCounts = new Map();
    const allocateId = (base, heading, prefix = "") => {
      const requested = heading.id || [prefix, slug(heading.title)].filter(Boolean).join("_");
      const count = (idCounts.get(requested) || 0) + 1;
      idCounts.set(requested, count);
      if (count > 1) {
        diagnostics.push({ severity: "error", code: "duplicate-heading-id", message: `Duplicate heading ID '${requested}'`, start: heading.start, end: heading.end });
        return `${requested}_${count}`;
      }
      return requested;
    };

    const reportHeadings = headings.filter(heading => heading.level === 1);
    if (reportHeadings.length > 1) {
      for (const heading of reportHeadings.slice(1)) {
        diagnostics.push({ severity: "warning", code: "multiple-report-titles", message: "Only the first level-one heading is used as the report title", start: heading.start, end: heading.end });
      }
    }
    const reportTitle = reportHeadings[0] || null;
    const sectionHeadings = headings.filter(heading => heading.level === 2);
    const sections = [];
    if (!sectionHeadings.length) {
      sections.push({ id: "front_matter", title: "Front matter", start: 0, end: text.length, headingStart: 0, explicitId: true, subsections: [] });
    } else {
      if (text.slice(0, sectionHeadings[0].start).trim()) {
        sections.push({ id: "front_matter", title: "Front matter", start: 0, end: sectionHeadings[0].start, headingStart: 0, explicitId: true, subsections: [] });
      }
      sectionHeadings.forEach((heading, index) => {
        const id = allocateId(heading.id || slug(heading.title), heading);
        if (!heading.explicitId) {
          diagnostics.push({ severity: "warning", code: "implicit-section-id", message: `Section '${heading.title}' uses generated ID '${id}'; add {#${id}} to keep it stable when renamed`, start: heading.start, end: heading.end });
        }
        sections.push({
          id,
          title: heading.title,
          start: heading.start,
          end: sectionHeadings[index + 1]?.start ?? text.length,
          headingStart: heading.start,
          explicitId: heading.explicitId,
          subsections: []
        });
      });
    }

    for (const section of sections) {
      const subsectionHeadings = headings.filter(heading => heading.level === 3 && heading.start >= section.start && heading.start < section.end);
      if (!subsectionHeadings.length) {
        section.subsections.push({ id: section.id, title: section.title, start: section.start, end: section.end, implicit: true, explicitId: section.explicitId });
        continue;
      }
      if (subsectionHeadings[0].start > section.start) {
        section.subsections.push({ id: `${section.id}__intro`, title: section.title, start: section.start, end: subsectionHeadings[0].start, implicit: true, explicitId: true });
      }
      subsectionHeadings.forEach((heading, index) => {
        const id = allocateId(heading.id || `${section.id}_${slug(heading.title)}`, heading, section.id);
        if (!heading.explicitId) {
          diagnostics.push({ severity: "warning", code: "implicit-subsection-id", message: `Subsection '${heading.title}' uses generated ID '${id}'; add {#${id}} to keep it stable when renamed`, start: heading.start, end: heading.end });
        }
        section.subsections.push({
          id,
          title: heading.title,
          start: heading.start,
          end: subsectionHeadings[index + 1]?.start ?? section.end,
          implicit: false,
          explicitId: heading.explicitId
        });
      });
    }

    return { reportTitle, headings, sections, diagnostics };
  }

  function contextForPosition(structure, position) {
    const section = structure.sections.find(item => position >= item.start && position < item.end)
      || structure.sections[structure.sections.length - 1]
      || { id: "front_matter", title: "Front matter", subsections: [] };
    const subsection = section.subsections.find(item => position >= item.start && position < item.end)
      || section.subsections[section.subsections.length - 1]
      || { id: section.id, title: section.title };
    return { sectionId: section.id, subsectionId: subsection.id };
  }

  function contextTitleForPosition(structure, position) {
    const section = structure.sections.find(item => position >= item.start && position < item.end)
      || structure.sections[structure.sections.length - 1];
    if (!section) return "Generated prose";
    const subsection = section.subsections.find(item => position >= item.start && position < item.end)
      || section.subsections[section.subsections.length - 1];
    return subsection?.title || section.title || "Generated prose";
  }

  function directiveDataNames(attributes) {
    const values = [attributes.data || attributes.inputs || "", attributes.caption_ref || ""];
    return values.flatMap(value => {
      const raw = String(value || "").trim();
      if (!raw) return [];
      const unwrapped = raw.replace(/^[\[{]/, "").replace(/[\]}]$/, "");
      return unwrapped.split(/[\s,;]+/).map(item => item.trim()).filter(Boolean);
    });
  }

  function authoredCaptionBody(value) {
    return String(value || "")
      .trim()
      .replace(/^(?:table|figure|chart)\s+\d+(?:\.\d+)*\s*[.:]\s*/i, "")
      .trim();
  }

  function textReferenceNames(value) {
    return scanInlineTokens(value || "").flatMap(token => {
      if (token.type === "reference") return [token.content];
      try {
        return collectIdentifiers(parseDocumentExpression(token.content));
      } catch {
        return [];
      }
    });
  }

  function replaceRanges(source, replacements, baseOffset) {
    let output = source;
    const sorted = [...replacements].sort((a, b) => b.start - a.start);
    for (const replacement of sorted) {
      const start = replacement.start - baseOffset;
      const end = replacement.end - baseOffset;
      output = output.slice(0, start) + replacement.value + output.slice(end);
    }
    return output;
  }

  function compileDocument(source, options = {}) {
    const parsed = parseDocument(source);
    const structure = scanDocumentStructure(parsed.source);
    const scopeId = slug(options.scopeId || "document");
    const globalNodes = options.globalNodes || {};
    const globalIds = new Set(Array.isArray(globalNodes) ? globalNodes : Object.keys(globalNodes));
    const implicitNodes = {};
    const globalMetadata = id => Array.isArray(globalNodes)
      ? implicitNodes[id] || {}
      : globalNodes[id] || implicitNodes[id] || {};
    const diagnostics = [...parsed.diagnostics, ...structure.diagnostics];
    const definitions = new Map();
    const generatedNodes = [];
    const artifacts = [];
    const sectionExports = [];
    const dependencyIds = new Set();
    const localIds = new Map();
    const localArtifactIds = new Map();
    const definitionNodes = parsed.nodes.filter(node => ["definition", "literal_definition", "record_definition", "invalid_definition"].includes(node.type));
    const generatedDefinitionNodes = parsed.nodes.filter(node => node.type === "generated_definition");

    for (const node of parsed.nodes.filter(item => item.type === "directive" && !["artifact", "include", "pagebreak", "export"].includes(item.kind))) {
      const rawId = node.id || node.attributes.id || `${node.kind}_${hashText(`${node.start}:${JSON.stringify(node.attributes)}`)}`;
      const directiveId = slug(rawId);
      const runtimeId = `doc.${scopeId}.artifact.${directiveId}`;
      for (const alias of [rawId, directiveId].filter(Boolean)) {
        if (!localArtifactIds.has(alias)) localArtifactIds.set(alias, runtimeId);
      }
    }

    for (const node of [...definitionNodes, ...generatedDefinitionNodes]) {
      if (!LOCAL_NAME_PATTERN.test(node.name)) continue;
      if (definitions.has(node.name)) {
        diagnostics.push({ severity: "error", code: "duplicate-definition", message: `Duplicate definition '${node.name}'`, start: node.start, end: node.end });
        continue;
      }
      definitions.set(node.name, node);
      localIds.set(node.name, `doc.${scopeId}.var.${node.name}`);
    }

    for (const [name, node] of definitions) {
      if (node.type !== "invalid_definition") continue;
      generatedNodes.push({
        id: localIds.get(name),
        name,
        label: name.replace(/_/g, " ").replace(/\b\w/g, character => character.toUpperCase()),
        tool: "INVALID_DEFINITION",
        valueType: "text",
        deps: [],
        availability: "missing",
        baseValue: null,
        invalid: true,
        start: node.start,
        end: node.end,
        named: true,
        ...contextForPosition(structure, node.start)
      });
    }

    const resolveName = (name, range, allowUnknown = false) => {
      if (localIds.has(name)) return localIds.get(name);
      if (localArtifactIds.has(name)) return localArtifactIds.get(name);
      if (globalIds.has(name)) return name;
      if (/^dt\.[A-Za-z_][A-Za-z0-9_.:-]*$/.test(name)) {
        if (!allowUnknown) diagnostics.push({
          severity: "error",
          code: "unknown-digital-twin-field",
          message: `Unknown digital-twin field '${name}'. Register source-backed project evidence explicitly, or use a registered req.* field for a report evidence requirement.`,
          start: range?.start || 0,
          end: range?.end || 0
        });
        return "";
      }
      if (/^req\.[A-Za-z_][A-Za-z0-9_.:-]*$/.test(name)) {
        if (!allowUnknown) diagnostics.push({
          severity: "error",
          code: "unknown-report-requirement",
          message: `Unknown report requirement '${name}'. Add it to the explicit report-requirement catalog before using it.`,
          start: range?.start || 0,
          end: range?.end || 0
        });
        return "";
      }
      if (!allowUnknown) diagnostics.push({ severity: "error", code: "unknown-reference", message: `Unknown data node or variable '${name}'`, start: range?.start || 0, end: range?.end || 0 });
      return "";
    };

    const compileTextTemplate = (value, node, idBase) => {
      const replacements = [];
      const deps = new Set();
      for (const token of scanInlineTokens(value || "", 0)) {
        if (token.type === "reference") {
          if (!IDENTIFIER_PATTERN.test(token.content)) {
            diagnostics.push({ severity: "error", code: "invalid-reference", message: `Invalid reference '${token.content}'`, start: node.start, end: node.end });
            continue;
          }
          const resolved = resolveName(token.content, node);
          if (!resolved) continue;
          deps.add(resolved);
          replacements.push({ ...token, value: `{${resolved}}` });
          continue;
        }
        try {
          const ast = parseDocumentExpression(token.content);
          const identifiers = collectIdentifiers(ast);
          const resolved = identifiers.map(identifier => resolveName(identifier, node)).filter(Boolean);
          const generatedId = `${idBase}.expr.${hashText(`${token.start}:${token.content}`)}`;
          generatedNodes.push({
            id: generatedId,
            label: `Inline calculation ${token.content}`,
            tool: "DOC_EXPRESSION",
            valueType: "number",
            deps: [...new Set(resolved)],
            expression: token.content,
            ast: rewriteIdentifiers(ast, identifier => resolveName(identifier, node, true)),
            start: node.start,
            end: node.end,
            named: false,
            ...contextForPosition(structure, node.start)
          });
          deps.add(generatedId);
          replacements.push({ ...token, value: `{${generatedId}}` });
        } catch (error) {
          diagnostics.push({ severity: "error", code: "invalid-expression", message: String(error.message || error), start: node.start, end: node.end });
        }
      }
      return { template: replaceRanges(String(value || ""), replacements, 0), deps: [...deps] };
    };

    for (const [name, node] of definitions) {
      if (node.type !== "definition") continue;
      try {
        const expression = unwrapDefinition(node.rhs);
        const ast = parseDocumentExpression(expression);
        const identifiers = collectIdentifiers(ast);
        const resolved = identifiers.map(identifier => resolveName(identifier, node)).filter(Boolean);
        const rewrittenAst = rewriteIdentifiers(ast, identifier => resolveName(identifier, node, true));
        const rootCall = ast.type === "call" ? ast.name.toLowerCase() : "";
        const valueType = ["series", "dataset"].includes(rootCall) || ast.type === "array" ? "dataset" : "number";
        generatedNodes.push({
          id: localIds.get(name),
          name,
          label: name.replace(/_/g, " ").replace(/\b\w/g, character => character.toUpperCase()),
          tool: valueType === "dataset" ? "GROUP_VALUES" : "DOC_EXPRESSION",
          valueType,
          deps: [...new Set(resolved)],
          expression,
          ast: rewrittenAst,
          start: node.start,
          end: node.end,
          named: true,
          ...contextForPosition(structure, node.start)
        });
      } catch (error) {
        diagnostics.push({ severity: "error", code: "invalid-expression", message: `${node.name}: ${String(error.message || error)}`, start: node.start, end: node.end });
      }
    }

    for (const [name, node] of definitions) {
      if (node.type !== "literal_definition") continue;
      const id = localIds.get(name);
      const compiled = compileTextTemplate(node.value, node, id);
      generatedNodes.push({
        id,
        name,
        label: name.replace(/_/g, " ").replace(/\b\w/g, character => character.toUpperCase()),
        tool: "DEFINE_TEXT",
        valueType: "text",
        deps: compiled.deps,
        template: compiled.template,
        literal: node.value,
        start: node.start,
        end: node.end,
        named: true,
        ...contextForPosition(structure, node.start)
      });
    }

    for (const [name, node] of definitions) {
      if (node.type !== "record_definition") continue;
      try {
        const parentId = localIds.get(name);
        const fields = parseRecordDefinition(node.rhs);
        const fieldIds = [];
        const usedFieldIds = new Set();
        const recordEntries = [];
        for (const field of fields) {
          const rootFieldId = `${parentId}.field.${slug(field.label)}`;
          let fieldId = rootFieldId;
          let suffix = 2;
          while (usedFieldIds.has(fieldId)) {
            fieldId = `${rootFieldId}_${suffix}`;
            suffix += 1;
          }
          usedFieldIds.add(fieldId);
          fieldIds.push(fieldId);
          const identifiers = collectIdentifiers(field.ast);
          const resolved = identifiers.map(identifier => resolveName(identifier, node)).filter(Boolean);
          generatedNodes.push({
            id: fieldId,
            name: `${name}.${slug(field.label)}`,
            label: field.label,
            tool: "DOC_EXPRESSION",
            valueType: "number",
            deps: [...new Set(resolved)],
            expression: field.valueSource,
            ast: rewriteIdentifiers(field.ast, identifier => resolveName(identifier, node, true)),
            start: node.start,
            end: node.end,
            named: true,
            recordParentId: parentId,
            ...contextForPosition(structure, node.start)
          });
          recordEntries.push({ label: field.label, nodeId: fieldId, source: field.valueSource });
        }
        generatedNodes.push({
          id: parentId,
          name,
          label: name.replace(/_/g, " ").replace(/\b\w/g, character => character.toUpperCase()),
          tool: "GROUP_VALUES",
          valueType: "dataset",
          deps: fieldIds,
          recordEntries,
          start: node.start,
          end: node.end,
          named: true,
          ...contextForPosition(structure, node.start)
        });
      } catch (error) {
        diagnostics.push({ severity: "error", code: "invalid-record", message: `${name}: ${String(error.message || error)}`, start: node.start, end: node.end });
      }
    }

    for (const [name, node] of definitions) {
      if (node.type !== "generated_definition") continue;
      const recipe = generatedRecipeConfig(node.kind);
      const instructionKey = node.kind === "distill"
        ? (node.attributes.question !== undefined ? "question" : "instructions")
        : (node.attributes.instructions !== undefined ? "instructions" : "prompt");
      const instructionSourceRange = node.attributeRanges?.[instructionKey]
        ? { ...node.attributeRanges[instructionKey] }
        : null;
      const sourceNames = node.kind === "distill"
        ? directiveDataNames({ data: node.attributes.source || node.attributes.text || "" })
        : [];
      const instructions = String(node.kind === "distill"
        ? node.attributes.question || node.attributes.instructions || ""
        : node.attributes.instructions || node.attributes.prompt || "").trim();
      if (node.kind === "distill" && !sourceNames.length) {
        diagnostics.push({ severity: "error", code: "missing-summary-source", message: `Evidence summary '${name}' requires a source node`, start: node.start, end: node.end });
      }
      if (!instructions) diagnostics.push({
        severity: "error",
        code: node.kind === "distill" ? "missing-summary-question" : "missing-instructions",
        message: node.kind === "distill" ? `Evidence summary '${name}' requires a question` : `Generated text '${name}' requires instructions`,
        start: node.start,
        end: node.end
      });
      const references = [...sourceNames, ...textReferenceNames(instructions)];
      const resolved = references.map(reference => resolveName(reference, node)).filter(Boolean);
      const resolvedSourceIds = sourceNames.map(reference => resolveName(reference, node, true)).filter(Boolean);
      const estimatedWordsAttribute = node.attributes.estimated_max_words ?? node.attributes.max_words;
      const requestedEstimatedMaxWords = estimatedWordsAttribute === undefined
        ? recipe?.defaultEstimatedMaxWords
        : Number(estimatedWordsAttribute);
      const estimatedMaxWords = Number.isFinite(Number(requestedEstimatedMaxWords))
        ? Math.max(40, Math.min(700, Math.round(Number(requestedEstimatedMaxWords))))
        : recipe?.defaultEstimatedMaxWords || 0;
      if (estimatedWordsAttribute !== undefined && !Number.isFinite(Number(estimatedWordsAttribute))) {
        diagnostics.push({ severity: "error", code: "invalid-estimated-max-words", message: `'${name}' estimated_max_words must be numeric`, start: node.start, end: node.end });
      }
      const frozen = /^(true|yes|1)$/i.test(String(node.attributes.frozen || "false"));
      const profile = String(node.attributes.profile || recipe.profile);
      const outputContractId = String(node.attributes.output_contract || node.attributes.output_contract_id || recipe.outputContractId);
      generatedNodes.push({
        id: localIds.get(name),
        name,
        label: name.replace(/_/g, " ").replace(/\b\w/g, character => character.toUpperCase()),
        kind: "generated_markdown",
        tool: recipe.tool,
        valueType: recipe.outputType,
        deps: [...new Set(resolved)],
        instructions,
        prompt: instructions,
        question: node.kind === "distill" ? instructions : "",
        sourceNodeIds: resolvedSourceIds,
        estimatedMaxWords,
        profile,
        outputContractId,
        outputContractVersion: GENERATED_OUTPUT_CONTRACT_VERSION,
        outputRulesVersion: GENERATED_OUTPUT_RULES_VERSION,
        model: String(node.attributes.model || ""),
        frozen,
        manual: true,
        definitionHash: hashText(JSON.stringify({
          name,
          recipe: node.kind,
          instructions,
          profile,
          tool: recipe.tool,
          sourceNodeIds: resolvedSourceIds,
          estimatedMaxWords,
          model: node.attributes.model || "",
          frozen,
          outputContractId,
          resolved
        })),
        start: node.start,
        end: node.end,
        instructionSourceRange,
        named: true,
        ...contextForPosition(structure, node.start)
      });
    }

    const localGraph = new Map(generatedNodes.map(node => [node.id, node.deps.filter(id => id.startsWith(`doc.${scopeId}.var.`))]));
    const visiting = new Set();
    const visited = new Set();
    const visit = (id, path = []) => {
      if (visiting.has(id)) {
        const cycle = [...path.slice(path.indexOf(id)), id];
        diagnostics.push({ severity: "error", code: "cyclic-definition", message: `Cyclic definition: ${cycle.map(item => item.split(".").pop()).join(" -> ")}`, start: 0, end: 0 });
        return;
      }
      if (visited.has(id)) return;
      visiting.add(id);
      for (const dep of localGraph.get(id) || []) visit(dep, [...path, id]);
      visiting.delete(id);
      visited.add(id);
    };
    for (const id of localGraph.keys()) visit(id);

    for (const node of parsed.nodes) {
      if (node.type === "executable_code") {
        const deps = [...new Set((node.declaredNames || []).map(name => resolveName(name, node)).filter(Boolean))];
        deps.forEach(id => dependencyIds.add(id));
        artifacts.push({
          type: "executable_code",
          id: `doc.${scopeId}.artifact.code.${hashText(`${node.start}:${node.source}`)}`,
          source: node.source,
          language: node.language || "code",
          declaredNames: [...(node.declaredNames || [])],
          start: node.start,
          end: node.end,
          deps,
          ...contextForPosition(structure, node.start)
        });
      }
      if (node.type === "placement_reference") {
        const resolved = resolveName(node.name, node);
        const target = generatedNodes.find(item => item.id === resolved);
        if (resolved) dependencyIds.add(resolved);
        if (isGeneratedTool(target?.tool)) {
          artifacts.push({
            type: "generated_text",
            id: `doc.${scopeId}.placement.${hashText(`${node.start}:${resolved}`)}`,
            nodeId: resolved,
            title: contextTitleForPosition(structure, node.start),
            profile: target.profile,
            start: node.start,
            end: node.end,
            deps: resolved ? [resolved] : [],
            ...contextForPosition(structure, node.start)
          });
        } else if (resolved) {
          artifacts.push({
            type: "markdown",
            id: `doc.${scopeId}.artifact.markdown.${hashText(`${node.start}:${resolved}`)}`,
            source: `{${resolved}}`,
            originalSource: node.source,
            start: node.start,
            end: node.end,
            deps: [resolved],
            ...contextForPosition(structure, node.start)
          });
        }
      }
      if (node.type === "markdown") {
        const replacements = [];
        const markdownDependencyIds = new Set();
        for (const token of node.tokens) {
          if (token.type === "reference") {
            if (!IDENTIFIER_PATTERN.test(token.content)) {
              diagnostics.push({ severity: "error", code: "invalid-reference", message: `Invalid reference '${token.content}'`, start: token.start, end: token.end });
              continue;
            }
            const resolved = resolveName(token.content, token);
            if (resolved) {
              const target = generatedNodes.find(item => item.id === resolved);
              if (target?.valueType === "markdown_block") {
                diagnostics.push({ severity: "error", code: "block-output-inline", message: `Generated prose '${target.name}' must be placed on its own line`, start: token.start, end: token.end });
              }
              dependencyIds.add(resolved);
              markdownDependencyIds.add(resolved);
              replacements.push({ ...token, value: `{${resolved}}` });
            }
          } else {
            try {
              const ast = parseDocumentExpression(token.content);
              const identifiers = collectIdentifiers(ast);
              const deps = identifiers.map(identifier => resolveName(identifier, token)).filter(Boolean);
              const generatedId = `doc.${scopeId}.expr.${hashText(token.content)}`;
              generatedNodes.push({
                id: generatedId,
                label: `Inline calculation ${token.content}`,
                tool: "DOC_EXPRESSION",
                valueType: "number",
                deps: [...new Set(deps)],
                expression: token.content,
                ast: rewriteIdentifiers(ast, identifier => resolveName(identifier, token, true)),
                start: token.start,
                end: token.end,
                named: false,
                ...contextForPosition(structure, token.start)
              });
              dependencyIds.add(generatedId);
              markdownDependencyIds.add(generatedId);
              replacements.push({ ...token, value: `{${generatedId}}` });
            } catch (error) {
              diagnostics.push({ severity: "error", code: "invalid-expression", message: String(error.message || error), start: token.start, end: token.end });
            }
          }
        }
        let markdown = replaceRanges(node.source, replacements, node.start);
        markdown = markdown.replace(/\s+\{#[A-Za-z_][A-Za-z0-9_.:-]*\}\s*$/gm, "");
        markdown = markdown.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (match, label, target) => {
          const normalized = String(target).trim().replace(/^node:/, "");
          const resolved = resolveName(normalized, node, true);
          if (!resolved) return match;
          dependencyIds.add(resolved);
          markdownDependencyIds.add(resolved);
          return `[${label}](${resolved})`;
        });
        if (markdown.trim()) {
          artifacts.push({
            type: "markdown",
            id: `doc.${scopeId}.artifact.markdown.${hashText(`${node.start}:${markdown}`)}`,
            source: markdown,
            originalSource: node.source,
            start: node.start,
            end: node.end,
            deps: [...markdownDependencyIds],
            ...contextForPosition(structure, node.start)
          });
        }
      }
      if (node.type === "directive") {
        const generatedRecipe = generatedRecipeConfig(node.kind);
        const generatedDirective = Boolean(generatedRecipe);
        const generatedInstructionKey = node.kind === "distill"
          ? (node.attributes.question !== undefined ? "question" : "instructions")
          : (node.attributes.instructions !== undefined ? "instructions" : "prompt");
        const generatedInstructionSourceRange = generatedDirective && node.attributeRanges?.[generatedInstructionKey]
          ? { ...node.attributeRanges[generatedInstructionKey] }
          : null;
        const generatedSourceNames = node.kind === "distill"
          ? directiveDataNames({ data: node.attributes.source || node.attributes.text || "" })
          : [];
        const generatedInstructions = generatedDirective
          ? String(node.kind === "distill"
            ? node.attributes.question || node.attributes.instructions || ""
            : node.attributes.instructions || node.attributes.prompt || "").trim()
          : "";
        if (node.kind === "distill" && !generatedSourceNames.length) {
          diagnostics.push({ severity: "error", code: "missing-summary-source", message: `Evidence summary '${node.id || "distill"}' requires a source node`, start: node.start, end: node.end });
        }
        if (generatedDirective && !generatedInstructions) {
          diagnostics.push({
            severity: "error",
            code: node.kind === "distill" ? "missing-summary-question" : "missing-instructions",
            message: node.kind === "distill" ? "Evidence summaries require a question" : `${node.kind} directives require instructions`,
            start: node.start,
            end: node.end
          });
        }
        const promptNames = generatedDirective ? textReferenceNames(generatedInstructions) : [];
        let ruleDependencyNames = [];
        if (RULE_DIRECTIVE_KINDS.has(node.kind)) {
          if (typeof options.resolveRuleDependencies === "function") {
            try {
              const resolved = options.resolveRuleDependencies({
                kind: node.kind,
                id: node.id || node.attributes.id || "",
                attributes: { ...node.attributes },
                start: node.start,
                end: node.end
              });
              ruleDependencyNames = Array.isArray(resolved) ? resolved.map(String).filter(Boolean) : [];
            } catch (error) {
              diagnostics.push({
                severity: "error",
                code: "rules-dependency-resolution",
                message: `Could not resolve rules dependencies: ${String(error?.message || error)}`,
                start: node.start,
                end: node.end
              });
            }
          } else if (options.rulesStoreNodeId) {
            ruleDependencyNames = [String(options.rulesStoreNodeId)];
          }
        }
        const dataIds = [...new Set([...directiveDataNames(node.attributes), ...generatedSourceNames, ...promptNames, ...ruleDependencyNames])]
          .map(name => resolveName(name, node))
          .filter(Boolean);
        dataIds.forEach(id => dependencyIds.add(id));
        const directiveId = slug(node.id || node.attributes.id || `${node.kind}_${hashText(`${node.start}:${JSON.stringify(node.attributes)}`)}`);
        const context = contextForPosition(structure, node.start);
        if (node.kind === "export") {
          const rawExportId = node.id || node.attributes.id || "";
          if (!rawExportId) {
            diagnostics.push({ severity: "error", code: "missing-section-export-id", message: "Section exports require a stable {#identifier}", start: node.start, end: node.end });
          }
          if (!dataIds.length) {
            diagnostics.push({ severity: "error", code: "missing-section-export-data", message: "Section exports require at least one local data node", start: node.start, end: node.end });
          }
          for (const dataId of dataIds) {
            const target = generatedNodes.find(item => item.id === dataId);
            if (!target) {
              diagnostics.push({ severity: "error", code: "invalid-section-export-target", message: `Section export '${rawExportId || context.sectionId}' must reference a document-local value`, start: node.start, end: node.end });
            } else if (target.sectionId !== context.sectionId) {
              diagnostics.push({ severity: "error", code: "section-export-boundary", message: `Section export '${rawExportId || context.sectionId}' cannot export '${target.name || target.id}' from section '${target.sectionId}'`, start: node.start, end: node.end });
            }
          }
          sectionExports.push({
            id: `doc.${scopeId}.export.${slug(rawExportId || `${context.sectionId}_${node.start}`)}`,
            name: rawExportId,
            nodeIds: dataIds,
            start: node.start,
            end: node.end,
            ...context
          });
        } else if (node.kind === "artifact") {
          const id = node.attributes.ref || node.attributes.block || node.id || "";
          if (!id) diagnostics.push({ severity: "error", code: "missing-artifact", message: "Artifact directives require a block ID", start: node.start, end: node.end });
          artifacts.push({ type: "artifact", id, start: node.start, end: node.end, deps: [], ...context });
        } else if (node.kind === "include") {
          const id = node.attributes.ref || node.attributes.component || node.id || "";
          if (!id) diagnostics.push({ severity: "error", code: "missing-include", message: "Include directives require a component ID", start: node.start, end: node.end });
          artifacts.push({ type: "include", id, start: node.start, end: node.end, deps: [], ...context });
        } else if (node.kind === "pagebreak") {
          artifacts.push({ type: "pagebreak", id: `doc.${scopeId}.artifact.${directiveId}`, start: node.start, end: node.end, deps: [], ...context });
        } else {
          if (["table", "chart"].includes(node.kind) && !dataIds.length) {
            diagnostics.push({ severity: "error", code: "missing-data", message: `${node.kind} '${directiveId}' requires a data node or dataset`, start: node.start, end: node.end });
          }
          const chartType = String(node.attributes.type || "bar").toLowerCase();
          const tableType = String(node.attributes.type || "key-value").toLowerCase();
          if (node.kind === "chart" && !["bar", "pie", "donut"].includes(chartType)) {
            diagnostics.push({ severity: "error", code: "invalid-chart-type", message: `Unsupported chart type '${chartType}'`, start: node.start, end: node.end });
          }
          const frozen = /^(true|yes|1)$/i.test(String(node.attributes.frozen || "false"));
          const estimatedWordsAttribute = node.attributes.estimated_max_words ?? node.attributes.max_words;
          const requestedEstimatedMaxWords = estimatedWordsAttribute === undefined
            ? generatedRecipe?.defaultEstimatedMaxWords
            : Number(estimatedWordsAttribute);
          const estimatedMaxWords = Number.isFinite(Number(requestedEstimatedMaxWords))
            ? Math.max(40, Math.min(700, Math.round(Number(requestedEstimatedMaxWords))))
            : generatedRecipe?.defaultEstimatedMaxWords || 0;
          if (estimatedWordsAttribute !== undefined && !Number.isFinite(Number(estimatedWordsAttribute))) {
            diagnostics.push({ severity: "error", code: "invalid-estimated-max-words", message: `'${directiveId}' estimated_max_words must be numeric`, start: node.start, end: node.end });
          }
          const generatedProfile = generatedDirective
            ? String(node.attributes.profile || generatedRecipe.profile)
            : "";
          const generatedOutputContractId = generatedDirective
            ? String(node.attributes.output_contract || node.attributes.output_contract_id || generatedRecipe.outputContractId)
            : "";
          const definitionHash = hashText(JSON.stringify({
            kind: node.kind,
            id: directiveId,
            prompt: generatedInstructions,
            sourceNodeIds: generatedSourceNames,
            estimatedMaxWords,
            schema: node.attributes.schema || "",
            model: node.attributes.model || "",
            dataIds,
            profile: generatedProfile,
            outputContractId: generatedOutputContractId,
            frozen
          }));
          artifacts.push({
            type: generatedDirective ? "llm" : node.kind,
            id: `doc.${scopeId}.artifact.${directiveId}`,
            recipe: node.kind,
            title: node.attributes.title || (generatedDirective ? contextTitleForPosition(structure, node.start) : directiveId.replace(/_/g, " ")),
            caption: node.attributes.caption || "",
            intro: node.attributes.intro || "",
            prompt: generatedInstructions,
            instructions: generatedInstructions,
            schema: node.attributes.schema || "",
            model: node.attributes.model || "",
            frozen,
            manual: generatedDirective,
            question: node.kind === "distill" ? generatedInstructions : "",
            sourceNodeIds: node.kind === "distill" ? dataIds : [],
            estimatedMaxWords,
            toolId: generatedDirective ? generatedRecipe.tool : "",
            profile: generatedProfile,
            outputContractId: generatedOutputContractId,
            outputContractVersion: generatedDirective ? GENERATED_OUTPUT_CONTRACT_VERSION : undefined,
            outputRulesVersion: generatedDirective ? GENERATED_OUTPUT_RULES_VERSION : undefined,
            definitionHash,
            chartType,
            tableType,
            headers: String(node.attributes.headers || "").replace(/^\[/, "").replace(/\]$/, "").split(",").map(value => value.trim()).filter(Boolean),
            attributes: { ...node.attributes },
            ...(["table", "chart"].includes(node.kind) ? {
              directiveAnchor: String(node.id || node.attributes.id || directiveId),
              directiveFields: {
                title: String(node.attributes.title || "").trim(),
                data: String(node.attributes.data || node.attributes.inputs || "").trim(),
                caption: authoredCaptionBody(node.attributes.caption || ""),
                intro: String(node.attributes.intro || "").trim(),
                recipe: node.kind === "chart" ? chartType : tableType,
                headers: node.kind === "table"
                  ? String(node.attributes.headers || "").replace(/^\[/, "").replace(/\]$/, "").split(",").map(value => value.trim()).filter(Boolean)
                  : []
              }
            } : {}),
            dataIds,
            start: node.start,
            end: node.end,
            instructionSourceRange: generatedInstructionSourceRange,
            deps: dataIds,
            ...context
          });
        }
      }
    }

    const metadataById = new Map(generatedNodes
      .filter(node => !node.ast)
      .map(node => [node.id, normalizeMetadata(node)]));
    const metadataResolver = id => metadataById.get(id) || globalMetadata(id);
    for (let pass = 0; pass <= generatedNodes.length; pass += 1) {
      let changed = false;
      for (const generated of generatedNodes) {
        if (!generated.ast) continue;
        const metadata = inferExpressionMetadata(generated.ast, metadataResolver);
        const serialized = JSON.stringify(metadata);
        if (JSON.stringify(metadataById.get(generated.id) || {}) !== serialized) {
          metadataById.set(generated.id, metadata);
          changed = true;
        }
      }
      if (!changed) break;
    }
    for (const generated of generatedNodes) {
      if (!generated.ast) continue;
      const metadata = metadataById.get(generated.id) || normalizeMetadata({ valueType: generated.valueType });
      generated.valueType = metadata.valueType;
      generated.tool = metadata.valueType === "dataset" ? "GROUP_VALUES" : "DOC_EXPRESSION";
      generated.unit = metadata.unit;
      generated.scaleFactor = metadata.scaleFactor;
      generated.scaleLabel = metadata.scaleLabel;
      generated.digits = metadata.digits;
      const mismatches = expressionUnitMismatches(generated.ast, metadataResolver);
      for (const mismatch of mismatches) {
        diagnostics.push({
          severity: "error",
          code: "unit-mismatch",
          message: `${generated.name || generated.label}: incompatible units in ${mismatch}`,
          start: generated.start,
          end: generated.end
        });
      }
    }

    const generatedById = new Map(generatedNodes.map(node => [node.id, node]));
    const expandDatasetIds = (ids, visited = new Set()) => ids.flatMap(id => {
      if (visited.has(id)) return [];
      const generated = generatedById.get(id);
      if (!generated || generated.valueType !== "dataset") return [id];
      visited.add(id);
      return expandDatasetIds(generated.deps, visited);
    });
    for (const artifact of artifacts) {
      if (artifact.type !== "chart" || !["pie", "donut"].includes(artifact.chartType)) continue;
      const units = [...new Set(expandDatasetIds(artifact.dataIds || []).map(id => normalizeMetadata(metadataResolver(id)).unit).filter(Boolean))];
      if (units.length > 1) {
        diagnostics.push({
          severity: "error",
          code: "chart-unit-mismatch",
          message: `${artifact.chartType} chart '${artifact.title}' mixes incompatible units: ${units.join(", ")}`,
          start: artifact.start,
          end: artifact.end
        });
      }
    }

    let tableOrdinal = 0;
    let figureOrdinal = 0;
    for (const artifact of artifacts) {
      if (!["table", "chart"].includes(artifact.type)) continue;
      const isTable = artifact.type === "table";
      const number = isTable ? ++tableOrdinal : ++figureOrdinal;
      const label = `${isTable ? "Table" : "Figure"} ${number}`;
      const body = authoredCaptionBody(artifact.caption || artifact.title || "");
      artifact.caption = body;
      artifact.captionNumber = number;
      artifact.captionLabel = label;
      artifact.displayCaption = `${label}.${body ? ` ${body}` : ""}`;
    }

    const generatedArtifactIds = artifacts.filter(artifact => !["artifact", "include"].includes(artifact.type)).map(artifact => artifact.id);
    for (const id of new Set(generatedArtifactIds)) {
      if (generatedArtifactIds.filter(candidate => candidate === id).length > 1) {
        const artifact = artifacts.find(candidate => candidate.id === id);
        diagnostics.push({ severity: "error", code: "duplicate-artifact", message: `Duplicate generated artifact '${id}'`, start: artifact.start, end: artifact.end });
      }
    }

    const sectionExportIds = sectionExports.map(item => item.id);
    for (const id of new Set(sectionExportIds)) {
      if (sectionExportIds.filter(candidate => candidate === id).length > 1) {
        const item = sectionExports.find(candidate => candidate.id === id);
        diagnostics.push({ severity: "error", code: "duplicate-section-export", message: `Duplicate section export '${item.name || id}'`, start: item.start, end: item.end });
      }
    }

    const exportedNodeIds = new Set(sectionExports.flatMap(item => item.nodeIds));
    const localProducerById = new Map([...generatedNodes, ...artifacts].map(item => [item.id, item]));
    const crossSectionDiagnostics = new Set();
    for (const consumer of [...generatedNodes, ...artifacts]) {
      for (const dependencyId of consumer.deps || []) {
        const producer = localProducerById.get(dependencyId);
        if (!producer || producer.sectionId === consumer.sectionId || exportedNodeIds.has(dependencyId)) continue;
        const key = `${consumer.id}:${dependencyId}`;
        if (crossSectionDiagnostics.has(key)) continue;
        crossSectionDiagnostics.add(key);
        diagnostics.push({
          severity: "error",
          code: "unexported-cross-section-reference",
          message: `'${producer.name || producer.id}' crosses from section '${producer.sectionId}' into '${consumer.sectionId}' without a section export`,
          start: consumer.start,
          end: consumer.end
        });
      }
    }

    for (const node of generatedNodes) node.deps.forEach(id => dependencyIds.add(id));
    const compiledSections = structure.sections.map(section => {
      const sectionArtifacts = artifacts.filter(artifact => artifact.sectionId === section.id);
      const sectionNodes = generatedNodes.filter(node => node.sectionId === section.id);
      const exportsForSection = sectionExports.filter(item => item.sectionId === section.id);
      return {
        ...section,
        artifactIds: sectionArtifacts.map(artifact => artifact.id),
        generatedNodeIds: sectionNodes.map(node => node.id),
        exportIds: exportsForSection.map(item => item.id),
        exportNodeIds: [...new Set(exportsForSection.flatMap(item => item.nodeIds))],
        dependencyIds: [...new Set([
          ...sectionArtifacts.flatMap(artifact => artifact.deps || []),
          ...sectionNodes.flatMap(node => node.deps || []),
          ...exportsForSection.flatMap(item => item.nodeIds || [])
        ])]
      };
    });
    const irNodes = generatedNodes.map(node => ({
      id: node.id,
      symbol: node.name || node.id,
      kind: isGeneratedTool(node.tool) ? "generated" : "computed",
      toolId: node.tool,
      outputType: node.valueType === "number" && node.unit ? "quantity" : node.valueType,
      dependencies: node.deps,
      config: {
        expression: node.expression || "",
        instructions: node.instructions || "",
        question: node.question || "",
        sourceNodeIds: node.sourceNodeIds || [],
        estimatedMaxWords: node.estimatedMaxWords || 0,
        profile: node.profile || "",
        outputContractId: node.outputContractId || "",
        outputContractVersion: node.outputContractVersion || 0,
        outputRulesVersion: node.outputRulesVersion || 0,
        model: node.model || "",
        frozen: Boolean(node.frozen),
        definitionHash: node.definitionHash || ""
      },
      sourceRange: { start: node.start, end: node.end },
      sectionId: node.sectionId,
      subsectionId: node.subsectionId
    }));
    for (const artifact of artifacts.filter(item => item.type === "llm")) {
      const profile = artifact.profile || "prose";
      irNodes.push({
        id: artifact.id,
        symbol: artifact.id.split(".").pop(),
        kind: "generated",
        toolId: artifact.toolId || "GENERATE_MARKDOWN",
        outputType: profile === "short_text" ? "markdown_inline" : "markdown_block",
        dependencies: artifact.deps,
        config: {
          instructions: artifact.instructions || artifact.prompt,
          question: artifact.question || "",
          sourceNodeIds: artifact.sourceNodeIds || [],
          estimatedMaxWords: artifact.estimatedMaxWords || 0,
          profile,
          outputContractId: artifact.outputContractId || `climinvest.generate_markdown.${profile}`,
          outputContractVersion: artifact.outputContractVersion || GENERATED_OUTPUT_CONTRACT_VERSION,
          outputRulesVersion: artifact.outputRulesVersion || GENERATED_OUTPUT_RULES_VERSION,
          model: artifact.model,
          frozen: artifact.frozen,
          definitionHash: artifact.definitionHash,
          legacyDirective: artifact.recipe === "llm"
        },
        sourceRange: { start: artifact.start, end: artifact.end },
        sectionId: artifact.sectionId,
        subsectionId: artifact.subsectionId
      });
    }
    const irPlacements = artifacts.map(artifact => ({
      id: artifact.type === "llm" ? `${artifact.id}.placement` : artifact.id,
      nodeId: artifact.type === "generated_text" ? artifact.nodeId : artifact.type === "llm" ? artifact.id : "",
      kind: artifact.type,
      renderMode: ["generated_text", "llm"].includes(artifact.type) ? "block" : "artifact",
      dependencies: artifact.deps,
      config: { ...artifact },
      sourceRange: { start: artifact.start, end: artifact.end },
      sectionId: artifact.sectionId,
      subsectionId: artifact.subsectionId
    }));
    const ir = reportIr?.createReportIR({
      source: parsed.source,
      sourceHash: hashText(parsed.source),
      structure: { ...structure, sections: compiledSections },
      nodes: irNodes,
      placements: irPlacements,
      exports: sectionExports,
      externalNodeIds: [...globalIds],
      diagnostics
    }) || null;
    return {
      source: parsed.source,
      ast: parsed,
      scopeId,
      structure: { ...structure, sections: compiledSections },
      definitions: Object.fromEntries(localIds),
      generatedNodes: dedupeById(generatedNodes),
      artifacts,
      sectionExports,
      implicitNodes,
      dependencyIds: [...dependencyIds],
      diagnostics: ir?.diagnostics || diagnostics,
      ir
    };
  }

  function dedupeById(items) {
    const byId = new Map();
    for (const item of items) if (!byId.has(item.id)) byId.set(item.id, item);
    return [...byId.values()];
  }

  return {
    hashText,
    slug,
    parseMarkdownTableAt,
    tokenizeExpression,
    parseExpression,
    evaluateExpression,
    collectIdentifiers,
    inferExpressionMetadata,
    parseDocumentExpression,
    parseRecordDefinition,
    completeMarkdownHeading,
    scanInlineTokens,
    parseDocument,
    scanDocumentStructure,
    compileDocument,
    RULE_DIRECTIVE_KINDS
  };
});
