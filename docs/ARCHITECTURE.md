# Architecture

This document describes the current runtime shape of the Co-Scientist workspace.

## Layers

```
+--------------------- frontend (src/workbench) ---------------------+
| BrowserRouter                                                      |
|   /                  -> ChatWorkspace   (session home)             |
|   /runs, /runs/new   -> redirect to /                              |
|   /runs/:id          -> redirect to the details tab                |
|   /runs/:id/:tab     -> RunDetail (active tab persisted in URL)    |
|   /chats/:id         -> ChatWorkspace   (one saved conversation)   |
|   /access            -> researcher access-code exchange            |
|   *                  -> NotFoundPage                               |
|                                                                    |
| useChatSession (chat timeline, steering + Q&A)                     |
| useRunStream  (fetch + SSE reader on /api/runs/:id/events)         |
| src/api/runs.ts  (typed client for every backend endpoint)         |
+------------------------------+-------------------------------------+
                               |
                          HTTP + SSE
                               |
+------------------------------v-------------------------------------+
| FastAPI (app/app)                                                  |
|                                                                    |
|   main.py        — composes router, CORS, lifespan                 |
|   config.py      — pydantic-settings                               |
|   runs/          — /api/runs/* lifecycle, read, messages, and SSE   |
|   engine_tasks/   — durable node/fan-out/match executor; the only  |
|                     way any run advances (no in-process workflow)  |
|   task_worker/   — leased worker cohort draining scientific_tasks  |
|   engine_adapter/ — provider selection + offline/real LLM backend  |
|                     switch; bridges to the engine                  |
|   store/         — SQLite store (runs/events/hypotheses/evidence/  |
|                    citations/matches/reviews/reports/safety/       |
|                    scientific_tasks/checkpoints/supervisor_plan)   |
|   elo.py         — app-side leaderboard projection (initial=1200,  |
|                    configurable K); the Elo math lives in the      |
|                    engine's ranking agent                          |
|   safety/        — intake + final gate: deterministic rules first, |
|                    then an optional contextual model assessment    |
|   citations/     — verified|partial|unsupported|unavailable        |
+------------------------------+-------------------------------------+
                               |
                               v
                     +----------------------+
                     | co_scientist         |
                     | Scientific engine    |
                     | (offline or real LLM |
                     |  backend)            |
                     +----------+-----------+
                                |
                     (optional) v
                     +----------------------+
                     | MCP literature server|
                     +----------------------+
```

## Pipeline events (canonical timeline)

Every run executes through the durable task queue, and the same event-log table is written regardless of which LLM backend (offline or real) is behind it. A run produces this sequence:

```
1.  lifecycle       (created)                    written by POST /api/runs
2.  lifecycle       (queued)                     written by POST /{id}/start
3.  safety.intake   (allow/redact/block)
4.  scientific_task (task=bootstrap)
5.  scientific_task (task=supervisor,        successor=generate)
    scientific_task (task=generate,          successor=review)
    scientific_task (task=review,            successor=comprehensive_reflection)
    …                                            one row per durable node commit,
    scientific_task (task=research_overview, successor=null)
6.  safety.hypothesis  (per-hypothesis screen counts)
7.  citation.grounding (claim-grounding counts)
8.  citation_audit     ({verified, partial, unsupported, unavailable})
9.  safety.final
10. report             (structured payload + markdown)
11. status             (completed)
```

Events 1-2 come from the HTTP layer. Events 3-5 come from the worker: `safety.intake` is the `engine.bootstrap` task's first act (`engine_tasks/inputs.py::_screen_bootstrap_intake`, which is also where the run flips to `running`), then one `scientific_task` per node commit. Events 6-11 come from the terminal `engine.finalize` task (`report.finalize.finalize_report`), which is why the citation audit lands *after* `research_overview` rather than before it. There is no `status (running)` event — the transition into `running` is a `runs` row update, not an event.

Every engine node reports under the single `scientific_task` type, carrying the node it completed in `payload.task` and the node it scheduled next in `payload.successor` (`engine_tasks/support.py::_emit_node_completion`). The engine's named stage vocabulary (`supervisor.plan`, `literature_review`, `generate`, `ranking`, …) survives only as milestone *chat messages* appended to `messages` by `engine_adapter.events.append_node_milestone`; no `run_events` row carries those types. The frontend's active-run view reads the node out of `payload.task` for exactly that reason (`run_detail_active.tsx::activityPhase`).

Which nodes appear, and how often, is the orchestrator's decision rather than a fixed script: `review → comprehensive_reflection → safety_screen → deep_verification → ranking → orchestrator` recurs once per cycle, `meta_review → evolve` precedes a re-review, `proximity` runs only when the pool grew since the previous pass, and `literature_review`/`reflection` are absent entirely when no MCP server is reachable (durable routing bypasses those nodes).

The SSE endpoint at `GET /api/runs/{id}/events?after=<seq>` always replays history starting at the requested sequence, then tails live. This is what makes "reopen after restart" work: the client never depends on in-memory event state.

## Persistence model

Tables (SQLite, WAL):

| Table | Append-only? | Notes |
| --- | --- | --- |
| `runs` | mutable status/error/timestamps | one row per run |
| `feedback` | bounded | owner-scoped message plus session diagnostic export; newest 200 within 10 MiB, visible for 30 days |
| `feedback_admissions` | bounded | durable rolling-minute owner/host/global admission budgets, independent of feedback eviction |
| `run_events` | append-only | canonical event log; `(run_id, seq)` |
| `hypotheses` | append-only | original rows never mutated; `parent_id` for lineage |
| `hypothesis_state` | mutable | Elo, win/loss, scores, status, cluster_id — separated to preserve append-only invariant on `hypotheses` |
| `evidence` | append-only | retrieved sources |
| `citations` | append-only | per-hypothesis claim → evidence with classification state |
| `reviews` | append-only | reflection, review, meta_review |
| `matches` | append-only | full pairwise tournament audit log |
| `safety_decisions` | append-only | intake + final |
| `reports` | append-only | structured JSON + rendered Markdown in SQLite |
| `messages` | append-only steering/milestones; Q&A can rewind | consumed run input is preserved when the scientist edits a question or retries an answer |
| `scientific_tasks` | mutable (leases/status) | the durable queue itself — every engine node, fan-out item, and tournament match is a leased, idempotent row here; this is the only path a run executes through |
| `checkpoints` | append-only, pruned | `WorkflowState` snapshot after each committed task, the resume point |
| `supervisor_plan` / `supervisor_allocations` | replaced wholesale at finalize, plus synced on every checkpoint | the Supervisor's plan and terminal rationale, and an append-only-per-run ledger of every task the orchestrator scheduled with the observed stats behind each decision; retained internally for checkpoint provenance |

`hypothesis_state` is the critical decoupling: it holds the values that *must* change as the run progresses (Elo, win counts) without violating the rule that an original hypothesis row is the historical record of what was generated.

## Provider selection

`engine_adapter.select_provider()` always returns `"engine"` — the app's earlier mock workflow has been retired, and the engine is now a hard runtime dependency (a missing `co_scientist` install raises at startup instead of silently falling back).

What varies per run is the **LLM backend**, not the provider. `engine_adapter.offline_mode()` returns `True` when:

1. `COSCIENTIST_FORCE_OFFLINE=1` is set, OR
2. no supported provider key is configured.

An offline-backed run still executes the real durable engine; `co_scientist.offline.llm.install_offline_router()` installs the engine's completion backend for `offline/`-prefixed models, which returns deterministic, schema-valid content instead of calling a real provider. The resolved backend (`"offline"` | `"real"`) is persisted per run as `llm_backend` and reported at `/status`; the deprecated `mock_mode` mirror of that value has since been removed from the API surface. A re-opened run remembers which backend produced it.

## Curated example chats

The three seeded examples include fixed scope conversations, completed plan
cards, illustrative Q&A and their scientific results. Titles begin `Example: `.
Desktop Recents and a mobile example strip open `/examples/:id`, which requests
`POST /api/runs/{id}/example-chat` and navigates to the visitor's owned chat.

`store/examples.py` copies the curated scientific records and transcript in one
SQLite transaction, remapping identities and lineage. It reuses one copy per
owner and source on later opens, preserving continued chat. No engine tasks,
credentials, logs or free-generation allowance are copied or
consumed; the copy makes no provider or retrieval call. Existing researcher
authentication still applies. Shared examples allow reads and this copy endpoint;
other mutations return 403. Seed version 15 backfills the full conversations,
with a readiness marker committed only after the curated bundle is complete.

## Run chat context

Run Q&A reads a consistent SQLite snapshot without draining the engine or
acquiring its write lock. Active runs use the latest compatible checkpoint
for hypotheses, reviews and tournament matches. Published rows remain
available alongside checkpoint science, interview answers, setup, supervisor
plan, literature, evidence, safety decisions, meta-review and reports.
`qa/snapshot.py` selects scientific channels; runtime handles, routing and
credentials never enter chat context.

The initial prompt is bounded to 24,000 characters plus grounding rules.
`search_ideas` provides short idea bodies; `search_run_artifacts` searches or
pages every record and its remaining text (three 2,400-character chunks per
lookup). At most four tool calls share one lookup round, then one answer
round under the existing Q&A spend scope. The numbered evidence manifest
remains the sole citation namespace: checkpoint literature does not become
verified merely because chat can read it. Finalized tables remain authoritative
for completed runs; checkpoint-only scientific detail stays retrievable.
Failed or cancelled runs retain their latest committed checkpoint science.

## Frontend state

The workbench caches no *run or hypothesis* data in the browser — nothing
like a Redux store of fetched entities. On mount it:

1. Calls `getRun(id)` for status + summary counts.
2. Calls `getHypotheses / getEvidence / getMatches / getReviews / getClaimEvidence / getSafety / getReport` in parallel.
3. Streams `/api/runs/{id}/events?after=0`, which replays every event since the run
   started and then tails live. Not an `EventSource`: the browser API cannot set
   request headers, and the stream is authenticated (`Authorization` for a
   researcher session, `X-Client-ID` otherwise), so it is a `fetch` whose body is
   read by the frame reader in `src/api/runs_http.ts::readSseFrames`.
4. Run-scoped Q&A (`POST /api/runs/{id}/messages/ask`) and steering
   (`POST /api/runs/{id}/messages`) remain available to API clients. The
   frontend's unused wrappers are removed; the chat workspace does not poll
   run-scoped messages.

This means a hard refresh, a backend restart, or a new browser session all
produce the same *content* — every run/hypothesis/report view is always
re-fetched from the API, never read back from a client cache.

It does persist a handful of small, non-content keys, all via
`localStorage`/`sessionStorage` (not a state-management library): the
client id and (when a researcher session is active) its bearer token
(`lib/client_id.ts` — `co_scientist_client_id`, `co_scientist_access_token`),
the light/dark theme (`workbench/theme_context.tsx` —
`cosci-theme`), a scientist's own BYOK provider key when set
(`lib/api_key.ts` — `cosci-api-key`, `cosci-api-provider`), and the Logs
popover's per-session baseline row id (`workbench/layout_diagnostics_state.ts`
— `cosci-logs-session-baseline`). These are identity, preference, and UI
bookkeeping, not a cache of server content, which is why point 1-4 above
still holds: nothing here lets a view render without hitting the API.

## Why this shape

-   The complete scientific workflow is preserved — every run drives the
    engine through the durable task queue (`engine_tasks`), one leased task
    per engine node, fan-out item, and tournament match; only the LLM backend
    underneath (offline or real) varies with configuration.
-   The FastAPI app is a single ASGI application composed from routers in
    `main.py` — the run router alongside the diagnostics endpoints
    (`/health`, `/config`, `/status`, defined in `diagnostics_api.py` and
    mounted by `app.main`).
-   Frontend stack is preserved: React 19 + Vite 7 + Tailwind v4 + Bun + gts.
    The workbench lives under `src/workbench/`; the earlier public landing
    page and demo routes were removed, and `src/public/` now holds only
    residual helpers (404 page, no-index). A landing page now lives *under*
    the chat home instead (`pages/home_landing*.tsx`), one scroll below the
    composer, so the app still opens on the chat.
-   The engine's offline LLM backend exists so the system has **observable
    behaviour without any external dependency**. The same durable tasks
    run either way; only the completion backend's answer for `offline/`
    models differs. This unlocks CI, deterministic tests, and a usable demo
    without provider keys.

## Shared evidence gathering

`co_scientist.evidence` owns search configuration, source fan-out, retries,
ranking, evidence budgets, article construction and research-record provenance.
Generation and Reflection call the same `collect_papers` operation; Reflection
keeps its small probe budget and disables the semantic relevance model pass.
Agent-specific query planning, synthesis and failure presentation remain in
`agents/`. The evidence package never imports an agent, enforced by
`engine/tests/test_literature_review_retrieval.py`.

Evidence consumers import helpers from their defining modules:
`search_support`, `search_budget`, `retrieval_support` and `article_support`.
The former internal `evidence.helpers` facade is removed. The node and search
orchestrators expose only the collaborators they actually use.

## Code organization

Modules group related behavior. The generator prepares state and tool
capabilities; durable tasks own execution. PubMed retrieval uses one source
class instead of a mixin chain. Report construction and frontend components shape their data
where it is consumed, without pass-through payload objects or single-use
style facades. Private helpers are imported from their defining modules.

The durable task dispatcher lives in `engine_tasks/__init__.py`; bootstrap
lives in `final_state.py`, specialist execution and state overlays in `node.py`,
and final draining/publication in `finalize.py`. All paths retain the shared
lease and checkpoint commit guards. Line-count ceilings are retired in favor
of cohesive modules, with behavior, type, and layer boundaries checked in CI.

## Generation operations and execution ownership

`co_scientist.agents.generation` exposes `GenerationPlan`, `GenerationCounts`,
`GenerationResults`, `prepare_generation` and `finalize_generation`.
`operations.py` owns input validation, allocation, citation context, result
assembly, enrichment and lineage. The generation agent coordinates parallel
strategies; `app.engine_tasks` owns durable scheduling, leases, retry keys,
partial-failure isolation and checkpoint commits. Finalization may perform
network work and runs before the store transaction.

The interface preserves existing execution differences: the generation agent
performs expansion research and grounds assumptions with literature; durable
generation retains its current assumptions inputs and per-strategy tasks.
Changing those differences requires an explicit grounding and spending policy.

## Ranking, Reflection and Evolution operations

The Ranking package exposes preparation, remaining-round budgets, deterministic
pairing, immutable prompt/judging contexts, one-match judging and Elo application,
and finalization. The ranking agent commits each result before selecting its
next pair.
The durable adapter selects a wave from checkpoint pool order, judges it against
one median snapshot and commits surviving outcomes in wave order. Both meter
reported debate turns with budgeted depth as fallback. Agent prompts retain
preferences; durable prompts retain their existing criteria-only adaptation.

Reflection exports initial-review gates, verification selection and one-item
verification/observation/mature-review operations. The engine assembles evidence
and private contexts; the app persists markers, reviews and separate research
ledgers. Ordinary item failures preserve siblings; platform-cap and call-budget
exceptions reach the worker. Agent verification bounds stored details and
marks issuance before calls; durable aggregation retains raw results, marks issuance
on aggregation and meters successful valid items.

Evolution owns the public `EvolutionContext` and round-context assembly,
including guidance, citation sources, parent validation and duplicate guards.
The app adapts checkpoints through these public operations.

`app/tests/test_architecture.py` enforces that app production
modules import public engine symbols and the engine does not import the app.
The [operation-boundary plan](https://github.com/guy915/Co-Scientist/blob/7c2878aeb071a962cb713e9c271cd88e1635ca5f/docs/superpowers/plans/2026-10-02-engine-operation-boundaries.md)
records the interfaces and characterized execution adaptations.

## HTTP, storage and frontend ownership

Interview routers and SSE transport call `interviews.turns.advance_turn`.
`interviews.support` owns interview access and request-credential guards;
`staged_documents` resolves owned attachments for both interviews and runs.
Logs, diagnostics and API documentation share `operator_access.is_operator`,
which checks the admin token or the direct loopback client address.

The reference MCP server's `pubmed_storage` owns metadata JSON, digest proofs
for empty PMC lookups and portable run links. It imports only the standard
library; retrieval and shared-pool orchestration depend on it. Evaluation
identity hashing, validation and request-policy snapshots similarly live in
the execution-independent `evaluations._identity` module.

Run-detail frontend composition separates event invalidation policy, parallel
snapshot reads and collection state. Requests own each resource they fetch:
an older partial response cannot replace a newer terminal snapshot, while
disjoint collection reads can both apply. Navigation and unmount invalidate
pending requests and debounce work. Run and chat histories share the same
list-reload lifecycle while retaining their own API reads and events.
