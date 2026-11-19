# ReAct report-building benchmark v2

Version two evaluates whether iterative ReAct-style agents can construct a
calculation-enriched GCF bankability report from a fixed document model and a
project evidence store. It uses all 20 projects. The document model is adapted
from the Climinvest ESG Enhanced Bankability Report: its investment-committee
spine is retained, while unsupported EU-specific compliance scores and
investment recommendations are not invented for the GCF corpus.

The normative human-readable endpoint, aggregation, eligibility, and study
contract is [`design/scoring-and-study-spec.md`](design/scoring-and-study-spec.md).
The generated plan, compiled contracts, conditions, executable golds, and bound
hashes are its machine-enforced instances. Legacy V1 `QComplete` documentation
does not apply to V2.

## Document model

The pinned TraceMark compiler compiles three project-family templates:

- `asset_delivery` for physical asset and delivery projects;
- `financing_facility` for funds, facilities, and intermediated finance; and
- `land_use_nature` for land-use, forestry, agriculture, and nature projects.

Each project is assigned to exactly one family. The family is fixed benchmark
metadata, not an experimental condition. Every template has 15 visible sections:
11 shared bankability sections and four family-specific sections. The shared
sections cover executive assessment, project status, promoter and delivery,
climate rationale, technical readiness, costs and finance, financial
sustainability, impact and safeguards, KPIs and MRV, risk and constraints, and
conclusions and evidence requirements. Family sections supply the analysis that
would otherwise be artificial: capacity and commissioning for assets;
additionality, instruments, allocation, and mobilisation for facilities; and
land allocation, carbon consistency, and people/co-benefits for nature projects.

Tables expose evidence and deterministic results. Text beneath a table must
interpret the decision significance of those results rather than repeat its
rows. Every section has exactly one neutral, prompt-controlled `:::llm`
component and at least one table; a section can have more than one table where
that is useful. V2 does not turn TraceMark concepts such as `distill` or
`conclusion` into agent tools.

There are deliberately no target calculation-count or dependency-depth quotas.
A calculation exists only when it supports a report component or a deterministic
semantic obligation. The compiled DAG records its actual topology, source
closure, and section reach; unused calculation nodes fail validation. Longer
chains arise from the analysis, not from padding the graph.

## Evidence preparation

Evidence preparation is split into two inspectable, hash-bound stages:

1. `normalize_all20.py` rebuilds and atomizes what the project evidence actually
   says. It cleans representation but does not impute absent facts.
2. `enrichment_all20.py` fills contract gaps with explicitly
   disclosed deterministic benchmark assumptions. Enrichment never overwrites
   a normalized node, and synthetic values remain distinguishable from source
   claims in provenance and scoring.

KPI reporting priority is an important example of that separation. The complete
cleaned source KPI collection remains `dt.kpis`; the separate
`dt.kpi_reporting_priorities` collection labels the benchmark-only priority
assigned to each KPI. `calc.prioritized_kpis` joins them deterministically. The
nominal top two KPIs are selected using an inclusive cutoff: every KPI tied at
the second-ranked priority is included, so the selected set can contain more
than two records. This reporting priority is not project evidence and is not an
MRV-readiness score.

Risk priority is derived rather than enriched. Available source probability and
impact labels map `low=1`, `medium=2`, and `high=3`; the priority score is their
product. The report must identify every risk tied at the maximum available
score. A missing or invalid probability or impact leaves that risk unscored—it
is never converted to zero—and scored and incomplete counts remain visible.

Rebuild the two layers, in order, without provider calls:

```sh
python3 -m benchmarks.react_report_building.v2.normalize_all20
python3 -m benchmarks.react_report_building.v2.enrichment_all20
```

## Compiler and runtime contract

All deterministic calculations are compiled TraceMark `:::calculation`
components. Semantic collection calculations for risk and KPI selection are
registered in the same public calculation catalogue and participate in the same
DAG. The compiled contracts pin template and compiler hashes, exact sections,
subsections and components, table shapes, output-contract schemas, calculation
dependencies, applicability rules, and project-family bindings.

Rebuild and verify them with:

```sh
node benchmarks/react_report_building/v2/compile_contract.js --write
node benchmarks/react_report_building/v2/compile_contract.js --check
```

The agent uses the same four tools as the current demo:

```text
get_data(ids[])
calculate(ids[])
create_report(markdown)
create_section(section_id, mode, markdown?)
```

No extra document-model tool and no search tool is introduced in this
checkpoint. Prompts expose the usable evidence, derivable calculations, tool
descriptions, and section instructions. Those catalogues describe what is
available; they do not predetermine which retrieval or calculation calls the
agent must make. A calculation request names complete canonical `calc.*` result
IDs. The runtime resolves their registered dependency closure; operation IDs,
input bindings, parameters, and expression ASTs remain private.

Action schema v2 also supplies declared typed tool/ID-routing scaffolding:
`get_data` can express only complete `dt.*`, `reference.*`, or `req.*` IDs and
`calculate` only nonempty `calc.*` IDs. This rules out cross-namespace routing
but does not enumerate catalogue membership or choose a real or relevant ID.
It is held constant across final reference and candidate comparisons.

Whole-report and section create/update prompts receive the same complete
project catalogue, including irrelevant candidates. Catalogue entries do not
assert current availability; only tool observations establish available,
missing, or not-applicable evidence. The model-visible output requirements
describe table rows, record sources, and prose questions using public catalogue
descriptions. They omit exact retrieval-ID lists, inline ID placeholders, and
private evaluator bindings. The underlying compiled contract remains available
only to the runtime and scorer. This policy is versioned as
`react_report.prompt_policy/v3-full-catalogue-semantic-requirements`. Tool
observations likewise use a compact claim view while the full provenance,
enrichment recipe, generator metadata, and calculated nodes remain in the
runtime store and saved audit snapshot.

After a terminal submission, the runtime records diagnostics for the compiled
heading/component contract, table shape, citations, and available evidence IDs.
Those diagnostics never reject the terminal candidate and are never returned to
the model for revision. Section and whole-report agents therefore face the same
document model and evidence, differing only in generation scope.

## Executable gold

V2 gold is not a model-authored reference report. It is a project-resolved,
executable oracle containing:

- ordered sections, subsections, and typed components;
- the calculation DAG and resolved calculation or missing states;
- exact table records, typed cells, and citation targets; and
- output-contract-specific semantic obligations, allowed support IDs, and exact
  selected sets such as maximum-tied risks and priority KPIs.

It contains no expected prose. Consequently, building the complete gold corpus
uses zero provider calls and does not spend inference tokens. Prose can be
paraphrased freely if it satisfies the component's semantic obligations and
supports them with the permitted evidence. Deterministic metrics score structure,
tables, calculations, citations, missingness, selected sets, and update behavior;
an LLM judge can be added separately for semantic support or fluency.

Build baseline golds, or baseline plus every frozen condition, with:

```sh
python3 -m benchmarks.react_report_building build-gold-v2
python3 -m benchmarks.react_report_building build-gold-v2 --include-conditions
```

Gold artifacts pin the contract, prepared evidence, resolved state, and overall
gold hashes. Validation freshly resolves the same project/condition and rejects
missing, unexpected, corrupt, or stale artifacts.

`author-gold-v2` is retained only as an optional prose-quality diagnostic. Its
outputs are not evaluation gold, are not required for a benchmark run, and
should not be generated as part of routine corpus preparation. Manual review or
promotion of those drafts is likewise optional QA, not a prerequisite for
scoring agents.

## Scoring and study contract

For a completed record, the active V2 deterministic content score is a weighted
aggregate of structure (20%), tables (25%), citations and prose support
obligations (20%), calculation-bearing cells (25%), and missingness (10%).
Update records additionally expose a separate affected-content/unaffected-
preservation score and, for section scope, separate all-and-only routing
metrics. No reference prose or LLM judge contributes to that deterministic
score. It does not measure whether surrounding prose is true, coherent, or
answers the analytical question: unsupported assertions can retain the same
score when their tables and cited values are unchanged. Score outputs declare
`semantic_prose_quality_measured: false`. A calibrated semantic assessment is
required before interpreting these results as overall report quality.

A report-scope record contains one episode. A full section-scope record contains
15 independently scheduled episodes that are composed and scored as one
scientific observation. Partial section smokes remain unscored diagnostics.
Analysis must report both quality conditional on a valid completed record and
end-to-end quality with every planned failure retained as zero, while preserving
failure classes as separate operational diagnostics.

Exact component formulas, update semantics, paired aggregation rules, full-plan
counts, reproducibility requirements, and the decisions still open before an
inferential run are frozen in the
[`V2 scoring and study specification`](design/scoring-and-study-spec.md).

## Conditions and zero-provider validation

The authoritative perturbation population contains one mask and one mutation in
each of five topology categories for every project: 100 masks and 100 mutations.
The categories distinguish values with and without calculation descendants,
single-section and cross-section fan-out, and collections with cross-section
descendants. Selection uses the assigned family DAG and applicable evidence;
conditions pin contract and prepared-evidence hashes and fail closed when stale.

Rebuild the conditions and executable gold, then run the all-project preflight:

```sh
python3 -m benchmarks.react_report_building generate-conditions-v2
python3 -m benchmarks.react_report_building build-gold-v2 --include-conditions
python3 -m benchmarks.react_report_building preflight-v2 \
  --output /tmp/climinvest-v2-preflight.json
```

The preflight resolves all 20 projects and their family contracts without a
provider. Explicit `not_applicable` inputs are accepted only where the selected
contract permits them; dependent calculations remain visibly unavailable rather
than becoming fabricated zeroes. Any smaller diagnostic selection is
operational only and is not the study population.

After the zero-provider gates pass, exercise the deterministic controller without
an API key:

```sh
python3 -m benchmarks.react_report_building smoke-v2 --scope report
python3 -m benchmarks.react_report_building smoke-v2 \
  --scope section --section risk_and_bankability_constraints
```

Only then should a provider-backed smoke be considered. The cluster runner,
immutable artifact handoff, and fixed-judge workflow are documented in the
repository root README and
[`manifests/climinvest-v2/README.md`](../../../manifests/climinvest-v2/README.md).
The model catalog is
[`manifests/climinvest-v2/catalog.yaml`](../../../manifests/climinvest-v2/catalog.yaml),
and the candidate reasoning-behaviour matrix is in
[`design/model-slate.md`](design/model-slate.md).
Operational observations and next-campaign practices—including the storage,
two-stage smoke, 7+1, cache, and monitoring design—are recorded in
[`manifests/climinvest-v2/OPERATIONS.md`](../../../manifests/climinvest-v2/OPERATIONS.md).

## Per-model provider workflow

Each catalog treatment has an independent directory under
`manifests/climinvest-v2/models/<alias>/`. Its `smoke.study.yaml` contains four
scientific records and five provider episodes: whole-report completion, ordinary
section completion, a missingness section, and a two-section update covering an
affected rewrite and unaffected retention. Its `full.study.yaml` freezes the
complete 20-project design for that treatment. The matching
`generation.cluster.yaml` exposes separate `smoke` and `full` cluster targets;
smoke is the safe default.

The checked-in full study is an executable definition, not evidence that a
candidate is qualified or promoted. Every candidate remains unpromoted until an
operator reviews its exact smoke plan, provider readiness, protocol behaviour,
terminal outcomes, deterministic score diagnostics, retry/cost profile, and
then explicitly approves that treatment's full target. A smoke result never
starts or authorizes a full run automatically.

The current v3 action interface requests deterministic calculations by canonical
result ID, resolves their dependency closures inside the controller, and uses
the provider response boundary for terminal Markdown. Model observations retain
all values and citation IDs while inheriting documented default metadata inside
collections. Exact duplicate calls in one fully parseable response execute once
but remain visible in raw and emitted-action accounting.

Terminal capture remains separate from output quality.
`all_terminal_submissions_recorded` means every selected episode produced an
accepted terminal action; `all_terminal_outputs_valid` and
`all_output_contract_diagnostics_valid` mean every captured candidate passed its
post-submission contract diagnostic. Valid, invalid, and missing diagnostics are
also counted explicitly. None of these diagnostics creates a model repair turn.

The normal runner requires a readiness report bound to the exact plan. Cluster
launchers explicitly bypass that repeated gate after validating their committed
study config; they rely on the release-time dataset checks instead of rerunning
the ten-minute deterministic fixture in every Job. Evidence from one plan does
not authorize a changed prompt, adapter, catalogue, model treatment, retry
configuration, or scope. Full-run review remains subject to the active
[`scoring and study specification`](design/scoring-and-study-spec.md).
