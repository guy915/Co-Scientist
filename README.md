# Google DeepMind AI Co-Scientist Clone

A locally-runnable, open clone of Google DeepMind's AI Co-Scientist — a scientist-in-the-loop, multi-agent hypothesis-generation workbench. It scopes a research goal, retrieves literature, generates candidate hypotheses, critiques them, ranks them through Elo tournaments, evolves the strongest ideas, audits citations, applies safety gates, and synthesises a structured research report.

The clone is **not** a chatbot, summariser, or paper generator. It is a scientific workbench.

> Status: end-to-end runnable. Default behaviour is deterministic **Mock Mode** so the full pipeline, persistence layer, SSE stream, and UI surface are exercisable without any LLM provider key. Drop a key into `.env` to flip the engine adapter to the upstream LangGraph engine.

## Quickstart

```bash
make setup          # creates .venv (Python 3.12), installs engine + app editable + frontend
make dev            # prints URLs and side-by-side instructions
make dev-api        # FastAPI on http://localhost:8008
make dev-ui         # Vite on    http://localhost:5173
```

In a browser at <http://localhost:5173>: click **New run**, type a research goal, pick Standard or Advanced, hit **Start**. The Overview tab streams the pipeline live; tabs for Ideas, Evidence, Tournament, and Report fill in as the workflow progresses. Runs survive an API restart — reopen from the Dashboard.

## Workbench tour

| Tab | Shows |
| --- | --- |
| Overview | Live pipeline timeline (supervisor → intake → safety → literature → generation → reflection → proximity → ranking → evolution → meta-review → citation audit → safety → report), counts of hypotheses / evidence / matches / events |
| Ideas | Ranked hypotheses by Elo. Click any row for the modal: statement, mechanism, expected effect, experimental design, lineage, reviews, citations |
| Evidence | Retrieved sources with abstracts, links, and per-citation classification: verified / partial / unsupported / unavailable |
| Tournament | Leaderboard plus full per-iteration matchup log with Elo deltas and judge rationale |
| Report | Server-generated Markdown report with download buttons (Markdown + JSON) and the final-safety verdict |

## Architecture

```
+-----------------------+        +-------------------------+
|  React + Vite + TS    | <--->  |  FastAPI                |
|  Tailwind v4 / Bun    |  SSE   |  /api/runs/* + /health  |
+-----------+-----------+        +-------+------+----------+
            ^                            |      ^
            |                            v      |
            |                +----------------------------+
            |                |  SQLite (runs/events/      |
            |                |  hypotheses/evidence/      |
            |                |  matches/reviews/reports/  |
            |                |  safety_decisions)         |
            |                +-------------+--------------+
            |                              |
            |                +-------------+---------------+
            |                |  EngineAdapter              |
            |                |  - select_provider()        |
            |                |  - mock workflow (default)  |
            |                |  - open_coscientist LangGraph (if key) |
            |                +-------------+---------------+
            |                              |
            |                  (optional)  v
            |                +-----------------------------+
            |                |  MCP literature server      |
            |                +-----------------------------+
            v
   browser-side state (router only — durable state lives in the API)
```

Full diagrams and module map in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Mock Mode vs Real Engine

The system reports its mode at `/status`:

```bash
$ curl http://localhost:8008/status | jq .mock_mode
true
```

| | Mock Mode | Real engine |
| - | - | - |
| Trigger | No LLM key in env | `GEMINI_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` set, engine importable |
| Behaviour | Deterministic seed → 11 agent steps, stable hypotheses, stable Elo updates | LangGraph engine emits `engine.*` events, persists final hypotheses |
| Cost | Free | Provider billing applies |
| Determinism | Same goal+profile → byte-identical results | LLM stochasticity applies |
| UI banner | "Mock Mode" yellow strip | "Live engine mode" muted strip |

Force mode for development: `COSCIENTIST_FORCE_MOCK=1`.

## Run commands

| Command | What it does |
| --- | --- |
| `make setup` | Creates `.venv`, installs engine + app editable, installs frontend deps |
| `make dev` | Prints both URLs and instructions for `dev-api` / `dev-ui` |
| `make dev-api` | FastAPI dev server with reload (port 8008) |
| `make dev-ui` | Vite dev server (port 5173, proxies `/api` to 8008) |
| `make dev-mcp` | Optional MCP reference server on 8888 (requires python3.12) |
| `make test` | Backend pytest: health, lifecycle, Elo, evolution, citation, safety |
| `make build` | `tsc && vite build` for the frontend |
| `make lint` / `make typecheck` | Backend ruff / mypy |
| `make reset-db` | Drops `coscientist.db` |
| `make clean` | Wipes venv, node_modules, caches |

## Environment

Copy `.env.example` to `.env`. Empty keys keep you in Mock Mode. Key variables:

```
GEMINI_API_KEY=        # any non-empty key triggers Real Engine selection
COSCIENTIST_DB_PATH=./coscientist.db
COSCIENTIST_REPORTS_DIR=./reports
ALLOWED_ORIGINS=http://localhost:5173
ELO_INITIAL=1200
ELO_K_FACTOR=24
SAFETY_MODE=standard   # 'strict' redacts dual-use language at intake
```

## API surface

```
POST   /api/runs                       create
GET    /api/runs                       list
GET    /api/runs/{id}                  read + summary
POST   /api/runs/{id}/start            start the workflow (background)
POST   /api/runs/{id}/cancel           request cancellation
GET    /api/runs/{id}/events           SSE; replays full history then tails live
GET    /api/runs/{id}/hypotheses
GET    /api/runs/{id}/evidence
GET    /api/runs/{id}/matches
GET    /api/runs/{id}/reviews
GET    /api/runs/{id}/safety
GET    /api/runs/{id}/citations
GET    /api/runs/{id}/report           structured JSON
GET    /api/runs/{id}/report.md        rendered Markdown (attachment)
GET    /status                         provider + mock_mode + MCP availability
```

## Tests

```
$ make test
27 passed in 6.76s
```

Covered:
- Health + status (mock-mode reporting).
- Run lifecycle: create, start, completion, persistence summary.
- Reopen after restart (TestClient reload simulating cold-boot).
- Advanced profile produces strictly more artefacts than Standard.
- Elo: initial 1200, equal-rating update is K/2, K-factor configurable, upset amplifies.
- Append-only evolution: every evolved row has `parent_id`, distinct from initial ids, lineage walks to gen-0.
- Citation classifier: all four states (`verified` / `partial` / `unsupported` / `unavailable`).
- Safety: intake block on weaponization, allow on benign, final-output block on hard patterns.

## Fidelity invariants

The clone is held to these invariants (full list with sources in [`docs/FIDELITY.md`](docs/FIDELITY.md)):

1. Supervisor coordinates 11 agent-equivalent steps (intake, literature, generation, reflection, proximity, ranking, evolution, meta-review, citation audit, safety, report).
2. Hypotheses start at Elo **1200**; K factor is configurable; standard Elo update formula.
3. Evolution is **append-only**: evolved hypotheses are new rows with `parent_id` set; original rows are never mutated.
4. Meta-review critique is persisted per iteration.
5. Citations are classified into exactly four states: `verified`, `partial`, `unsupported`, `unavailable`.
6. Safety runs at intake and at final-output stage.
7. Standard and Advanced profiles produce observably different compute depth.

## Repository layout

```
.
├── Makefile              # root commands
├── .env.example          # mock-mode-ready defaults
├── README.md             # this file (workspace entrypoint)
├── CLAUDE.md             # agent / contributor guidance
├── docs/
│   ├── ARCHITECTURE.md
│   ├── FIDELITY.md
│   ├── screenshots/      # visual validation evidence
│   └── archive/          # historical planning docs (PLAN, TASKS, IMPLEMENTATION_REPORT)
├── scripts/
│   └── dev_all.sh        # run API + UI together
├── Code/
│   ├── ai-coscientist-engine/    # local LangGraph engine (editable install)
│   └── ai-coscientist-app/
│       ├── app/                  # FastAPI + store/elo/safety/citations/mock/adapter/runs
│       ├── tests/                # pytest suite
│       └── frontend/             # React + Vite + Tailwind workbench
└── reference/            # source corpus & product refs (Context, Research, Media, NotebookLM)
```

## Non-goals

The clone is deliberately not:

- A chat wrapper over papers.
- An autonomous wet-lab executor.
- A medical / clinical / regulatory decision system.
- A multi-tenant SaaS — this is a local-first research tool.
