# Final Report — Co-Scientist workbench product-flow stabilization

Four evidence-backed broken/incomplete product flows in the workbench were
fixed. Every fix works fully offline (no provider key, no `COSCIENTIST_FORCE_MOCK`),
carries new tests, and passes the full verification suite. No item was left
infeasible; there are no unresolved blockers.

## Changes per fix

### Fix 1 — Offline Q&A returns a grounded answer, not an API-key error

**Problem.** `POST /api/runs/{id}/messages/ask` always called `litellm`; with no
provider key every question streamed back a persisted "requires a language
model API key" error frame.

**Change.**
- `app/app/qa.py`: added `build_offline_answer(...)` — a deterministic synthesis
  of the run's own persisted artifacts (top hypotheses by Elo, the latest
  reviewer note, and the numbered evidence manifest with `[n]` citation
  markers). It is a pure function of run state and deliberately does **not**
  interpret the question text, so it never fabricates a question-specific claim.
  Added `stream_offline_answer(...)`, which mirrors the LLM stream's SSE framing
  (`sources` → `chunk` → `done`) and persists the exchange with its manifest.
- `app/app/runs.py` (`ask_question`): branches on
  `engine_adapter.select_provider() == "mock"` — the offline path for the mock
  provider, the unchanged `qa.stream_answer` (litellm) path otherwise.

The real-LLM path (`stream_answer`, `_stream_llm_deltas`) is untouched; its
existing tests still pass and a new test asserts a configured provider still
streams through litellm.

**Files:** `app/app/qa.py`, `app/app/runs.py`,
`app/tests/test_qa.py`, `app/tests/test_qa_endpoint.py` (new).

### Fix 2 — Recents cards show a run's real top hypotheses

**Problem.** `home_recents_data.ts` fabricated three "winning idea" titles per
card by keyword-matching goal text (the code comment admitted it was decorative
placeholder content).

**Change.**
- `app/app/store/runs.py`: `list_runs` now enriches each run with
  `top_hypotheses` — the run's top hypothesis titles by Elo, capped at three,
  via one windowed query over just the listed run ids (matching
  `list_hypotheses`' `elo DESC, created_at ASC` order). `RunRow`/`to_dict`
  extended (`app/app/store/models.py`).
- `app/frontend/src/api/run_types.ts`: `Run.top_hypotheses?: string[]`.
- `app/frontend/src/workbench/pages/home_recents.tsx`: renders
  `run.top_hypotheses`; the winner list is omitted when a run produced none.
- `app/frontend/src/workbench/pages/home_recents_data.ts`: deleted the
  `HOME_RUN_IDEA_TITLE_RULES` fabrication table and `homeRunIdeaTitles`.

**Files:** `app/app/store/runs.py`, `app/app/store/models.py`,
`app/frontend/src/api/run_types.ts`, `home_recents.tsx`, `home_recents_data.ts`,
`app/tests/test_store.py`, `chat_workspace_home.test.tsx`,
`home_recents_data.test.ts`.

### Fix 3 — Home-card progress and duration from persisted run data

**Problem.** `homeRunStepIndex` advanced the progress indicator by elapsed
wall-clock; `formatHomeRunDuration` fabricated a flat 60s for completed runs.

**Change.**
- `app/app/store/runs.py`: `list_runs` also enriches each run with
  `latest_stage` — the type of its most recent pipeline-stage event (from a
  defined `_STAGE_EVENT_TYPES` set) via one windowed query. `RunRow`/`to_dict`
  extended.
- `app/frontend/src/api/run_types.ts`: `Run.latest_stage?: string | null`.
- `home_recents_data.ts`: `homeRunStepIndex` now maps `run.latest_stage` onto the
  four-step flow via `STAGE_STEP_INDEX` (kept in sync with the backend stage
  set), with a status fallback (`queued`→1, `synthesizing`→4, running-without-a-
  stage→1). Removed the elapsed-minutes heuristic. `completedDurationLabel` now
  computes the real span from `created_at`/`completed_at`(/`updated_at`),
  rendering a sub-minute span as "< 1 minute" — the fabricated 60s branch is
  gone.

**Files:** `app/app/store/runs.py`, `app/app/store/models.py`,
`run_types.ts`, `home_recents_data.ts`, `app/tests/test_store.py`,
`home_recents_data.test.ts`.

### Fix 4 — Cancel works for any non-terminal run after a restart

**Problem.** `cancel_run` returned 404 unless an in-process handle existed, so a
run that survived a server restart could not be cancelled.

**Change.** `app/app/runs.py` (`cancel_run`):
- With an active handle: unchanged cooperative cancel (sets the handle event,
  emits `lifecycle`/`cancel_requested`, returns `cancelling`).
- Without a handle: an already-terminal run returns 409; any non-terminal run
  (draft, or a restart survivor left `running`/`queued`/`synthesizing`/`paused`)
  is transitioned to `CANCELLED` in the store and a terminal `status`
  `{"status":"cancelled"}` event is emitted (mirroring `_mark_workflow_failed`)
  so open SSE streams close. Added `_TERMINAL_STATUS_VALUES`.

**Files:** `app/app/runs.py`, `app/tests/test_runs_edge.py`.

## Verification

All commands run from the worktree root with no API keys configured.

```
make test-all
  engine pytest: 961 passed
  app pytest:    242 passed
  parity:        62 requirement rows (verified=54, external=6, undisclosed=2) — OK

cd app/frontend
  bun run test:  39 files, 252 passed
  bun run lint:  clean (gts)
  bun run build: tsc + vite build OK

app strict checks: ruff check app tests — clean; mypy . — 79 files, no issues
```

### Offline proof (keyless, no `COSCIENTIST_FORCE_MOCK`)

With every provider key stripped from the environment, `select_provider()`
returns `mock` on its own, and each flow was exercised end-to-end via the ASGI
`TestClient`:

- **Fix 1:** `POST /messages/ask` on a completed run returned HTTP 200 with no
  error frame; the streamed answer listed the run's 24 real hypotheses (top by
  Elo, with a `[1]` citation), the latest reviewer note, and its 8 sources.
- **Fix 2:** `GET /api/runs` returned `top_hypotheses` = the run's real top-3
  hypothesis titles by Elo (`H5…`, `H3…`, `H7…`).
- **Fix 3:** `latest_stage` = `research_overview` for the completed run and
  `reflection` (→ step 3) for a live run; real duration ≈ 1.2s, not 60s.
- **Fix 4:** cancelling a restart-survivor run (persisted `running`, no handle)
  returned `{"status":"cancelled"}`, the run became `cancelled`, and a terminal
  `status`/`cancelled` event was emitted; cancelling a completed run returned
  409.

### Live UI confirmation

The workbench home page (worktree backend + Vite dev server, no keys) renders
the ferroptosis recents card with the run's real winning ideas
(`H8: Decoupling co-expression…`, `H4: Stabilizing a transient intermediate…`,
`H3:…`), the real `Top score: 1295`, and `Total time: < 1 minute`.

## Scope adherence

Untouched, as required: `/health` `/config` `/status`, logging, `ExecutionMetrics`,
E2E/browser tests, CI workflows, CLI/MCP, engine resume semantics, and mid-run
steering. The shared grounding-prompt builder (`qa.build_system_prompt`) and its
parity-cited test were preserved, so `docs/PARITY.md` evidence stays resolvable
and `make parity` is green.

## Unresolved blockers

None. All four fixes landed with passing new tests and green verification.
