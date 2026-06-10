.PHONY: help setup dev dev-api dev-ui dev-mcp test lint typecheck build clean stop reset-db

ROOT := $(shell pwd)
ENGINE := $(ROOT)/ai-coscientist-engine
APP    := $(ROOT)/ai-coscientist-app
FRONTEND := $(APP)/frontend
VENV  := $(ROOT)/.venv
PY    := $(VENV)/bin/python
PIP   := $(VENV)/bin/pip

# Default URLs printed by `make dev`
API_URL := http://localhost:8008
UI_URL  := http://localhost:5173
DOCS_URL := http://localhost:8008/docs

help:
	@echo "AI Co-Scientist Clone — root commands"
	@echo "  make setup        Create .venv, install engine (editable) + app (editable), install frontend"
	@echo "  make dev          Print URLs and instructions for running both servers"
	@echo "  make dev-api      Run FastAPI dev server   ($(API_URL))"
	@echo "  make dev-ui       Run Vite dev server      ($(UI_URL))"
	@echo "  make dev-mcp      Run reference MCP server (optional, needs Python 3.12)"
	@echo "  make test         Run backend pytest suite (engine + app)"
	@echo "  make lint         Lint backend (ruff)"
	@echo "  make typecheck    Typecheck backend (mypy)"
	@echo "  make build        Build frontend (tsc + vite build)"
	@echo "  make clean        Remove .venv, caches, frontend dist"
	@echo "  make reset-db     Drop the local SQLite store (coscientist.db)"

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
setup: $(VENV)/bin/activate
	@echo ">> Installing engine (editable)"
	@$(PIP) install -e "$(ENGINE)[dev]"
	@echo ">> Installing app (editable, dev extras)"
	@# Skip the PyPI open-coscientist pin (we have it editable already from $(ENGINE))
	@$(PIP) install -e "$(APP)" --no-deps
	@$(PIP) install fastapi "uvicorn[standard]" python-dotenv pydantic pydantic-settings httpx
	@$(PIP) install pytest pytest-asyncio black ruff mypy
	@# Reference MCP server is optional and pins Python 3.12, so we don't install it here.
	@echo ">> Installing frontend (bun preferred, npm fallback)"
	@cd "$(FRONTEND)" && (command -v bun >/dev/null 2>&1 && bun install) || (echo "bun not found; using npm" && npm install --no-audit --no-fund --silent)
	@test -f "$(ROOT)/.env" || cp "$(ROOT)/.env.example" "$(ROOT)/.env"
	@echo ""
	@echo "Setup complete. Next:"
	@echo "  make dev-api    # in one terminal"
	@echo "  make dev-ui     # in another terminal"

$(VENV)/bin/activate:
	@echo ">> Creating venv at $(VENV) (using python3.12 if available)"
	@(command -v python3.12 >/dev/null 2>&1 && python3.12 -m venv "$(VENV)") || \
	 (command -v python3.13 >/dev/null 2>&1 && python3.13 -m venv "$(VENV)") || \
	 python3 -m venv "$(VENV)"
	@$(PIP) install --upgrade pip setuptools wheel >/dev/null

# ---------------------------------------------------------------------------
# Dev servers
# ---------------------------------------------------------------------------
dev:
	@echo ""
	@echo "AI Co-Scientist Clone — dev URLs"
	@echo "  API   : $(API_URL)"
	@echo "  Docs  : $(DOCS_URL)"
	@echo "  UI    : $(UI_URL)"
	@echo ""
	@echo "Open two terminals and run:"
	@echo "  Terminal 1:  make dev-api"
	@echo "  Terminal 2:  make dev-ui"

dev-api:
	@echo ">> Starting FastAPI on $(API_URL)"
	@cd "$(APP)" && COSCIENTIST_DB_PATH="$(ROOT)/coscientist.db" "$(PY)" -m uvicorn app.main:app --reload --reload-dir app --host 0.0.0.0 --port 8008

dev-ui:
	@echo ">> Starting Vite UI on $(UI_URL)"
	@cd "$(FRONTEND)" && (command -v bun >/dev/null 2>&1 && bun run dev) || npm run dev

dev-mcp:
	@echo ">> Reference MCP server requires Python 3.12; running with system python3.12 if available."
	@cd "$(ENGINE)/mcp_server" && (command -v python3.12 >/dev/null 2>&1 && python3.12 -m pip install -e . && python3.12 -m uvicorn mcp_server.server:app --host 0.0.0.0 --port 8888) || (echo "python3.12 not found; MCP server skipped" && exit 0)

# ---------------------------------------------------------------------------
# Test / lint / typecheck / build
# ---------------------------------------------------------------------------
test:
	@cd "$(APP)" && COSCIENTIST_TEST_MODE=1 "$(PY)" -m pytest -q

lint:
	@cd "$(APP)" && "$(PY)" -m ruff check app/ tests/ || true

typecheck:
	@cd "$(APP)" && "$(PY)" -m mypy app/ || true

build:
	@cd "$(FRONTEND)" && (command -v bun >/dev/null 2>&1 && bun run build) || npm run build

clean:
	rm -rf "$(VENV)" "$(FRONTEND)/dist" "$(FRONTEND)/node_modules" "$(APP)"/.coscientist_cache "$(APP)"/cache

reset-db:
	rm -f "$(ROOT)/coscientist.db"
	@echo ">> Removed $(ROOT)/coscientist.db"
