# Architecture review after the package and boundary campaign

Reviewed 1 October 2026 against the layout after #100/#101 and the follow-up
architecture commits. This is a direct source, dependency and contract review;
the handoff's named `improve-codebase-architecture` skill was unavailable.
Scope: engine/app package ownership, production import closure, evidence
retrieval, provider seams, durable execution, and frontend JSON contracts.

## Completed boundaries

| Boundary | Result | Evidence |
|---|---|---|
| Engine/app package moves | Engine modules import in a fresh interpreter; #100 CI builds API/MCP/frontend images and validates compose | #100 CI run 36937236061; main browser suite 18 passed; Railway API deployment 7e565d7c-4b59-4631-87d3-c84e37a51300 started on merge a097e34 and logged `/health` 200 |
| Free catalog | `CatalogReader` owns its synchronous loader, TTL snapshot and thread lock; fixtures install a scoped source through public functions | `engine/tests/test_free_catalog.py`; no test patches on catalog `_snapshot` or `_fetch_catalog` remain |
| Durable finalize dispatch | Test patches the captured dispatch-table entry and asserts that its fake runs | `app/tests/test_engine_tasks_dispatch.py::test_worker_consumes_independent_specialist_task_chain` failed before the patch was corrected |
| Evidence gathering | `co_scientist.evidence` owns configuration, fan-out, retries, ranking, budgets, article assembly and research-record provenance; Reflection no longer imports Generation | `engine/tests/test_evidence_layering.py`, `test_evidence_gathering_contract.py`, existing search/probe/research suites |
| JSON contracts | Backend `TypedDict` response models drive FastAPI validation/OpenAPI and generated frontend modules; old import paths re-export types | `app/tests/test_response_contracts.py`, `test_response_contract_characterization.py`, frontend saved-report/insights regressions |

Generation now contains 36 Python files / 9,209 lines, down from the handoff's
approximately 12.4k lines. The shared evidence package holds 16 files / 3,200
lines and imports no agent. Size reduction follows ownership: planning,
analysis, synthesis and agent-specific diagnostics stayed in Generation.
Reflection retains its small probe budget, disables the semantic relevance
model pass, rejects retracted sources and preserves corpus fallback/provenance.

Response models preserve absent fields separately from null and retain extra
persisted fields. The review uncovered inaccuracies in the former frontend
contracts: current run modes include depth tiers; saved reports can omit
modern sections or even the leaderboard; curated evidence spans can omit
source names and offsets; interview field edits can omit documents; scientist steering can use a
researcher identity as its message sender. Those
shapes are now modeled and exercised through real reads. Public shares still
apply the existing release gates and explicit field projection before response
validation. Generated types do not replace ownership or publication policy.

## Remaining findings

1. **OWNER DECISION — tool-call throttling.** `llm/attempts/contract.py` and
   `llm/tools/iteration.py` deliberately use an escalation-only plan for tools.
   A 429 does not get the ordinary completion backoff/park behavior. Decide the
   intended tool-turn retry and spending policy before changing it.
2. **OWNER DECISION — app provider accounting.** `app/app/llm_request.py`
   applies offline/free admission but calls LiteLLM directly, outside the
   engine attempt-loop timeout, call budget and telemetry. The token/timeout
   floors in `config_thinking.py` are still repeated. Routing interview, Q&A,
   titling and other app calls through the engine changes spend accounting;
   a shared transport must also preserve streaming and conversational effort.
3. **Follow-up, medium — durable generation reaches private agent helpers.**
   `app/app/engine_tasks/fanout_generation.py` and `fanout_aggregates.py` import
   Generation coordinator internals. These are the next cross-package boundary
   worth making explicit: expose strategy planning and result aggregation as
   engine operations, then characterize the durable fan-out against the graph
   path. Do not erase documented topology differences or change task counts,
   retry keys, leases or per-strategy spend while extracting that interface.
4. **Follow-up, low — internal compatibility facades.** Generation's `node`
   and the shared `evidence/helpers.py` still re-export many private helpers for
   older callers/tests. They are intra-package coupling rather than an agent
   ownership violation. Future edits should import the defining module and
   patch where globals are actually read, removing unused exports only after
   checking consumers. The lazy public LLM facade remains intentional.

The catalog installation is process-wide, matching the completion backend
because worker cohorts use different event loops/threads. It is for process
configuration and isolated tests, not per-request tenant selection. Its cache
uses a thread lock, never a shared asyncio primitive, and a failed refresh
cannot return expired prices. No paid fallback or zero-price routing policy
changed in this campaign.

Direct HTTP requests to production were blocked by the workspace network
proxy; the read-only Railway deployment/startup and healthcheck logs above are
the production evidence. No production configuration or data was written.

## Follow-up validation

- Fresh interpreter import of every engine and app module succeeds.
- Strict mypy succeeds for app, engine and evaluations; Python/frontend lint,
  parity references and both length gates pass.
- All 880 frontend tests pass; the production frontend builds and prerenders;
  all 18 isolated browser tests pass using the installed system Chromium.
- Full local engine, app and evaluation runs exposed remaining test contracts:
  one concatenated retry patch, one subprocess catalog reset, researcher
  message senders, and two invalid publication/policy fixtures. The fixes pass
  their focused suites (21 engine, 3 evaluation and 32 app tests). The full
  suites run again in presubmit on the final PR commit before merging.

The completed `HANDOFF-ARCHITECTURE.md` is removed. OWNER DECISION items remain
recorded above and were skipped as instructed; the new follow-ups are review
findings, outside the completed handoff backlog.
