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
|   /shared/:token     -> public read-only Goal Report               |
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
|   runs.py        — /api/runs/* lifecycle, read, messages, and SSE   |
|   engine_tasks.py — durable node/fan-out/match executor; the only  |
|                     way any run advances (no in-process workflow)  |
|   task_worker.py — leased worker cohort draining scientific_tasks  |
|   engine_adapter/ — provider selection + offline/real LLM backend  |
|                     switch; bridges to the engine                  |
|   store/         — SQLite store (runs/events/hypotheses/evidence/  |
|                    citations/matches/reviews/reports/safety/       |
|                    scientific_tasks/checkpoints/supervisor_plan)   |
|   elo.py         — app-side leaderboard projection (initial=1200,  |
|                    configurable K); the Elo math lives in the      |
|                    engine's ranking agent                          |
|   safety.py      — intake + final gate: deterministic rules first, |
|                    then an optional contextual model assessment    |
|   citations.py   — verified|partial|unsupported|unavailable        |
+------------------------------+-------------------------------------+
                               |
                               v
                     +----------------------+
                     | co_scientist         |
                     | LangGraph engine     |
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

Events 1-2 come from the HTTP layer. Events 3-5 come from the worker: `safety.intake` is the `engine.bootstrap` task's first act (`engine_tasks.py::_screen_bootstrap_intake`, which is also where the run flips to `running`), then one `scientific_task` per node commit. Events 6-11 come from the terminal `engine.finalize` task (`report.finalize.finalize_report`), which is why the citation audit lands *after* `research_overview` rather than before it. There is no `status (running)` event — the transition into `running` is a `runs` row update, not an event.

Every graph node reports under the single `scientific_task` type, carrying the node it completed in `payload.task` and the node it scheduled next in `payload.successor` (`engine_tasks_emit.py::_emit_node_completion`). The engine's named stage vocabulary (`supervisor.plan`, `literature_review`, `generate`, `ranking`, …) survives only as milestone *chat messages* appended to `messages` by `engine_adapter.events.append_node_milestone`; no `run_events` row carries those types. The frontend's active-run view reads the node out of `payload.task` for exactly that reason (`run_detail_active.tsx::activityPhase`).

Which nodes appear, and how often, is the orchestrator's decision rather than a fixed script: `review → comprehensive_reflection → safety_screen → deep_verification → ranking → orchestrator` recurs once per cycle, `meta_review → evolve` precedes a re-review, `proximity` runs only when the pool grew since the previous pass, and `literature_review`/`reflection` are absent entirely when no MCP server is reachable (they are excluded from the graph, not skipped at runtime).

The SSE endpoint at `GET /api/runs/{id}/events?after=<seq>` always replays history starting at the requested sequence, then tails live. This is what makes "reopen after restart" work: the client never depends on in-memory event state.

## Persistence model

Tables (SQLite, WAL):

| Table | Append-only? | Notes |
| --- | --- | --- |
| `runs` | mutable status/error/timestamps | one row per run |
| `run_events` | append-only | canonical event log; `(run_id, seq)` |
| `hypotheses` | append-only | original rows never mutated; `parent_id` for lineage |
| `hypothesis_state` | mutable | Elo, win/loss, scores, status, cluster_id — separated to preserve append-only invariant on `hypotheses` |
| `evidence` | append-only | retrieved sources |
| `citations` | append-only | per-hypothesis claim → evidence with classification state |
| `reviews` | append-only | reflection, review, meta_review |
| `matches` | append-only | full pairwise tournament audit log |
| `safety_decisions` | append-only | intake + final |
| `reports` | append-only | structured JSON + path to `reports/<run>.md` |
| `messages` | append-only | steering, milestone, and Q&A chat messages |
| `scientific_tasks` | mutable (leases/status) | the durable queue itself — every graph node, fan-out item, and tournament match is a leased, idempotent row here; this is the only path a run executes through |
| `checkpoints` | append-only, pruned | `WorkflowState` snapshot after each committed task, the resume point |
| `supervisor_plan` / `supervisor_allocations` | replaced wholesale at finalize, plus synced on every checkpoint | the Supervisor's plan and terminal rationale, and an append-only-per-run ledger of every task the orchestrator scheduled with the observed stats behind each decision; readable via `GET /api/runs/{id}/supervisor-plan` |

`hypothesis_state` is the critical decoupling: it holds the values that *must* change as the run progresses (Elo, win counts) without violating the rule that an original hypothesis row is the historical record of what was generated.

## Provider selection

`engine_adapter.select_provider()` always returns `"engine"` — the app's earlier mock workflow has been retired, and the engine is now a hard runtime dependency (a missing `co_scientist` install raises at startup instead of silently falling back).

What varies per run is the **LLM backend**, not the provider. `engine_adapter.offline_mode()` returns `True` when:

1. `COSCIENTIST_FORCE_OFFLINE=1` is set (or its deprecated alias `COSCIENTIST_FORCE_MOCK=1`), OR
2. no supported provider key is configured.

An offline-backed run still executes the real engine graph; `co_scientist.offline_llm.install_offline_router()` intercepts `litellm.acompletion` for `offline/`-prefixed models and returns deterministic, schema-valid content instead of calling a real provider. The resolved backend (`"offline"` | `"real"`) is persisted per run as `llm_backend` and reported at `/status`; the deprecated `mock_mode` mirror of that value has since been removed from the API surface. A re-opened run remembers which backend produced it.

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
4. Two run-scoped endpoints are built on the backend and have **no frontend
   caller**: `POST /api/runs/{id}/messages/ask` (streaming Q&A — client function
   `askRunQuestion` exists, nothing calls it; audit row D4) and
   `POST /api/runs/{id}/messages` (scientist steering — `sendRunSteering`, likewise
   uncalled). The chat workspace does not poll messages.

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

-   Original engine LangGraph workflow is preserved — every run drives the
    engine through the durable task queue (`engine_tasks`), one leased task
    per graph node, fan-out item, and tournament match; only the LLM backend
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
    behaviour without any external dependency**. The same LangGraph graph
    runs either way; only `litellm.acompletion` for `offline/` models is
    intercepted. This unlocks CI, deterministic tests, and a usable demo
    without provider keys.
