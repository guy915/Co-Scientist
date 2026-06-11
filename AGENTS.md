# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Layout

This is a research/reference workspace organized around replicating Google DeepMind's AI Co-Scientist.

- `app/` — FastAPI + React workbench viewer
- `engine/` — LangGraph-based multi-agent hypothesis-generation engine
- `references/` — folder containing research, product screenshots, and design specs
  - `context/` — long-form architecture/spec markdown for the planned system
  - `research/` — papers describing the original Co-Scientist
  - `notebooklm/`, `media/`, `gemini/` — UX captures and product references
- `docs/` — live project docs (`ARCHITECTURE.md`, `FIDELITY.md`, `screenshots/`); `docs/archive/` holds historical planning docs (`PLAN.md`, `TASKS.md`, `IMPLEMENTATION_REPORT.md`)
- `.remember/` — session handoff notes (`.remember/remember.md` is the live handoff file)

There is no top-level build system. Each project is independently installable and runnable.

## engine (Python library)

LangGraph-based multi-agent hypothesis-generation framework. Package name: `open-coscientist`. Source under `src/open_coscientist/`.

**Commands** (run from `engine/`):
```bash
pip install -e '.[dev]'          # install with dev deps
python examples/run.py            # interactive CLI demo
pytest                            # tests (testpaths = ["tests"], none committed yet)
black . && ruff check --fix .     # format
ruff check .                      # lint
mypy .                            # typecheck
```

Individual nodes can be exercised in isolation via the scripts in `dev/` (`run_supervisor_standalone.py`, `run_generate_standalone.py`, `run_lit_review_standalone.py`, etc.) — useful for iterating on a single agent without spinning up the full graph. These scripts load a `.env` from `dev/` itself, not from the engine root — copy your API keys there before running.

**Architecture**

`HypothesisGenerator` (`src/open_coscientist/generator.py`) is the public entry point. It compiles a LangGraph `StateGraph` whose nodes live in `src/open_coscientist/nodes/`:

| Node | File |
|---|---|
| Supervisor (planning) | `nodes/supervisor.py` |
| Literature Review (MCP-gated) | `nodes/literature_review.py` |
| Generate | `nodes/generate.py`, `nodes/generation/` |
| Reflection | `nodes/reflection.py` |
| Review | `nodes/review.py` |
| Ranking | `nodes/ranking.py` |
| Tournament (Elo pairwise, inside ranking flow) | `nodes/ranking.py` |
| Meta-Review | `nodes/meta_review.py` |
| Evolve | `nodes/evolve.py` |
| Proximity (dedup) | `nodes/proximity.py` |

Shared state flows through `WorkflowState` in `state.py`; note the custom `deduplicate_hypotheses` reducer that auto-dedupes on every state update. Prompts are markdown files in `src/open_coscientist/prompts/` (also bundled via `package-data`). YAML tool/domain configs live in `src/open_coscientist/config/` with examples per domain (biomed/cyber/etc.).

LLM calls go through LiteLLM (`llm.py`); literature-review tools are pulled from an external MCP server via `mcp_client.py` using `langchain-mcp-adapters`. The graph auto-detects MCP availability — without a server, the literature/reflection nodes fall back to LLM-only mode.

Caching (`cache.py`) is on by default and controlled by `COSCIENTIST_CACHE_ENABLED` / `COSCIENTIST_CACHE_DIR` env vars.

**Reference MCP server** lives in `mcp_server/` as a separately installable package. Install with `pip install -e mcp_server/` and run with `uvicorn mcp_server.server:app --host 0.0.0.0 --port 8888`. **Requires Python 3.12** (engine itself is 3.10+) — install into a 3.12 venv or you'll hit cryptic solver errors. Uses FastMCP + Biopython for PubMed + INDRA CoGex.

**Style conventions** (from `CONTRIBUTING.md`, enforced informally):
- Docstrings capitalized, full sentences.
- `logger.debug()` lowercase; `info`/`warning`/`error` capitalized.
- No emojis or unicode decoration in code or logs.
- Rich library only in `examples/` and `dev/`, never in core library code.

## app (FastAPI + React viewer)

Web UI and HTTP/SSE API that wraps `open-coscientist` for live hypothesis-generation runs.

### Backend (`app/`)

Single-file FastAPI app (`app/main.py`, ~800 lines) with settings in `app/config.py` (pydantic-settings, loads `.env`).

**Commands** (run from `app/`):
```bash
make install         # pip install -e ".[dev]"   (also: pixi install)
make dev             # uvicorn app.main:app --reload --port 8008
make test            # pytest (asyncio_mode = "auto", testpaths = ["tests"])
make format / lint / typecheck   # black+ruff / ruff / mypy
```

Tasks are mirrored under `[tool.pixi.tasks]` — `pixi run dev` etc. work identically.

**Key endpoints** (`app/main.py`):
- `GET /health`, `/config`, `/status` — diagnostics; `/status` reports MCP/PubMed availability.
- `POST /generate` — synchronous, blocking generation (uses server-default config).
- `POST /generate/start` → returns `task_id`; `GET /generate/stream/{task_id}` — SSE stream of node events. The UI uses this pair; in-flight runs are tracked in the module-global `_active_tasks` dict guarded by `_active_tasks_lock`.
- `POST /cancel_hypothesis_generation` — sets the cancellation event for a `task_id`.

A single `HypothesisGenerator` instance is constructed in the `lifespan` startup hook and reused across requests. Per-run overrides (`max_iterations`, `initial_hypotheses_count`, `evolution_max_count`) come from the request body on the streaming endpoint — server-side `.env` values are only defaults and only apply to the non-streaming `/generate`.

### Frontend (`frontend/`)

React 19 + Vite 7 + TypeScript + Tailwind v4 + shadcn/ui + Radix. Package manager is **Bun**. Linter/formatter is **Biome**, not ESLint/Prettier.

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
bun run check        # biome check --write . (lint + format + organize imports)
bun run lint         # biome lint .
```

Vite reads `VITE_API_BASE_URL` (defaults to `http://localhost:8008`). The live UI is the **workbench**: `src/main.tsx` mounts `BrowserRouter` + `src/workbench/WorkbenchApp.tsx`, with pages under `src/workbench/pages/` (Dashboard, NewRun, RunDetail) and run views under `src/workbench/components/` (incl. `tabs/`). HTTP + SSE/streaming entry points live in `src/api/runs.ts` and `src/hooks/useRunStream.ts`. Theme state is in `src/workbench/ThemeContext.tsx` — no Redux/Zustand. Shared primitives: `src/components/ui/` (shadcn), `src/components/ErrorBoundary.tsx`, `src/lib/utils.ts`.

### Docker workflow

`docker-compose.yml` runs three services: `api` (FastAPI), `ui` (Vite), `mcp` (reference MCP server). The api container expects a sibling `../open-coscientist` checkout mounted at `/workspace/open-coscientist`; if absent, the entrypoint clones from `OPEN_COSCIENTIST_REPO` at ref `OPEN_COSCIENTIST_REF`. Override `OPEN_COSCIENTIST_PATH` in `.env` if the engine checkout is elsewhere. The container hardcodes `TOOLS_CONFIG` to `indra_cancer.yaml` — change it there, not in `.env`, when iterating on tools.

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

- The `open-coscientist` (engine) and `open-coscientist-viewer` (app) are upstream open-source projects from Jataware. This repo vendors them as plain directories (not submodules) — when editing, treat the boundary carefully and don't assume changes propagate to PyPI/Docker images. The viewer's pip install pulls `open-coscientist>=0.2.0` from PyPI by default; for local dev against engine changes, run `pip install -e ../engine` after `make install`.
- The app (`app/`) has a committed pytest suite under `tests/`; the engine (`engine/`) has none yet, so its `pytest` exits clean.
- When invoked from this workspace, `.remember/remember.md` is the session-handoff file — read/update it per the `remember` skill instructions.

## Required environment

Both projects use **LiteLLM** for model dispatch. Set the relevant provider key (`DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, …) and `MODEL_NAME` (e.g. `deepseek/deepseek-chat`) before running. Production uses DeepSeek. The viewer also reads `MCP_SERVER_URL` (default `http://localhost:8888/mcp`) and `TOOLS_CONFIG` (path or http URL to a YAML tools config). Full list of viewer env vars in `app/.env.example`.

## Git hygiene

Never mention yourself or any other AI tool in commits, pull requests, or pushes. This applies to all AI agents working in this repo.

- No `Co-Authored-By: <AI name>` trailers in commit messages.
- No "Generated with [tool]" or "Created by [AI]" lines in commit messages or PR bodies.
- No references to AI tools (Claude, Devin, ChatGPT, Copilot, etc.) anywhere in git history.

Commit messages should read as if written directly by the human developer.
