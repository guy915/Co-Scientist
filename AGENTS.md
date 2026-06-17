# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## Repository Layout

This is a research/reference workspace organized around replicating Google DeepMind's AI Co-Scientist.

- `app/` — FastAPI + React workbench viewer
- `engine/` — LangGraph-based multi-agent hypothesis-generation engine
- `references/` — folder containing research, product screenshots, and design specs
  - `google-co-scientist/` — long-form architecture/spec markdown analyzing the original system
    - `media/` — UX captures and product references for Google Co-Scientist
    - `research/` — papers describing the original Co-Scientist
  - `notebooklm/`, `gemini/`, `gemini-enterprise/` — UX captures and product references
  - `antigravity-science-skills/`, `claude-code/`, `idea-generator/` — additional reference projects
- `docs/` — live project docs (`architecture.md`, `fidelity.md`, `screenshots/`, SVG diagrams); `docs/archive/` holds historical planning docs (`plan.md`, `tasks.md`, `implementation_report.md`); `docs/superpowers/` holds design specs and plans
- `.remember/` — session handoff notes (`remember.md` is the live handoff file; also `now.md`, `recent.md`, daily logs, `logs/`, `tmp/`)
- `Makefile` — root-level build orchestration (`setup`, `dev`, `dev-api`, `dev-ui`, `dev-mcp`, `test`, `lint`, `typecheck`, `build`, `clean`, `reset-db`)
- `CLAUDE.md` — byte-for-byte copy of this file (keep in sync)
- `README.md` — project overview, features, installation, and usage

There is a root `Makefile` for cross-project orchestration. Each project is also independently installable and runnable.

## engine (Python library)

LangGraph-based multi-agent hypothesis-generation framework. Package name: `co-scientist-engine`. Source under `src/co_scientist/`.

**Commands** (run from `engine/`):
```bash
pip install -e '.[dev]'          # install with dev deps
python examples/run.py            # interactive CLI demo
pytest                            # unit tests (testpaths = ["tests"])
yapf -ir src dev examples         # format (Google style, 80 cols)
pylint --rcfile=../pylintrc src/co_scientist   # lint
mypy .                            # typecheck
```

Individual nodes can be exercised in isolation via the scripts in `dev/` (`run_supervisor_standalone.py`, `run_generate_standalone.py`, `run_lit_review_standalone.py`, etc.) — useful for iterating on a single agent without spinning up the full graph. These scripts load a `.env` from `dev/` itself, not from the engine root — copy your API keys there before running.

**Architecture**

`HypothesisGenerator` (`src/co_scientist/generator.py`) is the public entry point. It compiles a LangGraph `StateGraph` whose nodes live in `src/co_scientist/nodes/`:

| Node | File |
|---|---|
| Supervisor (planning) | `nodes/supervisor.py` |
| Literature Review (MCP-gated) | `nodes/literature_review.py`, `nodes/literature_review_helpers.py` |
| Generate | `nodes/generate.py`, `nodes/generation/` (incl. `coordinator.py`, `debate.py`, `citations.py`, `papers.py`, `literature_tools/`) |
| Reflection | `nodes/reflection.py`, `nodes/reflection_helpers.py` |
| Review | `nodes/review.py` |
| Ranking | `nodes/ranking.py` |
| Tournament (Elo pairwise, inside ranking flow) | `nodes/ranking.py` |
| Meta-Review | `nodes/meta_review.py` |
| Evolve | `nodes/evolve.py` |
| Proximity (dedup) | `nodes/proximity.py` |

Shared state flows through `WorkflowState` in `state.py`; note the custom `deduplicate_hypotheses` reducer that auto-dedupes on every state update. Prompts are markdown files in `src/co_scientist/prompts/` (also bundled via `package-data`). YAML tool/domain configs live in `src/co_scientist/config/` with examples per domain (biomed/cyber/etc.).

Key supporting modules: `models.py` (dataclasses: `Hypothesis`, `HypothesisReview`, `ExecutionMetrics`, `Article`), `schemas.py` (JSON schemas for structured LLM output), `constants.py` (Elo params, token limits, temperatures), `exceptions.py` (domain exception hierarchy), `console.py` (Rich-based terminal reporter), `tools/` (tool registry subpackage for YAML-based tool configuration).

LLM calls go through LiteLLM (`llm.py`); literature-review tools are pulled from an external MCP server via `mcp_client.py` using `langchain-mcp-adapters`. The graph auto-detects MCP availability — without a server, the literature/reflection nodes fall back to LLM-only mode.

Caching (`cache.py`) is on by default and controlled by `COSCIENTIST_CACHE_ENABLED` / `COSCIENTIST_CACHE_DIR` env vars.

Engine-specific docs live in `engine/docs/` (architecture, configuration, development, domain customization, generation modes, literature review tools, logging, MCP integration).

**Reference MCP server** lives in `mcp_server/` as a separately installable package. Install with `pip install -e mcp_server/` and run with `uvicorn mcp_server.server:app --host 0.0.0.0 --port 8888`. **Requires Python 3.12** (engine itself is 3.10+) — install into a 3.12 venv or you'll hit cryptic solver errors. Uses FastMCP + Biopython for PubMed + INDRA CoGex.

**Style conventions** (from `CONTRIBUTING.md`, enforced informally):
- Code follows the Google Python Style Guide: yapf (`based_on_style = google`, 80 columns), pylint with the repo-root `pylintrc`, Google-format docstrings (`Args:`/`Returns:`/`Raises:`).
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
make format / lint / typecheck   # yapf / pylint / mypy
```

Tasks are mirrored under `[tool.pixi.tasks]` — `pixi run dev` etc. work identically.

**Source modules** (`app/app/`):

| Module | Purpose |
|---|---|
| `main.py` | App setup, lifespan, legacy `/generate` endpoints |
| `config.py` | Pydantic settings (model names, API keys, DB path, Elo tuning, safety mode) |
| `runs.py` | Durable run-lifecycle router (`/api/runs` endpoint group) |
| `store.py` | SQLite persistence layer (WAL mode, append-only event log) |
| `engine_adapter.py` | Engine/mock provider selection with lazy imports and mock fallback |
| `mock_workflow.py` | Deterministic mock workflow (full 14-stage agent-equivalent sequence) |
| `elo.py` | Elo rating utilities |
| `citations.py` | Citation classification (verified, partial, unsupported, unavailable) |
| `safety.py` | Safety decision storage + intake/final-output screening |
| `seed.py` | Startup demo run seeder |

**Key endpoints**:

Legacy (in `main.py`):
- `GET /health`, `/config`, `/status` — diagnostics; `/status` reports MCP/PubMed availability.
- `POST /generate` — synchronous, blocking generation (uses server-default config).
- `POST /generate/start` → returns `task_id`; `GET /generate/stream/{task_id}` — SSE stream of node events.
- `POST /cancel_hypothesis_generation` — sets the cancellation event for a `task_id`.

Run lifecycle (in `runs.py`, mounted at `/api/runs`) — **primary API used by the frontend**:
- `POST /api/runs` — create a draft run; `GET /api/runs` — list runs.
- `GET /api/runs/{id}` — get run details; `POST /api/runs/{id}/start` — start workflow.
- `POST /api/runs/{id}/cancel` — cancel; `GET /api/runs/{id}/events` — SSE stream (live + replay).
- `GET /api/runs/{id}/hypotheses` — hypotheses with Elo + lineage.
- `GET /api/runs/{id}/evidence`, `/reviews`, `/matches`, `/citations`, `/safety` — run data.
- `GET /api/runs/{id}/report` (JSON) and `/report.md` (Markdown) — structured reports.
- `POST /api/runs/{id}/messages` — queue user steering message; `GET` to list.
- `POST /api/runs/{id}/messages/ask` — Q&A with streaming LLM response (uses `chat_model_name` config).

A single `HypothesisGenerator` instance is constructed in the `lifespan` startup hook and reused across requests. Per-run overrides (`max_iterations`, `initial_hypotheses_count`, `evolution_max_count`) come from the request body. The `engine_adapter.py` module selects between the real engine and `mock_workflow.py` based on configuration and availability.

### Frontend (`frontend/`)

React 19 + Vite 7 + TypeScript + Tailwind v4 + shadcn/ui + Radix. Package manager is **Bun**. Linter/formatter is **gts** (Google TypeScript Style: ESLint + Prettier).

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

Frontend tests are colocated `*.test.ts`/`*.test.tsx` files run by Vitest (config in `vite.config.ts`, setup in `src/test-setup.ts`); they are typechecked by `tsc` and linted by gts like any other source.

Vite reads `VITE_API_BASE_URL` (defaults to `http://localhost:8008`). The live UI is the **workbench**: `src/main.tsx` mounts `BrowserRouter` + `src/workbench/workbench_app.tsx`, with pages under `src/workbench/pages/` (dashboard, new run, run detail) and run views under `src/workbench/components/` (incl. `tabs/`). HTTP + SSE/streaming entry points live in `src/api/runs.ts` and `src/hooks/use_run_stream.ts`. Theme state is in `src/workbench/theme_context.tsx` — no Redux/Zustand. Shared primitives: `src/components/ui/` (shadcn), `src/components/error_boundary.tsx`, `src/lib/utils.ts`.

**Routing** (`workbench_app.tsx`): `/` (public landing page), `/demos/:slug` (public demo), `/runs` (dashboard), `/runs/new`, `/runs/:id`, `/runs/:id/:tab`, `*` (404). Public-facing pages live in `src/public/` (`landing_page.tsx`, `demo_page.tsx`, `not_found_page.tsx`, `seo.tsx`).

**Tabs** (`src/workbench/components/tabs/`): `overview_tab.tsx`, `ideas_tab.tsx`, `evidence_tab.tsx`, `tournament_tab.tsx`, `report_tab.tsx`, `chat_tab.tsx` (scientist-in-the-loop Q&A with auto-steering, manual steering, and Q&A modes).

**MD3 wrappers** (`src/md3/`): `md_dialog.tsx`, `md_tabs.tsx` — thin wrappers around `@material/web` components.

### Docker workflow

`app/docker-compose.yml` runs three services: `api` (FastAPI), `ui` (Vite), `mcp` (reference MCP server). The api container expects a sibling engine checkout mounted at `/workspace/co-scientist-engine`; if absent, the entrypoint clones from `COSCIENTIST_ENGINE_REPO` at ref `COSCIENTIST_ENGINE_REF`. Override `COSCIENTIST_ENGINE_PATH` in `.env` if the engine checkout is elsewhere. The container hardcodes `TOOLS_CONFIG` to `indra_cancer.yaml` — change it there, not in `.env`, when iterating on tools.

## Production hosting

The app is deployed as three services:

| Layer | Platform | URL |
|---|---|---|
| Frontend (Vite/React) | Vercel — project `co-scientist-ui` | https://co-scientist-ui.vercel.app |
| API (FastAPI) | Railway — service `api` | https://api-production-97eb.up.railway.app |
| MCP server | Railway — service `mcp` | internal only (`mcp.railway.internal:8888`) |

**Railway project**: `co-scientist` (id `74f2b037-0094-49d2-b645-4849991234af`), environment `production`.

Both Railway services build from `guy915/Co-Scientist` using repo-root Dockerfiles (`Dockerfile.api`, `Dockerfile.mcp`). The api service has a persistent volume mounted at `/app/data` (SQLite DB + cache live there).

Key env vars on the Railway **api** service:

```
MODEL_NAME=deepseek/deepseek-chat
DEEPSEEK_API_KEY=<secret>
MCP_SERVER_URL=http://mcp.railway.internal:8888/mcp
COSCIENTIST_DB_PATH=/app/data/coscientist.db
COSCIENTIST_CACHE_DIR=/app/data/cache
```

Vercel reads `VITE_API_BASE_URL=https://api-production-97eb.up.railway.app` (set in production environment).

## Working in this repo

- The `engine/` and `app/` directories are vendored as plain directories (not submodules). `co-scientist-engine` is not published to PyPI; it's installed editable from the local checkout (`pip install -e ../engine`, which `make setup` and the Dockerfiles do).
- Both the app (`app/`) and the engine (`engine/`) have committed pytest suites under `tests/`. `mypy .` is strict-clean for each (the engine excludes the separate `mcp_server` package and the `dev/` scripts; run `mypy .` from `mcp_server/` for that package).
- When invoked from this workspace, `.remember/remember.md` is the session-handoff file — read/update it per the `remember` skill instructions.

## Required environment

Both projects use **LiteLLM** for model dispatch. Set the relevant provider key (`DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, …) and `MODEL_NAME` (e.g. `deepseek/deepseek-chat`) before running. The app defaults to `gemini/gemini-2.5-flash` locally; production uses DeepSeek. The viewer also reads `MCP_SERVER_URL` (default `http://localhost:8888/mcp`), `TOOLS_CONFIG` (path or http URL to a YAML tools config), `SUPERVISOR_MODEL_NAME` (separate strategic model for supervisor/meta-review), and `CHAT_MODEL_NAME` (model for Chat tab Q&A). Full list of viewer env vars in `app/.env.example`.

## Git hygiene

Never mention yourself or any other AI tool in commits, pull requests, or pushes. This applies to all AI agents working in this repo.

- No `Co-Authored-By: <AI name>` trailers in commit messages.
- No "Generated with [tool]" or "Created by [AI]" lines in commit messages or PR bodies.
- No references to AI tools (Claude, Devin, ChatGPT, Copilot, etc.) anywhere in git history.

Commit messages should read as if written directly by the human developer.
