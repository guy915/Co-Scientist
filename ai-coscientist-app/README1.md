# Open CoScientist Viewer

A web workbench for running and monitoring the [Open CoScientist](https://github.com/jataware/open-coscientist) multi-agent hypothesis-generation engine. Submit a research goal and watch in real time as a team of AI agents conducts a literature review, generates candidate hypotheses, debates them in an Elo tournament, evolves the survivors, and synthesizes a final report.

## Architecture

```
ai-coscientist-app/
├── app/            FastAPI backend (Python)
│   ├── main.py     API entrypoint (~800 lines), legacy /generate + /parse endpoints
│   ├── runs.py     Durable run-lifecycle router (create / start / stream / cancel)
│   ├── store.py    SQLite persistence layer (WAL, append-only event log)
│   ├── engine_adapter.py  Bridges to open-coscientist or mock workflow
│   ├── mock_workflow.py   Deterministic mock for dev without an LLM key
│   ├── elo.py      Elo rating utilities
│   ├── citations.py       Citation extraction helpers
│   ├── safety.py   Safety decision storage
│   └── config.py   Pydantic-settings config (loads .env)
└── frontend/       React 19 + Vite 7 + TypeScript + Tailwind v4
    └── src/
        ├── workbench/
        │   ├── pages/      Dashboard, NewRun, RunDetail
        │   └── components/ RunStatusPill, IdeaModal, LogConsole, EloTrajectoryChart
        │       └── tabs/   Overview, Ideas, Evidence, Tournament, Report
        ├── api/runs.ts     HTTP + SSE client
        └── hooks/useRunStream.ts  Live SSE hook
```

The backend stores every run and its event log in a local SQLite database (`coscientist.db`). Streams survive client reconnects and full server restarts because they replay from the persisted event log.

## Quick start

### Prerequisites

- Python 3.10+
- Node.js / [Bun](https://bun.sh) (frontend)
- A LLM provider API key — `GEMINI_API_KEY` by default (Gemini 2.5 Flash)

### Local development (no Docker)

**Backend**

```bash
cd ai-coscientist-app

# Install Python deps (pulls open-coscientist from PyPI)
make install

# For local engine changes, pin to the sibling checkout instead:
# pip install -e ../ai-coscientist-engine

# Copy and edit the env file
cp .env.example .env   # set GEMINI_API_KEY at minimum

# Start the API server (hot-reload)
make dev               # listens on :8008
```

**Frontend**

```bash
cd ai-coscientist-app/frontend

bun install
cp .env.example .env   # VITE_API_BASE_URL defaults to http://localhost:8008
bun run dev            # Vite dev server on :5173
```

Open `http://localhost:5173` in your browser.

### Docker Compose (all services)

```bash
cd ai-coscientist-app

cp .env.example .env   # set GEMINI_API_KEY

docker compose up --build
```

This starts three containers:

| Service | Port | Description |
|---|---|---|
| `api` | 8008 | FastAPI backend |
| `ui` | 5173 | Vite dev server |
| `mcp` | 8888 | Reference MCP server (PubMed + INDRA) |

The `api` container mounts the engine from `../ai-coscientist-engine` (or clones it from GitHub if that path is absent). Override `OPEN_COSCIENTIST_PATH` in `.env` if the engine checkout is elsewhere.

## Configuration

All backend settings are read from `.env` (or environment variables). See `.env.example` for the full list; the most important ones:

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | — | **Required.** Google Gemini API key (or set the relevant provider key instead) |
| `MODEL_NAME` | `gemini/gemini-2.5-flash` | LiteLLM model ID |
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
2. **New run** — enter a research goal (free text), choose a run profile, and optionally tune iteration counts. Three example goals are shown as inspiration.
3. **Run detail** — five tabs update live via SSE as the workflow progresses:
   - **Overview** — live log, agent activity timeline, and key metrics.
   - **Ideas** — ranked hypothesis list with Elo scores and lineage.
   - **Evidence** — retrieved literature and citations.
   - **Tournament** — Elo pairwise matchup history and trajectory chart.
   - **Report** — synthesized Markdown report, downloadable.

Runs can be cancelled mid-flight. The backend stores the full event log so completed runs can be re-explored after the fact.

## API reference

The backend exposes two groups of endpoints.

### Run lifecycle (`/api/runs`)

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/runs` | Create a draft run |
| `GET` | `/api/runs` | List runs (most recent first) |
| `GET` | `/api/runs/{id}` | Get run + summary counts |
| `POST` | `/api/runs/{id}/start` | Start the workflow in the background |
| `POST` | `/api/runs/{id}/cancel` | Cancel a running workflow |
| `GET` | `/api/runs/{id}/events` | SSE stream (live + replay via `?after=`) |
| `GET` | `/api/runs/{id}/hypotheses` | Hypotheses with Elo scores and lineage |
| `GET` | `/api/runs/{id}/evidence` | Retrieved literature |
| `GET` | `/api/runs/{id}/matches` | Tournament matchup history |
| `GET` | `/api/runs/{id}/reviews` | Reviewer and meta-review notes |
| `GET` | `/api/runs/{id}/safety` | Safety decisions |
| `GET` | `/api/runs/{id}/citations` | Citations with classification states |
| `GET` | `/api/runs/{id}/report` | Structured report (JSON) |
| `GET` | `/api/runs/{id}/report.md` | Rendered Markdown report |

### Utility endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/config` | Server-default config values |
| `GET` | `/status` | MCP/PubMed availability, provider, API key presence |
| `POST` | `/parse` | LLM-powered research goal parser |
| `POST` | `/generate` | Synchronous blocking generation (legacy) |

Interactive docs are available at `http://localhost:8008/docs` when the server is running.

## Development commands

**Backend** (from `ai-coscientist-app/`):

```bash
make install     # install with dev deps
make dev         # hot-reload server on :8008
make test        # pytest
make format      # black + ruff --fix
make lint        # ruff check
make typecheck   # mypy
```

Pixi users can substitute `pixi run <task>` for any `make` target.

**Frontend** (from `ai-coscientist-app/frontend/`):

```bash
bun install
bun run dev      # Vite dev server on :5173
bun run build    # tsc && vite build
bun run check    # biome check --write (lint + format + import sort)
bun run lint     # biome lint
```

## Mock mode

If `open-coscientist` is not installed or no LLM API key is set, the server falls back to a deterministic mock workflow that returns pre-built fake hypotheses. The UI displays a "Mock mode" banner. This is useful for frontend development and CI.

## Literature review (MCP)

The literature review and reflection nodes connect to an MCP server that provides PubMed search and INDRA CoGex tools. Without a running MCP server the nodes fall back to LLM-only mode — hypothesis quality is reduced but the workflow still completes.

The reference MCP server lives in `../ai-coscientist-engine/mcp_server/`. Run it separately or let Docker Compose manage it:

```bash
cd ../ai-coscientist-engine
pip install -e mcp_server/     # requires Python 3.12
uvicorn mcp_server.server:app --host 0.0.0.0 --port 8888
```

Set `ENTREZ_EMAIL` (and optionally `ENTREZ_API_KEY`) for full PubMed access.
