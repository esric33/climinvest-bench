# V2 scoring and study specification

Status: **active normative V2 specification**
Score schema: `react_report.score/v3-executable-gold`
Scoring policy: `react_report.executable_gold_scoring/v2-component-alignment`
Last reconciled with the implementation: **2026-09-05**

This document is the authoritative human-readable scoring and study contract
for the V2 executable-gold benchmark. The generated study plan, compiled
contracts, condition manifest, executable golds, and their bound hashes are the
machine-enforced instances of this contract. If this document and a bound
artifact disagree, do not run or merge results: reconcile the discrepancy,
version the affected artifact, and create a new plan.

The legacy V1 `QComplete` score is not a V2 endpoint. V2 does not compare model
prose with a reference report and does not require provider-authored gold prose.

## Research questions

V2 is designed to answer three related questions:

1. How does the driving model affect successful completion, deterministic
   report quality, update correctness, cost, and latency on the same frozen
   project-condition instances?
2. How does one whole-report trajectory compare with 15 independently generated
   section trajectories that are composed locally into the same report
   contract?
3. How robust is each model and generation scope to missing evidence and to
   evidence updates with different dependency and section fan-out?

The driving model and generation scope are the primary experimental factors.
Task and perturbation category describe the benchmark case. Template family is
fixed project metadata and is reported diagnostically; it is not an assigned
experimental treatment.

## Frozen population, tasks, and conditions

The population contains all 20 projects in
`data/study/twenty-project-study-population.json`, each bound once to one of the
three compiled template families. Every project has 15 visible report sections.

Each project has 11 frozen condition states:

- one unperturbed `complete` state;
- five `missingness` masks, one in each topology category; and
- five `update` mutations, one in each topology category.

The five categories are:

1. `value_without_dependents.single_section`;
2. `value_without_dependents.cross_section`;
3. `value_with_dependents.single_section`;
4. `value_with_dependents.cross_section`; and
5. `collection_with_dependents.cross_section`.

Every state is evaluated in both `report` and `section` scope. The same frozen
project, condition, prompt/interface version, turn limit, and model treatment
must be used for paired comparisons.

## Scientific records and episodes

The scientific observation is a **record**, not an individual section episode.
A record is identified by model treatment, project, task, condition/category,
scope, and replicate.

- A report-scope record contains one ReAct episode.
- A full section-scope record contains 15 independent ReAct episodes, one per
  section, followed by a deterministic local composition step.
- A partial section smoke is diagnostic only. It is not a scientific record for
  quality comparison and deliberately has `score: null`.

For one replicate, each model-project pair has 22 records: 2 complete records,
10 missingness records, and 10 update records. With `M` models the full plan is:

```text
records  = M * 20 projects * 22 records
episodes = M * 20 projects * 11 states * (1 report + 15 sections)
```

Each per-model `full.study.yaml` under
`manifests/climinvest-v2/models/<alias>/` therefore expands to 440 records and
3,520 provider episodes. The additional 440 local reducers make 3,960 scheduler
work items for that treatment. The manifest catalog and each plan's bound model
treatment are the executable source of truth; the presence of a full study file
does not mean that a candidate has been promoted or approved to run.

Fifteen section episodes must never be analysed as 15 independent project
observations. Their quality and cost are reduced into one section-scope record.

Execution can partition a canonical full study into whole-project shards.
`--shard-index` is zero based; `--shard-count 4` assigns sorted projects round
robin, five per shard. This is an execution filter: study ID, treatment, record
keys, episode IDs and dependencies remain those of the canonical 20-project
plan. Each run binds its subset receipt and the complete canonical plan.
Resuming restores that subset and verifies its current implementation bindings.
Shard completion is distinct from canonical coverage. `verify-shards` checks
coverage and rejects divergent duplicate records; it does not establish
scientific readiness or authorize pooling incompatible treatments.

## Corrected native action and context contract

The corrected campaign explicitly selects `react_report.terminal_protocol/v2`:

- Fresh sections submit `create_section(section_id, markdown)`.
- Section updates choose `keep_section(section_id)` or
  `replace_section(section_id, markdown)` themselves.
- Fresh and updated whole reports submit `create_report(markdown)`.

The model authors the Markdown. There is no content renderer, affected-section
oracle, extra repair turn, or feedback from post-submission validation. At most
seven ordinary turns precede one reserved terminal opportunity. Early completion
is allowed; a terminal call must be the sole call in its response. Invalid
terminal attempts do not earn another turn. On the reserved turn, the configured
provider policy is explicit: `required` where qualified, or `auto` for an endpoint
that cannot support it. An update palette always offers both keep and replace;
named selection cannot force the model's answer. The effective policy and native
normalizations are retained in provenance. Legacy terminal-v1 configurations
remain explicitly distinguishable.

Stage A v4 allows the two retrieval/calculation calls together or sequentially,
in either order, and requires authentic continuation and a terminal response
within three requests. Four additional fresh terminal-schema checks make the
maximum seven generation requests. Same-response parallelism is recorded as
an optional capability, never a qualification requirement. Production keeps
the same eight-turn budget. Native call names and arguments are not repaired
for any model (`native_tool_calls/v4`).

Report and section create/update prompts now expose the complete project
catalogue without condition-specific availability claims. Output requirements
describe the necessary information and table rows semantically, omitting
per-component retrieval-ID checklists and inline identifier placeholders. The
private compiled bindings continue to drive evaluation. This changes the prompt
treatment and requires fresh qualification; old receipts remain historical.

Context budgeting uses the finalized Responses request, including schemas,
replayed native items, observations and evidence. Configurations bind context
window, safety margin and count mode. The direct OpenAI count API and the
self-hosted inference-free `vllm_responses` renderer provide input counts.
The latter is qualified against measured generation usage. Self-hosted counting
makes no generation request; the old `responses_probe` mode is retired. An explicitly
selected `conservative_bytes` mode is an estimate of serialized request bytes,
not a guaranteed token upper bound or an exact server-template count.
The requested output cap is reduced to the available space after the margin;
fewer than 256 available output tokens or a failed count stops generation. No
input or evidence is truncated. A margin must be at least 256 tokens. Actual
model windows, margins, supported reasoning and final-tool policies are owned by
the corresponding model task and bound in each study.

Mercury and Solar's corrected smoke treatments select
`openrouter_probe_on_clamp`, versioned as `react_report.context_budget/v2`.
It first applies the byte estimate to the complete request. If that estimate
would reduce or reject the requested output allowance, it sends one counting
probe through the same pinned OpenRouter Responses route, preserving the input,
schemas, reasoning and routing fields and setting `max_output_tokens: 1`.
Only a validated native `usage.input_tokens` count may replace the estimate.
Probe output is discarded, no tool action is executed, and no probe content or
feedback enters the trajectory. The exact count then determines whether to keep
the requested cap, reduce it, or stop before task generation. Probe failure
stops generation; it does not disable budgeting or introduce a token multiplier.
Requests that fit the initial estimate make no counting call and retain an
explicit `count_kind: estimate` receipt. Existing count modes retain their v1
policy identities.

Conditional probes require explicit request and USD cost limits bound into the
treatment. A durable per-run, per-model ledger reserves the route's worst-case
probe liability before sending a request. Reservations survive retry, restart
and concurrent workers; unknown charges retain that liability. Valid observed
cost settles the reservation, while a price-cap overrun or unsupported cost
precision is recorded and blocks further probes with liability retained.
A limit denial sends no request. Qualification may impose
stricter limits than the declared model policy, never broader limits.

Counting request totals, latency, usage and provider-reported monetary cost are
recorded separately from task-generation accounting. Receipts bind payload
hashes, the estimate, whether a probe was triggered, the effective output cap,
route metadata and bounded reservation state. Failed probes retain any reported
usage and cost; absent cache or reasoning counts remain unknown. A request that
does not trigger a probe, or is denied before HTTP, has zero probe overhead.
Compact accounting excludes raw response text. Preflight generation does not
count as a model action, repair turn or scientific output.

## Executable gold and eligibility

The executable gold resolves the project-specific contract into ordered
structure, typed tables, calculations and missing states, exact citation
targets, and prose support obligations. It contains no target prose. Candidate
wording may be freely paraphrased subject to those obligations.

A record receives a deterministic content score after its first syntactically
valid terminal submission and, for section scope, completion and composition of
all 15 first submissions. The submitted Markdown is immutable: output-contract
diagnostics and gold-derived scores are computed only afterward and are never
returned to the model. Operational nonterminal tool errors may still be repaired
on a later turn. Records with no accepted terminal submission, blocked records,
and intentionally partial section diagnostics have no conditional content score.

Analysis must report both:

- **conditional quality**, computed only for completed, scored records; and
- **end-to-end quality**, with every planned record retained in the denominator
  and any record without a valid score assigned zero.

Conditional quality must not be used alone to rank systems because doing so
rewards systems that fail on difficult cases. Provider/infrastructure failures,
protocol failures, turn-limit failures, and failed post-submission validation
diagnostics must also be reported separately rather than hidden by the zero
assignment.

## Deterministic V2 content score

Every component and the aggregate lie in `[0, 1]`. For a completed record, the
field `primary_score` is:

```text
V2Score = 0.20 * structure
        + 0.25 * tables
        + 0.20 * citations
        + 0.25 * calculations
        + 0.10 * missingness
```

These weights are part of score schema
`react_report.score/v3-executable-gold`. Changing a weight or component formula
requires a new score-schema version and rescoring all compared records.

### Structure

The structure component is:

```text
0.05 * exact report title
+ 0.45 * section-sequence F1
+ 0.35 * required-block-sequence F1
+ 0.15 * table-presence F1
```

Sequence matches use longest-common-subsequence precision, recall, and F1. The
block sequence covers required subsection headings and typed table/prose blocks
within their sections.

### Tables

Each required table receives:

```text
0.20 * exact headers
+ 0.25 * row-sequence F1
+ 0.45 * semantic cell score
+ 0.10 * exact shape
```

The component is the unweighted mean across required tables. Numeric values are
compared exactly after removing presentation separators. Unit strings are
compared exactly; aliases, scaling, and implicit conversion are not accepted.
For tables containing numeric units, semantic cell score is the mean of value
accuracy and unit accuracy; otherwise it is value accuracy. Surface formatting
accuracy is retained as a diagnostic and is not part of this score.

### Calculations

The calculation component applies the same typed value/unit comparison to cells
after the row-identity column in every table that is contractually backed by at
least one calculation. It scores the rendered deterministic results, not whether
the model happened to call `calculate` in a particular sequence. Calculation
table cells consequently contribute to both the table component and the
calculation component; that overlap is intentional in the current schema.

### Citations and prose obligations

Component matching uses headings, block types, table headers and ordered local
alignment. An extra caption remains a strict-format violation, but it does not
shift every later prose obligation or suppress recognizable later sections.
Table titles are non-rendered metadata unless the contract explicitly includes
a visible caption component. Collection and child citation requirements follow
the public component obligations, with parent coverage handled consistently.
The sensitivity marker is `(benchmark sensitivity variant)`, avoiding nested
square-bracket citations. These input and alignment changes require corrected
artifact bindings and the scoring policy above; historical scores are never
silently pooled with corrected scores.

The citation component is:

```text
0.40 * exact table-citation F1
+ 0.60 * prose-obligation score
```

Table citations are scored in their aligned table cells. Prose is never compared
with reference wording. For each required prose component, its obligation score
is:

```text
0.55 * required support-group coverage
+ 0.15 * numeric value accuracy
+ 0.20 * selected-set score
+ 0.10 * local citation-target validity
```

Selected-set score is 80% exact-membership F1 and 20% order F1. It is used for
requirements such as all risks tied at the maximum available priority and all
KPIs selected at the inclusive priority cutoff. Free-form equivalence for
categorical or textual claims is not judged; those claims receive deterministic
credit through required local support groups and valid citation targets.

### Missingness

Missingness is F1 over the unique expected and observed `missing.*` targets.
Repeated truthful references do not reduce the score. Expected and observed
occurrence counts are retained as diagnostics, while table scoring separately
checks whether missing values appear in the required cells.

## Update-specific scoring

Models receive a neutral inventory of citation IDs already visible in T0,
without affected-section labels or a suggested keep/replace decision. A whole
report update may retain T0 calculation citations in an unchanged section only
when the canonical T0 validation proof, report hash, section hash and contract
hash verify. Changed sections must use the current episode's citation context.
This inheritance rule establishes citation validity, not update correctness:
affected-content scores and unaffected preservation remain separate.

An update record first receives the five-component `V2Score` against the
executable T1 gold. It also receives a separate `update` result; neither is a
substitute for the other.

For affected sections, direct correctness is the mean of the section's resolved
table scores and prose-obligation scores. For unaffected sections, preservation
requires exact equality with the canonical T0 section after parsing its heading,
subheadings, tables, and paragraphs. The update content score is:

```text
UpdateContent = 0.50 * affected-section correctness
              + 0.50 * unaffected-section preservation
```

The record also exposes strict all-affected, all-unaffected, and all-and-only
content flags.

Section-scope updates query all 15 sections without exposing the private impact
set. Their explicit retain/rewrite decisions additionally produce:

- affected-section recall;
- unnecessary-regeneration rate;
- unaffected-section retain rate;
- decision coverage; and
- an all-and-only routing flag.

Routing metrics are deliberately separate from `V2Score` and `UpdateContent`.
Report-scope updates do not emit explicit per-section routing decisions, so
their routing result is null.

## Aggregation and comparisons

The following rules apply to V2 reporting:

1. Report each task and scope separately. Do not manufacture one pooled
   complete/missingness/update score without a separately versioned analysis
   decision.
2. For model comparisons, pair systems on the same project, task, category,
   scope, and replicate. For scope comparisons, pair report and section records
   on model, project, task, category, and replicate.
3. Compute project-macro results by first averaging the frozen category records
   within each project/task/scope cell, then averaging the 20 project values.
   This gives each project equal weight. Complete has one state per scope.
4. Also report micro diagnostics from the underlying atomic requirements and
   component counts. Do not substitute micro weighting for the project-macro
   comparison.
5. Report template-family strata as diagnostics. The unequal family counts
   (4 asset, 13 facility, 3 land-use) are not balanced treatment groups.
6. Cost for a section-scope record is the sum across its 15 episodes. Report
   input, cached input, output, reasoning, total tokens, model turns, tool calls,
   latency, retries, and protocol errors separately where available.
7. Keep all planned cells visible. Never delete a failed model-condition cell
   or silently replace it with a retry under a different plan.

The generic legacy summarizer is not yet the complete V2 analysis pipeline. In
particular, V2 analysis must join results back to the bound plan so blocked or
missing reducers remain in the end-to-end denominator, and it must aggregate
`update.score` and routing metrics explicitly.

## Provider readiness and run approval

Operational review applies to one exact model/protocol treatment and bound plan:

1. Zero-provider validation must pass before the release commit. A manual run
   remains fail-closed on a target-bound readiness report, while the checked-in
   cluster launchers use the explicit `--skip-readiness-gate` operator override
   to avoid replaying the deterministic fixture in every Job.
2. Stage A runs `benchrun native-smoke` against the exact production Responses
   adapter, native schemas and final-turn policy, using synthetic evidence.
   It checks real array arguments with optional same-response parallelism, stateless continuation, Markdown
   roundtrip and create/report/keep/replace capture. Four final-phase cases use
   explicitly scripted prior history; they are not seven real model calls.
   The hard bound is seven action requests per model. Direct exact-count and
   self-hosted modes allow up to seven configured counting requests. Conditional
   OpenRouter qualification instead shares one counting-request allowance
   across the complete gate, including a synthetic counting-only case that
   exercises the production request builder without generating a task answer.
   This verifies counting transport, not real-report reliability. Mercury's
   action-output cap is 2,048; Solar uses the same cap. Each has a total output
   ceiling of `7 * 2,048 + 1 = 14,337` tokens. Other gates default to 2,048
   unless their exact plan records an override. Gate limits remain distinct
   from the production
   32,000 cap. No retries or dataset loading occur. Receipts retain raw versus
   normalized conformance, hashes and costs.
3. Stage B runs the treatment's checked-in
   `manifests/climinvest-v2/models/<alias>/smoke.study.yaml` through its matching
   `generation.cluster.yaml` smoke target. The smoke covers whole-report and
   section completion, missingness, and affected/unaffected update behaviour in
   five records and six provider episodes, including a whole-report update.
   Mercury's conditional-count smoke is bounded to 12 probes and $0.15 total
   probe cost; Solar's is bounded to 12 probes and $0.50. These are shared
   per-run/per-model counting limits, additional to the action-request budget.
   They do not authorize a full study. Both models' full-study configurations
   retain the earlier conservative mode and remain held pending live smokes and
   discussion of explicit full-study probe budgets.
4. Review availability, protocol errors, terminal capture, post-submission
   diagnostics, deterministic scores where eligible, retries, latency, tokens,
   and cost. The smoke is an operational diagnostic, not a powered comparison;
   do not invent a post-hoc ranking or universal pass threshold from it.
5. A full target requires a separate plan review and explicit approval for that
   exact treatment. Smoke completion never launches, authorizes, or records an
   automatic promotion to full.

If the prompt, adapter, catalogue, model treatment, retry settings, limits, or
scope changes, create and validate a new plan. Evidence from the earlier plan
does not transfer to the changed treatment.

The conditional-count correction is qualified by offline code and receipt
tests. Live Stage A counting/serving evidence and Stage B benchmark evidence
remain pending; offline validation is not evidence that either route has
completed those gates. No full-study promotion follows from this correction.

## Freeze and reproducibility rules

Before an inferential run:

- all deterministic builds, contract checks, executable-gold validation, and
  all-20 readiness checks must pass;
- the exact model IDs, reasoning treatments, provider profiles, action protocol,
  prompts, public catalogues, adapter implementation, generation limits,
  conditions, contracts, and prepared evidence must be hash-bound into one plan;
- the executable-gold manifest must pass validation, and every scored record
  must retain the resolved executable-gold hash;
- provider readiness must be generated for that exact target plan before an
  inferential full run, unless its omission is explicitly approved and recorded;
- operational smokes must include complete scored compositions, not only partial
  section diagnostics; and
- results from different plan IDs must not be pooled as one treatment.

Retries and resumes preserve the same scientific record identity. They are
operational recovery, not additional replicates. Any deliberate change to a
model treatment or benchmark interface creates a new plan.

## Decisions still required before the full run

The deterministic record-level score above is frozen. The following broader
study decisions are not yet implemented or promoted and must be resolved before
making inferential claims:

1. **Model slate and reasoning treatment.** Per-model full definitions exist,
   but candidate treatments are not promoted or approved by their presence.
   Several IDA launcher reasoning behaviours remain unverified and must be
   resolved before authorizing the corresponding full target.
2. **Inferential procedure.** Confidence intervals, paired test/model choice,
   multiplicity control, minimum operational-completion gate, and treatment of
   a provider-wide outage need a written analysis plan and implementation. The
   project-macro and pairing rules above constrain that choice.
3. **Stochastic replication.** The current plan uses one replicate. It estimates
   performance for one sampled trajectory per cell, not within-model generation
   variance.
4. **Judged report quality.** Fluency, investment judgement, unsupported
   implication, and broader semantic faithfulness are outside the deterministic
   score. A human or LLM-judge endpoint may be added only as a separately
   specified secondary endpoint with a rubric, blinding, calibration, and
   reliability checks.
5. **Update headline.** `V2Score`, `UpdateContent`, and routing are currently
   reported separately. Any combined update headline would require a declared
   formula and a new analysis-contract version.
6. **Domain-validity review.** Deterministic correctness does not establish that
   every synthetic enrichment assumption or reporting obligation is the best
   investment-domain choice. Representative artifacts require subject-matter
   review before external validity claims.
