# Open Coscientist Viewer

Web application for the [open-coscientist](https://github.com/jataware/open-coscientist) hypothesis generation framework, with a full-featured web UI.

## Features

- **Full-Stack Application**: FastAPI backend + React frontend
- **Modern Web UI**: Built with Vite, TypeScript, Tailwind CSS, and shadcn/ui
  - Real-time hypothesis generation workflow visualization
  - Interactive agent activity monitoring, with hypothesis ranking and evolution tracking
  - Export to JSON/CSV/Markdown
- **Server-Sent Events (SSE) streaming** for real-time updates during hypothesis generation
- **Configurable via environment variables** — see `.env.example`

## MCP Server (Literature Review)

The open coscientist and viewer can work without an MCP server (for testing), but hypotheses grounded in recent literature, in real papers — requires one. The [open-coscientist](https://github.com/jataware/open-coscientist) repo includes a reference MCP server (`mcp_server/`) that provides PubMed search and INDRA CoGex knowledge graph tools.

**Docker** handles the MCP server automatically. For **pip/pixi** setups, you need to run it separately — see the MCP server section under each install method below. See [open-coscientist/mcp_server/README.md](https://github.com/jataware/open-coscientist/blob/v0.2.0/mcp_server/README.md)

To point the viewer at a running MCP server, set `MCP_SERVER_URL` in `.env`:
```bash
MCP_SERVER_URL=http://localhost:8888/mcp
```

To configure which tools the hypothesis generator uses, set `TOOLS_CONFIG` to a YAML tools config file. Example configs are in `open-coscientist/src/open_coscientist/config/examples/`.

---

## Setup

### 1. pip (recommended)

Requires Python 3.10+.

```bash
# Install dependencies (includes open-coscientist from PyPI)
make install

# Configure environment
cp .env.example .env
# Edit .env — at minimum set GEMINI_API_KEY (or your provider's key)

# Run the API server
make dev

# In a separate terminal, run the frontend
cd frontend
bun install  # first time only
bun run dev
```

- Frontend UI: http://localhost:5173
- Backend API: http://localhost:8008
- API docs: http://localhost:8008/docs

> If you are also developing `open-coscientist` locally, run `pip install -e ../open-coscientist`
> after `make install` to override the PyPI version with your local checkout.

**MCP server (for literature review):**

Clone `open-coscientist` and run its MCP server in a separate terminal:

```bash
git clone https://github.com/jataware/open-coscientist.git
cd open-coscientist/mcp_server
pip install -e .
cp .env.example .env
# Edit .env — set ENTREZ_EMAIL for PubMed access
uvicorn mcp_server.server:app --host 0.0.0.0 --port 8888
```

Alternatively, use the MCP server's Docker Compose (from the `open-coscientist` repo) if you prefer not to install its dependencies locally:

```bash
cd open-coscientist
docker compose up --build
```

---

### 2. Docker for development

Runs all three services (API, UI, MCP server) in containers with hot reload. The MCP server is included automatically — no separate setup needed.

**Prerequisites:** Docker with Compose, and the [open-coscientist](https://github.com/jataware/open-coscientist) repo cloned as a sibling directory:

```
parent/
├── open-coscientist/       # clone this
└── open-coscientist-viewer/
```

```bash
# Configure the viewer
cp .env.example .env
# Edit .env — set GEMINI_API_KEY and any other vars

# Configure the MCP server
cp ../open-coscientist/mcp_server/.env.example ../open-coscientist/mcp_server/.env
# Edit to set ENTREZ_EMAIL for PubMed access

# Build and start all services
docker compose up --build
```

- Frontend UI: http://localhost:5173
- Backend API: http://localhost:8008
- MCP server: http://localhost:8888

The API container mounts your local `open-coscientist` checkout and installs it as an editable package, so changes to the library are reflected on restart. If the sibling directory is absent, the container clones it automatically from GitHub on first start.

**Custom open-coscientist path:** Set `OPEN_COSCIENTIST_PATH` in `.env` if your checkout is not at `../open-coscientist`:

```bash
OPEN_COSCIENTIST_PATH=/path/to/your/open-coscientist
```

---

### 3. Pixi

Requires [Pixi](https://pixi.sh/).

```bash
# Install pixi (if not already installed)
curl -fsSL https://pixi.sh/install.sh | bash

# Install dependencies
pixi install

# Configure environment
cp .env.example .env

# Run the API server
pixi run dev

# In a separate terminal, run the frontend
cd frontend
bun install  # first time only
bun run dev
```

**MCP server:** Same as the pip instructions above — clone `open-coscientist` and run the MCP server separately.

---

## Configuration

All configuration is via environment variables. See `.env.example` for the full list.

**Required:**
- `GEMINI_API_KEY` — API key for Google Gemini (default model). For other providers use the corresponding key (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.) as required by [LiteLLM](https://docs.litellm.ai/).

**Key optional overrides:**
| Variable | Default | Description |
|---|---|---|
| `MODEL_NAME` | `gemini/gemini-2.5-flash` | LLM model (LiteLLM format) |
| `MCP_SERVER_URL` | `http://localhost:8888/mcp` | MCP server URL for literature/api tools |
| `TOOLS_CONFIG` | _(none)_ | Path or URL to a tools config YAML |
| `MAX_ITERATIONS` | `3` | Refinement cycles |
| `INITIAL_HYPOTHESES_COUNT` | `5` | Initial hypothesis pool size |
| `EVOLUTION_MAX_COUNT` | `3` | Top hypotheses to evolve per iteration |
| `COSCIENTIST_CACHE_ENABLED` | `true` | Cache LLM responses |
| `COSCIENTIST_CACHE_DIR` | `./cache` | Cache directory |

**Note:** The UI always overrides `MAX_ITERATIONS`, `INITIAL_HYPOTHESES_COUNT`, and `EVOLUTION_MAX_COUNT` per run via the Advanced Configuration panel. Server-side defaults only apply to the non-streaming `/generate` endpoint.

---

## Development

Available commands via both `make` and `pixi run`:

| Task | make | pixi |
|---|---|---|
| Install deps | `make install` | `pixi install` |
| Run dev server | `make dev` | `pixi run dev` |
| Run tests | `make test` | `pixi run test` |
| Format | `make format` | `pixi run format` |
| Lint | `make lint` | `pixi run lint` |
| Type check | `make typecheck` | `pixi run typecheck` |

### API Documentation

With the server running:
- Swagger UI: http://localhost:8008/docs
- ReDoc: http://localhost:8008/redoc

---

Copyright Jataware Corp, 2026.
