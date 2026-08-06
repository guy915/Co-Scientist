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
|                                                                    |
| useChatSession (chat timeline, steering + Q&A)                     |
| useRunStream  (EventSource on /api/runs/:id/events)                |
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
|   engine_adapter/ — provider selection + offline/real LLM backend  |
|                     switch; bridges to the engine                  |
|   store/         — SQLite store (runs/events/hypotheses/evidence/  |
|                    citations/matches/reviews/reports/safety)       |
|   elo.py         — pure Elo helpers (initial=1200, configurable K) |
|   safety.py      — intake + final regex-based gate                 |
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

Every run executes on the engine, and the engine adapter emits its events into the same event-log table regardless of which LLM backend (offline or real) is behind it. A standard run produces this canonical sequence:

```
1.  lifecycle      (created)
2.  lifecycle      (queued)
3.  safety.intake  (allow/redact/block)
4.  status         (running)
5.  supervisor.plan
6.  literature_review (N evidence)
7.  generate          (initial_hypotheses_count rows)
8.  reflection
9.  proximity         (cluster summary, when the pool grew since the previous proximity pass)
10. ranking           (iter 1)
11. evolve            (evolution_max_count children with parent_id)
12. meta_review       (per-iteration critique)
13. ranking           (iter 2, …)
14. deep_verification (probing questions on the top-k by Elo)
15. citation_audit    ({verified, partial, unsupported, unavailable})
16. research_overview (roadmap + NIH Specific Aims)
17. safety.final
18. report            (structured payload + markdown)
19. status            (completed)
```

The frontend's active-run view (`run_detail_active.tsx`) renders this as a live timeline while a run is in flight. The SSE endpoint at `GET /api/runs/{id}/events?after=<seq>` always replays history starting at the requested sequence, then tails live. This is what makes "reopen after restart" work: the client never depends on in-memory event state.

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

`hypothesis_state` is the critical decoupling: it holds the values that *must* change as the run progresses (Elo, win counts) without violating the rule that an original hypothesis row is the historical record of what was generated.

## Provider selection

`engine_adapter.select_provider()` always returns `"engine"` — the app's earlier mock workflow has been retired, and the engine is now a hard runtime dependency (a missing `co_scientist` install raises at startup instead of silently falling back).

What varies per run is the **LLM backend**, not the provider. `engine_adapter.offline_mode()` returns `True` when:

1. `COSCIENTIST_FORCE_OFFLINE=1` is set (or its deprecated alias `COSCIENTIST_FORCE_MOCK=1`), OR
2. no supported provider key is configured.

An offline-backed run still executes the real engine graph; `co_scientist.offline_llm.install_offline_router()` intercepts `litellm.acompletion` for `offline/`-prefixed models and returns deterministic, schema-valid content instead of calling a real provider. The resolved backend (`"offline"` | `"real"`) is persisted per run as `llm_backend` and reported at `/status`; `mock_mode` remains as a deprecated mirror of the same value. A re-opened run remembers which backend produced it.

## Frontend state

The workbench caches no *run or hypothesis* data in the browser — nothing
like a Redux store of fetched entities. On mount it:

1. Calls `getRun(id)` for status + summary counts.
2. Calls `getHypotheses / getEvidence / getMatches / getReviews / getClaimEvidence / getSafety / getReport` in parallel.
3. Opens an `EventSource` on `/api/runs/{id}/events?after=0` which replays every event since the run started, then tails live.
4. The chat workspace polls `/api/runs/{id}/messages` while a run is active and uses the streaming `/messages/ask` endpoint for Q&A responses.

This means a hard refresh, a backend restart, or a new browser session all
produce the same *content* — every run/hypothesis/report view is always
re-fetched from the API, never read back from a client cache.

It does persist a handful of small, non-content keys, all via
`localStorage`/`sessionStorage` (not a state-management library): the
client id and (when a researcher session is active) its bearer token
(`lib/client_id.ts` — `co_scientist_client_id`, `co_scientist_access_token`),
the self-declared audience (`workbench/audience_context.tsx` —
`cosci-audience`), the light/dark theme (`workbench/theme_context.tsx` —
`cosci-theme`), a scientist's own BYOK provider key when set
(`lib/api_key.ts` — `cosci-api-key`, `cosci-api-provider`), and the Logs
popover's per-session baseline row id (`workbench/layout_diagnostics_state.ts`
— `cosci-logs-session-baseline`). These are identity, preference, and UI
bookkeeping, not a cache of server content, which is why point 1-4 above
still holds: nothing here lets a view render without hitting the API.

## Why this shape

-   Original engine LangGraph workflow is preserved — every run drives the
    engine through the durable task queue (`engine_tasks`), translating event
    names; only the LLM backend underneath (offline or real) varies with
    configuration.
-   FastAPI single-file app is preserved; the new router is mounted alongside
    the diagnostics endpoints (`/health`, `/config`, `/status`).
-   Frontend stack is preserved: React 19 + Vite 7 + Tailwind v4 + Bun + gts.
    The workbench lives under `src/workbench/`; the earlier public landing
    page and demo routes were removed, and `src/public/` now holds only
    residual helpers (404 page, no-index).
-   The engine's offline LLM backend exists so the system has **observable
    behaviour without any external dependency**. The same LangGraph graph
    runs either way; only `litellm.acompletion` for `offline/` models is
    intercepted. This unlocks CI, deterministic tests, and a usable demo
    without provider keys.
