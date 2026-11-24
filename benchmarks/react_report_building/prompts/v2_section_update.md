Independently decide whether the authoritative evidence change requires this
section to be rewritten. You receive no affected-section or impact oracle.

Make one explicit decision:

- RETAIN: if the original section remains fully valid, call keep_section with
  section_id only.
- REWRITE: if any direct, calculated, comparative, tabular, or interpretive
  content changes, call replace_section with section_id and the whole
  replacement section Markdown.

For REWRITE, the Markdown must begin exactly `## {section_heading}` and satisfy
every component in the exact section contract. Retrieve current evidence and run
canonical calculations as needed. Finish with exactly one keep_section or replace_section call.

PROJECT: {project_id}
SECTION ID: {section_id}
CANONICAL T0 SHA256: {canonical_t0_sha256}

PUBLIC AUTHORITATIVE UPDATE EVENT:
{update_event}

ORIGINAL T0 SECTION:
{original_section}

AVAILABLE EVIDENCE — COMPLETE PROJECT CATALOGUE (includes unrelated items):
{evidence_catalogue}

DERIVABLE CALCULATIONS — COMPLETE PROJECT CATALOGUE (includes unrelated items):
{calculation_catalogue}

AVAILABLE TOOLS:
{tool_catalogue}

EXACT REQUESTED-SECTION OUTPUT CONTRACT:
{section_contract}
