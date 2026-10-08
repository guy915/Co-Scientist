# Decision model evaluation and admission

Liquid's text-only `d1:free` API is the sole approved decision provider. Paid
models require a separate owner decision. `LIQUID_API_KEY` is a server-side
secret; the owner supplies a separate production key through the launch
runbook. Missing credentials or `DECISION_ENABLED=false` preserve the LLM path.
No call site is enabled by the client alone.

The client accepts typed `noul`, `choice` and `score` questions, validates
complete finite probability distributions and reserves every physical request
before HTTP. Binary confidence is the probability of the chosen answer; choice
and score confidence cannot exceed the largest probability. Swapped pairwise
judgments align A/B distributions and treat disagreement as zero confidence.

Context is bounded at 32,768 tokens using a conservative UTF-8 byte estimate
plus framing allowance for each question. Oversized inputs fall back in full;
they are never shortened to fit. Each question reserves the state again, since
providers can account for repeated question inputs. This bound may refuse text
that the provider's actual tokenizer would accept.

## Configuration

| Variable | Default | Effect |
|---|---|---|
| `LIQUID_API_KEY` | empty | Liquid API credential; absent means LLM fallback |
| `DECISION_ENABLED` | false | Decision-only kill switch |
| `DECISION_MODEL_NAME` | d1:free | Any other model is refused before dispatch |
| `DECISION_BASE_URL` | https://api.liquid.ai/decisions/v1 | HTTPS base; client appends /systemone |
| `DECISION_TIMEOUT_SECONDS` | 15 | Total HTTP deadline, bounded to 60 seconds |
| `DECISION_MAX_CALLS_PER_DAY` | 256 | Durable decision-only call ceiling |
| `DECISION_MAX_TOKENS_PER_DAY` | 4,000,000 | Durable conservative input-token ceiling |
| `DECISION_MAX_INPUT_BYTES` | 131,072 | Maximum serialized request bytes |
| `DECISION_MAX_QUESTIONS` | 32 | Maximum questions per request |

These are application ceilings, not published Liquid free-tier allowances.
The provider's free RPM/RPD and question/token limits remain unconfirmed.
A 429 starts a durable cooldown using Retry-After (60 seconds if missing),
with no automatic retry or paid substitution. Network errors, malformed output,
timeout, low confidence and decision-only exhaustion invoke the original LLM
callback. Cancellation and shared run/provider budget control signals propagate.
The existing LLM path still applies its own bounds and failure behavior.

Decision usage retains reservations on errors and survives client/process
recreation. The decision-specific quota and unchanged shared SR-01 admission
currently commit separately: both must succeed before I/O, and refusal of the
second conservatively retains the first. The writer transaction ends before
HTTP. W4 can combine reservations with its prospective EUR ledger once its
shared admission interface is available. No shared call/token limit is raised.
`LLM_ENABLED=false`, when supplied by W4, also disables decision configuration;
W4 remains responsible for the persistent/global kill-switch policy.

Physical telemetry includes decision requests in `calls`, distinguished by the
additive `decision_calls` field and `liquid/d1:free` model key. Reported input
usage is separate from reservation estimates. Model credentials and input text
do not enter production telemetry. Site integrations must preserve stored
schemas and add model/probability provenance with a short generated decision
note. Keep unvalidated sites on the existing LLM.

## Manual bake-off

`decision-bakeoff.yml` is workflow_dispatch-only. It downloads completed real
Benchmark artifacts, extracts research text without credentials/owner IDs,
renders current call-site prompts and obtains fresh judgments from the current
zero-priced OpenRouter default. Its original free-only routing/price guard
applies. Liquid answers the same prompt inputs; ranking also receives reversed
presentation. Model secrets are exposed only to the live evaluation step.
Presubmit tests use fake clients and no network.

Start with five cases per site, after announcing the dispatch on #332. The full
panel is limited to 150 unique cases per site, uses the first 100 for threshold
selection and the remainder for held-out validation. Requests are paced with
four-second gaps; errors stop that site's panel and preserve a partial report.
The temporary evaluation store allows up to 512 decision attempts and 32M
reserved decision tokens; the original shared ceilings also remain enforced.
No production setting is changed.

Results distinguish judge agreement from correctness. The paired one-sided
lower bound is `mean(d) - 1.645 * stdev(d) / sqrt(n)`, with a provisional -0.02
agreement tolerance. Fewer than 100 labels yield no threshold. Thresholds are
not adoption approval: ranking requires owner spot checks and mature-review
inputs; relevance also requires score/order agreement; proximity requires
full-pool equivalence and false-deduplication validation; safety needs risk-domain
coverage and class-specific false-allow checks. The initial report marks all
sites unadopted. The docs lane publishes the accepted training-use disclosure.

## Relevance draft

`DECISION_LITERATURE_RELEVANCE_THRESHOLD` stays unset until the local quality
panel passes. One ordered five-level question per candidate produces a
continuous semantic score for the existing 50/50 lexical fusion. Every candidate
must meet the calibrated threshold to accept its batch; otherwise the
original whole-batch LLM scorer runs. Accepted records carry a model/probability
note and a distinct retriever version; LLM fallback clears prior decision
provenance. Original abstract boundaries remain identical, with no extra
truncation to fit Liquid.

The manual workflow's `delay` input selects four- or thirty-second gaps. Thirty
seconds is the default after a large free Liquid batch returned 429; it is an
evaluation pacing choice, not a verified provider allowance. Provider errors
still stop the panel without retry. Reports retain the selected delay.

The manual site selector can evaluate one site without dispatching the others.
`quota_diagnostics=true` instead selects one relevance request with Liquid only.
It supplies no OpenRouter key, obtains no oracle labels and exports only bounded
numeric quota fields, recognized units/windows and existing safe headers.
It exports no error body, research state or arbitrary provider string. This mode
uses the same admission and timeout checks and never establishes adoption.
Relevance cases are production-sized batches of up to ten unique papers. The
first complete batches providing at least 100 paper labels calibrate the
threshold; subsequent complete batches form the holdout. Reports distinguish
paper agreement/calibration from batch acceptance, semantic ordering and
request savings. Lexical-fusion selection needs separate validation before
adoption. No threshold or production credential is supplied by the draft.
