# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Layout

This is a research/reference workspace organized around replicating Google DeepMind's AI Co-Scientist. Most folders are reference material, not code:

- `Code/` — the only directory with runnable software (two projects, see below)
- `Context/` — long-form architecture/spec markdown for the planned system
- `Research/` — papers describing the original Co-Scientist
- `NotebookLM/`, `Media/` — UX captures and product references
- `.remember/` — session handoff notes (`.remember/remember.md` is the live handoff file)

There is no top-level build system. Each project under `Code/` is independently installable and runnable.

## Code/ai-coscientist-engine (Python library)

LangGraph-based multi-agent hypothesis-generation framework. Package name: `open-coscientist`. Source under `src/open_coscientist/`.

**Commands** (run from `Code/ai-coscientist-engine/`):
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

## Code/ai-coscientist-app (FastAPI + React viewer)

Web UI and HTTP/SSE API that wraps `open-coscientist` for live hypothesis-generation runs.

### Backend (`app/`)

Single-file FastAPI app (`app/main.py`, ~800 lines) with settings in `app/config.py` (pydantic-settings, loads `.env`).

**Commands** (run from `Code/ai-coscientist-app/`):
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

**Commands** (run from `Code/ai-coscientist-app/frontend/`):
```bash
bun install
bun run dev          # vite dev server on :5173
bun run build        # tsc && vite build
bun run check        # biome check --write . (lint + format + organize imports)
bun run lint         # biome lint .
bun run stories      # storybook dev on :6006
```

Vite reads `VITE_API_BASE_URL` (defaults to `http://localhost:8008`). All HTTP/SSE entry points live in `src/api/client.ts` and `src/hooks/useSSE.ts` + `src/hooks/useHypothesisGeneration.ts`. State is held in React context (`src/context/`: `GenerationContext`, `DomainContext`, `HypothesisFocusContext`, `ThemeContext`) — no Redux/Zustand.

Domain presets (prompt copy / examples per research area) are JSON in `src/domains/` keyed off `DomainContext`.

### Docker workflow

`docker-compose.yml` runs three services: `api` (FastAPI), `ui` (Vite), `mcp` (reference MCP server). The api container expects a sibling `../open-coscientist` checkout mounted at `/workspace/open-coscientist`; if absent, the entrypoint clones from `OPEN_COSCIENTIST_REPO` at ref `OPEN_COSCIENTIST_REF`. Override `OPEN_COSCIENTIST_PATH` in `.env` if the engine checkout is elsewhere. The container hardcodes `TOOLS_CONFIG` to `indra_cancer.yaml` — change it there, not in `.env`, when iterating on tools.

## Working in this repo

- The `open-coscientist` (engine) and `open-coscientist-viewer` (app) are upstream open-source projects from Jataware. This repo vendors them as plain directories (not submodules) — when editing, treat the boundary carefully and don't assume changes propagate to PyPI/Docker images. The viewer's pip install pulls `open-coscientist>=0.2.0` from PyPI by default; for local dev against engine changes, run `pip install -e ../ai-coscientist-engine` after `make install`.
- There are currently no committed tests in either project's `tests/` directory; `pytest` will exit clean.
- When invoked from this workspace, `.remember/remember.md` is the session-handoff file — read/update it per the `remember` skill instructions.

## Required environment

Both projects use **LiteLLM** for model dispatch. Set `GEMINI_API_KEY` (default) or the relevant provider key (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, …) before running. The viewer also reads `MCP_SERVER_URL` (default `http://localhost:8888/mcp`) and `TOOLS_CONFIG` (path or http URL to a YAML tools config). Full list of viewer env vars in `Code/ai-coscientist-app/.env.example`.
