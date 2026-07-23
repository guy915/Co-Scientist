"""FastAPI application main module."""

import asyncio
import logging
import os
import sqlite3
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Load .env file before importing settings
# pydantic-settings reads env vars at Settings() construction time (module
# import below), so .env must be loaded into os.environ before that import.
load_dotenv()

from app import engine_adapter, store
from app.auth import (
    Principal,
    auth_required,
    principal_for_request,
)
from app.auth import (
    router as auth_router,
)
from app.config import settings

# Re-exports keep the diagnostics HTTP surface importable from app.main,
# where it lived before moving to app.diagnostics_api.
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
from app.feedback import router as feedback_router
from app.interviews import router as interviews_router
from app.logging_setup import (
    configure_log_capture,
    configure_logging,
    level_to_number,
    shutdown_log_capture,
)
from app.logs_api import router as logs_router
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
_app_log_level = logging.DEBUG if settings.debug else logging.INFO
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


def _reclaim_disk_space() -> None:
    """Prune the checkpoint history no run could resume from.

    Only the newest checkpoint per run is ever loaded, so the rest is
    unreadable state that nonetheless filled the production volume until
    every write failed. Runs remain resumable: each keeps its newest.

    Deliberately does not VACUUM. Reclaiming the freed pages would shrink
    the file, but VACUUM needs exclusive access and SQLite makes a writer
    waiting for it block every other writer behind it -- and this process
    can never grant it, because the log-capture thread writes a row for
    every record the app emits. The VACUUM waits for a quiet moment that
    never arrives, and while it waits nothing else can write. Production
    wedged that way from both sides of the lifespan: an idle database, no
    writes for minutes, and every run creation failing with "database is
    locked". Pruning reclaims what actually grows without bound, commits in
    small batches, and never blocks a reader; the file keeps its high-water
    mark, which a 5 GB volume holding a 53 MB database can afford.

    Never fatal. This is opportunistic housekeeping, and the disk-full state
    it exists to relieve is exactly the state in which a DELETE cannot get
    its journal written -- so the first deploy carrying this sweep crashed on
    boot against the very database it was meant to reclaim. Serving with a
    bloated table beats not serving at all.
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
    """Install the offline router, log engine config, validate tools_config.

    The offline LLM router is installed unconditionally: it is a harmless
    passthrough for real models -- only ``offline/``-prefixed calls are
    answered locally -- so no offline traffic flows until a run requests
    the offline backend. ``select_provider()`` always returns "engine" now
    (or raises if the engine is not importable) -- there is no mock
    fallback, logged once here. Validation fails loudly if a configured
    tools_config path is unreadable rather than silently running the
    engine's default tools (the historical bug: the setting was logged but
    never forwarded to the generator, so a bad path went unnoticed); the
    generator is built per run, so this is checked here at startup, once.
    """
    from co_scientist.offline_llm import install_offline_router

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
    """Reconcile runs left non-terminal by a previous process, and log it.

    A fresh process has no workflow tasks running, so anything still
    queued/running was interrupted by a crash or restart and would
    otherwise be stuck forever.
    """
    reconciled = store.reconcile_interrupted_runs()
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
    """Relaunch every run left with a resumable checkpoint.

    Auto-resume launcher: relaunches each resumable run from its last
    checkpoint so an interrupted run finishes rather than staying stuck.
    """
    if not resumable:
        return
    from app.runs import resume_interrupted_runs

    await resume_interrupted_runs(resumable)


def _launch_embedded_recovery_workers(
    recovery_workers: list[asyncio.Task[None]],
) -> None:
    """Start one recovery worker-pool task per run with an active engine task.

    A per-run recovery cohort waits out any unexpired lease and then
    resumes the same durable queue. Scientific effects remain exactly-once
    because every claim is lease- and checkpoint-gated. It runs on a
    thread because the cohort's SQLite writes and state serialization are
    synchronous: on the event loop they starve request handling, which is
    how a boot with runs to recover stopped answering its healthcheck.
    """
    if os.getenv("COSCIENTIST_EMBEDDED_WORKER", "1") != "1":
        return
    from app import task_worker

    for run_id in store.list_active_engine_task_run_ids():
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
    """Cancel and await the recovery task and its embedded worker tasks."""
    recovery.cancel()
    await asyncio.gather(recovery, return_exceptions=True)
    for worker in recovery_workers:
        worker.cancel()
    if recovery_workers:
        await asyncio.gather(*recovery_workers, return_exceptions=True)


def _start_recovery_task(
    reconciled: dict[str, list[str]],
) -> tuple[asyncio.Task[None], list[asyncio.Task[None]]]:
    """Fire off the recovery task, off the startup critical path.

    Returns the task itself alongside the (initially empty, later
    populated) list of embedded recovery-worker tasks it launches, so the
    caller can cancel and await both at shutdown.
    """
    recovery_workers: list[asyncio.Task[None]] = []

    async def _recover_runs() -> None:
        """Relaunch interrupted runs, off the startup critical path.

        Restarting a run means executing it, so awaiting this before the
        hook yields put provider calls ahead of binding a port. Production
        deploys failed their five-minute healthcheck exactly that way, and
        because a failed healthcheck kills the container mid-run, each
        attempt left another interrupted run for the next boot to resume --
        a spiral in which runs only ever advanced during the doomed startup
        window. Recovery is not a precondition for serving, so it runs
        alongside it.
        """
        await _resume_checkpointed_runs(reconciled["resumable"])
        _launch_embedded_recovery_workers(recovery_workers)

    recovery = asyncio.create_task(_recover_runs())
    return recovery, recovery_workers


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
)

# CORS middleware
# ALLOWED_ORIGINS is a comma-separated allowlist (e.g. the production
# frontend origin); unset falls back to "*" for local/dev use. In practice
# browsers ignore credentialed requests against a literal "*" origin, so
# ALLOWED_ORIGINS should be set explicitly wherever cookies/auth matter.
_allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "")
_allowed_origins = (
    [o.strip() for o in _allowed_origins_env.split(",") if o.strip()]
    if _allowed_origins_env
    else ["*"]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    middleware itself.
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
    if client_id == run.client_id:
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
    principal = principal_for_request(request)
    auth_response = _auth_gate_response(request, principal, public_api)
    if auth_response is not None:
        return auth_response
    ownership_response = _run_ownership_response(request, principal)
    if ownership_response is not None:
        return ownership_response
    return cast(Response, await call_next(request))


# Mount the new run-lifecycle router (durable, persisted, SSE).
app.include_router(runs_router)
app.include_router(interviews_router)
app.include_router(shares_router)
app.include_router(feedback_router)
app.include_router(auth_router)
app.include_router(logs_router)
# Diagnostics endpoints (/, /health, /config, /status).
app.include_router(diagnostics_api_router)


if __name__ == "__main__":
    # Direct `python -m app.main` entry point; `make dev` instead invokes
    # uvicorn's own CLI directly against app.main:app, bypassing this block.
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
