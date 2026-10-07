# Azure readiness plan

Prepared 7 October 2026 for the later Azure implementation lane. This PR changes
documentation only. Deployment clicks
belong to Guy; no code, provider defaults, production or hosting settings change
here. Coordination: [Azure readiness on campaign board #332](https://github.com/guy915/Co-Scientist/issues/332).
The portal checklist is [azure-setup.md](azure-setup.md).

## Decisions and status

Owner decisions: Azure AI Foundry; Global Standard, pay per token; only **Direct
from Azure** models; supervisor `gpt-6-luna`, worker `gpt-5-nano`; effort never
above `medium`; retain an explicitly selected free provider. Startup credit is
funding, not a spending limit.

Owner-reported account state, **unconfirmed independently**: project
`guybarel2006-4361`, Default Directory (`guybarel2006gmail.onmicrosoft.com`),
subscription **Azure subscription 1** (ID ending `181e1dfbb5b3`), Azure Plan under
a Microsoft Customer Agreement; $200 startup credit, displayed as €175.99,
6 October 2026–4 January 2027, then card billing; Marketplace purchases policy
**No**; `monthly-1-eur-alert` at €1/month, email only. The subscription's actual
credit application must be checked after the smoke calls. Do not derive an
ongoing USD/EUR exchange rate from the credit's displayed conversion.

Guy chose to spread the remaining startup credit through **4 January 2027**.
Current remaining credit is **unconfirmed**;
if €175.99 remains on 7 October, pace about **€1.9554/day over 90 calendar days**.
Use the dated EUR budget schedule below, carrying unused allowance forward and
preserving a hard total limit. No settings are deployed here. The existing €1
email alert can remain an early-warning alert.

## Microsoft facts

Checked 7 October 2026. “Confirmed” means supported by the cited Microsoft
source; it does not mean this account has been inspected or a deployment tested.

| Fact | Status and evidence |
|---|---|
| Both models are Azure-direct catalog models | **Confirmed:** [Luna model card](https://ai.azure.com/catalog/models/gpt-6-luna), version `2026-09-22`, and [Nano model card](https://ai.azure.com/catalog/models/gpt-5-nano), version `2025-08-07`. The cards identify OpenAI as publisher and Direct from Azure as the billing collection. Publisher name alone does not decide credit eligibility. |
| Luna Global Standard USD prices per million tokens | **Confirmed:** short-context input **$0.10**, cache read **$0.01**, cache write **$0.125**, output **$0.50**; long-context input **$0.20**, cache read **$0.02**, cache write **$0.25**, output **$0.75**. [Azure launch pricing table](https://azure.microsoft.com/en-us/blog/gpt-6-astra-sol-and-luna-for-production-agents-in-microsoft-foundry/) and [current Azure pricing](https://azure.microsoft.com/en-us/pricing/details/azure-openai/). |
| Nano Global Standard USD prices per million tokens | **Confirmed:** input **$0.05**, cached input **$0.005**, output **$0.40**. [Azure pricing](https://azure.microsoft.com/en-us/pricing/details/azure-openai/), `GPT-5-nano Global` row. The text renderer showed `$-`; a direct read of that same Microsoft's page found numeric `data-amount` regional values `0.05`, `0.005`, `0.4`. These are Azure values, not OpenAI list prices. |
| Cache writes | **Confirmed:** newer families, including Luna, have a write meter; Nano predates GPT-5.6 and has no extra cache-write charge. Record `cache_write_tokens` as well as reads. [Microsoft cache documentation](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/prompt-caching). **Unconfirmed:** exact account meter reconciliation and whether the write rate replaces or adds to uncached-input billing in the actual invoice; reserve the additive amount until reconciled. |
| The brief's universal “over 272k input costs more” rule | **Unconfirmed for these exact deployments:** Luna has separate short/long prices, but the inspected Luna card/table did not define the boundary; the explicit 272k label on the pricing page describes GPT-5.4. Do not apply its threshold universally to Nano. Before allowing long requests, verify the Luna boundary on the signed-in card; otherwise reserve long-context prices for every Luna call and enforce an input bound. [Pricing](https://azure.microsoft.com/en-us/pricing/details/azure-openai/). |
| Responses reasoning request | **Confirmed:** `POST /openai/v1/responses`, `model` is the **deployment name**, `input` carries the prompt and `reasoning: {"effort": "medium"}` carries effort. Use `max_output_tokens`, not Chat Completions' `max_completion_tokens`. [Responses guide](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/responses). |
| Effort and tools | **Confirmed:** both support Responses, structured output and function tools. Luna supports reasoning including `none`; original GPT-5 Nano supports `low`/`medium` and must not be assigned `none` without model evidence. Preserve returned reasoning items alongside function calls/results in later turns. [Reasoning guide](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/reasoning). |
| API version | **Confirmed:** the v1 OpenAI-compatible API uses a base URL ending `/openai/v1/` and does not need a dated `api-version` query. Keep the requested `AZURE_OPENAI_API_VERSION` configuration, validate `v1` for this adapter, and reject unsupported dated settings rather than silently ignoring them. [API lifecycle](https://learn.microsoft.com/en-us/azure/foundry/openai/api-version-lifecycle). |
| New-subscription TPM/RPM | **Confirmed published Tier 1 Global Standard:** Luna **1,000,000 TPM / 1,000 RPM**; Nano **5,000,000 TPM / 5,000 RPM**. **Unconfirmed for this new subscription:** its assigned tier, available capacity, actual deployed TPM/RPM and minimum allocation. Tier 0 lists neither selected model. There is no evidence that this account automatically gets Tier 1. [Quota tiers and limits](https://learn.microsoft.com/en-us/azure/foundry/openai/quotas-limits). |
| Quota allocation is a spending cap | **Confirmed false:** TPM is based on estimated prompt plus maximum output and RPM also limits bursts. Allocation is availability, not permission to spend the whole pool. Inspect actual deployment values. [Quota management](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/quota). |
| Startup sponsorship covers Azure OpenAI | **Confirmed policy:** models sold and billed directly by Azure qualify; partner/Marketplace billing does not. Both catalog cards say Direct from Azure. **Unconfirmed account result:** actual debit from this subscription's €175.99 credit. [Microsoft sponsorship coverage](https://learn.microsoft.com/en-us/startups/benefits/technical-benefits/azure-credits/foundry-model-sponsorship-coverage). |
| Budget alert stops spending | **Confirmed false:** it emails after cost evaluation; resources continue running. [Budget tutorial](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets). **Unconfirmed independently:** this MCA subscription's lack of a subscription spending limit, reported by Guy. [Azure spending limits](https://learn.microsoft.com/en-us/azure/cost-management-billing/manage/spending-limit). |
| Quality numbers in the brief | **Unconfirmed here:** Luna AA index 30 medium/22 low and factual error 17.5%/27.7%; Nano 12 medium/13 high. They are owner's rationale, not verified Microsoft facts or application evaluation results. Preserve the selected efforts; evaluate later with an explicitly authorized budget. |

## Research-only usage estimate

**Confirmed historical usage; unconfirmed Azure run cost.** No new inference was
performed. Read the already completed GitHub benchmark artifacts, which ran on
Ling/Nemotron free routes, and reprice their recorded tokens at the selected
Azure rates. These are two samples, not production traffic measurements or
quality/latency predictions for Luna/Nano.

| Completed benchmark | Physical calls | Supervisor input / output | Worker input / output | Repriced USD, no cache savings |
|---|---:|---:|---:|---:|
| [Express, rearch-baseline-1, `35d68bf`](https://github.com/guy915/Co-Scientist/actions/runs/37619174808), artifact `benchmark-express-rearch-baseline-1` | 85 | 126,396 / 47,540 | 389,408 / 307,147 | **$0.179** ($0.036 Luna + $0.142 Nano) |
| [Standard, baseline-standard, `a82eed8`](https://github.com/guy915/Co-Scientist/actions/runs/37558735897), artifact `benchmark-standard-baseline-standard` | 343 | 1,501,294 / 297,768 | 2,287,846 / 1,428,710 | **$0.985** ($0.299 Luna + $0.686 Nano) |

Reproduction: read `evaluations/results/claim-support-live-2026-10-07.json` in
each artifact, then sum `usage_evidence.model_usage` by the phase before `::`.
Supervisor phases are `supervisor`, `meta_review`, `research_overview` and its
dot-prefixed subphases; all remaining recorded phases are workers, including
`orchestrator` (supervisor_decision). This phase-level allocation approximates
the later per-call role ledger; it cannot separate differently tiered calls
within a phase. Use **physical_calls**, not logical `llm_calls` (72/283).

Formula: `(Luna_input * 0.10 + Luna_output * 0.50 + Nano_input * 0.05 +
Nano_output * 0.40) / 1,000,000`. Output includes reasoning; never add reasoning
again. The samples report about 274k/1.108M reasoning tokens. A few legacy
aggregates report reasoning greater than completion (Express claim_grounding,
Standard orchestrator), so this is a planning estimate, not an invoice audit.
Retain headroom and normalize Azure's exact usage fields in the implementation.

No cache discount is assumed. Historical cached input totals were 41,536 and
456,896; Azure hit rates will differ. Charging one Luna cache write for every
supervisor input token would add $0.016/$0.188 at short rates. Using Luna long
input/output prices plus one additive long cache write gives approximately
$0.235/$1.585 total; four writes on every Luna input would give $0.330/$2.711.
Those are stress assumptions, not observed write usage. Context boundary,
write-meter semantics, FX and tax remain unconfirmed.

For normal short requests, reserve a **planning allowance of €0.40 per Express
and €2 per Standard**, assuming an illustrative conservative `F=1 EUR/USD`.
This covers substantial variation over the sampled base, not every possible
run: steering, retries, larger reports, interviews/chat and long/cache-write
stress can cost more. The hard ledger admits each actual call, so it stops
before the configured total even if an estimate is wrong. A 55k-input/4k-output
Nano chat turn is about $0.00435 before tools/repeats; ten such turns are about
$0.044. [Historical prompt evidence](optimization/findings.md) records sizeable
reasoning and repeated transcripts; do not assume a research run is one request.

| Hosted activity assumption, not a traffic forecast | Express / Standard per month | Planning model spend |
|---|---:|---:|
| Owner and a few testers | 10 / 2 | €8 |
| Small maintainer-funded demo | 50 / 10 | €40 |
| Modest public uptake | 200 / 50 | €180 |

Open-source installs using other people's Azure credentials do not spend Guy's
credit. Hosted demand is **unconfirmed**; no GitHub popularity figure predicts
paid runs. Existing free routes remain an explicitly selected fallback.

### Credit-expiry spending schedule

**Owner-selected objective:** use the available sponsorship credit evenly up to
the last valid day. The following is a provisional model budget only, assuming
the entire €175.99 is still available and not needed by other Azure services.
From 7 October 2026 through 4 January 2027 inclusive is **90 days**.

| Period | Days | Incremental EUR allowance | Cumulative allowance |
|---|---:|---:|---:|
| 7–31 October 2026 | 25 | €48.88 | €48.88 |
| November 2026 | 30 | €58.66 | €107.54 |
| December 2026 | 31 | €60.62 | €168.16 |
| 1–4 January 2027 | 4 | €7.83 | **€175.99** |

Amounts use cumulative cent rounding: `floor(17599 * elapsed_days / 90)` cents;
differences produce the monthly increments. Average allowance is €1.9554/day,
with cent allocations of €1.95 or €1.96. The exact expiry timestamp/timezone is
**unconfirmed**: January 4 is provisionally inclusive, and dispatch must stop
before the provider's actual cutoff. If January 4 is excluded, use 89 days,
about €1.9774/day, and recompute the periods.

At planning allowances, the full credit supports approximately **439 Express
or 87 Standard** runs, or **300 Express plus 27 Standard** (€174) with €1.99
left for chat/variation. That mixed scenario is about 3.3 Express and 0.3
Standard runs/day. These are capacity estimates, not required requests; no
synthetic calls should be made to exhaust unused credit.

Before enablement, read the **remaining** credit and expiry in billing, subtract
other Azure charges/reservations, and recompute using `available_model_eur /
remaining_valid_days`. Other services can consume the same credit; these model
estimates exclude hosting, search and taxes. Keep a total runway limit as well
as monthly/daily settings. Unused dated allowance carries forward without
increasing that total. Recompute the daily pace against remaining credit/days
as demand changes; late legitimate demand may use banked allowance. Do not
silently enable card spending after expiry or credit exhaustion: disable Azure
unless Guy separately approves a post-credit budget. Actual traffic is needed
to use the full amount; a spending cap cannot guarantee exact exhaustion.

## The two-call smoke test

**Status: unconfirmed / not executed. Paid requests made by this lane: 0.**
Guy's latest instruction is research only: do not use either model or waste
usage. The earlier two-call allowance is suspended; deployment/export
confirmation alone does not reinstate it. The protocol below is for a later
explicitly authorized test, not an action scheduled by this lane.
Do not invoke the existing wrappers: their token floors, JSON retries and SDK
retries would break the 20-token and two-request limits. Do not use the Foundry
playground, credential validation, a benchmark, or a health probe as another test.

Only after Guy separately authorizes those two calls, confirms deployments and exports `AZURE_OPENAI_ENDPOINT` and
`AZURE_OPENAI_API_KEY` into the shell this lane can access, first check presence
as booleans without printing values. Confirm the two non-secret deployment names
and endpoint type. Use one direct HTTP POST per deployment, sequentially, with
automatic retries and redirects disabled, timeout 60 seconds, no tools:

```json
{
  "model": "<deployment-name>",
  "input": "Reply OK.",
  "reasoning": {"effort": "low"},
  "max_output_tokens": 20,
  "store": false
}
```

Use `<resource endpoint>/openai/v1/responses` with the API key only in the
in-memory `api-key` request header. Never echo the environment, headers, key,
complete request/response or SDK exception representations. Record only latency
from a monotonic clock, HTTP status, response `status`/`incomplete_details`, model,
`usage.input_tokens`, `input_tokens_details.cached_tokens` and
`cache_write_tokens` if present, `output_tokens`,
`output_tokens_details.reasoning_tokens`, `total_tokens`, and the top-level
`reasoning` object. Report reasoning-item field names/types without hidden
reasoning text or encrypted content. Missing fields stay unknown, not zero.

Twenty output tokens include reasoning. An `incomplete` response with reason
`max_output_tokens` and no visible answer still measures connectivity and usage;
it is not permission to increase the limit or repeat the call. A 400/429/timeout
uses that model's one attempt; record it and stop testing that model.

| Deployment | Latency | HTTP / response status | Input / cached / cache-write | Output / reasoning / total | Returned reasoning fields |
|---|---|---|---|---|---|
| Luna, name unconfirmed | Not measured | Not called | Unknown | Unknown | Unknown |
| Nano, name unconfirmed | Not measured | Not called | Unknown | Unknown | Unknown |

On the day after the calls, Guy checks Cost Management and sponsorship balance
as described in the setup checklist. If called on 7 October, check on **8 October
2026**. Cost ingestion may lag and tiny usage may round to zero; absence of a
line item does not confirm credit coverage. No extra call is authorized to make
the charge visible. These two calls do not verify tool calling, streaming,
caching, effort quality or the backend cap; offline adapter tests cover shape.

## Call-site map

Survey baseline: `ec53ff0435fe823fa4947e58ebdd5c127eab18f9`, after #350 moved the
gateway and #351 moved retrieval, sandbox and telemetry. `app/app/config.py`
already moved in #343 to `engine/src/co_scientist/core/config.py`; no stale-path
shim exists. Map follows [REARCHITECTURE.md](REARCHITECTURE.md), resolved to actual
package `co_scientist` and source root by [ADR-001](adr/001-module-map.md), and the
gateway interface by [ADR-004](adr/004-llm-gateway.md). Other lanes continue moving
files; recheck these paths on the implementation branch.

All science rows below use current prefix `engine/src/co_scientist/agents/`.
Their target prefix is `engine/src/co_scientist/science/`, with the same suffix.
Line numbers refer to the survey baseline, not future moved files. `J`, `T` and
`F` mean `call_llm_json`, `call_llm`, and `call_llm_with_tools` respectively;
`S` means `platform.llm.llm_request.acompletion`, future `complete_surface`.
All ultimately dispatch through `platform/llm/request/transport.py::complete_request`.
Efforts are the **later Azure policy**, not the current boolean thinking flags.

| Current suffix : call line | Wrapper and work | Role / Azure effort |
|---|---|---|
| `supervisor/supervisor.py:66` | J, research plan | Supervisor Luna / medium |
| `supervisor/supervisor_decision.py:273` | J, per-cycle allocation | Worker Nano / low, despite supervisor directory |
| `meta_review/meta_review.py:164` | J, meta-review | Supervisor Luna / medium |
| `meta_review/research_overview.py:400` | J, interim/final synthesis and report | Supervisor Luna / medium |
| `meta_review/research_overview_review.py:73` | J, overview review | Supervisor Luna / low |
| `meta_review/research_overview_knowledge_base.py:48` | J, outline and bounded theme calls | Supervisor Luna / none; currently `enable_thinking=False` |
| `meta_review/research_overview_direction_calls.py:145` | Injected `ask=call_llm_json` via overview line 336, one body per direction | Supervisor Luna / none; currently `enable_thinking=False` |
| `generation/debate.py:202` | T, debate turns | Worker Nano / medium |
| `generation/debate.py:121` | J, final debate synthesis | Worker Nano / medium |
| `generation/assumptions.py:239` | J, assumption-based generation variants | Worker Nano / medium |
| `generation/literature_review/queries.py:95` | J, search queries | Worker Nano / low |
| `generation/literature_review/synthesis.py:54` | J, per-paper analysis | Worker Nano / low (plan recommendation) |
| `generation/literature_review/synthesis.py:167` | T, literature synthesis | Worker Nano / medium |
| `generation/literature_tools/draft.py:346` | F, bounded tool drafting | Worker Nano / low, per owner's literature-tools policy |
| `generation/literature_tools/validate.py:625` | J, novelty analysis | Worker Nano / low |
| `generation/literature_tools/validate.py:660` | F, validation synthesis batches | Worker Nano / low |
| `reflection/reflection.py:131` | J, literature reflection | Worker Nano / medium |
| `reflection/review.py:345` | J, single-hypothesis review | Worker Nano / medium |
| `reflection/review.py:418` | J, batch review | Worker Nano / medium |
| `reflection/comprehensive_reflection.py:164` | J, comprehensive review modes | Worker Nano / medium |
| `reflection/deep_verification.py:174` | J, assumption verification | Worker Nano / medium |
| `reflection/review_evidence.py:198` | J, evidence query generation | Worker Nano / medium, as requested |
| `reflection/simulation_execution.py:121` | F, confined simulation, followed by review | Worker Nano / medium (plan recommendation) |
| `ranking/ranking_debate.py:580` | J, every tournament debate/judgment | Worker Nano / low; later compare a few runs with medium under separate authorization |
| `evolution/evolve.py:190` | J, hypothesis evolution; operations call this seam | Worker Nano / medium |
| `evolution/evolve_grounding.py:81` | J, grounding queries | Worker Nano / medium, as requested |
| `proximity/proximity.py:75` | J, deduplication/proximity | Worker Nano / low |

No extra physical calls occur in `generate.py`, generation/evolution
`operations.py`, ranking matchmaking/review coordinators, orchestrator, or the
safety-screen node: they delegate to these seams. Keep delegation covered by
role-mapping tests, including both durable fan-out and node callers.

| Other current path : call line | Wrapper and callers | Target path; role / effort |
|---|---|---|
| `engine/src/co_scientist/platform/retrieval/evidence/relevance.py:138` | J, candidate relevance; probe paths disable the multiplying pass | Same target; worker Nano / low |
| `engine/src/co_scientist/platform/retrieval/research_adapter/__init__.py:132` | J, shared `_ask`: `plan_stances`, `ask_questions`, `to_query`, `extract`, `compress`; generation, expansion and review research callers | Same target; worker Nano / low for planning/query/compression, medium for extraction (recommendation). Explicitly carry each sub-role through `_ask`. |
| `app/app/claims/verifier.py:66` | J, `_call_claim_json_async`: verification, single and batch entailment | `engine/src/co_scientist/domains/research_state/claims/verifier.py`; worker Nano / low. Currently thinking disabled; Nano must receive low, not none. |
| `app/app/safety/semantic.py:162` | J, contextual intake/final semantic safety | `engine/src/co_scientist/domains/safety/semantic.py`; worker Nano / low |
| `app/app/interviews/questions.py:127` | J, question repair | `engine/src/co_scientist/domains/chat/interviews/questions.py`; worker Nano / low (recommendation) |
| `app/app/interviews/model.py:526` | S, streamed goal interview, tool/answer rounds | `engine/src/co_scientist/domains/chat/interviews/model.py`; worker Nano / medium (recommendation) |
| `app/app/qa/__init__.py:74` | S, `_stream_completion`, Q&A and subsequent tool rounds | `engine/src/co_scientist/domains/chat/qa/__init__.py`; worker Nano / medium (recommendation) |
| `app/app/goal_text.py:135` | S, title and goal restatement, answerless retry | `engine/src/co_scientist/domains/chat/goal_text.py`; worker Nano / low (recommendation) |
| `app/app/run_start_announcement.py:101` | S, streamed start confirmation, answerless retry | `engine/src/co_scientist/domains/chat/run_start_announcement.py`; worker Nano / low (recommendation) |
| `app/app/credentials.py:301`, delegate at 288 | S, one-token caller-funded credential probe | Validation moves inside `engine/src/co_scientist/platform/llm/` in phase 5; storage remains `domains/access/credentials.py`. Caller BYOK model/effort contract, not operator Luna/Nano. Never run this for Azure readiness. |

Chat currently has its own `chat_model_name`, defaulting to the worker when
unset; semantic safety has its own setting; claim verification uses its configured
model or worker. Explicitly map all three to Nano for operator-funded Azure.
`X-LLM-Model` and `X-LLM-Supervisor-Model` are caller BYOK overrides, not permission
to select an arbitrary operator-paid Azure deployment.

Physical dispatch inventory: `request/backend.py::LitellmBackend.complete` calls
`litellm.acompletion`; `request/transport.py::_await_provider` calls the selected
backend with/without timeout; `request/completion.py` is the shared timeout seam;
`attempts/json_attempt.py` serves text/JSON attempts; `tools/loop.py` dispatches
tool turns **and the closing no-tools harvest**. App S calls delegate through
`llm_request.py`. The offline router delegates only non-offline requests to its
inner backend. Provider code in tests/evaluations/dev scripts is outside the
product inventory and must remain hermetic unless deliberately invoked.

## Controls already present and gaps

Confirmed from source, not only from the owner's earlier findings:

- `core/config.py`: per-surface operation cap 4; client/day 64 calls and 2M
  reserved tokens; global/day 1,024 calls and 32M reserved tokens; maximum surface
  output 32,768 and input 256,000 bytes. `platform/llm/provider_usage.py` reserves
  input bytes + 1,024 + output in SQLite before operator-funded **surface**
  dispatch. Failed/partial calls keep the reservation. These counters are not a
  global science EUR cap, and old days are pruned.
- `domains/access` target for `free_usage.py`: default three Express runs per
  owner per UTC day; atomic create admission in an independent `free_run_usage`
  ledger, so deleting a run does not refund it. Bigger tiers/numeric expansion
  require BYOK. Concurrency defaults to ten runs per client, across all tiers.
  A browser-selected client ID is not authenticated identity; the global budget
  must survive ID rotation.
- `core/run_modes` and `platform/llm/admission/call_budget.py`: physical run-call
  backstops 1,200/2,500/7,000/14,000 for Express/Standard/Extended/Ultra;
  operation budgets count retries/tools. The run counter is process memory,
  bounded to 500 tracked runs, not a restart-proof financial ledger.
- `platform/llm/admission/free_policy.py`, `execution_policy.py`: checked
  zero-price catalog, expiry, routing and price ceiling; free runs get durable
  `zero_cost_admission` stamps. No paid fallbacks under free routes. Azure-paid
  runs cannot inherit the free replay guarantee or bypass it by pretending the
  deployment key is BYOK.
- `platform/llm/attempts/`: bounded retries/escalation, jittered throttle backoff,
  durable rate parking. Timeout/call ceiling/free eligibility are terminal.
  Tools execute outside the retry boundary. Transcript/turn/output bounds are
  separate controls and do not sum to a monthly currency budget.
- `platform/llm/telemetry.py`, `request/response.py`, `core/constants`: input,
  cached-input, output, reasoning, latency, retries and USD estimates, aggregated
  by phase and committed at node/task boundaries. Reasoning is already part of
  output. Unknown exact price routes currently return **0.0**, and response
  extraction expects Chat Completions fields. Neither behavior is safe for an
  Azure cost cap; Azure cache-write accounting is absent.

There is **no confirmed durable all-call EUR ledger, monthly/daily EUR admission,
`LLM_ENABLED` kill switch or spending admin view** in this baseline. Thinking is
mostly on/off; `CompletionSpec`/`LLMCallOptions` have no per-call effort.
`thinking.py` hardcodes DeepSeek high, while the current Ling profile pins medium.
The tool entry point does not use the supplied options to select thinking.
`call.py` also rebuilds options for attempts. A new effort field must survive
both paths and every retry rung. Current Azure credential detection uses
`AZURE_API_KEY`, not the owner's requested `AZURE_OPENAI_API_KEY`.

## Later implementation, using the target structure

This is a proposal for the later lane, not authorization to change code or
hosting now. Re-architecture moves preserve behavior; land Azure behavior only
after the moved gateway interface is settled. Keep the change focused.

| Target paths (all relative to repository root) | Planned change |
|---|---|
| `engine/src/co_scientist/core/config.py`, `core/exceptions.py` | Validated Azure env, budgets, effort allowlist, provider and kill-switch settings; typed budget errors. Provider maps/delegates move out of core per ADR-004. |
| `engine/src/co_scientist/platform/llm/values.py`, `call.py`, `request/completion.py`, `request/thinking.py`, `tools/loop.py` | Typed role and per-call effort propagated through attempts/tool/closing turns. Validate none/low/medium globally, then per model; Nano permits low/medium. Retry escalation can reduce effort but never raise it above medium. |
| `engine/src/co_scientist/platform/llm/request/backend.py`, proposed `request/azure.py`, `request/response.py`, `tools/transcript.py` | One Azure Responses adapter, typed request/response translation, JSON/stream/function/reasoning items, usage normalization. Preserve existing wrapper return contracts. |
| `engine/src/co_scientist/platform/llm/profile/__init__.py`, `telemetry.py`, `provider_usage.py`, proposed `admission/spend.py`, `admission/spend_repository.py` | Exact deployment-to-model/version/prices; integer EUR ledger, atomic reservations/settlement, unknown usage handling, all-call admission. |
| `engine/src/co_scientist/platform/db/schema.py` | Additive ledger/settings schema migration; independent of run/message deletion and retention. Repository SQL stays within allowed adapter/repository boundaries. |
| `engine/src/co_scientist/domains/access/`, `orchestration/`, `api/` | Atomic per-user run admission, start/resume checks, terminal budget/kill/throttle outcomes, authenticated operator spending endpoint (proposed `api/spending.py`). Keep wire changes narrow and explain new budget refusal. |
| `engine/src/co_scientist/science/{supervisor,meta_review,generation,reflection,ranking,evolution,proximity}/`, `domains/{chat,safety,research_state}/`, `platform/retrieval/` | Apply the explicit role/effort map at every inventoried call, including delegated calls. Preserve prompts/schemas/scoring. |
| `engine/src/co_scientist/science/prompts/`, `platform/llm/` | Stable goal/literature prefix and Responses tool-context preservation, with prompt-content equivalence checks. |
| `app/frontend/src/features/diagnostics/` (phase-7 target), shared UI | Operator-only spend view if UI is needed; existing operator authorization must protect its API independently of client ID. |
| `.env.example`, `app/.env.example` while it exists, existing `engine/tests/`, `app/tests/`, `evaluations/tests/`, `docs/azure-setup.md` | Non-secret env examples, offline tests, updated owner checklist; dependency metadata/locks only if adapter adds a runtime dependency. |

### Azure client and configuration

Use the Responses v1 API for plain, JSON, streaming and function-tool calls.
Keep the free adapter selected with `LLM_PROVIDER=azure|free` (default free until
an explicit cutover). Proposed env: `AZURE_OPENAI_ENDPOINT`,
`AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_API_VERSION=v1`,
`AZURE_OPENAI_SUPERVISOR_DEPLOYMENT`, `AZURE_OPENAI_WORKER_DEPLOYMENT`,
`LLM_SUPERVISOR_EFFORT=medium`, `LLM_WORKER_EFFORT=medium`; named sub-role overrides
select low/none according to the table. Settings validation hides input values.
Treat deployment names separately from pricing model/version IDs.

One process-owned, thread-safe synchronous Azure/OpenAI client dispatched off
the event loops is the recommended way to meet the “one client” requirement:
cohorts run separate event loops, so a single global async SDK client/lock is
unsafe. Close it in lifecycle shutdown. Disable SDK automatic retries; the
existing attempt ladder is the sole retry owner. No provider fallback from Azure
to a paid alternative, and no failure-triggered switch that resends a billed
request to free. Provider changes are explicit and apply to new runs; existing
runs retain their funding/provider stamp.

Translate chat-style schemas to Responses `text.format`, flatten function tool
definitions, pair `function_call` with `function_call_output.call_id`, and retain
every required reasoning item through the tool return. Handle `incomplete` before
JSON parsing. Never persist keys or plaintext hidden reasoning as ledger metadata.
Disable unpriced Azure-hosted tools; repository tools remain locally executed.

### Ledger, EUR budget and admission

1. Store an append-only financial ledger independent of research artifacts.
   Each physical attempt has a unique ID linked to run/task/operation, owner,
   funding source, role, deployment/model/version, price version and UTC billing
   day/month. Keep reserved, settled and unknown-outcome amounts, measured token
   fields and latency. Settlement appends an idempotent adjustment rather than
   deleting the admission row. Restart/deletion must never refund spend.
2. Use Decimal prices and integer micro-EUR, rounding reservations upward.
   Configure `LLM_MONTHLY_BUDGET_EUR`, `LLM_DAILY_BUDGET_EUR`,
   `LLM_ENABLED`, a documented conservative `LLM_USD_TO_EUR_RATE` and tax/price
   headroom. Actual FX/tax/account discounts are **unconfirmed**. Never treat
   sponsorship credit as a deduction from usage cost. Missing/invalid budgets,
   exchange rate or model pricing refuse Azure startup/admission.
   Add a dated credit-runway policy (total allowance, start and expiry, cumulative
   daily entitlement) for the owner-selected schedule above. Monthly/day limits
   follow that policy; carry unused allowance within the total, including over
   month boundaries. Scheduled setting updates must be auditable and atomic.
   Never reset the lifetime total at month rollover. Expiry is a terminal
   admission condition; renew funding only through an explicit owner decision.
3. Normalize Responses input `I`, cached read `C`, output `O`, reasoning `R`
   and cache write `W`. Cost before FX is
   `((I-C)*input_rate + C*cache_rate + O*output_rate)/1e6`, plus the conservative
   additive cache-write reserve `W*write_rate/1e6` until invoice semantics are
   verified. `R` is a subset of `O`: **never add it again**. Nano write fee is
   zero. Use Luna long rates while its boundary is unconfirmed. If writes/usage
   are missing, keep the upper reservation and report unknown, not free.
4. Before **every** physical call, atomically compare settled charges plus
   outstanding/unknown reservations plus the next upper bound against global
   day, month and remaining-credit/runway budgets. Reserve before sending,
   release the transaction,
   then perform network I/O. Include all prompt/schema/tool/history bytes using
   a conservative token bound, post-floor/post-escalation output cap, no assumed
   cache discount, and worst-case cache writes (up to four repeated prefixes for
   Luna). Re-admit every retry, tool turn and closing harvest independently.
5. Record known actual usage and release unused allowance only after a verified
   final usage event. Cancellation, timeout, incomplete stream, malformed/missing
   usage or crash after admission keeps a conservative charge; recovery never
   resends that paid attempt. A reservation created but provably never dispatched
   may be released through an explicit idempotent transition. Otherwise fail
   closed. If measured cost exceeds its reservation, book it, disable further
   Azure admission and flag the pricing/bounding defect.
6. Check budgets at run creation/start/resume and at the transport boundary;
   admission requires enough headroom for the next bounded call, not merely a
   positive balance. Per-user daily run limits must be independent of deletions,
   use `domains/access` admission and cover all permitted Azure run tiers. Keep
   existing concurrency/call/token limits. Global ledger remains binding for
   rotated anonymous IDs. BYOK costs stay caller-funded and labeled separately;
   the operator cap still covers every operator Azure call, including safety/chat.
7. Persist a runtime operator kill flag alongside env `LLM_ENABLED`; effective
   enablement requires both. Check again atomically at dispatch, including work
   already queued. “Off” stops new provider dispatch, including retries and
   safety calls; it cannot unbill a request already in flight. Finish accounting,
   cancel dependent work and terminate with a clear unavailable/budget message.
   Poll read-only; do not write per worker tick or per streaming token.
8. Use a typed non-retryable budget/disabled error that propagates through
   optional enhancements, broad exception fallbacks and gathers into durable
   worker outcomes. The refusal should say “The research budget is used up.
   Please try again after the reset or contact the owner.” Expose reset time;
   do not present exhaustion as a successful unreviewed report.

These reservation/settlement writes are required for a hard cap, unlike existing
aggregate telemetry. Keep transactions short and off the serving loop, with at
most admission and settlement writes per attempt, never holding a lock over I/O.
Preserve one SQLite writer, leases, idempotency and no cross-loop primitives from
[OPERATIONS.md](OPERATIONS.md). The cap covers requests sent through this backend;
Guy's separate portal/key use and other Azure services need independent controls.

### Quota arithmetic

Let `F` be conservative EUR per USD, `B` the monthly EUR allowance assigned to a
deployment, and `P` its output USD price per million. The owner's 30-day envelope
is `TPM * 60 * 24 * 30 * P / 1e6 * F <= B`. Allocate the total budget **between**
deployments; never give each the whole monthly budget.

At example `F=1`, split November's €58.66 into €19.55 Luna / €39.11 Nano:

| Model / assumption | Maximum theoretical TPM | At 1,000 TPM for 30 days |
|---|---:|---:|
| Luna short output $0.50/M, €19.55 share | 905.09 | €21.60 |
| Nano output $0.40/M, €39.11 share | 2,263.31 | €17.28 |
| Luna long output $0.75/M, €19.55 share | 603.40 | €32.40 |

At short output prices, 1,000 TPM **on each** permits €38.88/month for `F=1`.
At long Luna output it permits €49.68. The brief's output-only calculation does
not cover all cache-write charges; additive worst-case Luna input plus four
cache writes at long rates is $1.20 per million input tokens, a theoretical
€51.84/month at 1,000 TPM, or just **377.12 TPM** for the €19.55 Luna share.
That input/write bound plus Nano output is €69.12 at 1,000 TPM each, exceeding
November's allowance. Recompute for each period's actual days (25/30/31/4),
available credit and FX; a 30-day envelope is not January's four-day budget.

The portal's minimum/step and actual RPM at the chosen allocation are
**unconfirmed**. If it only permits 1,000-TPM units, none of those fractional
allocations is selectable. Also the existing reasoning floor is 18k output
tokens, so a 1k-TPM deployment may reject normal research requests before they
start. Do not promise the credit-runway hard limit through quota alone, disable output
bounds, or increase a deployment automatically. Guy sets the smallest available
allocation only for a separately authorized test, dynamic quota off; the later lane proposes a
workable per-request allocation only after backend admission is verified. Show
the new arithmetic and budget before Guy changes the quota. Quota tiers may
auto-upgrade; do not equate a subscription quota pool with the deployment limit.

### Caching, 429 and operator view

Keep reusable goal/literature blocks byte-identical at the beginning of prompts,
before hypothesis-specific content. Reorder existing blocks only; preserve their
words and source boundaries. Test the assembled blocks against the old prompt
content. No timestamp/run ID in the shared prefix. Never move untrusted evidence
into an instruction role. Caching needs at least 1,024 identical prefix tokens;
the two smoke prompts cannot prove caching. Luna supports explicit cache options,
Nano does not; do not forward Luna-only fields to Nano. [Prompt caching](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/prompt-caching).

For Azure 429, honor `Retry-After`/`retry-after-ms` with jitter and a bounded
attempt/wall-clock allowance at the existing retry layer. Reserve spend anew
before any repeat. Existing long quota parking must have an Azure run deadline:
after the bound, end cleanly with a clear throttle message instead of recurring
paid replays. Keep free-provider parking semantics intact. SDK transport does
not independently retry. Never retry an unknown paid outcome or repeat tools.

An operator-only read view shows enabled/provider state, configured budgets,
settled/reserved/unknown cost, remaining day/month headroom and UTC resets,
per-deployment/model/role/run totals, token/cache-write/reasoning counts, FX/price
versions, unknown usage, remaining credit/runway, expiry and daily pace versus
actual spend. Use verified operator authorization, not `X-Client-ID`;
no keys, research prompts or hidden reasoning. Keep queries read-only and cached;
a kill-switch mutation needs the same auth and an audit record. The user-facing
flow only needs a clear refusal, not ledger internals.

## Implementation gates and unresolved checklist

Offline tests must verify role mapping at every inventory seam; none/low/medium
validation and Nano rejecting none; effort surviving retry and tool paths;
Responses JSON/stream/function/reasoning shape; output including reasoning once;
cache read/write and long prices; unknown-price/usage refusing or retaining
reserve; concurrent admission, day/month resets, expiry, carry-forward and
remaining-credit ceilings, deletion/restart persistence;
run/start/resume and per-user bounds; kill switch preventing queued/retry calls;
401/403/400 terminal handling, bounded 429, timeout/crash no replay; operator auth;
free/offline isolation and existing zero-cost stamps. No live tests in CI.

The later code PRs run the repository's required lint/types/tests/e2e/architecture
gates serialized with the lead. Any live evaluation needs separate authorization:
the latest owner instruction permits no inference in this lane.

| Remaining fact | Status / closure |
|---|---|
| Deployments exist, version, resource region, endpoint type, selected TPM/RPM and minimum allocation | **Unconfirmed**; Guy follows setup and reports only non-secret metadata. |
| Two model latencies, token counts, returned reasoning fields | **Unconfirmed, intentionally not tested**; owner requested research only. No call fabricated. |
| This subscription's model quota tier/capacity | **Unconfirmed**; read Foundry quota and, if needed, the control-plane tier read described in Microsoft's quota reference. |
| Actual sponsorship debit | **Unconfirmed**; next-day Cost Management plus credit balance, allow ingestion/rounding lag. |
| Backend EUR budgets, FX/tax headroom | **Confirmed owner objective:** evenly use remaining credit by January 4. **Unconfirmed live balance/settings/cutoff:** provisional €175.99 over 90 inclusive days, about €1.96/day; recheck billing, other charges and FX before enablement. |
| Luna context-price boundary and cache-write invoice semantics | **Unconfirmed**; signed-in card/meter verification, conservative reservation until then. |
| Quality evidence and low-vs-medium ranking results | **Unconfirmed**; not part of the two-call test; no additional paid evaluation now. |

Documentation can merge with these unknowns explicitly labeled. **Azure rollout
must remain disabled** until configuration, ledger/admission and owner quota steps
are complete. This readiness document does not claim production readiness.
