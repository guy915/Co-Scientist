.PHONY: help setup dev dev-api dev-ui dev-all dev-mcp preflight ensure-deps open-when-ready test test-app test-engine test-all lint typecheck build clean stop reset-db

ROOT := $(shell pwd)
ENGINE := $(ROOT)/engine
APP    := $(ROOT)/app
FRONTEND := $(APP)/frontend
VENV  := $(ROOT)/.venv
PY    := $(VENV)/bin/python
PIP   := $(VENV)/bin/pip
# The reference MCP server pins Python 3.12, and Homebrew pythons are
# PEP 668 externally-managed, so it gets its own venv.
MCP_VENV := $(ROOT)/.venv-mcp

# Default URLs printed by `make dev`
API_URL := http://localhost:8008
UI_URL  := http://localhost:5173
DOCS_URL := http://localhost:8008/docs

help:
	@echo "Co-Scientist — root commands"
	@echo "  make setup        Create .venv, install engine (editable) + app (editable), install frontend"
	@echo "  make dev          One command: install missing deps, free ports, run MCP + API + UI, open browser"
	@echo "  make stop         Stop anything listening on the dev ports (8008/5173/8888)"
	@echo "  make dev-api      Run FastAPI dev server   ($(API_URL))"
	@echo "  make dev-ui       Run Vite dev server      ($(UI_URL))"
	@echo "  make dev-mcp      Run reference MCP server (optional, needs Python 3.12)"
	@echo "  make test         Run viewer backend pytest suite"
	@echo "  make test-app     Run viewer backend pytest suite"
	@echo "  make test-engine  Run engine pytest suite"
	@echo "  make test-all     Run backend pytest suites (engine + app)"
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
	@# Skip the PyPI co-scientist-engine pin (we have it editable already from $(ENGINE))
	@$(PIP) install -e "$(APP)" --no-deps
	@$(PIP) install fastapi "uvicorn[standard]" python-dotenv pydantic pydantic-settings httpx
	@$(PIP) install pytest pytest-asyncio ruff mypy
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
# `make dev` is the single entry point: it installs anything missing, frees
# the dev ports, starts MCP + API + UI together, and opens the app in the
# browser once both the API and the UI answer. Ctrl-C stops everything.
dev: preflight
	@echo ""
	@echo "Co-Scientist — dev URLs"
	@echo "  API   : $(API_URL)"
	@echo "  Docs  : $(DOCS_URL)"
	@echo "  UI    : $(UI_URL)"
	@echo ""
	@$(MAKE) dev-all

preflight:
	@$(MAKE) ensure-deps
	@$(MAKE) stop

ensure-deps:
	@test -f "$(ROOT)/.env" || { echo ">> No .env found — copying .env.example"; cp "$(ROOT)/.env.example" "$(ROOT)/.env"; }
	@if ! { test -x "$(PY)" && "$(PY)" -c "import uvicorn, fastapi, pydantic_settings, co_scientist" >/dev/null 2>&1; }; then \
		echo ">> Backend deps missing or broken — running setup"; \
		$(MAKE) setup; \
	elif [ ! -d "$(FRONTEND)/node_modules" ]; then \
		echo ">> Frontend deps missing — installing"; \
		cd "$(FRONTEND)" && { command -v bun >/dev/null 2>&1 && bun install; } || npm install --no-audit --no-fund; \
	fi

dev-all:
	@bash -c "trap 'kill 0' INT TERM EXIT; \
		($(MAKE) dev-mcp 2>&1 | sed 's/^/[mcp] /') & \
		($(MAKE) dev-api 2>&1 | sed 's/^/[api] /') & \
		($(MAKE) dev-ui 2>&1 | sed 's/^/[ui]  /') & \
		($(MAKE) open-when-ready 2>&1 | sed 's/^/[web] /') & \
		wait"

open-when-ready:
	@i=0; \
	until curl -sf "$(API_URL)/health" >/dev/null 2>&1 && curl -sf "$(UI_URL)" >/dev/null 2>&1; do \
		i=$$((i+1)); \
		if [ $$i -ge 240 ]; then \
			echo ">> Timed out waiting for the app — open $(UI_URL) manually once it is up"; \
			exit 0; \
		fi; \
		sleep 0.5; \
	done; \
	echo ">> App is up — opening $(UI_URL)"; \
	open "$(UI_URL)" 2>/dev/null || xdg-open "$(UI_URL)" 2>/dev/null || echo ">> Open $(UI_URL) in your browser"

stop:
	@echo ">> Stopping Co-Scientist dev servers (ports 8008/5173/8888)"
	@pkill -f "uvicorn app.main:app" 2>/dev/null || true
	@pkill -f "uvicorn mcp_server.server:app" 2>/dev/null || true
	@# Catch-all: kill whatever still listens on the dev ports. uvicorn --reload
	@# and vite run under a supervising parent that respawns the listener, so
	@# take out the parent too when it is a python/node/bun process.
	@for port in 8008 5173 8888; do \
		for pid in $$(lsof -ti tcp:$$port -sTCP:LISTEN 2>/dev/null); do \
			ppid=$$(ps -o ppid= -p $$pid 2>/dev/null | tr -d ' '); \
			pcomm=$$(ps -o comm= -p $$ppid 2>/dev/null); \
			case "$$pcomm" in \
				*python*|*Python*|*node*|*bun*) kill $$ppid 2>/dev/null || true;; \
			esac; \
			kill $$pid 2>/dev/null || true; \
		done; \
	done
	@n=0; while [ $$n -lt 10 ]; do \
		busy=$$( { lsof -ti tcp:8008 -sTCP:LISTEN; lsof -ti tcp:5173 -sTCP:LISTEN; lsof -ti tcp:8888 -sTCP:LISTEN; } 2>/dev/null | head -1 ); \
		[ -z "$$busy" ] && break; \
		sleep 0.3; n=$$((n+1)); \
	done; \
	{ lsof -ti tcp:8008 -sTCP:LISTEN; lsof -ti tcp:5173 -sTCP:LISTEN; lsof -ti tcp:8888 -sTCP:LISTEN; } 2>/dev/null | xargs kill -9 2>/dev/null || true
	@echo ">> Dev ports are free"

dev-api:
	@echo ">> Starting FastAPI on $(API_URL)"
	@cd "$(APP)" && COSCIENTIST_DB_PATH="$(ROOT)/coscientist.db" "$(PY)" -m uvicorn app.main:app --reload --reload-dir app --host 0.0.0.0 --port 8008

dev-ui:
	@echo ">> Starting Vite UI on $(UI_URL)"
	@cd "$(FRONTEND)" && (command -v bun >/dev/null 2>&1 && bun run dev) || npm run dev

dev-mcp:
	@# Single shell block on purpose: each make recipe line runs in its own
	@# shell, so an `exit 0` skip on one line would not stop the next one.
	@# The server runs from $(ENGINE) so the mcp_server package resolves as a
	@# directory package (the editable install's import map is empty).
	@if ! command -v python3.12 >/dev/null 2>&1; then \
		echo ">> python3.12 not found; MCP server skipped (literature tools fall back to LLM-only)"; \
		exit 0; \
	fi; \
	if ! test -x "$(MCP_VENV)/bin/python"; then \
		echo ">> Creating MCP venv at $(MCP_VENV) (Python 3.12)"; \
		python3.12 -m venv "$(MCP_VENV)" || { echo ">> Could not create MCP venv; skipping MCP server"; exit 0; }; \
	fi; \
	if ! "$(MCP_VENV)/bin/python" -c "import fastmcp, uvicorn" >/dev/null 2>&1; then \
		echo ">> Installing reference MCP server (first run / when deps change)"; \
		"$(MCP_VENV)/bin/python" -m pip install -q --upgrade pip >/dev/null 2>&1; \
		"$(MCP_VENV)/bin/python" -m pip install -q -e "$(ENGINE)/mcp_server" || { echo ">> MCP deps install failed (offline?); skipping MCP server"; exit 0; }; \
	fi; \
	echo ">> Starting reference MCP server on http://localhost:8888"; \
	cd "$(ENGINE)" && "$(MCP_VENV)/bin/python" -m uvicorn mcp_server.server:app --host 0.0.0.0 --port 8888

# ---------------------------------------------------------------------------
# Test / lint / typecheck / build
# ---------------------------------------------------------------------------
test:
	@$(MAKE) test-app

test-app:
	@cd "$(APP)" && COSCIENTIST_TEST_MODE=1 "$(PY)" -m pytest -q

test-engine:
	@cd "$(ENGINE)" && "$(PY)" -m pytest -q

test-all:
	@$(MAKE) test-engine
	@$(MAKE) test-app

lint:
	@cd "$(APP)" && "$(PY)" -m ruff check app tests
	@cd "$(ENGINE)" && "$(PY)" -m ruff check .

typecheck:
	@cd "$(APP)" && "$(PY)" -m mypy app/ || true

build:
	@cd "$(FRONTEND)" && (command -v bun >/dev/null 2>&1 && bun run build) || npm run build

clean:
	rm -rf "$(VENV)" "$(MCP_VENV)" "$(FRONTEND)/dist" "$(FRONTEND)/node_modules" "$(APP)"/.coscientist_cache "$(APP)"/cache

reset-db:
	rm -f "$(ROOT)/coscientist.db"
	@echo ">> Removed $(ROOT)/coscientist.db"
