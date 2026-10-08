# W4 owner-local check prompt

Paste the block below into a local executor with the owner's environment.
Do not paste secret values into a conversation. Authority and allocation:
[campaign owner decision](https://github.com/guy915/Co-Scientist/issues/453#issuecomment-6063799306).

```text
You are the local executor for Lane W4 (models and spend) in guy915/Co-Scientist.
W4 has completed the hermetic transport/credit work in a cloud session that has
no provider keys. Your job is to collect bounded live evidence and return only
safe results for issue #453. Read AGENTS.md, engine/AGENTS.md, app/AGENTS.md,
docs/azure-setup.md, docs/anthropic-credit.md, docs/llm-caching.md and the latest
W4, T, E0 and EQ comments on #453 first.

Authority: W4 allocation is 9 October 2026 UTC only: at most 50 total outbound
provider requests, at most $5 Claude API, at most €5 Azure. The credit/key
incident is closed for lanes on the owner's fresh-launch-key disposition.
Do not rotate, revoke or delete keys or artifacts. Do not use the old projects'
keys in the new launch setup. Never assume another lane's unused requests are
available. If the date/allocation does not match, perform offline preparation
only and report that condition. Do not block a terminal waiting overnight.

Use existing keys from the owner's local environment. Check presence without
printing values. Do not print env dumps, command traces, headers, raw provider
exceptions, URLs with query keys, prompts, responses or private run data. Disable
raw SDK/HTTP logging and private trace exports. Never upload an unfiltered DB,
trace or log. If settings are missing, return variable NAMES only; do not ask for
keys in chat. Do not change hosted env, Azure quotas or deployments here.

First fetch origin/main and use an isolated checkout of the merged W4 routing,
explicit test adapter, spend view, E cuts and T's stable-prefix boundaries.
Record the exact SHA. If any required source is unmerged, report the missing PR;
do not substitute an unpublished branch or claim the integrated result.
Recheck primary provider docs. Use only claude-haiku-5-5, direct Anthropic API;
Azure gpt-6-luna-2026-09-22 and gpt-5-nano-2025-08-07, native Responses API.
Claude always adaptive thinking/low, no sampling, own count_tokens, prompt
<=100K, existing role output caps. Never Sonnet, Opus, Fable or a paid route
outside the two Azure models. No Message Batches for these live checks.

Prepare a temporary local SQLite ledger and synthetic public goals. Keep the
normal per-user/global/app/call limits. Set only isolated process settings:
Claude monthly test credit $5 (the 95% guard stops at $4.75), Azure total €5,
FX .88 and the owner's valid expiry date. Keep the deterministic adapter OFF.
Do not reuse or edit production data. Prevent operator-funded Standard runs.

Before the first provider request, install a thread-safe durable counter for
the whole allocation at outgoing SDK HTTP dispatch. Persist each reservation
before sending; a process restart must keep all previous attempts charged.
Use one counter across subprocesses. Include count_tokens, catalogue reads, retries,
429s, failures and unknown outcomes in the 50. Every outgoing request consumes a
slot BEFORE send. Fail closed at 50, without allowing a retry to bypass it.
Use the gateway's conservative money reservations BEFORE each call. Unknown
outcomes retain their full hold; never infer free success or rerun them. All SDK
retries stay zero. A refusal is billed and goes to separately admitted Azure
for that call; count that fallback in the same 50. Stop on any money guard.

Choose the smallest honest check set within those bounds. Prefer one bounded
Express workflow on each provider with repeated stable-prefix calls in one
wave. Preflight the E0 envelope: the recorded default Express double uses about
52 completion calls, and each Claude count adds an outbound request. Therefore
two default complete runs may NOT fit 50. Keep the public Express controls and
free-run rules unchanged. If completed runs do not fit, collect representative
paired call types and stop, reporting full Express completion as unproved.
Return the needed request allocation to the coordinator; do not grant it to
yourself. Never raise limits, weaken quality assertions or call a truncated run
complete.

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
keep raw local artifacts private and remove the temporary data after extracting
the safe report. Do not claim launch readiness from these checks alone.

Separate owner-local dashboard step from the same decision: in Cloudflare
Dashboard -> Account details, rename the workers.dev subdomain whose current
name is the owner's email local part to a neutral name such as open-coscientist.
Check that the neutral name is available before applying this exact rename.
Do not change worker routes, DNS, services or keys. Return only the new neutral
subdomain name, never the old identifying name. If dashboard access is absent,
report this one pending owner step. No other hosted changes are authorized.
```

## Coordinator hand-off

```text
I am Lane W4 (models and spend) in guy915/Co-Scientist. Settlement, transport,
cache accounting, credit guards and routing are merged through #620. The
explicit adapter is merged as #626; the private spend view is in #632.

The remaining live acceptance gate needs an owner-local executor with existing
environment keys and merged T boundaries. Cloud has no provider keys. Do not
send keys in chat or run providers here. Use this document's local prompt.

W4 has 50 total provider HTTP attempts on 9 October, $5 Claude and €5 Azure.
Default Express uses about 52 completions; Claude also needs count_tokens
requests. Full Express runs on both providers plus paired quality/cache checks
cannot fit 50. Please assign a concrete later-day allowance before launch, or
identify the acceptance evidence the owner replaces. Keep all public run,
user and call limits; do not borrow E/EQ requests or claim truncated runs done.

Also confirm T's merged boundary source and P's operator-credit export scope.
Owner setup still needs usable Azure quota and fresh API-only keys. Report
only safe numbers and variable names. No new hosting action is requested.
```
