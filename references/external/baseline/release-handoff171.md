# M1 release handoff — preparation only

No PR exists for `feat/external-m01-free-baseline` as checked in cycle 171.
Do not merge until model selection, local live acceptance and security coverage
are complete. No configuration below has been applied to production.

Cycle 175 update: isolated checkout `/private/tmp/coscientist-scope174` contains
unintegrated policy commits `79d4a73a` and `465000c7`. The first adds `execution_policy`
columns to runs and interviews, defaulting legacy rows to `standard`. Once
integrated, include both columns in backup/schema and rollback verification;
the earlier single-column migration inventory will no longer be complete.
Context propagation and MCP coexistence are still under implementation.

## Prepared PR description

System-default free routes previously relied on static pricing and several app,
tool and evaluation paths could bypass cost admission. This change validates
current OpenRouter eligibility and attaches zero-price ceilings at request
boundaries, isolates credentials and caches in campaign-mode processes, and
restricts retrieval and workspace execution in those processes. Coexistence
with ordinary BYOK in shared production remains an open gate. Scientific assessment changes preserve
located evidence and record how contradictions were verified.

Offline component results are retained in `release-verification140.json`.
The original `make test-all` invocation failed a pause/resume test; the later
full app rerun passed 1,851 tests. Do not describe the original invocation as
passing. Final model configuration and live workflow evidence remain pending.

## Configuration handoff

| Setting | Required release value or action |
| --- | --- |
| MODEL_NAME | Qualified Nex Pro primary; final chain pending fallback evidence |
| SUPERVISOR_MODEL_NAME | Explicit qualified model, never inherited Minimax |
| CHAT_MODEL_NAME | Explicit qualified model, never inherited Minimax |
| SEMANTIC_SAFETY_MODEL | Explicit qualified model, never inherited Minimax |
| CLAIM_VERIFIER_MODEL | Explicit qualified model or documented primary inheritance |
| COSCIENTIST_REQUIRE_FREE_MODELS | Enable for campaign API/MCP execution; verify BYOK separation before choosing shared production scope |
| COSCIENTIST_CAMPAIGN_MCP_URL | Exact existing deployed MCP /mcp URL after server policy verification |
| RAILWAY_RUN_UID | Preserve 0 on API |
| API replicas | Preserve exactly 1 |
| COSCIENTIST_DB_PATH | Preserve /app/data/coscientist.db |
| COSCIENTIST_CACHE_DIR | Preserve /tmp/coscientist-cache |

Campaign mode overrides BYOK, so globally enabling it is not evidence that
ordinary users' BYOK behavior is preserved. Resolve that deployment boundary
before applying settings; system-default free admission exists independently.

## Ordered release gates

1. Finish fallback qualification and final configuration. Resolve M1-release-scope
   and verify concurrent campaign restrictions and ordinary BYOK through public
   requests and durable runs in the chosen production boundary; run affected checks.
2. Complete the isolated live browser workflow and retain sanitized evidence.
3. Complete security coverage for the actual release revision, including changes
   after the older fixed scan target. Prepare the PR with exact test evidence.
4. Immediately before merge, verify the consistent SQLite backup described in
   campaign.md. Preserve the additive verification_method column on rollback.
5. Deploy/verify MCP policy before enabling API campaign admission. Preserve
   service invariants; verify the API and frontend revisions and actual settings.
6. Run production smoke and the campaign-owned public goal with notifications
   disabled. Record deployment IDs and establish a verified zero-cost recovery
   target. The old Minimax deployment is not such a target.

This document supplies a reviewable handoff, not release acceptance or proof of
live scientific quality. Final PR text must include the actual selected chain,
final checks, live artifacts and any remaining limitations.
