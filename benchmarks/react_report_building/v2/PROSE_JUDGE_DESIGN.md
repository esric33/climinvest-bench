# Prose-only automated judging

**Current design: at most two judge calls per section.** This replaces the cancelled exhaustive per-fact/per-citation inference plan. Candidate tables are excluded from both calls. Existing benchmark generation results and deterministic scores are unchanged.

## 1. Units and inputs

Both generation modes use the same procedure. Extract each of the 15 sections from the assembled candidate report, then retain its prose, lists and quotations. Remove Markdown/HTML tables, malformed pipe-table rows, headings, link-definition metadata and code blocks. Preserve source hashes and character mappings for audit. Correct information appearing only in a table cannot satisfy a prose requirement.

The model, pinned revision, serving settings, prompts, extraction rules and output schemas are identical for report-generated and section-generated candidates. Bind every job to its exact project, evidence condition, generation contract, gold evidence and candidate hash. Updated and missing-evidence instances use their own evidence, not the baseline answer.

| Call | Candidate material | Reference material | Output |
|---|---|---|---|
| Specification match | Section prose | Its original generation specification and relevant condition-specific facts | One boolean per explicit content requirement, plus diagnostic constraint verdicts |
| Citation support | Section prose with short, code-assigned citation markers | The evidence actually linked by each prose citation, deduplicated within the request | One boolean per citation occurrence |

One source used three times creates three verdicts **inside one citation-support response**, not three requests. A short key identifies each item; the model never has to reproduce a source ID or quotation.

## 2. Specification match

The original specification is authoritative. Its own sentences form a visible checklist, with no table-completeness checklist or hidden numeric obligation. The current 45 family/section specifications yield **163 content requirements and 29 separate constraints**. These are reusable instruction templates, not 192 separate model requests.

For the condition-aware pilot, code resolves each requirement's dependencies against
the authoritative reference evidence and emits its availability and active
acceptance rule. For example, an unavailable count requires an acknowledgement,
not a number; a known zero remains a number; a fixed methodological definition
remains required. These rules never depend on candidate claims or control labels.
The original instruction is retained for audit, but the model receives only the
resolved rule, avoiding contradictory unconditional instructions in its input.
Unknown statuses, missing dependency targets and changed source instructions fail
preparation. Current reviewed compilers cover risk, MRV, and costs/financing
sections across the three report families; the other 12 section types need
explicit dependency review before full judging. Unsupported sections fail before
inference. The frozen fresh-section smoke includes a documented sensitivity:
the generic scalar rule asks for the funding-sum amount even though the source
sentence asks to describe its qualification. Treat any resulting discrepancy as
a rubric question, not automatically as a judge error; do not revise that frozen
run after reading its candidates.

Pure prohibitions and the executive-summary style instruction are kept in a separate constraints group. They do not inflate content coverage when prose is absent. An instruction containing several explicit clauses requires those clauses; its conjunction is visible in the original wording. Respect alternatives, applicability gates and phrases such as “a few”, rather than silently requiring every source fact.

Reference data can include facts that were displayed in the generation table: the judge needs those facts to assess the prose. **The candidate table itself is never supplied.** Providing a reference fact does not make its recital an obligation. Full risk registers are omitted from the coverage reference; selected maximum-risk records remain. KPI MRV/delta context is projected to the selected priority records, with aggregate counts supplied separately. An actually cited collection remains available in full to the independent support call.

Accept faithful paraphrases, equivalent units, reasonable rounding and defensible evidence-grounded interpretation. Distinguish unavailable evidence, documented source gaps, unscored records, incompatible units, inapplicability and known zero. An explicit limitation may be the correct content. A correct uncited answer can satisfy coverage.

### Risk-section example

The checklist asks whether the **prose**:

1. Discusses the complete maximum-score set in the requested order and states the selected count.
2. States the scored and unscored counts.
3. Explains why each selected risk matters and whether mitigation leaves a material residual issue.
4. Gives the specified rank-product interpretation and identifies it as a screening index rather than expected loss.
5. Treats unscored records as an evidence limitation rather than low risk.

“Do not narrate every risk row” is a separate constraint. There is no demand to narrate every nonselected record or repeat every table cell. Duplicate risk names retain their descriptions and source identities in the reference.

## 3. Citation support

Extract actual citation occurrences from prose using the audited Markdown-aware extractor. Preserve literal `missing.` markers and repeated occurrences. Code assigns `c0`, `c1`, etc., resolves the evidence, and inserts these short markers into the prose supplied to the judge. Citation presence, identifier validity and malformed syntax remain deterministic observations; the judge is not asked to discover citations or count them.

For each occurrence, assess whether **its own linked evidence supports the claim it accompanies**. Use surrounding prose to identify the relevant clause. One atomic field citation need not support unrelated adjacent claims. Another citation's evidence cannot rescue a wrong link. Parent risk/KPI identity is supplied only to identify the subject; it cannot substitute for the linked value.

A correct number attached to the wrong source can fail support while its content passes specification match. Conversely, a supported statement can omit what the section was required to discuss and therefore fail specification match. These are independent calls and separately reported results.

Unresolved source IDs and syntax problems are recorded explicitly. The raw support call judges supplied citations only. Its supplied-citation precision is a diagnostic: zero prose citations gives N/A precision. The headline **supported required-citation coverage** also includes missing required items in its denominator, as specified below. A section with required citations and no supplied citations therefore receives zero coverage without an extra model call. This is a focused assessment of required prose and cited claims; it is not exhaustive verification of every additional uncited assertion.

## 4. Results and aggregation

Each response uses a strict object of code-assigned boolean keys plus a short optional-in-meaning notes string. Notes assist review but do not determine mechanical validity. Missing keys, wrong types, truncated output or transport failures are missing/invalid measurements, never semantic zeroes. All raw responses are saved before validation.

- **Prose requirement satisfaction:** satisfied content requirements / all explicit content requirements in that section. Missing required content stays in the denominator and receives no credit; empty prose scores zero. This excludes citation requirements and candidate tables.
- **Constraints:** retain individual verdicts for diagnostic review, but omit this aggregate from headline results tables. Do not add their easy negative checks to content coverage.
- **Supported required-citation coverage:** required citation-target groups with at least one supported matching prose citation / all required citation-target groups in the assembled report's frozen executable gold. Sum both counts over its 15 sections before dividing. Missing required groups receive zero credit. Repeated citations cannot increase credit for one group; alternatives within a group are equivalent ways to satisfy that group. Preserve literal missing-evidence markers and use the correct project, section and evidence condition. No required groups means N/A, while required groups with no supplied citations means zero. Supplied citations outside the required groups cannot compensate for omissions. Verify the gold, candidate and judgment bindings before aggregation.
- **Supplied-citation support precision (diagnostic only):** supported actual prose citation uses / assessed prose citation uses, with N/A where there are none. Keep this separately labelled measure to identify unsupported extra citations; it is no longer the headline support column.
- **Reporting:** the new required-citation coverage metric uses one required-group fraction per assembled report, then equal report/project means. Thus a missing required item carries the same weight as another required item in that report, including when its section contains many obligations. Preserve section rates and their equal-section average as diagnostics. Existing prose requirement satisfaction retains its original equal-section average within each report, then equal report/project means. Report model × generation mode × evidence-condition results, retain all item counts, and state these weighting differences. A pooled ratio over every project's items is also a diagnostic rather than the headline mean.
- Do not combine content and citation support into one opaque judge score.

The coverage revision is offline aggregation of existing verdicts, approved on 17 September 2026; it does not change frozen inference requests, raw judgments or cache identities. Its report-level required-item denominator replaces the old equal-section occurrence-precision aggregation; section averages remain diagnostic. This choice was made before inspecting significance tests for the revised metric. A matching supported citation demonstrates support from a required source group, not a new semantic judgment that the exact required claim was cited. Keep content satisfaction separate and do not describe the coverage score as exhaustive claim verification.

Distinguish an omission in the generated report from a failed judge response. An omitted required citation is a known zero; a supplied citation whose judge response failed is unmeasured. Invalid applicable measurements leave the corresponding report metric missing under the complete-metric reporting policy, rather than becoming zero or disappearing from the denominator. Finished generation attempts lacking required terminal outputs retain the benchmark's separately declared end-to-end failure policy; they must not be silently excluded as judge failures.

The raw inference cache depends on the actual request and pinned serving configuration, not the validator version. Validation and aggregation can therefore be corrected without regenerating the model response. Identical requests can be reused in the full run. No semantic retries or answer repair are performed.

## 5. Smoke, review, full run

1. **CPU preparation:** verify all 45 specifications, source bindings, prose-only extraction, exact schemas and the two-call bound. Count tokens using the pinned tokenizer; compare with the server's token counts during serving.
2. **Serving/control smoke:** use both real schema paths and four crossed positive/negative examples. Eight small calls verify that correct content and supported citation use can vary independently. Protocol failure is distinct from semantic disagreement.
3. **Actual smoke:** twelve sections, at most 24 calls. Nine risk sections cover three families × complete/missing/updated evidence; three MRV sections exercise selected sets and mixed statuses. Include Luna and Muse and both generation scopes. This is a targeted smoke, not a claim to have empirically validated all section types.
4. **User review:** produce readable Markdown with candidate prose, the exact requirements, condition-specific evidence, every verdict, linked citation evidence, notes and timing. User reviews the output before full judging. If a prompt change is needed, version it and repeat the small smoke.
5. **Full judging:** freeze the reviewed protocol, then use the same compiler, prompts, model/settings, validator and cache for the full set. No automatic promotion from a completed smoke to a full run.
6. **Independent manual audit:** after the full run, use the agreed 30 sections and 30 citation uses total, as below.

Requests never silently truncate evidence, clamp the output budget or fall back to a call per citation. An oversized section is reported for review before inference. Empty prose is deterministically zero content coverage. No citations requires no support inference: it is N/A for supplied-citation precision and zero for required-citation coverage whenever required groups exist.

### Workload bound

| Population | Section instances | Maximum semantic calls |
|---|---:|---:|
| Actual smoke | 12 | 24 |
| Luna + Muse, 440 reports each | 13,200 | 26,400 |
| Six models, 440 reports each | 39,600 | 79,200 |

Empty sections, citation-free sections and exact cache reuse reduce those bounds. Derive the elapsed-time forecast from smoke timings **separately for the two call types**, including their input/output sizes. Do not assume that a section batch takes the same time as one old atomic judgment. As arithmetic only, 79,200 calls at ten seconds each would be 220 GPU-hours, or 55 hours with four equally loaded GPUs before overhead; this is not a measured forecast.

## 6. Final manual validation: 30 sections + 30 citation uses total

The user selected a total budget across the six models, not a per-model budget.

- Select **five section assessments per model** and **five citation uses per model**. Balance generation modes and complete/missing/updated evidence across the total sample; spread projects, report families and section types.
- Freeze a sampling seed and selection manifest. Sample after outputs exist, without using the automated verdict to select flattering cases. Exclude smoke/development cases and previously reviewed pilot cases. Prefer projects outside all development pilots when eligible; do not treat later smoke projects as unseen merely because they were outside the original three-project pilot.
- Sample citation uses separately, at most one from a given section, and avoid duplicate inference inputs. Do not require them to belong to the 30 coverage sections.
- Draw from valid model-generated judgments for the semantic agreement study. Report mechanical failures, missing measurements and deterministic special cases separately.
- Give the annotator prose + checklist + reference facts for coverage, and prose + the selected citation + its linked evidence for support. **Hide automated verdicts, notes and model identity until labels are saved.**
- Annotate each explicit content requirement within a selected section. Thus “30 sections” contains more than 30 requirement-level decisions; preserve the section as the sampling/uncertainty unit. Mark ambiguity separately rather than forcing an uncertain human label.
- Save human labels independently. Then reveal predictions and report agreement, false-positive/false-negative counts and confusion matrices separately for content and support. Report uncertainty; resample whole sections for requirement-level agreement so multiple requirements from one section are not treated as independent examples.
- This supports a pooled agreement estimate. Five examples per model do not support reliable per-model judge-accuracy claims. Report the sampling design and actual denominators.
- Preserve original labels when recording adjudicated disagreements. If the final audit is used to tune the judge, it becomes development data; use a fresh sample for a new independent validation claim.

## Implementation and prepared artifacts

### Prompt revision 2 smoke (16 September 2026)

The first two-call smoke served correctly (8/8 controls, 24/24 actual responses),
but semantic review found missing-evidence false negatives, incorrect treatment
of known-zero unscored counts, an invented selected-set member, and uneven
assessment of compound instructions. These results are development diagnostics,
not accepted production scores.

Prompt revision `2026-09-16-r2` makes evidence-state handling an explicit decision
procedure, applies conditional requirements before checking prose, requires every
applicable clause, and limits source grounding to the current request's records.
The model, serving treatment, extraction, original 24 jobs and output schema stay
unchanged. Prompt text and revision are bound into new inference cache identities.

The revised smoke has 28 synthetic control calls and 36 actual calls: the original
12 sections plus six previously unjudged sections from FP090, FP039 and FP128.
Those three additional projects are also development data once inspected; exclude
their smoke cases from the final manual audit. They are independent of the cases
used to draft this prompt, not a claim to have validated every section type.
The controls include positive/negative missingness, zero, inapplicability,
selected-set membership and compound-instruction cases. No full-run promotion is
automatic; review real results as well as control agreement.

The revision-2 smoke completed: all 64 responses were mechanically valid, but
only 23/28 control verdicts agreed. Invented zeros were accepted in missing and
undefined cases, and real missing-evidence coverage remained incorrect, including
in a fresh project. This revision is **not qualified for full scoring**. See
`artifacts/reports/prose-two-call-judge-smoke-r2-2026-09-16.md` for the results.

### Condition-aware specification smoke (revision 3)

The user explicitly requested deterministic availability per requirement and a
resmoke. Revision 3 replaces the specification call's raw instruction list with
compiled acceptance rules. Indirect dependencies such as "each selected risk"
are explicit; source instruction hashes guard the reviewed mappings. Citation
support requests and their cache identities remain exactly revision 2. Model,
serving settings, prose, evidence and output schema remain unchanged.

The same 18 sections and 28 controls are repeated for direct comparison; the
FP090/FP039/FP128 cases first introduced in revision 2 are now development cases,
not fresh held-out validation. There are still only two calls per section.
Seventy CPU tests pass, including checks for mixed availability, fixed definitions,
known zero, candidate-independent rules and rejection of unreviewed mappings.
The prepared package is `artifacts/judge-pilot/2026-09-16-prose-two-call-v5/`.
This is a pilot qualification step, not permission or readiness for full judging.

The revision-3 smoke completed successfully. All 64 responses were mechanically
valid; specification controls improved from 12/14 to 14/14, while unchanged
citation-support controls stayed at 11/14. Review of the same 18 real sections
found improved availability handling but remaining false negatives, invented
wording in explanations and a false positive on an omitted fixed definition.
Raw content satisfaction rose from 70/90 to 77/90; this is not an accuracy
estimate. Both complete diagnostic snapshots are copied and checksummed locally.
Full scoring remains unqualified and has not started. See
`artifacts/reports/prose-two-call-judge-smoke-r3-2026-09-16.md` and the linked
per-section comparison for the complete review. No further rerun is automatic.

### Frozen-prompt fresh-section smoke (run r4)

The user requested a new sample to test generalisation rather than continuing to
tune the previous cases. Both system prompts and serving settings remain frozen.
The Costs and financing structure section now has a reviewed condition mapping
for all three families, authored from specifications/source facts before opening
the new generations. This extends the compiler to three section types; the other
12 remain unreviewed. The runtime recognises `not_applicable_dependency` as the
existing not-applicable state. Old request identities remain unchanged.

The fresh sample contains nine Luna and nine Muse sections from FP102, FP081,
FP193 and FP080, all outside the previous six development projects. Selection is
deterministic from metadata, including both generation modes, a missing/updated
cost, and comparable/undetermined/non-comparable scopes. One no-citation section
has N/A support without inference. The 28 prior controls are unchanged; no prompt
revision, semantic repair or full-run promotion is part of this experiment.
Package: `artifacts/judge-pilot/2026-09-16-prose-two-call-v6-fresh/`.

Run r4 completed: 35 valid actual model responses plus one deterministic N/A,
and all 28 controls mechanically valid (14/14 specification, 11/14 support).
Both new missing-cost examples receive appropriate availability credit. The
specification judge nevertheless rejects sensible 0.11x rounding in four cases,
and the support judge inconsistently rejects one such use. Other disagreements
include omitted caveats, number/style over-penalties, and an explicitly recorded
rubric strictness issue. No prompt retuning followed this fresh test. Raw scores
and diagnostic review are in
`artifacts/reports/prose-two-call-judge-fresh-smoke-2026-09-16.md`; these are not
human-labelled accuracy estimates. Full judging has not been launched.

- Core: `prose_judge.py`.
- Preparation: `scripts/cluster/prepare_prose_judge_smoke.py`.
- Runner and readable result export: `scripts/cluster/run_prose_judge_smoke.py`.
- CPU tokenizer preflight: `scripts/cluster/check_prose_judge_tokens.py`.
- Prepared smoke: `artifacts/judge-pilot/2026-09-16-prose-two-call-v3/`.
- Revised smoke: `artifacts/judge-pilot/2026-09-16-prose-two-call-v4/`.

The exhaustive bank is reused solely as a checksummed, condition-bound source-evidence store. Its old questions and per-citation inference plan are not used. The user separately authorized the two small GPU smokes after preparation; full judging has not been launched.
