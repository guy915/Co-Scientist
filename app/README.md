# Co-Scientist Viewer

A web workbench for running and monitoring the multi-agent hypothesis-generation engine. Submit a research goal and watch in real time as a team of AI agents conducts a literature review, generates candidate hypotheses, debates them in an Elo tournament, evolves the survivors, and synthesizes a final report.

## Architecture

```
app/
├── app/            FastAPI backend (Python)
│   ├── main.py     App setup, lifespan, ownership middleware, router mounting
│   ├── runs/       Durable run-lifecycle router (create / start / stream / cancel); runs.lifecycle/collections/contrib/chat back it
│   ├── diagnostics_api.py  /health, /config, /status (mounted by app.main)
│   ├── engine_tasks/      Durable run execution — the production path — plus task_worker/
│   ├── store/      SQLite persistence layer (WAL, append-only event log)
│   ├── engine_adapter/    Provider selection + offline/real LLM backend switch
│   ├── report/            Goal Report package: payload, markdown, release gate, finalize path
│   ├── run_events.py      Run-event emission (make_emitter) for engine tasks and the adapter
│   ├── claims/ (gate, grounding, verifier), citations/   Citation-grounding pipeline
│   ├── safety/, hypothesis/safety.py, hypothesis/screening.py   Intake/final gates + per-hypothesis policy
│   ├── qa/, human_input.py    Q&A and scientist-in-the-loop steering
│   ├── elo.py      Elo rating utilities
│   └── config.py   Pydantic-settings config (loads .env)
├── dev/            Offline maintenance scripts (corpus_ingest.py, build_catalog.py) — not shipped code
└── frontend/       React 19 + Vite 7 + TypeScript + Tailwind v4
    └── src/
        ├── workbench/
        │   ├── pages/      chat workspace, run detail, researcher access, shared report
        │   ├── hooks/      chat-session, run-history, and utility hooks
        │   └── components/  shared workbench UI (settings dialog) + tabs/ (ideas_tab)
        ├── api/runs.ts     HTTP + SSE client
        └── hooks/          Shared app-level hooks (use_run_stream, ...)
```

The backend stores every run and its event log in a local SQLite database (`coscientist.db`). Streams survive client reconnects and full server restarts because they replay from the persisted event log.

## Quick start

### Prerequisites

- Python 3.12 recommended for the complete app and MCP service
- Node.js 22.13+ and [Bun](https://bun.sh) 1.3.14 (frontend)
- Optional LLM provider API key. With no key set, the app runs on the engine's deterministic offline LLM backend.

### Local development (no Docker)

**Backend (pip)**

```bash
cd app

# co-scientist-engine is not published to PyPI; install it from the
# sibling checkout first, then install the app and its remaining deps.
pip install -e ../engine
make install

# Copy and edit the env file
cp .env.example .env   # leave keys empty for offline mode

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
cp .env.example .env   # leave keys empty for offline mode
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

cp .env.example .env   # leave keys empty for offline mode

docker compose up --build
```

This starts three containers:

| Service | Port | Description |
|---|---|---|
| `api` | 8008 | FastAPI backend |
| `ui` | 5173 | Vite dev server |
| `mcp` | 8888 | Reference MCP server (PubMed, OpenAlex, ChEMBL/UniProt, INDRA, web fetch/search) |

The `api` container mounts the engine from `../engine`. Override `COSCIENTIST_ENGINE_PATH` in `.env` if the engine checkout is elsewhere; set `COSCIENTIST_ENGINE_REPO` only when you want the entrypoint to clone a checkout instead of using a local mount.

## Configuration

All backend settings are read from `.env` (or environment variables). See `.env.example` for the full list; the most important ones:

| Variable | Default | Description |
|---|---|---|
| `OPENROUTER_API_KEY` / `GEMINI_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `DEEPSEEK_API_KEY` | — | Optional provider keys. If none are set, the app uses the offline LLM backend. The default models need the OpenRouter one. |
| `COSCIENTIST_FORCE_OFFLINE` | `0` | Force the offline LLM backend even when a provider key is set (deprecated alias: `COSCIENTIST_FORCE_MOCK`) |
| `MODEL_NAME` | `openrouter/inclusionai/ling-3.1-flash` | LiteLLM worker model ID |
| `SUPERVISOR_MODEL_NAME` | `openrouter/inclusionai/ling-3.1-flash` | Model for supervisor and meta-review |
| `CHAT_MODEL_NAME` | `openrouter/inclusionai/ling-3.1-flash` | Model for chat-workspace Q&A; falls back to `MODEL_NAME` |
| `SEMANTIC_SAFETY_MODEL` | `openrouter/inclusionai/ling-3.1-flash` | Model for contextual safety screening |
| `MCP_SERVER_URL` | `http://localhost:8888/mcp` | MCP server for literature review tools (optional) |
| `COSCIENTIST_CACHE_ENABLED` | `true` | Enable LLM response caching |
| `COSCIENTIST_CACHE_DIR` | `./cache` | Cache directory path |
| `TOOLS_CONFIG` | — | Path or URL to a YAML tools config (optional) |
| `ENTREZ_EMAIL` | — | Email for NCBI Entrez / PubMed access (optional) |
| `COSCIENTIST_DEBUG` | `false` | Enable debug-level logging |
| `AUTH_MODE` | `compatibility` | Local development identity; set `required` before exposing the API |
| `AUTH_SECRET` | — | Random signing secret; required when authentication is required |
| `RESEARCHER_ACCESS_CODES` | `{}` | JSON mapping of researcher IDs to unique high-entropy invite codes |
| `AUTH_EXCHANGE_PER_MINUTE` | `20` | Invite-exchange attempt limit per connecting IP and API process |

The default free Nemotron 3 Ultra route falls back only to free models, keeps
the JSON schema in the prompt because its host accepts no response format, and
enforces a zero-price request ceiling. Explicit environment and BYOK model choices remain supported.
See [deployment](../docs/DEPLOYMENT.md) and [launch guidance](../docs/LAUNCH.md) before
hosting the service publicly.

The frontend reads a single variable:

| Variable | Default | Description |
|---|---|---|
| `VITE_API_BASE_URL` | — (same origin) | Backend URL. Unset, the API client uses same-origin relative paths and the Vite dev server proxies them to `http://localhost:8008`. Set the hosted API origin explicitly for a separate production frontend. |

## Using the workbench

1. **Chat workspace** (`/chats/:id`) — create a session from home (`/`). Describe a research goal in chat,
   review the inferred run setup, and hit Start. The timeline keeps progress,
   steering messages, leading hypotheses, and report status in chronological order.
2. **Run detail** — open the run from its chat timeline. Four views update live via SSE:
   - **Goal Details** — the run's goal, configuration, provider, artifact counts, and safety gates.
   - **Learning** — retrieved literature and citations.
   - **Research Overview** — synthesized Markdown report, downloadable.
   - **All Ideas** — ranked hypothesis list with Elo scores and lineage.

Runs can be paused, resumed, or cancelled mid-flight. The backend stores the full event log so completed runs can be re-explored after the fact.

## API reference

The backend mounts several routers (`runs`, `interviews`, `feedback`,
`auth`, `logs`) plus top-level diagnostics. The core run-lifecycle group is
below; for the complete, always-current surface use the interactive docs at
`/docs`.

### Run lifecycle (`/api/runs`)

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/runs` | Create a draft run |
| `GET` | `/api/runs` | List runs (most recent first) |
| `GET` | `/api/runs/demo` | Get the seeded public demo run |
| `GET` | `/api/runs/{id}` | Get run + summary counts |
| `POST` | `/api/runs/{id}/start` | Start the workflow in the background |
| `POST` | `/api/runs/{id}/pause` | Pause a running workflow |
| `POST` | `/api/runs/{id}/resume` | Resume a paused workflow |
| `POST` | `/api/runs/{id}/cancel` | Cancel a running workflow |
| `GET` | `/api/runs/{id}/events` | SSE stream (live + replay via `?after=`) |
| `GET` | `/api/runs/{id}/events?stream=false` | Persisted event log as a one-shot JSON snapshot |
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
| `GET` | `/status` | MCP/PubMed/web-search availability, provider, LLM backend |

Interactive docs are available when the server is running, to operator
callers only — a loopback client, or one sending `X-Logs-Token:
$LOGS_ADMIN_TOKEN`. Anyone else gets a 404.
- Swagger UI: http://localhost:8008/docs
- ReDoc: http://localhost:8008/redoc

## Development commands

**Backend** (from `app/`):

```bash
make install     # install with dev deps
make dev         # hot-reload server on :8008
make test        # pytest
make format      # ruff format
make lint        # ruff check
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
bun run build    # tsc && vite build && node scripts/prerender.mjs
bun run lint     # gts lint
bun run fix      # gts fix (format + autofix)
```

## Offline mode

Every run executes on the real engine; the engine is a hard runtime dependency. If no LLM API key is set (or `COSCIENTIST_FORCE_OFFLINE=1` is set — the deprecated alias `COSCIENTIST_FORCE_MOCK=1` is still honored), the server pins the engine's `offline/` model backend instead of a real provider, producing deterministic, schema-valid hypotheses and evidence with no API spend. The `/status` endpoint reports `llm_backend: "offline"`. This is useful for frontend development and CI.

## Literature review (MCP)

The literature review and reflection nodes connect to an MCP server that provides PubMed and OpenAlex search, full-text retrieval, ChEMBL/UniProt lookups, INDRA CoGex queries, URL fetching, and web search (registered only when `BRAVE_API_KEY` or `TAVILY_API_KEY` is set on the MCP server). Without a running MCP server the nodes fall back to LLM-only mode — hypothesis quality is reduced but the workflow still completes.

The reference MCP server lives in `../engine/mcp_server/`. Run it separately or let Docker Compose manage it:

```bash
cd ../engine
pip install -e mcp_server/     # requires Python 3.12
uvicorn mcp_server.server:app --host 0.0.0.0 --port 8888
```

Set `ENTREZ_EMAIL` (and optionally `ENTREZ_API_KEY`) for full PubMed access.

---
