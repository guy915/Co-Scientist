# Architecture

This document describes the current runtime shape of the Co-Scientist
workspace.

## Layers

```
+--------------------- frontend (src/workbench) ---------------------+
| BrowserRouter                                                      |
|   /                  -> LandingPage     (public overview)          |
|   /demos/:slug       -> DemoPage        (public demo run)          |
|   /runs              -> Dashboard       (lists runs)               |
|   /runs/new          -> NewRunForm      (research goal setup)      |
|   /runs/:id          -> RunDetail       (reference + support tabs) |
|   /runs/:id/:tab     -> active tab persisted in the URL            |
|                                                                    |
| RunStatusPill                                                      |
| IdeaModal                                                          |
| useRunStream  (EventSource on /api/runs/:id/events)                |
| useMessages   (steering + Q&A messages for Chat tab)               |
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
|   engine_adapter.py — provider selection + bridge to mock/engine   |
|   mock_workflow.py — deterministic offline pipeline                 |
|   store.py       — SQLite store (runs/events/hypotheses/evidence/  |
|                    citations/matches/reviews/reports/safety)       |
|   elo.py         — pure Elo helpers (initial=1200, configurable K) |
|   safety.py      — intake + final regex-based gate                 |
|   citations.py   — verified|partial|unsupported|unavailable        |
+------------------------------+-------------------------------------+
                               |
        +----------------------+--------------------+
        |                                           |
+-------v--------+                       +----------v-----------+
| mock workflow  |                       | co_scientist     |
| (default)      |                       | LangGraph engine     |
+----------------+                       | (real, optional)     |
                                         +----------+-----------+
                                                    |
                                         (optional) v
                                         +----------------------+
                                         | MCP literature server|
                                         +----------------------+
```

## Pipeline events (canonical timeline)

The mock workflow and the engine adapter both emit events into the same
event-log table. The mock workflow guarantees the full sequence:

```
1.  lifecycle      (created)
2.  lifecycle      (queued)
3.  safety.intake  (allow/redact/block)
4.  status         (running)
5.  supervisor.plan
6.  literature_review (N evidence)
7.  generate          (initial_hypotheses_count rows)
8.  reflection
9.  proximity         (cluster summary)
10. ranking           (iter 1)
11. evolve            (evolution_max_count children with parent_id)
12. meta_review       (per-iteration critique)
13. ranking           (iter 2, …)
14. citation_audit    ({verified, partial, unsupported, unavailable})
15. safety.final
16. report            (structured payload + markdown)
17. status            (completed)
```

The frontend's Progress tab renders this verbatim. The SSE endpoint at
`GET /api/runs/{id}/events?after=<seq>` always replays history starting at the
requested sequence, then tails live. This is what makes "reopen after restart"
work: the client never depends on in-memory event state.

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

`hypothesis_state` is the critical decoupling: it holds the values that *must*
change as the run progresses (Elo, win counts) without violating the rule that
an original hypothesis row is the historical record of what was generated.

## Provider selection

`engine_adapter.select_provider()` returns `"engine"` iff:

1. `COSCIENTIST_FORCE_MOCK` is unset, AND
2. at least one supported provider key is set, AND
3. `co_scientist` is importable.

Otherwise it returns `"mock"`. The chosen value is persisted on the run row so a
re-opened run remembers which engine produced it.

## Frontend state

The workbench holds no durable state in the browser. On mount it:

1. Calls `getRun(id)` for status + summary counts.
2. Calls `getHypotheses / getEvidence / getMatches / getReviews / getSafety /
   getCitations / getReport` in parallel.
3. Opens an `EventSource` on `/api/runs/{id}/events?after=0` which replays every
   event since the run started, then tails live.
4. The Chat tab polls `/api/runs/{id}/messages` while a run is active and uses
   the streaming `/messages/ask` endpoint for Q&A responses.

This means a hard refresh, a backend restart, or a new browser session all
produce the same view.

## Why this shape

-   Original engine LangGraph workflow is preserved —
    `engine_adapter.run_workflow` calls the engine when a key is available, only
    translating event names.
-   FastAPI single-file app is preserved; the new router is mounted alongside
    the existing `/generate` endpoints.
-   Frontend stack is preserved: React 19 + Vite 7 + Tailwind v4 + Bun + gts.
    The workbench lives under `src/workbench/`, with public landing and demo
    pages under `src/public/`.
-   The mock workflow exists so the system has **observable behaviour without
    any external dependency**. This unlocks CI, deterministic tests, and a
    usable demo without provider keys.
