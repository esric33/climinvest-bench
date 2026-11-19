# V2 candidate model slate

Status: **configured candidates; none is promoted by configuration alone**
Executable source of truth:
[`manifests/climinvest-v2/catalog.yaml`](../../../../manifests/climinvest-v2/catalog.yaml)
and the per-model smoke/full studies under
[`manifests/climinvest-v2/models/`](../../../../manifests/climinvest-v2/models/)
Model calls made while preparing this slate: **none**

The original remote slate combines three closed GPT-5.6 cost tiers with nine
IDA-hosted models. A separately selected five-treatment API slate adds a fresh
native-tools Luna-medium 7+1 condition and four price-bounded OpenRouter
candidates under the same native-tools experiment contract.
A separate four-model selected local-vLLM slate exercises one 48 GiB
A6000 per model; Granite remains configured only to preserve its failed-pilot
provenance. Together they separate reasoning behaviour, active-compute scale,
model family, and hosting treatment rather than simply selecting the largest
checkpoints. A treatment is the checkpoint plus its serving, reasoning,
decoder, and action-representation configuration—not weights in isolation.
The matrix is an operational classification, not an intelligence ranking;
parameter counts are not directly comparable between dense and
mixture-of-experts models.

## Reasoning-behaviour matrix

| Reasoning behaviour | Efficiency anchor | Independent/balanced anchor | Capability/scale anchor |
|---|---|---|---|
| Configurable hidden reasoning | GPT-5.6 Luna | GPT-5.6 Terra | GPT-5.6 Sol |
| Configurable visible reasoning | GPT-OSS-20B | Gemma 4 26B-A4B* | GPT-OSS-120B |
| Native/default visible thinking | GLM-4.7-Flash | Qwen-3.8-27B | Laguna-S-2.1 |
| Instruct/non-thinking controls | Ministral-3-14B-Instruct-2512 | Aya-Expanse-32B | Llama-3.3-70B-Instruct |

\* IDA exposes `gemma-4-26b-a4b`; the smoke must establish whether that name
maps to Google's instruction-tuned checkpoint and which thinking template the
launcher applies.

## Why each cluster is present

| Cluster | Selection rationale | Main smoke question |
|---|---|---|
| Configurable hidden reasoning | The three GPT-5.6 variants form a closed, same-generation cost/capability ladder. Pinning all three to `none` holds requested reasoning effort constant across the ladder. | Do all three complete strict action JSON without unexpected reasoning-token or turn-budget growth? |
| Configurable visible reasoning | GPT-OSS-20B and 120B form a within-family active-compute/scale pair; Gemma supplies an independent efficient architecture with switchable thinking. | Does the IDA Responses layer isolate visible thought from action JSON and preserve usable state across turns? |
| Native/default visible thinking | Qwen, GLM, and Laguna stress the protocol with thinking-first or agentic behaviour from three unrelated families. | Does model-native reasoning survive multi-turn tool observations without contaminating JSON, exhausting the output cap, or preventing a terminal action? |
| Instruct/non-thinking controls | Ministral gives a compact control, Aya adds multilingual/model-family diversity, and Llama supplies a mature large instruct anchor. | Can conventional instruct models follow the same tool protocol directly, and does extra reasoning machinery actually improve benchmark completion? |

## Candidate treatments

| Alias | Served model ID | Provider | Requested reasoning effort | Comparative role |
|---|---|---|---|---|
| `openai-luna` | `gpt-5.6-luna` | OpenAI | `none` | Closed efficiency tier |
| `openai-terra` | `gpt-5.6-terra` | OpenAI | `none` | Closed middle tier |
| `openai-sol` | `gpt-5.6-sol` | OpenAI | `none` | Closed capability tier |
| `ida-gpt-oss-20b` | `gpt-oss-20b` | IDA | omitted (launcher default) | Open reasoning efficiency/scale pair |
| `ida-gemma4-26b` | `gemma-4-26b-a4b` | IDA | omitted (launcher default) | Independent hybrid-thinking anchor |
| `ida-gpt-oss-120b` | `gpt-oss-120b` | IDA | omitted (launcher default) | Open reasoning capability/scale pair |
| `ida-glm47-flash` | `glm-4.7-flash` | IDA | omitted (launcher default) | Efficient native-thinking anchor |
| `ida-qwen38-27b` | `qwen-3.8-27b` | IDA | omitted (launcher default) | Balanced dense native-thinking anchor |
| `ida-laguna-s-21` | `laguna-s-2.1` | IDA | omitted (launcher default) | Agentic/code-specialist anchor |
| `ida-ministral3-14b` | `ministral-3-14b-instruct-2512` | IDA | omitted | Compact instruct control |
| `ida-aya-expanse-32b` | `aya-expanse-32b` | IDA | omitted | Multilingual instruct control |
| `ida-llama33-70b` | `llama-3.3-70b-instruct` | IDA | omitted | Large conventional instruct control |

## Selected 7+1 API native-tools slate

These are new treatment identities, not silent replacements for completed or
unrestricted runs. Every smoke and full study sets `max_turns: 8` and
`turn_policy: reserve_final_turn`, giving the controller at most seven ordinary
turns and reserving the eighth for a terminal-only final answer.

| Alias | Served model and route | Reasoning | Privacy | Unit-price cap (input/output USD per 1M tokens) | Comparative role |
|---|---|---|---|---:|---|
| `openai-luna-medium-7p1` | direct OpenAI `gpt-5.6-luna` | `medium` | direct OpenAI policy | provider pricing | Fresh native-tools 7+1 condition derived from, but not pooled with, the completed textual Luna-medium reference |
| `openrouter-mercury25-preview` | `inception/mercury-2.5-preview`, only `inception` | `none` | data collection denied; ZDR required | `$0.04 / $0.15` | Very-low-cost non-reasoning API candidate |
| `openrouter-muse-spark13-contributor` | `meta/muse-spark-1.3-contributor`, only `meta` | `minimal` | **provider collection allowed; no ZDR** | `$0.10 / $0.20` | Explicit data-sharing Contributor candidate |
| `openrouter-glm53-flash` | `z-ai/glm-5.3-flash`, only first-party `z-ai/fp8` | `low` (mandatory) | data collection denied; ZDR required | `$0.075 / $0.25` | New large Chinese reasoning candidate |
| `openrouter-solar-pro4` | `upstage/solar-pro4`, only first-party `upstage/zdr` | `high` | data collection denied; ZDR required | `$0.30 / $1.20` | Document-intensive, long-horizon agent specialist from a new model family |

The OpenRouter policy is part of each model specification and therefore part
of the plan/checkpoint identity. It disables fallback providers and context
compression, requires support for every requested parameter, and pins the
listed endpoint tag. This trades automatic availability recovery for a clean,
auditable treatment: a capacity failure remains a failure instead of silently
changing provider, quantization, privacy, or price mid-run.
Solar additionally binds `parallel_tool_calls: true`: its exact Upstage ZDR
endpoint advertises that parameter, while the three earlier OpenRouter routes
continue to omit it so their serialized policies remain unchanged.

The Mercury and GLM caps match promotional prices scheduled to end on
2026-09-08 07:00 UTC and 2026-09-09 16:00 UTC respectively. They intentionally
fail closed if those prices rise; verify the live endpoint listing and decide
on a new versioned treatment rather than weakening a submitted plan in place.
Solar Pro 4 is discounted to `$0.03 / $0.12` through 2026-09-10 23:59 UTC,
but its treatment deliberately caps the normal `$0.30 / $1.20` rates so a
multi-day run cannot become partial merely by crossing the published promotion
boundary. Its `high` reasoning setting follows Upstage's deep-analysis operating
point and is part of the treatment rather than a Luna-matched scale control.
Its requests use a 1,200-second timeout and its doctor uses a 4,096-token output
allowance so long reasoning is not mistaken for a protocol failure. The smoke
and full Job deadlines are 12 hours and 14 days respectively; provider
concurrency remains one.
Muse Contributor is not a privacy-equivalent cheap substitute. Its model ID,
catalog entry, Experiment labels, and documentation all identify the required
provider data collection, and its paid smoke needs a separate informed consent
decision.

The original GLM route pinned DeepInfra FP8. Repeated doctor-only attempts on
that route returned HTTP 429, so it was replaced with first-party Z.AI FP8
before any successful GLM benchmark run. The revision preserves
`z-ai/glm-5.3-flash`, native tool calling, mandatory low reasoning, ZDR, no
fallback, and the `$0.075 / $0.25` cap; results must remain attributable to the
exact route rather than pooled across provider endpoints.

Each selected API Experiment defaults to a doctor-only target: an exact-profile
provider-native probe that must produce a genuine two-call batch in one model
turn, plus a stateless native-call continuation probe. These checks exit before
loading the benchmark. Review that paid-but-minimal artifact before separately
authorizing the four-record/five-episode smoke. OpenRouter benchmark work begins
at concurrency one with at most two scheduler attempts. The smoke is a protocol
and cost calibration, not an authorization for a full matrix. Review returned
provider, route metadata, tokens, USD cost, latency, 429s, and scientific
records before setting a dedicated API-key budget and considering one full
OpenRouter Job at a time.

The four pre-Solar selected API manifests also expose an exceptional `resmoke`
target for the explicitly approved post-harness-fix repeat. It reuses the
unchanged smoke study and resources with `RUN_PROVIDER_DOCTOR=false`; the
ordinary `smoke` target remains doctor-gated, and the resmoke does not authorize
a full run. Solar Pro 4 was introduced after that fix and therefore has no
historical resmoke target.

For IDA, omission is a deliberate capability-smoke treatment: it means the
launcher/model default, not `none`. The runner can send an OpenAI-style
`reasoning.effort` value, but it has no per-family mapping for Qwen, Gemma, GLM,
or Laguna template controls. Before authorizing a candidate's per-model full
target, record the actual launcher checkpoint and template, verify supported
reasoning controls with the service owner, and repeat the smoke under a new
bound plan if its treatment changes.

IDA studies serialize requests at concurrency one so provider-side queue time
cannot consume a request timeout. A future Cognition-backed treatment must also
start at concurrency one; raise that limit only after a dedicated capacity
smoke demonstrates a documented higher allowance.

The original remote studies and completed unrestricted Luna reference retain
their explicit `action_json_schema` textual-action contract. The five selected
API 7+1 treatments are different conditions: they set
`generation.action_protocol` to `native_tools`, expose the same semantic tool
schemas through each provider's native interface, and permit several
nonterminal calls in one model turn. The controller still applies the common
typed argument and tool/ID-routing
scaffolding under action schema v2. That scaffolding prevents cross-namespace
calls but does not enumerate the catalogue or select a real or relevant ID.
The model still chooses evidence and calculations and authors the report
content and citations that the benchmark evaluates.

The catalog also records `openai-luna-medium` as a completed unrestricted
textual-action reference treatment, the five selected native-tools 7+1 API
treatments above, four selected `okd-*` treatments, and one retained failed
Granite pilot. The fresh Luna 7+1 treatment must never be pooled with that
completed reference because the experiment contract changed. These treatments
have the same per-model study-file shape but are not members of the 12-candidate
original remote slate.
In particular, the local Qwen treatment shares a base model with the fixed judge
and therefore requires an additional same-model-bias warning for judged results.

## Self-hosted A6000 treatments

| Alias | Exact checkpoint revision | Context | Serving treatment | Action output |
|---|---|---:|---|---|
| `okd-qwen3-8b` | `Qwen/Qwen3-8B@b968826d9c46dd6066d109eabc6255188de91218` | 131,072 | automatic weight dtype, factor-4 YaRN, `hermes` native tool parser, vLLM 0.18 `qwen3` reasoning parser | `native_tools` |
| `okd-gpt-oss-20b` | `openai/gpt-oss-20b@6cee5e81ee83917806bbde320786a8fb61efebee` | 131,072 | vLLM 0.22.1 CUDA 12.9, native MXFP4 through Marlin, Triton attention, OpenAI/Harmony parser, GPT-OSS reasoning parser, developer-role `instructions`, and provenance-retaining exact channel-suffix normalization | `native_tools` |
| `okd-nemotron-nano-12b-v2` | `nvidia/NVIDIA-Nemotron-Nano-12B-v2@f428df0ec725fed457b89cfca54dc26500fb88c1` | 131,072 | trusted pinned remote code, float32 Mamba state, pinned NVIDIA `nemotron_json` parser ported to vLLM 0.18 imports | `native_tools` |
| `okd-granite31-8b` (retained failed pilot; not selected) | `ibm-granite/granite-3.1-8b-instruct@4009206d5fc95d2e65a7b7633e159d6e97e25d35` | 131,072 | vLLM 0.22.1 CUDA 12.9, BF16 weights, default unquantized KV dtype, prefix caching, `granite` native tool parser, no reasoning parser, revision-pinned native-derived Responses replay template at SHA-256 `f804371f46101776a3028ad7fc46ecae24decdbfa609f47a8d597a42a51da1cd` | `native_tools` |
| `okd-xlam2-8b` | `Salesforce/Llama-xLAM-2-8b-fc-r@a0efe39a575ef33d1d233cb2e799ae053b636c0e` | 131,072 | vLLM 0.22.1 CUDA 12.9, BF16 weights, default unquantized KV dtype, prefix caching, built-in `xlam` native tool parser, no reasoning parser, and image-internal `/vllm-workspace/examples/tool_chat_template_xlam_llama.jinja` template | `native_tools` |

The xLAM checkpoint is a modern non-Qwen 8B function-calling control. Its
checkpoint is CC-BY-NC-4.0 and its Llama 3.1 base remains subject to the Llama
3.1 Community License, so this treatment is restricted to research use rather
than presented as a commercially deployable candidate.

The native-tool doctor asks the model to choose a function automatically, while the
scientific smoke retains the common 32,000-token per-turn ceiling. Granite
replaces the local Ministral pilot because vLLM 0.18's Mistral Responses replay
split parallel function calls into an invalid assistant/tool message ordering;
that integration failure is not benchmark evidence about the checkpoint.
Granite's pinned Hugging Face template likewise omitted structured assistant
tool calls from replayed Responses history, so this treatment vendors vLLM
0.22.1's Granite template verbatim as an explicit integration override. Upstream
documents that file for Granite 3.0 and normally permits Granite 3.1 to use its
Hugging Face template directly, so the override remains smoke-gated rather than
being treated as a generic 3.1 recommendation. It serializes assistant calls
and maps tool outputs to Granite's `tool_response` role; the native `granite`
parser remains unchanged.

GPT-OSS, Granite, and xLAM use the digest-pinned x86-64 CUDA 12.9 vLLM 0.22.1
image.
The earlier GPT-OSS diagnostic on vLLM 0.18 exposed the upstream Responses
Harmony bug fixed by vLLM change `7f65f8442827196970b1f3b09cb56ca2f6ea7c5d`;
that pre-fix smoke is not promotion evidence. Qwen and Nemotron keep their
already-started vLLM 0.18 treatments. Results therefore retain serving-image
version as an explicit treatment attribute.
No local treatment uses the benchmark's former synthetic textual action
carrier or schema-constrained decoder. Each server enables automatic tool
choice and converts the checkpoint's own tool syntax into Responses function
calls. The controller preserves those raw items before applying the common
semantic tool schemas.

Nemotron's parser does not stop or discard thinking: it preserves text before
the model's `<TOOLCALL>` envelope as response content and extracts only the
enclosed call array. Local GPT-OSS likewise retains native Harmony analysis;
its Responses path accepts automatic tool choice rather than the forced
synthetic carrier used in the earlier smoke. The untouched raw response and
arguments remain available for provenance and protocol diagnosis.

The shared action contract provides typed tool/ID-routing scaffolding:
`get_data` takes complete `dt.*`, `reference.*`, or `req.*` strings, while
`calculate` takes a nonempty `calc.*` string. This makes cross-namespace routes
unrepresentable and is therefore a system-level treatment choice. It does not
enumerate the catalogue or choose a real or relevant ID, so identifier
selection remains model behavior. Invalid catalogue choices remain visible in
the trace and can affect episode outcomes and scores. Every final reference and
candidate run must use action schema v2.

Each server and study scheduler admit one active sequence so the configured
maximum context can fit on the A6000 without consuming a request timeout in a
server-side queue. Local calls allow 1,800 seconds for the 32,000-token output
ceiling. That is a per-call ceiling, not a cumulative entitlement: the Job
deadline remains an independent runaway bound, and full-run feasibility must be
estimated from observed smoke latency before submission.
Model-download and compilation caches are isolated by alias, exact revision,
and vLLM version on a stable PVC, while benchmark artifacts remain isolated by
run ID. Each newly introduced treatment advances through its own two separately
reviewed smoke gates; passing one model never promotes another model's serving
configuration.

These maximum windows reduce avoidable context failures but do not make all
episodes equivalent: the 131,072-token treatments can still truncate or fail on
longer accumulated ReAct histories. The paper must report observed truncation
and context failures and exact serving/parser provenance alongside scores.

## Two-stage smoke gates

Every new self-hosted model has two independent gates. They answer different
questions and retain separate plans, run IDs, receipts, artifacts, and approval
decisions.

### 1. Model-serving gate

The serving smoke proves that the intended server treatment can actually load
and carry the protocol. It uses the exact runtime image digest, model and
tokenizer revision, quantization and weight dtype, cache and KV settings,
context limit, GPU type, native tool parser, reasoning parser, and chat template
intended for the benchmark. It checks health and model listing, performs a
minimal generation, elicits one automatically selected native tool call, and
continues once after a tool observation. It exits before loading or validating
the benchmark dataset, so a server/parser failure does not spend ten minutes on
an unrelated dataset preflight.

Passing this gate establishes model loading and wire-protocol compatibility
only. It says nothing about whether the model can complete a report-building
task.

### 2. Representative benchmark gate

The benchmark smoke reuses the exact serving treatment that passed stage 1 and
runs the common FP083 slice: one whole-report completion, one ordinary section
completion, one cross-section missingness section, and one cross-section update
split into an affected rewrite plus an unaffected retain decision. That is
**five provider episodes, four scientific records, and nine total work nodes per
treatment**. The manifests remain independent per model; combining their smoke
results does not turn them into one shared plan.

Report two outcome classes separately:

- **Operational:** Job and scheduler completion, expected work-item count,
  artifact/export presence, trace integrity, retries, latency, truncation, and
  server/protocol errors.
- **Scientific:** terminal task completion, output validity, whole-report versus
  section performance, missingness handling, affected-update rewrite,
  unaffected-section retention, turn usage, and reported reasoning tokens.

A coherent scientific failure can therefore coexist with an operationally
successful smoke and should remain benchmark evidence, not be relabelled as an
infrastructure failure. Promotion after such a result requires the user's
explicit acceptance. A new treatment proceeds only as `serve-smoke` → reviewed
`smoke` → reviewed `full`, with fresh approval for every submission.

Once both exact-config gates are reviewed and promoted, the matching full target
does not repeat the automatic-choice doctor. Protocol misses during study
episodes remain recorded as scientific outcomes.

A zero value for reported reasoning tokens is not proof that no reasoning took
place: the compatibility layer may omit that telemetry. Native parsing makes a
recognized call structurally executable; it does not make its arguments
correct or improve the score by fiat. A successful smoke is evidence for an
operator's review, not an automatic promotion or authorization to submit the
full target.

## Upstream behaviour references

These references describe upstream model behaviour. The IDA launcher remains
the authority for the checkpoint and template actually served.

- [OpenAI reasoning-effort guidance](https://developers.openai.com/api/docs/guides/deployment-checklist#set-up-reasoningeffort)
- [OpenAI GPT-OSS-120B](https://developers.openai.com/api/docs/models/gpt-oss-120b)
- [OpenAI GPT-OSS-20B](https://developers.openai.com/api/docs/models/gpt-oss-20b)
- [OpenAI GPT-OSS-20B checkpoint](https://huggingface.co/openai/gpt-oss-20b)
- [Qwen3-8B](https://huggingface.co/Qwen/Qwen3-8B)
- [NVIDIA Nemotron-Nano-12B-v2](https://huggingface.co/nvidia/NVIDIA-Nemotron-Nano-12B-v2)
- [IBM Granite 3.1 8B Instruct](https://huggingface.co/ibm-granite/granite-3.1-8b-instruct)
- [Salesforce Llama-xLAM-2-8B Function Calling](https://huggingface.co/Salesforce/Llama-xLAM-2-8b-fc-r)
- [Gemma 4 26B-A4B instruction-tuned model](https://huggingface.co/google/gemma-4-26B-A4B-it)
- [Qwen-3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B)
- [GLM thinking modes](https://docs.z.ai/guides/capabilities/thinking-mode)
- [Laguna-S-2.1](https://huggingface.co/poolside/Laguna-S-2.1)
- [Ministral-3-14B-Instruct-2512](https://huggingface.co/mistralai/Ministral-3-14B-Instruct-2512)
- [Aya-Expanse-32B](https://huggingface.co/CohereLabs/aya-expanse-32b)
- [Llama-3.3-70B-Instruct](https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct)
