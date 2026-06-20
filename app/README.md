# Co-Scientist Viewer

A web workbench for running and monitoring the multi-agent hypothesis-generation engine. Submit a research goal and watch in real time as a team of AI agents conducts a literature review, generates candidate hypotheses, debates them in an Elo tournament, evolves the survivors, and synthesizes a final report.

## Architecture

```
app/
├── app/            FastAPI backend (Python)
│   ├── main.py     App setup, diagnostics, and legacy /generate endpoints
│   ├── runs.py     Durable run-lifecycle router (create / start / stream / cancel)
│   ├── store.py    SQLite persistence layer (WAL, append-only event log)
│   ├── engine_adapter.py  Bridges to engine or mock workflow
│   ├── mock_workflow.py   Deterministic mock for dev without an LLM key
│   ├── elo.py      Elo rating utilities
│   ├── citations.py       Citation extraction helpers
│   ├── safety.py   Safety decision storage
│   └── config.py   Pydantic-settings config (loads .env)
└── frontend/       React 19 + Vite 7 + TypeScript + Tailwind v4
    └── src/
        ├── workbench/
        │   ├── pages/      dashboard, new_run, run_detail
        │   └── components/ run_status_pill, idea_modal, log_console, elo_trajectory_chart
        │       └── tabs/   Ideas, Knowledge Base, Summary, Run Specifications, Progress, Tournament, Chat
        ├── api/runs.ts     HTTP + SSE client
        └── hooks/          Live run stream + message hooks
```

The backend stores every run and its event log in a local SQLite database (`coscientist.db`). Streams survive client reconnects and full server restarts because they replay from the persisted event log.

## Quick start

### Prerequisites

- Python 3.10+
- Node.js / [Bun](https://bun.sh) (frontend)
- Optional LLM provider API key. With no key set, the app runs deterministic
  mock mode.

### Local development (no Docker)

**Backend (pip)**

```bash
cd app

# co-scientist-engine is not published to PyPI; install it from the
# sibling checkout first, then install the app and its remaining deps.
pip install -e ../engine
make install

# Copy and edit the env file
cp .env.example .env   # leave keys empty for mock mode

# Start the API server (hot-reload)
make dev               # listens on :8008
```

**Backend (Pixi)**

Requires [Pixi](https://pixi.sh/).

```bash
cd app

# Install pixi if not already installed
curl -fsSL https://pixi.sh/install.sh | bash

pixi install
cp .env.example .env   # leave keys empty for mock mode
pixi run dev           # listens on :8008
```

**Frontend**

```bash
cd app/frontend

bun install
cp .env.example .env   # VITE_API_BASE_URL defaults to http://localhost:8008
bun run dev            # Vite dev server on :5173
```

Open `http://localhost:5173` in your browser.

### Docker Compose (all services)

```bash
cd app

cp .env.example .env   # leave keys empty for mock mode

docker compose up --build
```

This starts three containers:

| Service | Port | Description |
|---|---|---|
| `api` | 8008 | FastAPI backend |
| `ui` | 5173 | Vite dev server |
| `mcp` | 8888 | Reference MCP server (PubMed + INDRA) |

The `api` container mounts the engine from `../engine`. Override
`COSCIENTIST_ENGINE_PATH` in `.env` if the engine checkout is elsewhere; set
`COSCIENTIST_ENGINE_REPO` only when you want the entrypoint to clone a checkout
instead of using a local mount.

## Configuration

All backend settings are read from `.env` (or environment variables). See `.env.example` for the full list; the most important ones:

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `DEEPSEEK_API_KEY` | — | Optional provider keys. If none are set, the app uses mock mode. |
| `MODEL_NAME` | `gemini/gemini-2.5-flash` | LiteLLM model ID |
| `SUPERVISOR_MODEL_NAME` | — | Optional stronger model for supervisor and meta-review |
| `CHAT_MODEL_NAME` | — | Optional model for Chat tab Q&A; defaults to `MODEL_NAME` |
| `MAX_ITERATIONS` | `3` | Workflow iterations (can be overridden per run in the UI) |
| `INITIAL_HYPOTHESES_COUNT` | `5` | Hypotheses generated per iteration |
| `EVOLUTION_MAX_COUNT` | `3` | Hypotheses selected for evolution |
| `MCP_SERVER_URL` | `http://localhost:8888/mcp` | MCP server for literature review tools (optional) |
| `COSCIENTIST_LIT_REVIEW_PAPERS_COUNT` | `10` | Papers read per literature review pass |
| `COSCIENTIST_CACHE_ENABLED` | `true` | Enable LLM response caching |
| `COSCIENTIST_CACHE_DIR` | `./cache` | Cache directory path |
| `TOOLS_CONFIG` | — | Path or URL to a YAML tools config (optional) |
| `ENTREZ_EMAIL` | — | Email for NCBI Entrez / PubMed access (optional) |
| `DEBUG` | `false` | Enable debug-level logging |

The frontend reads a single variable:

| Variable | Default | Description |
|---|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8008` | Backend URL |

## Using the workbench

1. **Dashboard** — lists all past runs with status, model, and hypothesis counts.
2. **New run** — describe a research goal in chat, review the inferred setup, and start the canonical workflow. Three example goals are shown as inspiration.
3. **Run detail** — reference report tabs plus supporting live views update via SSE:
   - **Ideas** — ranked hypothesis list with Elo scores and lineage.
   - **Knowledge Base** — retrieved literature and citations.
   - **Summary** — synthesized Markdown report, downloadable.
   - **Run Specifications** — provider, configuration, artifacts, and safety gates.
   - **Progress** — live log, agent activity timeline, and key metrics.
   - **Tournament** — Elo pairwise matchup history and trajectory chart.
   - **Chat** — scientist-in-the-loop steering and Q&A for the run.

Runs can be cancelled mid-flight. The backend stores the full event log so completed runs can be re-explored after the fact.

## API reference

The backend exposes two groups of endpoints.

### Run lifecycle (`/api/runs`)

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/runs` | Create a draft run |
| `GET` | `/api/runs` | List runs (most recent first) |
| `GET` | `/api/runs/demo` | Get the seeded public demo run |
| `GET` | `/api/runs/{id}` | Get run + summary counts |
| `POST` | `/api/runs/{id}/start` | Start the workflow in the background |
| `POST` | `/api/runs/{id}/cancel` | Cancel a running workflow |
| `GET` | `/api/runs/{id}/events` | SSE stream (live + replay via `?after=`) |
| `GET` | `/api/runs/{id}/events/log` | Persisted event log as JSON |
| `GET` | `/api/runs/{id}/hypotheses` | Hypotheses with Elo scores and lineage |
| `GET` | `/api/runs/{id}/evidence` | Retrieved literature |
| `GET` | `/api/runs/{id}/matches` | Tournament matchup history |
| `GET` | `/api/runs/{id}/reviews` | Reviewer and meta-review notes |
| `GET` | `/api/runs/{id}/safety` | Safety decisions |
| `GET` | `/api/runs/{id}/citations` | Citations with classification states |
| `GET` | `/api/runs/{id}/report` | Structured report (JSON) |
| `GET` | `/api/runs/{id}/report.md` | Rendered Markdown report |
| `GET` | `/api/runs/{id}/messages` | List steering, milestone, and Q&A messages |
| `POST` | `/api/runs/{id}/messages` | Queue a steering message |
| `POST` | `/api/runs/{id}/messages/ask` | Ask a streamed Q&A question |

### Utility endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/config` | Server-default config values |
| `GET` | `/status` | MCP/PubMed availability, provider, API key presence |
| `POST` | `/generate` | Deprecated synchronous blocking generation |
| `POST` | `/generate/start` | Deprecated streaming generation start |
| `GET` | `/generate/stream/{task_id}` | Deprecated streaming generation SSE |
| `POST` | `/cancel_hypothesis_generation` | Deprecated legacy task cancellation |

Interactive docs are available when the server is running:
- Swagger UI: http://localhost:8008/docs
- ReDoc: http://localhost:8008/redoc

## Development commands

**Backend** (from `app/`):

```bash
make install     # install with dev deps
make dev         # hot-reload server on :8008
make test        # pytest
make format      # yapf -ir
make lint        # pylint
make typecheck   # mypy
```

Pixi users can substitute `pixi run <task>` for any `make` target:

| Task | `make` | `pixi run` |
|---|---|---|
| Install deps | `make install` | `pixi install` |
| Run dev server | `make dev` | `pixi run dev` |
| Run tests | `make test` | `pixi run test` |
| Format | `make format` | `pixi run format` |
| Lint | `make lint` | `pixi run lint` |
| Type check | `make typecheck` | `pixi run typecheck` |

**Frontend** (from `app/frontend/`):

```bash
bun install
bun run dev      # Vite dev server on :5173
bun run build    # tsc && vite build
bun run lint     # gts lint
bun run fix      # gts fix (format + autofix)
```

## Mock mode

If the engine is not installed or no LLM API key is set, the server falls back
to a deterministic mock workflow that returns pre-built hypotheses and evidence.
The `/status` endpoint reports `mock_mode: true`. This is useful for frontend
development and CI.

## Literature review (MCP)

The literature review and reflection nodes connect to an MCP server that provides PubMed search and INDRA CoGex tools. Without a running MCP server the nodes fall back to LLM-only mode — hypothesis quality is reduced but the workflow still completes.

The reference MCP server lives in `../engine/mcp_server/`. Run it separately or let Docker Compose manage it:

```bash
cd ../engine
pip install -e mcp_server/     # requires Python 3.12
uvicorn mcp_server.server:app --host 0.0.0.0 --port 8888
```

Set `ENTREZ_EMAIL` (and optionally `ENTREZ_API_KEY`) for full PubMed access.

---
