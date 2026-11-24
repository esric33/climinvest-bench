Generate the complete {project_id} report described by the compiled v2 output contract.
Use the available retrieval and calculation tools as needed to satisfy the section
instructions, then call create_report with the complete Markdown document.

The first line must be `# ` followed by the retrieved project title. Follow it
with every section, subsection and required component in exact contract order.
Each `llm` component is one paragraph controlled only by its `instructions`.

PROJECT: {project_id}

AVAILABLE EVIDENCE — FULL UNFILTERED CATALOGUE:
{evidence_catalogue}

DERIVABLE CALCULATIONS — FULL UNFILTERED CATALOGUE:
{calculation_catalogue}

AVAILABLE TOOLS:
{tool_catalogue}

DOCUMENT AND SECTION INSTRUCTIONS:
{report_contract}

Table titles marked `metadata_only` describe components; do not render them as
extra captions. Emit only the components in the contract. A citation to a
required collection child also covers its ancestor collection; a citation to
the collection alone does not cover a specifically required child.
