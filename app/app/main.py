from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import JSONResponse

import app.engine_adapter as engine_adapter
from app import API_VERSION
from app.account_export import router as account_export_router
from app.auth import Principal, auth_required, principal_for_request
from app.auth import router as auth_router
from app.byok_models import router as byok_models_router
from app.config import settings
from app.diagnostics_api import router as diagnostics_api_router
from app.documents import router as documents_router
from app.feedback_api import router as feedback_router
from app.free_usage import router as free_usage_router
from app.interviews import router as interviews_router
from app.logging_setup import (
    configure_log_capture,
    configure_logging,
    level_to_number,
    shutdown_log_capture,
)
from app.logs_api import router as logs_router
from app.operator_access import is_operator
from app.runs import router as runs_router
from app.seed import seed_demo_runs
from app.shares import router as shares_router
from app.store import checkpoints as store
from app.store import db, runs, tasks
from app.store import runs_views as views
from app.store.models import DEMO_CLIENT_ID

logger = logging.getLogger(__name__)


def _reclaim_disk_space() -> None:
    """Keep the latest resume checkpoint and prune opportunistically; never
    VACUUM from the serving process or fail startup on housekeeping.
    """
    try:
        superseded = store.prune_superseded_checkpoints()
    except sqlite3.Error:
        logger.warning("Could not prune superseded checkpoints", exc_info=True)
    else:
        if superseded:
            logger.info(
                "Pruned %s superseded checkpoint(s) no run could resume from",
                superseded,
            )


def _startup_engine_setup() -> None:
    """The offline router is a harmless passthrough for real models;
    configured unreadable tools fail loudly at startup.
    """
    from co_scientist.offline.llm import install_offline_router

    install_offline_router()
    logger.info("Model: %s", settings.model_name)
    if settings.tools_config:
        logger.info("Tools config: %s", settings.tools_config)
    else:
        logger.info("Tools config: not set (generator defaults)")
    provider = engine_adapter.select_provider()
    logger.info("Workflow provider: %s", provider)
    engine_adapter.validate_tools_config(settings.tools_config)


def _reconcile_and_log_interrupted_runs() -> dict[str, list[str]]:
    reconciled = views.reconcile_interrupted_runs()
    if reconciled["failed"]:
        logger.info(
            "Reconciled %s interrupted run(s) to failed: %s",
            len(reconciled["failed"]),
            ", ".join(r[:8] for r in reconciled["failed"]),
        )
    if reconciled["resumable"]:
        logger.info(
            "Found %s resumable interrupted run(s) with a checkpoint: %s",
            len(reconciled["resumable"]),
            ", ".join(r[:8] for r in reconciled["resumable"]),
        )
    return reconciled


async def _resume_checkpointed_runs(resumable: list[str]) -> None:
    if not resumable:
        return
    from app.runs import resume_interrupted_runs

    await resume_interrupted_runs(resumable)


def _launch_embedded_recovery_workers(
    recovery_workers: list[asyncio.Task[None]],
) -> None:
    """Recover off the API loop so synchronous checkpoint writes and
    serialization cannot starve request handling or lease renewal.
    """
    if not settings.coscientist_embedded_worker:
        return
    import app.task_worker as task_worker

    for run_id in tasks.list_active_engine_task_run_ids():
        recovery_workers.append(
            asyncio.create_task(
                asyncio.to_thread(
                    task_worker.run_run_worker_pool_sync,
                    run_id,
                    f"embedded-recovery:{os.getpid()}",
                )
            )
        )


async def _shutdown_recovery(
    recovery: asyncio.Task[None],
    recovery_workers: list[asyncio.Task[None]],
) -> None:
    recovery.cancel()
    await asyncio.gather(recovery, return_exceptions=True)
    for worker in recovery_workers:
        worker.cancel()
    if recovery_workers:
        await asyncio.gather(*recovery_workers, return_exceptions=True)


def _start_recovery_task(
    reconciled: dict[str, list[str]],
) -> tuple[asyncio.Task[None], list[asyncio.Task[None]]]:
    """Recovery is independent of binding a port; startup must not wait for
    provider work.
    """
    recovery_workers: list[asyncio.Task[None]] = []

    async def _recover_runs() -> None:
        """Recovery runs beside serving; awaiting provider work before
        binding creates a healthcheck/restart spiral.
        """
        await _resume_checkpointed_runs(reconciled["resumable"])
        _launch_embedded_recovery_workers(recovery_workers)

    recovery = asyncio.create_task(_recover_runs())
    return recovery, recovery_workers


# Load environment before constructing Settings at import time.
load_dotenv()


configure_logging(settings.log_format, level=logging.INFO)


def _install_log_capture() -> None:
    if not settings.log_capture_enabled:
        return
    level = level_to_number(settings.log_capture_level) or logging.INFO
    configure_log_capture(level=level, max_rows=settings.log_capture_max_rows)


# Import-time capture includes setup diagnostics; lifespan reinstalls and drains
# it across reloads.
_install_log_capture()

coscientist_logger = logging.getLogger("co_scientist")
_app_log_level = logging.DEBUG if settings.coscientist_debug else logging.INFO
logger.setLevel(_app_log_level)
coscientist_logger.setLevel(_app_log_level)

# Bridge Settings back to environment because LiteLLM and the engine read
# provider variables directly.
if settings.gemini_api_key:
    os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
if settings.coscientist_cache_enabled:
    os.environ["COSCIENTIST_CACHE_ENABLED"] = "true"
if settings.coscientist_cache_dir:
    os.environ["COSCIENTIST_CACHE_DIR"] = settings.coscientist_cache_dir

# The engine MCP client reads its URL from environment rather than a Settings
# parameter.
if settings.mcp_server_url:
    os.environ["MCP_SERVER_URL"] = settings.mcp_server_url
    logger.info("mcp_server_url configured: %s", settings.mcp_server_url)
else:
    logger.info("mcp_server_url not set - literature review will be disabled")


@asynccontextmanager
async def lifespan(
    app: FastAPI,
) -> AsyncGenerator[None, None]:
    # A prior lifespan cycle may have drained capture, so startup reinstalls it.
    _install_log_capture()
    logger.info("Starting Co-Scientist server...")
    _startup_engine_setup()

    # Prune cheaply before readers arrive; never add serving-process VACUUM or
    # truncating checkpoint work.
    _reclaim_disk_space()

    reconciled = _reconcile_and_log_interrupted_runs()
    recovery, recovery_workers = _start_recovery_task(reconciled)

    await seed_demo_runs()

    try:
        yield
    finally:
        await _shutdown_recovery(recovery, recovery_workers)
        logger.info("Shutting down Co-Scientist server...")
        # Drain queued logging before the shutdown WAL merge.
        shutdown_log_capture()
        db.checkpoint_wal()


app = FastAPI(
    title="Co-Scientist API",
    description="FastAPI server for AI hypothesis generation",
    version=API_VERSION,
    lifespan=lifespan,
    # Built-in docs bypass operator policy; replace them with gated routes
    # rather than exposing the full schema publicly.
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def _resolve_cors_config(env_value: str) -> tuple[list[str], bool]:
    """Credentialed CORS requires an explicit origin allowlist; wildcard
    credentials would reflect arbitrary origins.
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
    if (
        auth_required()
        and request.scope["path"].startswith("/api/")
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
    """Empty subjects own nothing, including legacy empty-owner rows; non-
    owned run existence remains hidden.
    """
    parts = request.scope["path"].strip("/").split("/")
    if len(parts) < 3 or parts[:2] != ["api", "runs"]:
        return None
    run_id = parts[2]
    if run_id == "demo":
        return None
    run = runs.get_run(run_id)
    if run is None:
        return None
    if run.client_id == DEMO_CLIENT_ID:
        if request.method not in {"GET", "HEAD"} and not (
            request.method == "POST" and parts[3:] == ["example-chat"]
        ):
            return JSONResponse(
                {"detail": "shared examples are read-only"}, status_code=403
            )
        return None
    client_id = principal.subject if principal else ""
    if client_id and client_id == run.client_id:
        return None
    return JSONResponse({"detail": "run not found"}, status_code=404)


@app.middleware("http")
async def enforce_run_ownership(request: Request, call_next: Any) -> Response:
    # CORS preflights contain header names only; authorize the real request
    # after the middleware handles them.
    if request.method == "OPTIONS":
        return cast(Response, await call_next(request))
    # Authorize routed ASGI paths, not URLs reconstructed from caller-controlled
    # Host headers.
    path = request.scope["path"]
    public_api = (
        path.startswith("/api/auth/")
        or path.startswith("/api/shared/")
        or (path == "/api/feedback/admin" and request.method == "GET")
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


# Register CORS outside ownership so denied responses still carry the
# appropriate CORS headers.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(runs_router)
app.include_router(interviews_router)
app.include_router(documents_router)
app.include_router(shares_router)
app.include_router(account_export_router)
app.include_router(free_usage_router)
app.include_router(byok_models_router)
app.include_router(auth_router)
app.include_router(logs_router)
app.include_router(feedback_router)
app.include_router(diagnostics_api_router)


def _not_found_for_non_operator(request: Request) -> Response | None:
    """A 404 hides the existence of operator documentation rather than
    advertising it through an authorization challenge.
    """
    if is_operator(request):
        return None
    return JSONResponse({"detail": "not found"}, status_code=404)


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
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.coscientist_debug,
    )

__all__ = [
    "_reclaim_disk_space",
    "_reconcile_and_log_interrupted_runs",
    "_shutdown_recovery",
    "_start_recovery_task",
    "_startup_engine_setup",
]
