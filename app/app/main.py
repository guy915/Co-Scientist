"""FastAPI application main module.

The startup/shutdown helper bodies the ``lifespan`` hook below calls
live in ``app.main_lifespan`` and are re-exported here, so
``main._launch_embedded_recovery_workers`` and friends keep resolving
for the test suite; ``lifespan`` itself stays in this module -- see its
own docstring and AGENTS.md's "Gotchas" section for why.
"""

import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import JSONResponse

# Load .env file before importing settings
# pydantic-settings reads env vars at Settings() construction time (module
# import below), so .env must be loaded into os.environ before that import.
load_dotenv()

from app import store
from app.account_export import router as account_export_router
from app.auth import (
    Principal,
    auth_required,
    principal_for_request,
)
from app.auth import (
    router as auth_router,
)
from app.byok_models import router as byok_models_router
from app.config import settings
from app.diagnostics_api import (
    ConfigResponse as ConfigResponse,
)
from app.diagnostics_api import (
    Connector as Connector,
)
from app.diagnostics_api import (
    HealthCheckResult as HealthCheckResult,
)
from app.diagnostics_api import (
    HealthResponse as HealthResponse,
)
from app.diagnostics_api import (
    ProbeStatus as ProbeStatus,
)
from app.diagnostics_api import (
    SystemStatusResponse as SystemStatusResponse,
)

# Re-exports keep the diagnostics HTTP surface importable from app.main,
# where it lived before moving to app.diagnostics_api.
from app.diagnostics_api import _is_operator
from app.diagnostics_api import (
    get_config as get_config,
)
from app.diagnostics_api import (
    get_system_status as get_system_status,
)
from app.diagnostics_api import (
    health as health,
)
from app.diagnostics_api import (
    root as root,
)
from app.diagnostics_api import (
    router as diagnostics_api_router,
)
from app.documents import router as documents_router
from app.free_usage import router as free_usage_router
from app.interviews import router as interviews_router
from app.logging_setup import (
    configure_log_capture,
    configure_logging,
    level_to_number,
    shutdown_log_capture,
)
from app.logs_api import router as logs_router
from app.main_lifespan import (
    _launch_embedded_recovery_workers as _launch_embedded_recovery_workers,
)
from app.main_lifespan import (
    _reclaim_disk_space as _reclaim_disk_space,
)
from app.main_lifespan import (
    _reconcile_and_log_interrupted_runs as _reconcile_and_log_interrupted_runs,
)
from app.main_lifespan import (
    _resume_checkpointed_runs as _resume_checkpointed_runs,
)
from app.main_lifespan import (
    _shutdown_recovery as _shutdown_recovery,
)
from app.main_lifespan import (
    _start_recovery_task as _start_recovery_task,
)
from app.main_lifespan import (
    _startup_engine_setup as _startup_engine_setup,
)
from app.runs import (
    router as runs_router,
)
from app.seed import seed_demo_runs
from app.shares import router as shares_router
from app.version import API_VERSION

# Configure logging: one stdout handler (text by default, JSON via
# LOG_FORMAT=json) with run-id tagging; see app/logging_setup.py. Root
# stays at INFO to suppress DEBUG logs from dependencies (httpx, etc.).
configure_logging(settings.log_format, level=logging.INFO)


def _install_log_capture() -> None:
    """Start persistent log capture per settings; no-op when disabled."""
    if not settings.log_capture_enabled:
        return
    level = level_to_number(settings.log_capture_level) or logging.INFO
    configure_log_capture(level=level, max_rows=settings.log_capture_max_rows)


# Installed at import time so records emitted before the lifespan hook
# (provider selection, MCP configuration) are captured too; the lifespan
# re-installs on startup and drains on shutdown.
_install_log_capture()
# Set application loggers (viewer and co_scientist) to DEBUG if debug mode is
# enabled
logger = logging.getLogger(__name__)
coscientist_logger = logging.getLogger("co_scientist")
_app_log_level = logging.DEBUG if settings.coscientist_debug else logging.INFO
logger.setLevel(_app_log_level)
coscientist_logger.setLevel(_app_log_level)

# Set environment variables for the LLM engine
# LiteLLM uses provider-specific env vars (GEMINI_API_KEY, OPENAI_API_KEY, etc.)
# This bridges values that arrived via Settings/.env back into os.environ,
# since the engine and LiteLLM read the environment directly and know
# nothing about this app's pydantic-settings object.
if settings.gemini_api_key:
    os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
if settings.coscientist_cache_enabled:
    os.environ["COSCIENTIST_CACHE_ENABLED"] = "true"
if settings.coscientist_cache_dir:
    os.environ["COSCIENTIST_CACHE_DIR"] = settings.coscientist_cache_dir

# Set MCP server URL if available
# Same bridging rationale as above: the engine's MCP client reads
# MCP_SERVER_URL from the environment rather than accepting it as a param.
if settings.mcp_server_url:
    os.environ["MCP_SERVER_URL"] = settings.mcp_server_url
    logger.info("mcp_server_url configured: %s", settings.mcp_server_url)
else:
    logger.info("mcp_server_url not set - literature review will be disabled")


# The startup/shutdown helpers the lifespan hook below calls
# (_reclaim_disk_space, _startup_engine_setup,
# _reconcile_and_log_interrupted_runs, _resume_checkpointed_runs,
# _launch_embedded_recovery_workers, _shutdown_recovery,
# _start_recovery_task) live in app.main_lifespan, re-exported above.


@asynccontextmanager
async def lifespan(
    app: FastAPI,
) -> AsyncGenerator[None, None]:
    """Manages FastAPI application startup and shutdown."""
    # Startup. Re-install capture: a prior lifespan cycle (tests, reloads)
    # may have drained and stopped the import-time pipeline.
    _install_log_capture()
    logger.info("Starting Co-Scientist server...")
    _startup_engine_setup()

    # Deliberately inline, before a single request is served. VACUUM and a
    # truncating WAL checkpoint need exclusive access, and SQLite makes a
    # writer that is waiting for one block every other writer behind it. Run
    # alongside a serving process the sweep never gets its turn: a
    # long-lived reader (an SSE stream tailing a run) keeps it waiting
    # indefinitely while every write fails with "database is locked", which
    # is how this wedged production -- an idle database, no writes for
    # minutes, and every run creation returning 500. Startup is the one
    # moment the process is guaranteed no readers, and the sweep is cheap
    # enough to afford there: pruning and vacuuming a 575 MB database
    # measured under a second.
    _reclaim_disk_space()

    reconciled = _reconcile_and_log_interrupted_runs()
    recovery, recovery_workers = _start_recovery_task(reconciled)

    # No-op after the first successful startup; see seed.py for the
    # per-goal skip/re-seed logic.
    await seed_demo_runs()

    try:
        yield
    finally:
        await _shutdown_recovery(recovery, recovery_workers)
        # Shutdown
        logger.info("Shutting down Co-Scientist server...")
        # Drain queued log records into the store before the WAL merge below.
        shutdown_log_capture()
        # Merge the WAL into the main DB so a clean stop leaves no -wal sidecar.
        store.checkpoint_wal()


app = FastAPI(
    title="Co-Scientist API",
    description="FastAPI server for AI hypothesis generation",
    version=API_VERSION,
    lifespan=lifespan,
    # FastAPI's built-in /docs, /redoc, and /openapi.json are disabled here
    # and re-added below as operator-gated routes at the same paths: an
    # anonymous internet caller gets a live Swagger UI and the full OpenAPI
    # schema for free otherwise, which is a map of every endpoint and
    # request/response shape this deployment has -- useful to whoever is
    # running it, not to whoever finds it.
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def _resolve_cors_config(env_value: str) -> tuple[list[str], bool]:
    """Derive the CORS origin allowlist and credentials flag from the env.

    ``ALLOWED_ORIGINS`` is a comma-separated allowlist (e.g. the production
    frontend origin); unset falls back to a wildcard for local/dev use.

    The returned credentials flag tracks whether an explicit allowlist was
    given, rather than being unconditionally True. Nothing in this codebase
    sends a credentialed fetch (no cookies; identity travels as a plain
    Authorization or X-Client-ID header), so this is not a functional
    requirement -- it closes a real hole instead. Starlette's
    CORSMiddleware only sets a wildcard ``Access-Control-Allow-Origin`` when
    ``allow_credentials`` is False; with it unconditionally True (the
    previous behavior), the middleware reflects *any* requesting origin
    back as an explicit allow, because a wildcard origin cannot legally
    pair with credentials. Combined with the wildcard origin list and
    ``allow_headers=["*"]``, that meant every origin on the internet could
    already CORS-fetch this API and read the response -- an attacker's page
    just has to send whatever ``X-Client-ID`` it wants to read under
    compatibility auth, which is itself just a spoofable header. Tying
    credentials to an explicit origin list restores the wildcard's actual
    meaning (open, but never reflected as a credentialed peer) for
    deployments that have not set ``ALLOWED_ORIGINS``, while production --
    which does set it -- is unaffected.

    Args:
        env_value: The raw ``ALLOWED_ORIGINS`` environment value.

    Returns:
        The ``(allow_origins, allow_credentials)`` pair for
        ``CORSMiddleware``.
    """
    if not env_value:
        return ["*"], False
    origins = [o.strip() for o in env_value.split(",") if o.strip()]
    return origins, True


_allowed_origins, _allow_credentials = _resolve_cors_config(
    os.getenv("ALLOWED_ORIGINS", "")
)


def _auth_gate_response(
    request: Request, principal: Principal | None, public_api: bool
) -> Response | None:
    """Return a 401 response when auth is required but missing.

    Args:
        request: The incoming HTTP request.
        principal: The resolved principal, if any.
        public_api: Whether the path is one of the exempt public routes.

    Returns:
        A 401 JSONResponse, or None to let the request continue.
    """
    if (
        auth_required()
        and request.url.path.startswith("/api/")
        and not public_api
        and principal is None
    ):
        return JSONResponse(
            {"detail": "researcher access required"}, status_code=401
        )
    return None


def _run_ownership_response(
    request: Request, principal: Principal | None
) -> Response | None:
    """Return a 404 response when the request targets another's run.

    Non-owned runs are hidden as 404 rather than 403, and demo-owned runs
    are exempt, matching the ownership contract documented on the
    middleware itself. An empty subject (a compatibility caller sending no
    ``X-Client-ID`` header) never matches, even a run whose own
    ``client_id`` happens to be empty too (legacy data predating this
    guard, or ``app.auth.require_client_scope`` would have refused its
    creation) -- an identity-less caller owns nothing, the same rule
    ``require_client_scope`` enforces at creation time.
    """
    parts = request.url.path.strip("/").split("/")
    if len(parts) < 3 or parts[:2] != ["api", "runs"]:
        return None
    run_id = parts[2]
    if run_id == "demo":
        return None
    run = store.get_run(run_id)
    if run is None or run.client_id == store.DEMO_CLIENT_ID:
        return None
    client_id = principal.subject if principal else ""
    if client_id and client_id == run.client_id:
        return None
    return JSONResponse({"detail": "run not found"}, status_code=404)


@app.middleware("http")
async def enforce_run_ownership(request: Request, call_next: Any) -> Response:
    """Authenticate private API calls and hide runs from non-owners."""
    # CORS preflights carry the requested header names, not their values. Let
    # CORSMiddleware authorize them before applying ownership to the real call.
    if request.method == "OPTIONS":
        return cast(Response, await call_next(request))
    path = request.url.path
    public_api = path.startswith("/api/auth/") or path.startswith(
        "/api/shared/"
    )
    try:
        principal = principal_for_request(request)
    except HTTPException as exc:
        return JSONResponse(
            {"detail": exc.detail},
            status_code=exc.status_code,
            headers=exc.headers,
        )
    auth_response = _auth_gate_response(request, principal, public_api)
    if auth_response is not None:
        return auth_response
    ownership_response = _run_ownership_response(request, principal)
    if ownership_response is not None:
        return ownership_response
    return cast(Response, await call_next(request))


# Register CORS after ownership so it can add headers to auth and ownership
# denials as well as responses from the route handlers.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Mount the new run-lifecycle router (durable, persisted, SSE).
app.include_router(runs_router)
app.include_router(interviews_router)
app.include_router(documents_router)
app.include_router(shares_router)
app.include_router(account_export_router)
app.include_router(free_usage_router)
app.include_router(byok_models_router)
app.include_router(auth_router)
app.include_router(logs_router)
# Diagnostics endpoints (/, /health, /config, /status).
app.include_router(diagnostics_api_router)


def _not_found_for_non_operator(request: Request) -> Response | None:
    """Return a 404 for a docs route when the caller is not an operator.

    A 404 rather than a 401/403: an anonymous caller should not be able to
    distinguish "no docs here" from "docs exist but you may not see them",
    since the latter confirms this is a FastAPI service worth probing
    further.
    """
    if _is_operator(request):
        return None
    return JSONResponse({"detail": "not found"}, status_code=404)


# The three routes below re-add FastAPI's built-in docs UI/schema at their
# usual paths, gated to operator callers -- see `docs_url=None` etc. on the
# FastAPI() constructor above for why they are not the framework defaults.
@app.get("/docs", include_in_schema=False)
async def _operator_swagger_ui(request: Request) -> Response:
    """Swagger UI, visible only to an operator caller."""
    gate = _not_found_for_non_operator(request)
    if gate is not None:
        return gate
    return get_swagger_ui_html(
        openapi_url="/openapi.json", title=f"{app.title} - Swagger UI"
    )


@app.get("/redoc", include_in_schema=False)
async def _operator_redoc(request: Request) -> Response:
    """ReDoc UI, visible only to an operator caller."""
    gate = _not_found_for_non_operator(request)
    if gate is not None:
        return gate
    return get_redoc_html(
        openapi_url="/openapi.json", title=f"{app.title} - ReDoc"
    )


@app.get("/openapi.json", include_in_schema=False)
async def _operator_openapi_schema(request: Request) -> Response:
    """The full OpenAPI schema, visible only to an operator caller."""
    gate = _not_found_for_non_operator(request)
    if gate is not None:
        return gate
    return JSONResponse(app.openapi())


if __name__ == "__main__":
    # Direct `python -m app.main` entry point; `make dev` instead invokes
    # uvicorn's own CLI directly against app.main:app, bypassing this block.
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.coscientist_debug,
    )
