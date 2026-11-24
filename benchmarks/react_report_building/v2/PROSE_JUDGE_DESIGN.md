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
