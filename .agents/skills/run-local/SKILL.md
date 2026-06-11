---
name: run-local
description: Use when starting, launching, or running the AI Co-Scientist app locally. Covers backend (FastAPI) and frontend (Vite) startup, known gotchas with the venv, and expected URLs.
---

# Run AI Co-Scientist Locally

## URLs

| Service | URL |
|---|---|
| Frontend (UI) | http://localhost:5173 |
| Backend API | http://localhost:8008 |

## Prerequisites

- `.env` exists at `ai-coscientist-app/.env` with `DEEPSEEK_API_KEY` set (already committed)
- Bun installed (`bun --version`)

## Start Backend

```bash
cd "ai-coscientist-app"
.venv/bin/uvicorn app.main:app --reload --reload-dir app --host 0.0.0.0 --port 8008 > /tmp/backend.log 2>&1 &
```

Wait ~5s then verify: `curl -s http://localhost:8008/health`

### Venv gotcha

The `.venv` dir has a `python3.12 2` artifact (space in dir name) from a double-creation. If imports fail (e.g. `ModuleNotFoundError: No module named 'typing_extensions'`), rebuild it:

```bash
cd "ai-coscientist-app"
/opt/homebrew/bin/python3.12 -m venv .venv --clear
.venv/bin/pip install -e ".[dev]" -q
```

Do **not** use the system `python` or `python3` — they're Python 3.14 and don't have uvicorn. Do **not** use `/opt/homebrew/bin/uvicorn` directly without the venv active — it will use system site-packages and miss deps.

## Start Frontend

```bash
cd "ai-coscientist-app/frontend"
bun run dev > /tmp/frontend.log 2>&1 &
```

Wait ~3s then verify: `curl -s http://localhost:5173 | head -3`

## Check Running

```bash
lsof -ti:8008 && echo "backend up" || echo "backend down"
lsof -ti:5173 && echo "frontend up" || echo "frontend down"
```

## Logs

```bash
tail -f /tmp/backend.log
tail -f /tmp/frontend.log
```

## Kill

```bash
lsof -ti:8008 | xargs kill -9 2>/dev/null
lsof -ti:5173 | xargs kill -9 2>/dev/null
```
