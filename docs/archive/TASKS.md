# TASKS — AI Co-Scientist Clone Implementation

Live work board for the end-to-end build. Mark items `[x]` when complete; keep new tasks at the bottom of their phase.

Goal: a runnable, end-to-end Google DeepMind AI Co-Scientist clone integrating the local engine (`Code/ai-coscientist-engine`) and FastAPI+React app (`Code/ai-coscientist-app`) into a single workspace, with deterministic mock/degraded mode when API keys are absent.

## Phase 0 — Audit (done)

- [x] Read README.md, PLAN.md, CLAUDE.md
- [x] Read engine `generator.py`, `state.py`, `models.py`, ranking node Elo
- [x] Read app `main.py`, `config.py`, `pyproject.toml`, `Makefile`
- [x] Read frontend `App.tsx`, `api/client.ts`, `package.json`
- [x] Inventory `.env.example` files, `docker-compose.yml`, engine docs

## Phase 1 — Root setup

- [x] Author this TASKS.md
- [x] Root `Makefile`: `setup`, `dev`, `dev-api`, `dev-ui`, `test`, `lint`, `typecheck`, `build`, `clean`. `dev` prints URLs.
- [x] Root `.env.example` with deterministic mock-mode defaults
- [x] Root `README.md` rewrite anchored on quickstart + workbench flow
- [x] Root `scripts/` shims: `setup.sh`, `dev_all.sh`
- [x] Root `.gitignore` updates (`.venv/`, `*.db`, etc.)

## Phase 2 — Backend integration + persistence

- [x] Switch viewer to local editable engine in `make setup` (engine installed first → satisfies viewer dep)
- [x] New `app/store.py`: SQLite (stdlib) — `runs`, `run_events`, `hypotheses`, `evidence`, `matches`, `reviews`, `reports`, `safety_decisions`. Append-only event log.
- [x] New `app/safety.py`: intake + final-output keyword + dual-use heuristics. Allow / redact / block. Persist `safety_decisions`.
- [x] New `app/citations.py`: classify each citation as `verified | partial | unsupported | unavailable`.
- [x] New `app/elo.py`: pure-Python Elo calc (initial 1200, configurable K, standard formula). Used by mock + tests; mirrors engine's `calculate_elo_update`.
- [x] New `app/mock_workflow.py`: deterministic offline workflow emitting all 11 agent-equivalent steps with stable seed.
- [x] New `app/engine_adapter.py`: wraps real engine OR mock; lazy-imports `open_coscientist`; chooses provider based on key availability.
- [x] New `app/runs.py` (router): `POST/GET /api/runs`, `GET /api/runs/{id}`, `POST /api/runs/{id}/start`, `GET /api/runs/{id}/events` (SSE), `GET /api/runs/{id}/hypotheses|evidence|matches|reviews|safety|report|report.md`.
- [x] Mount router from `app/main.py`. Preserve existing `/generate*` endpoints.

## Phase 3 — Frontend workbench

- [x] Add `react-router-dom` (Bun)
- [x] New routes: `/` Dashboard, `/runs/new`, `/runs/:id` with tabs Overview / Ideas / Evidence / Tournament / Report
- [x] New `src/api/runs.ts` client for new endpoints
- [x] New `src/hooks/useRunStream.ts` SSE for `/api/runs/{id}/events`
- [x] New components: `RunsTable`, `NewRunForm` (Standard / Advanced toggle), `RunMonitor`, `IdeasList`, `IdeaModal`, `EvidencePanel`, `TournamentBoard`, `ReportView`, `MockBanner`
- [x] Reload after refresh: hydrate from `/api/runs/{id}` on mount
- [x] Report export (Markdown + JSON)

## Phase 4 — Tests

- [x] `Code/ai-coscientist-app/tests/test_health.py` — health
- [x] `tests/test_runs.py` — create/list/get/start/SSE/persistence/reopen
- [x] `tests/test_elo.py` — initial 1200, K factor, expected score, append-only history
- [x] `tests/test_evolution.py` — evolve produces NEW hypotheses with `parent_ids`, never mutates
- [x] `tests/test_citations.py` — classify all 4 states
- [x] `tests/test_safety.py` — allow/block intake + final output
- [x] Frontend `bun run build` (tsc + vite build)

## Phase 5 — Docs

- [x] Update root `README.md` with run commands + tab tour
- [x] `docs/ARCHITECTURE.md`
- [x] `docs/FIDELITY.md` — clone-defined unknowns
- [x] `IMPLEMENTATION_REPORT.md` — final pass/fail, blockers, repro steps

## Phase 6 — Validation

- [x] `make setup` clean from a fresh `.venv`
- [x] `make dev-api` boots, `/health` 200
- [x] `make dev-ui` boots, root page renders
- [x] Create goal in UI → start Standard mock run → stream completes → results persist
- [x] Run Advanced mock run → deeper iterations + more hypotheses observable
- [x] Restart API → reopen completed run → all tabs render
- [x] Export report.md
- [x] `make test` (backend + Elo + evolution + citation + safety)
- [x] `make build` (frontend)
- [x] Visual validation via Playwright/Chrome DevTools — screenshots
