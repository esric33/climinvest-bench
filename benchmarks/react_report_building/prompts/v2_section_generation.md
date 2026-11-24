Generate the complete requested {project_id} section from the compiled v2 output
contract. Use the available retrieval and calculation tools as needed to satisfy
the section instructions, then call create_section with section_id and the complete Markdown.

The submitted Markdown must begin exactly `## {section_heading}` and contain every
required subsection and component once in order. Each `llm` component is one
paragraph controlled only by its `instructions`.

PROJECT: {project_id}
SECTION ID: {section_id}

AVAILABLE EVIDENCE — COMPLETE PROJECT CATALOGUE (includes unrelated items):
{evidence_catalogue}

DERIVABLE CALCULATIONS — COMPLETE PROJECT CATALOGUE (includes unrelated items):
{calculation_catalogue}

AVAILABLE TOOLS:
{tool_catalogue}

SECTION INSTRUCTIONS:
{section_contract}
