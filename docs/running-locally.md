# Running the app locally

**TL;DR — from the repo root: `make start`.** It starts everything (API + UI + MCP)
and is fully configured. Everything below is context for when you're *not* in a
clean main checkout (e.g. a git worktree) or need to run a piece by hand.

## The one command

```bash
make start        # API :8008 + UI :5173 + MCP :8888, all wired
make stop         # stop them
```

`make start` runs `dev-all`, which launches:

| Service | Port | Notes |
|---|---|---|
| API (FastAPI) | 8008 | seeds 3 demo runs on startup; served at `/api/runs/demo` |
| UI (Vite/React) | 5173 | reads `VITE_API_BASE_URL`, defaults to `http://localhost:8008` |
| MCP (PubMed lit-review) | 8888 | Python **3.12** only; `make dev-mcp` auto-creates its venv |

Individual pieces: `make dev-api`, `make dev-ui`, `make dev-mcp`.

## Configuration (already set up — don't recreate it)

- **Env:** the repo-root `.env` holds everything — model keys, `MODEL_NAME`,
  `COSCIENTIST_DB_PATH` (`./coscientist.db`, relative), `ALLOWED_ORIGINS`
  (CORS allowlist for the UI origin), `MCP_SERVER_URL`
  (`http://localhost:8888/mcp`). The API loads `.env` **relative to its cwd**
  (`app/`), which `make start` handles.
- **Demo data:** seeded on API startup; no LLM/keys needed to view it. Demo
  runs are **not** in `/api/runs` (that's owned runs, empty for a fresh
  client) — they come from `/api/runs/demo`, which the home page uses.
- **MCP / PubMed:** the server lives at `engine/mcp_server/` (a flat package,
  run from `engine/` so `mcp_server.server:app` resolves). `make dev-mcp`
  creates a 3.12 venv and starts it. PubMed needs a contact email —
  `ENTREZ_EMAIL` in `engine/mcp_server/.env` (NCBI courtesy identifier, not
  auth). Without it: `pubmed_available: false`, literature falls back to LLM-only (no PubMed retrieval).
  Check status: `curl -s localhost:8008/status` → `mcp_available`,
  `pubmed_available`, `literature_review_available`.

## Running from a git worktree (the gotcha)

Worktrees under `.claude/worktrees/*` **do not carry gitignored files** — no
`.env`, no `.venv`, no `node_modules`. That is why `make start` won't "just work"
there. Options, cheapest first:

1. **Run `make start` from the main checkout** (`~/Code/Co-Scientist`). The
   backend code is identical across branches; only the frontend differs, and
   `bun run dev` in the worktree serves the worktree's frontend. This is almost
   always what you want for a UI change.
2. **If you must run the backend from the worktree:** copy the env and reuse the
   main venv (don't rebuild it):
   ```bash
   cp ~/Code/Co-Scientist/.env app/.env
   # backend: run from the worktree's app/ with the main venv
   (cd app && source ~/Code/Co-Scientist/.venv/bin/activate && uvicorn app.main:app --port 8008)
   # frontend:
   (cd app/frontend && bun install && bun run dev)   # or --port 5183 if 5173 is busy
   ```
   If the UI is on a non-default port (e.g. 5183), add it to `ALLOWED_ORIGINS`
   in `app/.env` or the API will CORS-block the browser.
3. **MCP from a worktree:** `python3.12 -m venv engine/mcp_server/.venv &&
   engine/mcp_server/.venv/bin/pip install -e engine/mcp_server/`, then
   `(cd engine && PYTHONPATH=. mcp_server/.venv/bin/python -m uvicorn
   mcp_server.server:app --port 8888)`. Restart the API afterward so it wires
   the MCP at startup.

## Don't repeat these mistakes

- Reach for **`make start`** before hand-rolling `uvicorn`/`vite` commands.
- The empty top-level `mcp_server/` is a stray dir — the real package is
  `engine/mcp_server/`.
- A worktree's missing `.env`/`.venv` is expected, not a broken setup.
