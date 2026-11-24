"use strict";

const fs = require("node:fs");
const path = require("node:path");
const documentEngine = require("../vendor/tracemark-core/document-engine.js");

const SECTION_IDS = new Map([
  ["Project overview", "project_overview"],
  ["Scale and calculated indicators", "scale_and_calculated_indicators"],
  ["Selected performance indicators", "selected_performance_indicators"],
  ["Priority risks", "priority_risks"],
  ["Overall evidence summary", "overall_evidence_summary"]
]);

function readInput() {
  const file = process.argv[2];
  return file ? fs.readFileSync(path.resolve(file), "utf8") : fs.readFileSync(0, "utf8");
}

function links(text) {
  const output = [];
  const pattern = /\[([^\]\n]+)\]\(([^)\n]+)\)/g;
  let match;
  while ((match = pattern.exec(text)) !== null) {
    output.push({text: match[1], target: match[2], start: match.index});
  }
  return output;
}

function parse(markdown) {
  const lines = String(markdown || "").split(/\r?\n/);
  const titleLine = lines.find(line => /^#\s+/.test(line));
  const sections = [];
  let current = null;
  let cursor = 0;
  while (cursor < lines.length) {
    const heading = lines[cursor].match(/^##\s+(.+?)(?:\s+\{#[^}]+\})?\s*$/);
    if (!heading) {
      cursor += 1;
      continue;
    }
    const headingText = heading[1].trim();
    const end = lines.findIndex(
      (line, index) => index > cursor && /^##\s+/.test(line)
    );
    const endIndex = end < 0 ? lines.length : end;
    const bodyLines = lines.slice(cursor + 1, endIndex);
    current = {
      id: SECTION_IDS.get(headingText) || headingText.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, ""),
      heading: headingText,
      start_line: cursor + 1,
      end_line: endIndex,
      headings: [],
      tables: [],
      paragraphs: [],
      blocks: [],
      links: links(bodyLines.join("\n"))
    };
    let inner = 0;
    let paragraph = [];
    const flushParagraph = () => {
      const text = paragraph.join("\n").trim();
      if (text) {
        const index = current.paragraphs.length;
        current.paragraphs.push({text, links: links(text)});
        current.blocks.push({kind: "prose", index});
      }
      paragraph = [];
    };
    while (inner < bodyLines.length) {
      const subheading = bodyLines[inner].match(/^###\s+(.+?)(?:\s+\{#[^}]+\})?\s*$/);
      if (subheading) {
        flushParagraph();
        const text = subheading[1].trim();
        const index = current.headings.length;
        current.headings.push({level: 3, text, line: cursor + inner + 2});
        current.blocks.push({kind: "subsection", index, heading: text});
        inner += 1;
        continue;
      }
      const parsedTable = documentEngine.parseMarkdownTableAt(bodyLines, inner);
      if (parsedTable) {
        flushParagraph();
        const raw = bodyLines.slice(inner, parsedTable.endIndex).join("\n");
        current.tables.push({
          index: current.tables.length,
          headers: parsedTable.headers,
          alignments: parsedTable.alignments,
          rows: parsedTable.rows,
          links: links(raw),
          raw
        });
        current.blocks.push({kind: "table", index: current.tables.length - 1});
        inner = parsedTable.endIndex;
        continue;
      }
      if (!bodyLines[inner].trim()) {
        flushParagraph();
      } else {
        paragraph.push(bodyLines[inner]);
      }
      inner += 1;
    }
    flushParagraph();
    sections.push(current);
    cursor = endIndex;
  }
  return {
    title: titleLine ? titleLine.replace(/^#\s+/, "").trim() : null,
    sections,
    links: links(markdown),
    markdown_length: markdown.length
  };
}

process.stdout.write(JSON.stringify(parse(readInput())));
