# Implementation report

## Summary

The repository now ships as a single integrated AI Co-Scientist clone:

- Root scaffolding (`Makefile`, `.env.example`, `scripts/`, `TASKS.md`, root `README.md`).
- FastAPI backend extended with `/api/runs/*` endpoints, SQLite persistence (runs, append-only event log, hypotheses with lineage, evidence, citations, matches, reviews, safety decisions, reports), an engine adapter that auto-selects between the local LangGraph engine and a deterministic mock workflow, and SSE event streaming that replays history + tails live.
- A complete frontend workbench (React 19 + Vite 7 + Tailwind v4 + react-router-dom) with Dashboard, NewRun, RunDetail (Overview / Ideas / Evidence / Tournament / Report tabs), IdeaModal, MockBanner, status pills. Reopens cleanly after refresh and backend restart.
- Backend pytest suite: 27 tests covering health, run lifecycle, persistence, reopen-after-restart, Standard-vs-Advanced depth, Elo (initial 1200, K factor, formula, upset amplification), append-only evolution lineage, citation classification (all four states), safety (block / allow at intake + final).
- Visual validation captured under `docs/screenshots/`.

The system runs end-to-end without any API keys in deterministic Mock Mode and labels itself as such in the backend `/status` response and as a banner in the UI. Setting any LLM provider key flips the adapter to the real LangGraph engine.

## Run commands

| Command | Result |
| --- | --- |
| `make setup` | Creates `.venv` (python3.12), installs engine editable, app editable, frontend npm. |
| `make dev-api` | `uvicorn app.main:app --reload --port 8008` |
| `make dev-ui` | `npm run dev` on port 5173 (proxies `/api` to 8008) |
| `make test` | `pytest -q tests/` in the app project against an isolated SQLite path |
| `make build` | `tsc && vite build` for the frontend |
| `make reset-db` | Drops `coscientist.db` |

## Pass / fail

| Item | Result | Notes |
| --- | --- | --- |
| `make setup` clean from a fresh `.venv` | PASS | Python 3.12.12 used; engine + viewer + fastapi + uvicorn + pytest installed editable. |
| Backend `/health` | PASS | `{"status":"healthy",...}` |
| Backend `/status` reports `mock_mode: true` when no key set | PASS | Verified via curl and via the UI banner. |
| `POST /api/runs` → `POST /api/runs/{id}/start` → run completes | PASS | Standard run completes in <2s, 15 events, 7 hypotheses (5 initial + 2 evolved), 12 matches. |
| Advanced profile produces more depth than Standard | PASS | Advanced produced 14 hypotheses (8 initial + 6 evolved), 36 matches across 3 ranking rounds, 8 evidence sources. |
| Reopen run after restart | PASS | Reload simulated by importlib.reload of the app module; all data still served. |
| Frontend type-check (`tsc --noEmit`) | PASS | Clean; legacy unreachable files excluded via `tsconfig.json`. |
| Frontend build (`bun/npm run build`) | PASS | `dist/index.html` 0.47 kB, `index.js` 301.68 kB (gzip 93.32 kB). |
| Pytest: backend lifecycle + Elo + evolution + citation + safety | PASS | 27 passed in 6.76s. |
| Visual validation (Dashboard / Overview / Ideas / Evidence / Tournament / Report / NewRun / Advanced overview / Advanced tournament) | PASS | Nine PNG screenshots under `docs/screenshots/`. |
| Export report Markdown | PASS | `GET /api/runs/{id}/report.md` returns rendered markdown with `Content-Disposition: attachment`. |
| Cancel a running workflow | PASS-API | Endpoint live; UI button only renders for `queued`/`running` runs. |

## Blockers

None at submit time. Two known limitations carried as documented gaps in `docs/FIDELITY.md`:

1. **Live literature retrieval** in the FastAPI adapter is delegated to the upstream engine — when in Mock Mode it serves deterministic stubs. Wiring PubMed/Europe PMC directly into the runs adapter independent of the engine would expand the value of the Knowledge Base panel.
2. **Real engine bridge** in `engine_adapter.run_workflow` translates engine node events 1:1 into the `engine.*` event namespace but does not yet persist the full final hypothesis / match snapshot from the engine — that path would benefit from a more thorough drain of LangGraph state into the SQLite store. This does not affect Mock Mode, which is the documented default.

## Changed / new files

```
.env.example                                                   (new — mock-mode defaults)
Makefile                                                       (new — root commands)
README.md                                                      (rewritten — workspace entrypoint)
TASKS.md                                                       (new — work board)
IMPLEMENTATION_REPORT.md                                       (this file)
docs/ARCHITECTURE.md                                           (new)
docs/FIDELITY.md                                               (new)
docs/screenshots/01..09-*.png                                  (visual validation)
scripts/setup.sh, scripts/dev_all.sh                           (new)
.gitignore                                                     (added .venv/, coscientist.db, reports/, caches)

Code/ai-coscientist-app/app/main.py                            (lazy litellm/engine import; adapter status in /status; mounted runs router; CORS via ALLOWED_ORIGINS)
Code/ai-coscientist-app/app/store.py                           (new — SQLite store + schema)
Code/ai-coscientist-app/app/elo.py                             (new — pure-Python Elo)
Code/ai-coscientist-app/app/safety.py                          (new — intake + final gates)
Code/ai-coscientist-app/app/citations.py                       (new — classifier)
Code/ai-coscientist-app/app/mock_workflow.py                   (new — deterministic 11-step pipeline)
Code/ai-coscientist-app/app/engine_adapter.py                  (new — provider selection + bridge)
Code/ai-coscientist-app/app/runs.py                            (new — router + SSE)
Code/ai-coscientist-app/tests/conftest.py                      (new)
Code/ai-coscientist-app/tests/test_health.py                   (new)
Code/ai-coscientist-app/tests/test_runs.py                     (new)
Code/ai-coscientist-app/tests/test_elo.py                      (new)
Code/ai-coscientist-app/tests/test_evolution.py                (new)
Code/ai-coscientist-app/tests/test_citations.py                (new)
Code/ai-coscientist-app/tests/test_safety.py                   (new)

Code/ai-coscientist-app/frontend/package.json                  (added react-router-dom 7)
Code/ai-coscientist-app/frontend/tsconfig.json                 (narrowed include to workbench tree)
Code/ai-coscientist-app/frontend/src/main.tsx                  (mounts BrowserRouter + WorkbenchApp)
Code/ai-coscientist-app/frontend/src/components/ErrorBoundary.tsx (type-only ReactNode import)
Code/ai-coscientist-app/frontend/src/api/runs.ts               (new — typed client)
Code/ai-coscientist-app/frontend/src/hooks/useRunStream.ts     (new — EventSource hook)
Code/ai-coscientist-app/frontend/src/workbench/*               (new — full workbench tree: WorkbenchApp, Layout, ThemeContext, pages/Dashboard, pages/NewRun, pages/RunDetail, components/MockBanner, components/RunStatusPill, components/IdeaModal, components/tabs/*)
```

## Reproducing the validation

```bash
# 1. Clean setup
cd "/Users/guy/Documents/Code/Google DeepMind AI Co-Scientist"
make clean
make setup

# 2. Tests
make test
# expected: 27 passed

# 3. Boot
make dev          # prints URLs
make dev-api &    # terminal 1
make dev-ui &     # terminal 2

# 4. Browser
open http://localhost:5173/

# 5. End-to-end
# Click "New run" → pick a research goal → choose Standard (or Advanced) → Start run.
# Watch Overview tab stream the pipeline. After completion, browse Ideas/Evidence/Tournament/Report.
# Reload the page (Cmd-R) — run state is fully rehydrated from the API.

# 6. Restart test
# Ctrl-C the API. Re-run `make dev-api`. Refresh the browser tab — the run still loads.

# 7. Report export
curl -O http://localhost:8008/api/runs/<id>/report.md
```

## Decision log highlights

- **Python 3.12** chosen as the venv interpreter because the engine pins (langgraph 1.0.x, litellm 1.80.x, langchain-core 1.2.x) do not resolve against the system's Python 3.14. The Makefile auto-falls-back to 3.13 / 3 if 3.12 isn't installed.
- **Mock workflow** lives in `app/mock_workflow.py` rather than under the engine, because the goal is for the *backend* to remain runnable without the engine importable. The engine adapter is the bridge.
- **Append-only via `hypothesis_state` split** rather than soft-delete columns on `hypotheses` directly, so an evolved child is genuinely a new row with its own id while Elo / scores can still mutate.
- **SSE replay-from-zero** (`?after=0` by default) so reload after refresh hydrates the timeline without client-side caching. The workbench depends on the event log being canonical.
- **Frontend tsconfig narrowed** to the new workbench tree to keep the build clean. Legacy single-page files remain on disk untouched and unreached; they were preserved per the goal's "don't replace" constraint.
- **Safety regex set** deliberately narrow: hard-blocks weaponization intent and engineered-pathogen language but does not block CRISPR, pathogen biology, or cancer research as a class. The strict-mode dual-use redact path is opt-in via `SAFETY_MODE=strict`.
