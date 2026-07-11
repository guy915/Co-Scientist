# Diagnostics repair & expansion — final report

Branch: `feat/continuous-diagnostics`

Repairs and expands Co-Scientist's diagnostics into real, offline-capable,
app-wide diagnostics. All six items landed with new passing tests; every
verification command below is green. No unresolved blockers.

## Commits

| Commit | Scope |
|---|---|
| `bd6d713a` | `feat(engine): include total_time and phase_times in streamed metrics` |
| `d9075000` | `feat(diagnostics): real health checks, probe hardening, metrics, logging` |
| `1f18335a` | `feat(workbench): system status chip and persisted run events in logs` |

37 files changed, ~1970 insertions. The engine change is a single additive
field pair on the streamed metrics dict; everything else is app-side or
frontend.

## What changed, by item

### 1. Real `/health` (was a hardcoded `"healthy"`)

- New `app/app/diagnostics.py`: `check_store()` opens a SQLite connection and
  runs `SELECT 1` through the existing `app.store` plumbing; `check_engine()`
  reuses `engine_adapter.provider._engine_importable` (a `find_spec` lookup,
  no import side effects); `derive_health_status()` folds them into
  `healthy | degraded | unhealthy`.
- `/health` (`app/app/main.py`) now returns that derived status plus a
  per-check breakdown and the active provider, and sets HTTP 503 only when the
  store is unreachable. Store down ⇒ `unhealthy`/503; a provider key set but
  the engine unimportable ⇒ `degraded`/200; pure offline mock ⇒ `healthy`/200.
- Kept fast for the `make dev` readiness gate: the two checks are a local DB
  round-trip and an import lookup — no network. `degraded` stays 200 so the
  gate is not tripped by the normal mock configuration.

### 2. `/status` probe defects

- **(a) literature-review gating** — `literature_review_available` is now
  `mcp_available AND pubmed_available`, matching the field's own description
  (previously derived from `mcp_available` alone).
- **(b) bounded timeout + TTL cache** — each probe runs under
  `asyncio.wait_for(..., timeout=settings.status_probe_timeout_seconds)`
  (default 3s), and the probe pair is memoized for
  `settings.status_probe_cache_ttl_seconds` (default 30s) via
  `probe_literature_stack_cached()`. Repeated `/status` calls no longer open a
  fresh MCP client per request. **Placement note:** the task cited
  `engine/src/co_scientist/mcp_client.py ~399-402` as the site of the
  fresh-client/no-timeout problem, but the fix lives app-side in
  `diagnostics.py`, and `mcp_client.py` is unchanged. This is deliberate: the
  scope boundary lists CLI/MCP as do-not-touch and the engine library is meant
  to stay as-is, so the timeout and cache wrap the engine probe from the app
  rather than editing the engine. The functional goal (bounded probes, no
  hammering) is met without touching the engine.
- **(c) down vs. errored** — the bare `except Exception: pass` is gone. Each
  probe yields a `ProbeResult` whose `state` is `up`/`down` (a definitive
  answer from a completed probe) or `error` (probe timed out or raised, so
  availability is unknown), with detail. `/status` now includes a `probes`
  object exposing `{state, error}` per probe. An unimportable engine reports
  `error` on both probes, not a misleading `down`.

### 3. Single-sourced API version

- New `app/app/version.py` reads the version from installed package metadata
  (`importlib.metadata`), with a `"0.1.0"` fallback for raw checkouts. The
  FastAPI `app` version, the `/` root payload, and `/health` all use
  `API_VERSION`. A test asserts the three surfaces agree.

### 4. ExecutionMetrics persistence & exposure

- **Engine:** the streamed per-node metrics dict
  (`generator/streaming.py::_build_stream_state_dict`) now also carries
  `total_time` and `phase_times`, matching the non-streaming result shape.
- **Adapter:** `engine_stream._merge_engine_state` no longer drops the
  `metrics` key; `_persist_run_metrics` writes the final cumulative dict to the
  store at finalize, filling `total_time` from the adapter's wall clock when
  the stream didn't measure one.
- **Store:** new `run_metrics` table (one upserted row per run) and
  `save_run_metrics` / `get_run_metrics` in `app/app/store/metrics.py`. The
  table is cleared by `clear_run_derived_data`, so a resume re-derives it.
- **Mock parity:** `_persist_mock_metrics` writes a deterministic,
  engine-shaped metrics dict derived from the run's persisted artifacts (a
  documented formula for `llm_calls`/`phase_times`), so the feature works fully
  offline.
- **API:** new `GET /api/runs/{id}/metrics` returns `{"metrics": ...}` (null
  before finalize, 404 for unknown runs).

### 5. Structured, run-correlated logging

- New `app/app/logging_setup.py`: `configure_logging()` installs one idempotent
  stdout handler — human-readable text by default, one JSON object per line when
  `LOG_FORMAT=json`. A `contextvars`-backed `run_log_context(run_id)` binds a
  run id that a `RunIdFilter` stamps onto every record (including records from
  libraries called within the scope); both formatters surface it.
- `runs._run_workflow_task` wraps the workflow body in `run_log_context(run_id)`,
  so every run-scoped log line — start path and resume path — carries the run id
  and correlates with the `run_events` timeline.
- `main.py` replaces `logging.basicConfig` with `configure_logging`. The engine
  library stays handler-free per `engine/docs/LOGGING.md`; its records propagate
  to the app's root handler.

### 6. Frontend wiring

- **`/status` consumer:** `useSystemStatus` polls `/status` on a slow interval;
  `SystemStatusIndicator` (in `layout_status.tsx`) renders a header chip — "Mock
  mode" when the backend runs the deterministic workflow, "API offline" when
  `/status` is unreachable, nothing in healthy engine mode.
- **Persisted events in the popover:** `getRunEvents` calls
  `GET /api/runs/{id}/events?stream=false` (a new additive one-shot JSON
  snapshot; the SSE default and event vocabulary are unchanged). The
  `DiagnosticsControl` popover now loads the active run's persisted event log
  whenever it opens, so the timeline survives a reload alongside the ephemeral
  in-page session events. Clear drops only session entries; Copy exports both.

## Verification

All commands run from the worktree root against the final committed state.

### `make test-all`
```
engine: 961 passed
app:    267 passed, 1 warning
```

### Frontend (`cd app/frontend`)
```
bun run test   → 41 files, 267 passed
bun run lint   → gts lint clean
bun run build  → tsc + vite build ok (dist/assets/index-*.js 445 kB)
```

### Types & parity
```
make typecheck        → app mypy + evaluations mypy clean
mypy .  (app)         → no issues in 86 source files (incl. tests)
mypy .  (engine)      → no issues in 197 source files
make parity           → 62 rows (verified=54, external=6, undisclosed=2); OK
```

New tests added: 37 backend (`test_diagnostics.py` 20, `test_logging_setup.py`
9, `test_store_metrics.py` 4, `test_metrics_endpoint.py` 3, `test_health.py`
rewrite 12 total across health+status; plus additions to
`test_engine_adapter_events.py`, `test_runs_events.py`, `test_main_diagnostics.py`)
and the engine `test_generator_streaming.py` update; frontend
`layout_status.test.tsx` (7), `system.test.ts` (2), and additions to
`layout.test.tsx` and `runs.test.ts`.

### Offline proof (no API keys, mock provider)

Backend started with `LOG_FORMAT=json` and no provider key against a fresh DB.

`GET /health`:
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "model_name": "deepseek/deepseek-chat",
  "provider": "mock",
  "checks": {
    "store": {"ok": true, "detail": null},
    "engine": {"ok": true, "detail": null}
  }
}
```

`GET /status`:
```json
{
  "mcp_available": false,
  "pubmed_available": false,
  "literature_review_available": false,
  "probes": {
    "mcp": {"state": "down", "error": null},
    "pubmed": {"state": "down", "error": null}
  },
  "mcp_server_url": "",
  "provider": "mock",
  "mock_mode": true,
  "has_provider_key": false,
  "engine_importable": true,
  "model_name": "deepseek/deepseek-chat",
  "supervisor_model_name": "deepseek/deepseek-chat"
}
```

One mock run created, started, and driven to `completed`.
`GET /api/runs/{id}/metrics`:
```json
{
  "metrics": {
    "total_time": 8.7,
    "hypothesis_count": 24,
    "reviews_count": 13,
    "tournaments_count": 36,
    "evolutions_count": 16,
    "llm_calls": 75,
    "phase_times": {
      "supervisor": 0.1, "literature_review": 0.4, "generate": 1.6,
      "reflection": 1.3, "ranking": 1.8, "evolve": 3.2, "meta_review": 0.3
    }
  }
}
```

`GET /api/runs/{id}/events?stream=false` returned all 24 persisted events
(`lifecycle` … `status: completed`).

Run-id-tagged JSON log lines (`LOG_FORMAT=json`), spanning multiple modules for
one run:
```json
{"time":"...","level":"INFO","logger":"app.engine_adapter.workflow","message":"starting workflow run=82a3fd84-... provider=mock run_mode=default","run_id":"82a3fd84-..."}
{"time":"...","level":"INFO","logger":"app.safety","message":"Safety gate allow run 82a3fd84-... at intake stage.","run_id":"82a3fd84-..."}
{"time":"...","level":"INFO","logger":"app.report_render","message":"Report finalized for run 82a3fd84-... (report_id=...).","run_id":"82a3fd84-..."}
```

Frontend against the offline backend: the header showed the **Mock mode** chip
(and **API offline** when the backend was stopped), and opening the Logs
popover on a run route loaded that run's 24 persisted events (Total 24,
Success 2, Info 22, Runs 1), each tagged `Run 82a3fd84`, with no console errors.

## Scope boundaries observed

Untouched, per the brief: run lifecycle behavior beyond metrics exposure; the
Q&A/ask flow, home recents, cancel semantics; E2E tests; CI workflows;
CLI/MCP; the engine library beyond the additive streamed-metrics field. The SSE
contract and event vocabulary are preserved — the events endpoint gained an
opt-in `stream=false` snapshot; its default behavior is unchanged. `make parity`
stays green.

## Unresolved blockers

None. All six items are implemented, tested, and verified.
