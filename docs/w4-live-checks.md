# W4 owner-local check prompt

Paste the block below into a local executor with the owner's environment.
Do not paste secret values into a conversation. Authority:
[300-attempt allocation](https://github.com/guy915/Co-Scientist/issues/453#issuecomment-6066450338)
and [unattended local run](https://github.com/guy915/Co-Scientist/issues/453#issuecomment-6066619391).

```text
You are the local executor for Lane W4 (models and spend) in guy915/Co-Scientist.
W4 has completed the hermetic transport/credit work in a cloud session that has
no provider keys. Your job is to collect bounded live evidence and return only
safe results for issue #453. Read AGENTS.md, engine/AGENTS.md, app/AGENTS.md,
docs/azure-setup.md, docs/anthropic-credit.md, docs/llm-caching.md and the latest
W4, T, E0 and EQ comments on #453 first.

Authority: one bounded local check, at most 300 provider HTTP attempts in total,
at most $5 Claude API and at most €5 Azure. These attempts do not use the
OpenRouter free-route 600/day split. Both money ceilings must be enforced in
code before dispatch, including outstanding reservations and unknown outcomes.
The credit/key incident is closed for lanes on the owner's fresh-launch-key
disposition. Do not rotate, revoke or delete keys or incident artifacts. Do not use the old projects'
keys in the new launch setup. Never assume another lane's unused requests are
available. If another paid check has used the shared $5/€5 allowance, reserve
only the remaining headroom; stop if its usage or holds cannot be verified.

Use existing keys from the owner's local environment. Check presence without
printing values. Do not print env dumps, command traces, headers, raw provider
exceptions, URLs with query keys, prompts, responses or private run data. Disable
raw SDK/HTTP logging and private trace exports. Never upload an unfiltered DB,
trace or log. If settings are missing, return variable NAMES only; do not ask for
keys in chat. Keys remain in this terminal's environment only; never write a
key to a file, log, board comment or git. Required names: ANTHROPIC_API_KEY,
AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT,
AZURE_OPENAI_SUPERVISOR_DEPLOYMENT and AZURE_OPENAI_WORKER_DEPLOYMENT.

Azure deployment capacity and the neutral workers.dev rename are done before
the run (done in Part A). Skip both steps. During this run, do not change
hosting, DNS, deployments, hosted settings or production data. Do not merge,
push or deploy. Do not rotate keys or change capacity, budgets or alerts.

Wait for a #453 comment with the exact phrase W4 local prompt ready and a main
commit SHA. Clone into a fresh temporary directory and check out that exact
SHA. Verify it is on main and includes the merged W4 routing, explicit test
adapter, spend view, E cuts and T's cache layout with stable-prefix boundaries.
Run only after T's cache layout is merged. Read this document again at the
announced SHA and record it. Do not substitute a later main, unpublished branch
or unmerged T source. If source or a safety limit is missing, post W4 local run:
stopped with the safe reason on #453 and stop without a provider request.
Run make setup in that checkout. Do not load local dotenv files or reuse a
production database. Keep private exports and raw SDK logging disabled.
Recheck primary provider docs. Use only claude-haiku-5-5, direct Anthropic API;
Azure gpt-6-luna-2026-09-22 and gpt-5-nano-2025-08-07, native Responses API.
Claude always adaptive thinking/low, no sampling, own count_tokens, prompt
<=100K, existing role output caps. Never Sonnet, Opus, Fable or a paid route
outside the two Azure models. No Message Batches for these live checks.

Prepare a temporary local SQLite ledger and synthetic public goals. Keep the
normal per-user/global/app/call limits. Set only isolated process settings:
ANTHROPIC_MONTHLY_CREDIT_USD=5 (the 95% guard stops at $4.75),
LLM_TOTAL_BUDGET_EUR=5, LLM_USD_TO_EUR=0.88 and the owner's valid LLM_AZURE_UNTIL.
Lower the test credit or total if shared headroom is smaller; never increase
them. Select the target provider at the start of each isolated test run; keep
Azure as the only allowed fallback for Claude. Send no OpenRouter requests.
Keep the deterministic adapter OFF.
Do not reuse or edit production data. Prevent operator-funded Standard runs.

Before the first provider request, install a thread-safe durable counter for
the whole allocation at outgoing SDK HTTP dispatch. Persist each reservation
before sending; a process restart must keep all previous attempts charged.
Use one counter across subprocesses. Include count_tokens, catalogue reads, retries,
429s, failures and unknown outcomes in the 300. Every outgoing request consumes
a slot BEFORE send. Fail closed at 300, without allowing a retry to bypass it.
Enforce this in code with one SQLite counter shared across threads/processes;
reserve an attempt in a short transaction before network I/O. Keep the counter
and both money ledgers across restarts. Never reset them to retry a check.
Before live dispatch, prove offline that concurrent attempts cannot pass 300,
restarting cannot reset it, and the code stops at both money ceilings. If any
guard is absent or cannot be proved, post W4 local run: stopped and stop.
Use the gateway's conservative money reservations BEFORE each call. Unknown
outcomes retain their full hold; never infer free success or rerun them. All SDK
retries stay zero. A refusal is billed and goes to separately admitted Azure
for that call; count that fallback in the same 300. Stop on any money guard.
Nothing is called after Azure fails or declines admission. No other paid slot
is allowed. Retain all failure and unknown reservations in the safe totals.

Run one default Express workflow on Claude and one on Azure, then the paired
cache and quality checks, within the same 300-attempt and $5/€5 guards. Use
synthetic public goals and repeated stable-prefix calls in one wave. Preflight
the E0 envelope: default Express used about 52 completion calls, and Claude
also needs native count_tokens requests. Reserve room for these requests and
paired checks before starting. Keep the public Express controls and free-run
rules unchanged. If actual attempts or money do not fit, stop at the guard and
mark unfinished runs/cells not run or incomplete. Never raise limits, weaken
quality assertions or call a truncated run complete. Do not rerun a failed
workflow or an unknown outcome to get a better result.

Use EQ's fixed public paired fixtures and rubric for roles actually exercised.
Use E0's meter for counts/sizes and real provider usage for costs. Repeat stable
run/item prefixes within five minutes, at least the checked provider minimum
(512 Claude / 1024 Azure), and include both typed T boundaries. Use run id plus
call type for Azure keys; obey the gateway's 15/minute key partitions. Record
per call type: own prompt/input tokens, output tokens, cache reads, cache writes,
cached share, cost without cache and actual cost, refusal count/rate, saved calls
and paired quality. Count thinking within output. Do not raise Claude effort
when quality drops; report numbers to the owner. A first cold write can cost
more than uncached input; do not call it a saving. If a provider omits priced
usage, label spend unknown and retain the reservation.

Return a compact results table with exact SHA, UTC date, total attempted HTTP
requests by provider and endpoint category, completions/refusals/errors, real
USD and EUR costs, unknown money held, cache-read/write counts and shares, paired
quality, workflow completion/status and reduced controls. Express and Standard
before/after cost projections must remain labelled estimates from E0 and the
Haiku factor; Standard is not an operator-funded live run. Do not fabricate a
rate from hermetic tests or infer cache hits from markers alone. List each
unproved acceptance item explicitly. Post only those safe numbers on #453;
keep raw local artifacts private. Use the safe results table below under W4
local run: results. No keys, old identifying subdomain, prompts, responses,
raw logs, headers, private data or unfiltered artifacts may be posted.
After posting, remove the fresh temporary checkout and all check data. Stop
polling and do not rerun this SHA. Do not claim launch readiness from these
checks alone.
```

## Safe results table

Use numbers or `not run`, `incomplete` and `unknown`; never invent a result.

| Field | Result |
|---|---|
| Exact main SHA / UTC date | |
| Azure capacity / Cloudflare | Done in Part A |
| Claude / Azure / total HTTP attempts | |
| Attempts by endpoint: count / completion / metadata / other | |
| Completions / refusals / errors by provider | |
| Actual Claude USD / Azure EUR / unknown holds | |
| Default Express: Claude / Azure completion status | |
| Express / Standard before-after cost estimates (E0) | |
| Unproved items / reduced controls | |

One row per provider and call type; mark estimates separately from billed costs.

| Provider / call type | Input / output tokens | Cache read / write tokens | Cached share | USD/EUR before cache / actual | Refusals / calls / rate | Saved calls | Paired quality |
|---|---|---|---|---|---|---|---|
| | | | | | | | |

The visitor export contains only visitor data. The operator credit ledger is
operator data and is outside that export. `/privacy` already lists Anthropic.
