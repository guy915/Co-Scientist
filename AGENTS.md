# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## Repository Layout

This is a research/reference workspace organized around replicating Google's AI Co-Scientist.

- `app/` — FastAPI + React workbench viewer
- `engine/` — LangGraph-based multi-agent hypothesis-generation engine
- `evaluations/` — eval harness (parity gate, citation/safety/scaling evals); wired to `make parity` / `make eval-smoke` and CI
- `e2e/` — Playwright end-to-end suite (bun-managed); wired to `make e2e` and CI
- `corpus/` — SBI paper corpus (extracted text + catalog; see `corpus/README.md`); baked into the prod images and pointed at via `SBI_CORPUS_DIR`
- `references/` — folder containing research, product screenshots, and design specs
  - `core/google-co-scientist/` — long-form architecture/spec markdown analyzing the original system (incl. `media/` UX captures and `research/` papers)
  - `peripheral/` — secondary reference projects (`antigravity-science-skills/`, `coding-agent-harness/`, `ai-chatbot-interface/`, `deep-research-agent/`)
  - `ui-ux/` — UX captures and product references (`gemini/`, `gemini-enterprise/`, `idea-generator/`, `notebooklm/`, `legacy-workbench-ui/`)
- `docs/` — project docs; `docs/README.md` indexes them (live: `ARCHITECTURE.md`, `CI.md`, `EXPLAINER.md`, `FIDELITY.md`, `PARITY.md`, `PARITY-VERIFICATION.md`, `RUNNING-LOCALLY.md`, `UI-FIDELITY.md`, `assets/`; historical dated records: `audits/`, `decisions/`, `plans/`, `specs/`, `reports/`)
- `.github/` — CI workflows plus the `setup-backend` composite action
- `.remember/` — session handoff notes (`remember.md` is the live handoff file; also `now.md`, `recent.md`, daily logs, `logs/`, `tmp/`)
- `Makefile` — root-level build orchestration (`setup`, `start`, `dev-api`, `dev-ui`, `dev-mcp`, `test`, `test-app`, `test-engine`, `test-all`, `e2e`, `parity`, `eval-smoke`, `lint`, `typecheck`, `build`, `clean`, `stop`, `reset-db`)
- `CLAUDE.md` — symlink to this file
- `README.md` — project overview, features, installation, and usage

There is a root `Makefile` for cross-project orchestration. Each project is also independently installable and runnable.

## engine (Python library)

LangGraph-based multi-agent hypothesis-generation framework. Package name: `co-scientist-engine`. Source under `src/co_scientist/`.

**Commands** (run from `engine/`):
```bash
pip install -e '.[dev]'          # install with dev deps
python examples/run.py            # interactive CLI demo
pytest                            # unit tests (testpaths = ["tests"])
ruff format .                     # format (80 cols)
ruff check .                      # lint
mypy .                            # typecheck
```

Individual nodes can be exercised in isolation via the scripts in `dev/` (`run_supervisor_standalone.py`, `run_generate_standalone.py`, `run_lit_review_standalone.py`, etc.) — useful for iterating on a single agent without spinning up the full graph. These scripts load a `.env` from `dev/` itself, not from the engine root — copy your API keys there before running.

**Architecture**

`HypothesisGenerator` (`src/co_scientist/generator/`) is the public entry point. It compiles a LangGraph `StateGraph` whose nodes are implemented in the six agent packages under `src/co_scientist/agents/` (Generation, Reflection, Ranking, Evolution, Proximity, Meta-review, plus Supervisor and a cross-cutting Safety screen). `src/co_scientist/nodes/` retains thin re-export shims at the old import paths, and the graph still registers each node under its original key string (so durable-run resume is unaffected). `co_scientist.agents.NODE_TO_AGENT` is the source-of-truth node→agent mapping:

| Node | File |
|---|---|
| Supervisor (planning) | `agents/supervisor/supervisor.py` |
| Orchestrator (per-cycle routing) | `agents/supervisor/orchestrator.py` |
| Literature Review (MCP-gated) | `agents/generation/literature_review/` (node, helpers, search/retrieval/article support) |
| Generate | `agents/generation/generate.py` (+ `coordinator.py`, `debate.py`, `citations.py`, `literature_tools/`) |
| Reflection | `agents/reflection/reflection.py`, `reflection_helpers.py` |
| Review | `agents/reflection/review.py` |
| Comprehensive Reflection | `agents/reflection/comprehensive_reflection.py` |
| Deep Verification (probing questions) | `agents/reflection/deep_verification.py` |
| Ranking + Tournament (Elo pairwise) | `agents/ranking/` (`ranking.py`, `ranking_elo.py`, `ranking_matchmaking.py`, ...) |
| Meta-Review | `agents/meta_review/meta_review.py` |
| Research Overview (synthesis/roadmap) | `agents/meta_review/research_overview.py` |
| Evolve | `agents/evolution/evolve.py` |
| Proximity (dedup) | `agents/proximity/proximity.py` |
| Safety screen (cross-cutting) | `agents/safety/safety_screen.py` |

Shared state flows through `WorkflowState` in `state.py`; note the custom `deduplicate_hypotheses` reducer that auto-dedupes on every state update. Prompts are markdown files in `src/co_scientist/prompts/templates/` (also bundled via `package-data`), loaded by the `prompts/` package. YAML tool/domain configs live in `src/co_scientist/config/` with examples per domain (biomed/cyber/etc.).

Key supporting modules: `models.py` (dataclasses: `Hypothesis`, `HypothesisReview`, `ExecutionMetrics`, `Article`), `schemas/` (JSON-schema package for structured LLM output — one module per prompt family plus `registry.py`), `constants.py` (Elo params, token limits, temperatures), `exceptions.py` (domain exception hierarchy), `progress.py` (shared progress-event emission used by all agent nodes; `nodes/progress.py` is a shim like the rest of `nodes/`), `tools/` (tool registry subpackage for YAML-based tool configuration).

LLM calls go through LiteLLM (`llm.py`); literature-review tools are pulled from an external MCP server via `mcp_client.py` using `langchain-mcp-adapters`. The graph auto-detects MCP availability — without a server, the literature/reflection nodes fall back to LLM-only mode.

Caching (`cache.py`) is on by default and controlled by `COSCIENTIST_CACHE_ENABLED` / `COSCIENTIST_CACHE_DIR` env vars.

Engine-specific docs live in `engine/docs/` (`ARCHITECTURE.md`, `CONFIGURATION.md`, `DEVELOPMENT.md`, `DOMAIN_CUSTOMIZATION.md`, `GENERATION_MODES.md`, `LITERATURE_REVIEW_TOOLS_CONFIGURATION.md`, `LOGGING.md`, `MCP_INTEGRATION.md`).

**Reference MCP server** lives in `mcp_server/` as a separately installable package. Install with `pip install -e mcp_server/` and run with `uvicorn mcp_server.server:app --host 0.0.0.0 --port 8888`. **Requires Python 3.12** (engine itself is 3.10+) — install into a 3.12 venv or you'll hit cryptic solver errors. Registered tool families (see `mcp_server/server.py`): PubMed search + full-text retrieval, OpenAlex search, ChEMBL/UniProt lookups, SBI paper-corpus search, INDRA CoGex queries, and web search/fetch.

**Style conventions** (from `CONTRIBUTING.md`, enforced informally):
- Code follows the Google Python Style Guide: ruff (formatter + linter, 80 columns, config in `pyproject.toml`), Google-format docstrings (`Args:`/`Returns:`/`Raises:`).
- Docstrings capitalized, full sentences.
- `logger.debug()` lowercase; `info`/`warning`/`error` capitalized.
- No emojis or unicode decoration in code or logs.
- Rich library only in `examples/` and `dev/`, never in core library code.

## app (FastAPI + React viewer)

Web UI and HTTP/SSE API that wraps the `co-scientist-engine` for live hypothesis-generation runs.

### Backend (`app/`)

FastAPI app with settings in `app/config.py` (pydantic-settings, loads `.env`). Package name: `co-scientist-viewer`.

**Commands** (run from `app/`):
```bash
make install         # pip install -e ".[dev]"   (also: pixi install)
make dev             # uvicorn app.main:app --reload --port 8008
make test            # pytest (asyncio_mode = "auto", testpaths = ["tests"])
make format / lint / typecheck   # ruff format / ruff check / mypy
```

Tasks are mirrored under `[tool.pixi.tasks]` — `pixi run dev` etc. work identically.

**Source modules** (`app/app/`):

| Module | Purpose |
|---|---|
| `main.py` | App setup, lifespan, diagnostics endpoints (`/health`, `/config`, `/status`) |
| `config.py` | Pydantic settings (model names, API keys, DB path, Elo tuning, safety mode) |
| `runs.py` | Durable run-lifecycle router (`/api/runs` endpoint group); backed by `runs_events.py` (SSE), `runs_models.py` (request models), `runs_registry.py` (active-run map) |
| `engine_tasks.py` | Durable run execution — **the production path**: claims queued runs, drives the engine, persists events (audit both this and the streaming `run_workflow` path when changing run behavior) |
| `task_worker.py` | Background worker loop that leases and executes `engine_tasks` work |
| `store/` | SQLite persistence layer (WAL mode, append-only event log) |
| `engine_adapter/` | Provider selection (always `"engine"`) and the offline/real LLM-backend switch; runs the intake safety gate at the shared `run_workflow` boundary and streams events |
| `report_render.py` | Shared report payload/markdown builders, the `finalize_report` path (final safety gate + report/completed emission), and event-payload stubs shared across the offline and real LLM backends |
| `elo.py` | Elo rating utilities |
| `citations.py` | Citation classification (verified, partial, unsupported, unavailable) |
| `claims.py`, `claim_grounding.py`, `claim_verifier.py` | Citation-grounding pipeline: claim extraction, assessor construction, NLI verification |
| `safety.py` | Intake/final-output screening; the intake gate runs at the shared `run_workflow` boundary and the final gate in the shared `report_render.finalize_report` path, so both are shared across providers |
| `hypothesis_safety.py`, `hypothesis_screening.py` | Per-hypothesis safety policy (adapter over `co_scientist.safety`) and its store-aware wiring |
| `qa.py` | Q&A answering over run data (chat workspace ask flow) |
| `human_input.py` | Scientist-in-the-loop steering/adjudication handling |
| `document_ingest.py`, `paper_corpus.py` | Uploaded-document extraction and SBI corpus access (offline corpus tooling lives in `app/dev/`) |
| `run_modes.py` | Run tier/focus normalization + durable setup/config resolution |
| `seed.py` | Startup demo run seeder |
| `logging_setup.py` | Stdout logging + run-id correlation + persistent capture (root logger -> `app_logs` table via a queue/listener thread) |
| `logs_api.py` | `GET /api/logs` and the filter/payload logic shared with `GET /api/runs/{id}/logs` |

**Key endpoints**:

Diagnostics (in `main.py`):
- `GET /health`, `/config`, `/status` — diagnostics; `/status` reports MCP/PubMed availability.

Run lifecycle (in `runs.py`, mounted at `/api/runs`) — **primary API used by the frontend**:
- `POST /api/runs` — create a draft run; `GET /api/runs` — list runs.
- `GET /api/runs/{id}` — get run details; `POST /api/runs/{id}/start` — start workflow.
- `POST /api/runs/{id}/pause`, `/resume`, `/cancel` — lifecycle control; `GET /api/runs/{id}/events` — SSE stream (live + replay).
- `GET /api/runs/{id}/hypotheses` — hypotheses with Elo + lineage.
- `GET /api/runs/{id}/evidence`, `/reviews`, `/matches`, `/citations`, `/safety` — run data.
- `GET /api/runs/{id}/report` (JSON) and `/report.md` (Markdown) — structured reports.
- `POST /api/runs/{id}/messages` — queue user steering message; `GET` to list.
- `POST /api/runs/{id}/messages/ask` — Q&A with streaming LLM response (uses `chat_model_name` config).

Additional routers mounted in `main.py`: `interviews`, `shares`, `feedback`, `auth`, and `logs` (see each module for its endpoint group).

**Persisted logs** (`logs_api.py` + `logging_setup.py` + `store/logs.py`) — one app-wide, durable log in the SQLite `app_logs` table:

- **Run stages**: every `run_events` row is mirrored into the log as a compact `app.run_stage` record (`store/events.py`), so a run's stage narrative — `lifecycle`, `safety.intake`, `supervisor.plan`, `literature_review`, `generate`, `reflection`, `proximity`, `ranking`, `evolve`, `meta_review`, `deep_verification`, `citation_audit`, `research_overview`, `report`, `status` — is readable from the Logs panel and `cosci logs --run <id>` rather than only over SSE. Payloads are summarized to `key=value` scalars (collections become their size, long strings are clipped, the line is capped at 200 chars): ~21 stage records per run instead of the full event bodies. Mirroring happens in the inner `_append_event`, so every event writer — including transactional ones — is covered, and it is best-effort — it can never fail an event write.
- **What is captured**: every record reaching the Python root logger (app modules, `co_scientist` engine, store/database, MCP client, dependencies), *plus* uvicorn's non-propagating `uvicorn`/`uvicorn.access` loggers (HTTP requests and server errors), *plus* frontend records POSTed by the UI (namespaced `ui.*`: session diagnostic events, route navigation, uncaught JS errors, unhandled rejections, React render errors, and user interactions — clicks on interactive elements and form submissions as `ui.interaction` — via `lib/ui_logging.ts`). Access records for `/api/logs` itself are filtered out so polling the log cannot grow it.
- **How**: a `QueueHandler` (run-id stamped) feeds a background `QueueListener` that writes rows and prunes to a cap; writes never block or raise into the caller. Settings: `log_capture_enabled` / `log_capture_level` / `log_capture_max_rows`. DEBUG records are only captured when the root logger also emits them (set `DEBUG=true` plus `log_capture_level=DEBUG`).
- **Repeat suppression**: capture persists the first of a record and drops verbatim repeats for `REPEAT_SUPPRESS_SECONDS` (10 min), keyed by exact `(logger, level, run id, message)` — so a different message from the same logger, or the same line from another run, still lands. This exists because the level filters exempt WARNING+, so any steady-state condition wrote a row per poll forever: the MCP availability probe warned twice per `/status` refresh, and inside a single run the tool registry logged two identical "initialized" lines per agent call (229 copies of each in one run). Those repeats were ~77% of the readable stream and, since the Logs panel shows a fixed newest-100 window, they crowded out the run narrative entirely and the log read as empty. Suppression is by *repetition*, not by logger name — do not fix a new flood by adding its logger to a deny-list.
- **Endpoints**: `GET /api/logs` (filters `after_id`/`limit`/`min_level`/`run_id`/`q`/`verbose`, plus a `last_id` polling cursor and a `total` matching-row count that ignores the window), `GET /api/runs/{id}/logs` (run-scoped view), `POST /api/logs` (client ingestion; batch ≤50, messages truncated to 2000 chars), `DELETE /api/logs` (clear all; ids restart at 1, and followers detect the reset by `last_id` dropping below their cursor — `cosci logs --follow` handles this automatically).
- **Default view vs. full capture**: everything is captured, but the default read path (UI popover, `cosci logs`, `GET /api/logs`) hides high-volume noise below WARNING — `uvicorn.access` requests, `ui.interaction` clicks, `ui.navigation`, dependency loggers (`httpx`/`httpcore`/`urllib3`/`litellm`), and `co_scientist.mcp_client` availability probes; the `NOISE_LOGGERS` list lives in `logs_api.py`. WARNING+ records always show regardless of source. Opt into the full stream with `verbose=1` or `cosci logs --all` — coding agents should stay on the default view and reach for `--all` only when debugging request-level or interaction-level behavior, since the verbose stream grows by thousands of records per session.
- **Access control**: the log carries other tenants' research goals and server internals, so reads and clears are scoped. Operators -- loopback callers (the local CLI/agents) or holders of `LOGS_ADMIN_TOKEN` via the `X-Logs-Token` header (`cosci logs --logs-token`, env `COSCIENTIST_LOGS_TOKEN`) -- get the app-wide view and a full clear. Every other caller sees only records it submitted plus records for runs it owns, and `DELETE` removes only those (leaving the shared id sequence alone). Un-owned server records are operator-only. Ingestion stays open because browsers must report their own errors, but records are stamped with the caller's client id, control characters are collapsed (a newline would otherwise forge lines in the CLI's tab-delimited output), and it is rate-limited per client (`LOGS_INGEST_PER_MINUTE`, 429 over the ceiling). Because scoping keys off caller identity, `src/api/logs.ts` must send `clientHeaders()` on every read *and* write: an unidentified caller matches nothing, so omitting them leaves the panel permanently empty wherever the browser does not reach the API over loopback (i.e. any real deployment) and stores submitted records ownerless.
- **Consumers**: `cosci logs` (`--run`/`--level`/`--grep`/`--follow`/`--clear`/`--all`) and the workbench Logs popover, which renders this single stream identically on every route (the newest 100 records, messages as plain text with the level in each entry's meta row; rows are renumbered consecutively by position in the filtered stream (store ids are global, so hidden noise would otherwise leave visible gaps like `#12, #13, #30`); the badge and Total chip carry that stream size, which is also the newest row's number, and Copy still emits real store ids alongside the display number so it stays cross-referenceable with `cosci logs`), jumps to the newest record on open but never while the user is scrolled up reading, copies the newest 50 as structured JSON, and whose Clear deletes server-side. The badge refreshes on a background poll plus a `cosci-app-logs-changed` window event fired by the api layer after every successful client POST/clear, so it stays current without opening the panel.

A single `HypothesisGenerator` instance is constructed in the `lifespan` startup hook and reused across requests. Per-run overrides (`max_iterations`, `initial_hypotheses_count`, `evolution_max_count`) come from the request body. Every run executes on the real engine (`engine_adapter.select_provider()` always returns `"engine"`; the engine is a hard runtime dependency). Keyless runs and runs with `COSCIENTIST_FORCE_OFFLINE=1` set are pinned instead to the engine's deterministic offline LLM backend (`co_scientist.offline_llm`), which intercepts `litellm.acompletion` for `offline/`-prefixed models rather than calling a real provider.

### CLI (`cosci`)

`app/app/cli/` ships an operator CLI — console script `cosci`, also runnable as `python -m app.cli` — that drives the running API over HTTP. It is the intended way for terminal-based agents to exercise the app without the UI.

Core loop:

```bash
cosci runs create "goal" --tier express --start   # create (+ start in one step)
cosci runs wait <id>                              # poll until settled; exit code = outcome
cosci runs report <id> --md                       # final report as Markdown
```

- **Commands**: `status`, `config`, `logs` (persisted backend logs: `--run`, `--level`, `--grep`, `--follow`); `runs list|demo|show|create|start|pause|resume|cancel|watch|wait|steer|ask` plus reads `hypotheses|evidence|reviews|citations|safety|matches|proximity|metrics|claim-evidence`.
- **Exit codes**: `runs wait` encodes the outcome — 0 completed, 3 failed, 4 blocked, 5 cancelled, 6 paused, 124 `--max-wait` exceeded; every command uses 130 for Ctrl-C and 141 for a broken pipe.
- **Global flags** (per subcommand): `--api-url` (env `COSCIENTIST_API_URL`), `--client-id` (env `COSCIENTIST_CLIENT_ID` — run listings are scoped by this header, so use a consistent id), `--timeout` (env `COSCIENTIST_TIMEOUT`), `--json` (raw API payloads), `--verbose` (request log on stderr).
- Text arguments (`create` goal, `steer` message, `ask` question) accept `-` to read from stdin.
- GETs retry transient failures (connect errors, 502/503/504); POSTs never retry. `runs watch` auto-reconnects a dropped SSE stream from the last seen `seq`.

Tests live in `tests/test_cli_*.py`; `test_cli_commands.py` spins up a real mock-mode uvicorn server, so the whole suite runs offline.

### Frontend (`frontend/`)

React 19 + Vite 7 + TypeScript + Tailwind v4. Package manager is **Bun**. Linter/formatter is **gts** (Google TypeScript Style: ESLint + Prettier).

**Design system:** `frontend/DESIGN.md` is the authoritative design reference for all UI work. It follows the [google-labs-code/design.md](https://github.com/google-labs-code/design.md) spec: YAML design tokens in frontmatter, markdown rationale in body. Read it before making visual changes — it documents the color system, typography scale, spacing grid, radius rules, component inventory, and Do's & Don'ts. Key points:
- Palette is Material Design 3, generated at runtime from seed `#1A6B6B` via `applyMd3Theme()` in `src/lib/theme.ts`. Never hardcode `--md-sys-color-*` values.
- All UI tokens are bridged via `--color-th-*` variables in `src/index.css`.
- Three border-radius values only: `rounded-md` (8px) for data blocks, `rounded-xl` (12px) for interactive containers, `rounded-full` (9999px) for pills/buttons/chips.
- No `box-shadow` on cards or inputs — tonal layers only.

**Commands** (run from `app/frontend/`):
```bash
bun install
bun run dev          # vite dev server on :5173
bun run build        # tsc && vite build
bun run lint         # gts lint
bun run fix          # gts fix (format + autofix)
bun run test         # vitest run (jsdom + React Testing Library)
```

Frontend tests are colocated `*.test.ts`/`*.test.tsx` files run by Vitest (config in `vite.config.ts`, setup in `src/test_setup.ts`); they are typechecked by `tsc` and linted by gts like any other source.

Vite reads `VITE_API_BASE_URL` (defaults to `http://localhost:8008`). The live UI is the **workbench**: `src/main.tsx` mounts `BrowserRouter` + `src/workbench/workbench_app.tsx`, with pages under `src/workbench/pages/` (chat workspace, run detail, proposals, researcher access, shared report) and run views under `src/workbench/components/` (incl. `tabs/`); `src/workbench/proposals/` backs the proposals graph page. HTTP + SSE/streaming entry points live in `src/api/runs.ts` and `src/hooks/use_run_stream.ts` (`src/hooks/` holds shared app-level hooks; workbench-specific hooks live in `src/workbench/hooks/`). Theme state is in `src/workbench/theme_context.tsx` — no Redux/Zustand. Shared primitives: `src/components/error_boundary.tsx`, `src/components/icon.tsx`, and helpers under `src/lib/` (theme, text, clipboard, sanitize_html, ...). Styling: `src/index.css` (Tailwind layers, fonts, `--color-th-*` token bridge) plus the surface sheets under `src/styles/`, aggregated by `src/styles/surfaces.css`.

**Routing** (`workbench_app.tsx`): `/` (chat workspace — session home), `/runs/:id`, `/runs/:id/:tab` (run detail), `/access` (researcher access), `/proposals` (proposals graph; `/recommendations` redirects to it), `/shared/:token` (shared goal report), `*` (404). `/runs` and `/runs/new` redirect to `/`. The old public surface (`/about` landing page, `/demos/:slug` public demos, `/runs` dashboard) was deliberately removed. `src/public/` now holds only the residual helpers still in use (plus their colocated tests): `not_found_page.tsx`, `no_index.tsx`, `public_link_button.tsx`, `seo.tsx`.

**Tabs** (`src/workbench/components/tabs/`): `ideas_tab.tsx` is the only live tab component; `run_detail.tsx` renders its other views (details, learning, research overview) inline. The earlier `overview_tab.tsx`, `evidence_tab.tsx`, `tournament_tab.tsx`, `run_specifications_tab.tsx`, and `chat_tab.tsx` were retired and preserved under `references/ui-ux/legacy-workbench-ui/retired-orphan-tabs/`.

**Workbench hooks** (`src/workbench/hooks/`): ~15 modules — the chat-session cluster (`use_chat_session.ts` + `chat_session_*` state/handlers/helpers), run history (`use_run_history.ts`, `run_history_context.tsx`), and utilities (`use_global_shortcuts.ts`, `use_toast.ts`, `use_system_status.ts`, `use_is_mobile.ts`, `use_overflowing.ts`, `use_debounced_callback.ts`).

### Docker workflow

`app/docker-compose.yml` runs three services: `api` (FastAPI), `ui` (Vite), `mcp` (reference MCP server). The api container expects a sibling engine checkout mounted at `/workspace/co-scientist-engine`; if absent, the entrypoint clones from `COSCIENTIST_ENGINE_REPO` at ref `COSCIENTIST_ENGINE_REF`. Override `COSCIENTIST_ENGINE_PATH` in `.env` if the engine checkout is elsewhere. The container hardcodes `TOOLS_CONFIG` to `indra_cancer.yaml` — change it there, not in `.env`, when iterating on tools.

## Production hosting

The app is deployed as three services:

| Layer | Platform | URL |
|---|---|---|
| Frontend (Vite/React) | Vercel — project `co-scientist-ui` | Public: https://ai-co-scientist.com/; Vercel deployment: https://co-scientist-ui.vercel.app |
| API (FastAPI) | Railway — service `api` | https://api-production-97eb.up.railway.app |
| MCP server | Railway — service `mcp` | internal only (`mcp.railway.internal:8888`) |

**Railway project**: `co-scientist` (id `74f2b037-0094-49d2-b645-4849991234af`), environment `production`.

Both Railway services build from `guy915/Co-Scientist` using repo-root Dockerfiles (`Dockerfile.api`, `Dockerfile.mcp`). The api service has a persistent volume mounted at `/app/data` (SQLite DB + cache live there).

Key env vars on the Railway **api** service (production switched to DashScope on 2026-07-19; check the Railway dashboard for the exact current model ids):

```
MODEL_NAME=<DashScope model>
DASHSCOPE_API_KEY=<secret>
MCP_SERVER_URL=http://mcp.railway.internal:8888/mcp
COSCIENTIST_DB_PATH=/app/data/coscientist.db
COSCIENTIST_CACHE_DIR=/app/data/cache
```

Vercel reads `VITE_API_BASE_URL=https://api-production-97eb.up.railway.app` (set in production environment).

## Working in this repo

- The `engine/` and `app/` directories are vendored as plain directories (not submodules). `co-scientist-engine` is not published to PyPI; it's installed editable from the local checkout (`pip install -e ../engine`, which `make setup` and the Dockerfiles do). Where the app is installed with `--no-deps` (make setup, CI, the compose dev image), its runtime deps come from the single-source list `app/requirements-app.txt` — keep it in sync with `app/pyproject.toml`.
- Both the app (`app/`) and the engine (`engine/`) have committed pytest suites under `tests/`. `mypy .` is strict-clean for each (the engine excludes the separate `mcp_server` package and the `dev/` scripts; run `mypy .` from `mcp_server/` for that package).
- When invoked from this workspace, `.remember/remember.md` is the session-handoff file — read/update it per the `remember` skill instructions.

## Required environment

Both projects use **LiteLLM** for model dispatch. Set the relevant provider key (`DEEPSEEK_API_KEY`, `DASHSCOPE_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, …) and `MODEL_NAME` before running. The app's local defaults are `deepseek/deepseek-v4-flash` (worker) and `deepseek/deepseek-v4-pro` (supervisor/chat) — see `app/app/config.py`; production runs on DashScope. The viewer also reads `MCP_SERVER_URL` (default `http://localhost:8888/mcp`), `TOOLS_CONFIG` (path or http URL to a YAML tools config), `SUPERVISOR_MODEL_NAME` (separate strategic model for supervisor/meta-review), and `CHAT_MODEL_NAME` (model for chat-workspace Q&A). Full list of viewer env vars in `app/.env.example`. With no provider key set, or with `COSCIENTIST_FORCE_OFFLINE=1` (deprecated alias `COSCIENTIST_FORCE_MOCK=1`), the viewer runs every hypothesis-generation call through the engine's deterministic offline LLM backend instead of a real provider — no key required.

## Git hygiene

Never mention yourself or any other AI tool in commits, pull requests, or pushes. This applies to all AI agents working in this repo.

- No `Co-Authored-By: <AI name>` trailers in commit messages.
- No "Generated with [tool]" or "Created by [AI]" lines in commit messages or PR bodies.
- No references to AI tools (Claude, Devin, ChatGPT, Copilot, etc.) anywhere in git history.

Commit messages should read as if written directly by the human developer.

Commit messages must follow the format `<type>(<scope>): <subject>`. Common types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`. Example:

```
feat(runs): add markdown_text column to reports table
fix(report-tab): handle missing markdown gracefully
docs(engine): rename docs to UPPER_SNAKE_CASE
```

Branch names must follow the format `<type>/<description>` using the same type vocabulary. Example:

```
feat/report-markdown-persistence
fix/report-tab-empty-state
docs/restructure-engine-docs
```

Pull requests should follow Google's public CL-description conventions, adapted
for a concise personal-project workflow:

- PR titles are short, standalone, imperative summaries of the change. Do not
  use Conventional Commit prefixes in PR titles. Prefer `Remove unused
  generate endpoints` over `refactor: remove unused generate endpoints`.
- PR bodies should briefly explain what changed, why it changed, and how it was
  tested. Add implementation context or tradeoffs only when they help future
  review or maintenance.
