# M1 release handoff — preparation only

No PR or remote campaign branch exists as checked in cycle 179; see
`release-state179.json`. API/MCP production still serves `7dce086d`.
Do not merge until model selection, local live acceptance and security coverage
are complete. No configuration below has been applied to production.

Cycle 179 update: reviewed policy changes are integrated through `f9c3b7fb`.
They add `execution_policy` columns to runs and interviews, defaulting legacy
rows to `standard`; include both in backup/schema and rollback verification.
Persisted policy now reaches request, deferred, durable and authenticated MCP
boundaries. Production configuration and live acceptance remain pending.

## Prepared PR description

System-default free routes previously relied on static pricing and several app,
tool and evaluation paths could bypass cost admission. This change validates
current OpenRouter eligibility and attaches zero-price ceilings at request
boundaries, isolates credentials and caches for campaign requests/tasks, and
restricts their retrieval and workspace execution. Persisted server-derived
policy preserves ordinary BYOK in shared services; deployed coexistence remains
an open gate. Scientific assessment changes preserve
located evidence and record how contradictions were verified.

Current local verification is retained in `release-verification178.json`:
complete test-all passed (3,134 engine, 1,873 app, 279 MCP tests and parity),
as did lint, typecheck, build, evaluation smoke, 718 frontend tests and nine
offline browser tests. Two existing engine skips remain; none were added to
obtain these results. Earlier failed invocations remain historical evidence.
Final model configuration and live workflow evidence remain pending.

## Configuration handoff

| Setting | Required release value or action |
| --- | --- |
| MODEL_NAME | Qualified Nex Pro primary; final chain pending fallback evidence |
| SUPERVISOR_MODEL_NAME | Explicit qualified model, never inherited Minimax |
| CHAT_MODEL_NAME | Explicit qualified model, never inherited Minimax |
| SEMANTIC_SAFETY_MODEL | Explicit qualified model, never inherited Minimax |
| CLAIM_VERIFIER_MODEL | Explicit qualified model or documented primary inheritance |
| COSCIENTIST_REQUIRE_FREE_MODELS | Keep global flag off in shared API/MCP; persisted policy enables campaign scope per request/task |
| CAMPAIGN_RESEARCHER_IDS | JSON array of verified bearer subjects for campaign-owned runs; unsigned compatibility IDs cannot originate campaign policy |
| COSCIENTIST_CAMPAIGN_MCP_URL | Exact existing deployed MCP /mcp URL after server policy verification |
| COSCIENTIST_MCP_SHARED_SECRET | Configure a matching secret on API/MCP before campaign activation; it was absent from the observed API configuration. Never record its value in evidence. |
| RAILWAY_RUN_UID | Preserve 0 on API |
| API replicas | Preserve exactly 1 |
| COSCIENTIST_DB_PATH | Preserve /app/data/coscientist.db |
| COSCIENTIST_CACHE_DIR | Preserve /tmp/coscientist-cache |

Campaign mode overrides BYOK, so globally enabling it is not evidence that
ordinary users' BYOK behavior is preserved. Resolve that deployment boundary
before applying settings; system-default free admission exists independently.

## Ordered release gates

1. Finish fallback qualification and final configuration. M1-release-scope-a through scope-d
   are locally verified in `scope-acceptance177.md`; verify the same behavior
   on deployed shared services and rerun checks affected by later changes.
2. Complete the isolated live browser workflow and retain sanitized evidence.
3. Complete security coverage for the actual release revision, including changes
   after the older fixed scan target. Prepare the PR with exact test evidence.
4. Immediately before merge, verify the consistent SQLite backup described in
   campaign.md. Preserve all three additive columns on rollback.
5. Deploy/verify MCP policy before enabling API campaign admission. Preserve
   service invariants; verify the API and frontend revisions and actual settings.
6. Run production smoke and the campaign-owned public goal with notifications
   disabled. Record deployment IDs and establish a verified zero-cost recovery
   target. The old Minimax deployment is not such a target.

This document supplies a reviewable handoff, not release acceptance or proof of
live scientific quality. Final PR text must include the actual selected chain,
final checks, live artifacts and any remaining limitations.

Cycle 179 incident: an unfiltered API variable query exposed four credentials
in tool history; only their names are retained in `release-state179.json`.
Coordinated rotation approval is pending. Do not repeat the values or change
live credentials without that approval. The unrelated security-plugin config
preflight remains unresolved as documented in `security-recovery171.md`.
