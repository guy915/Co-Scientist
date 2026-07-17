"""FastAPI application main module."""

import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Load .env file before importing settings
# pydantic-settings reads env vars at Settings() construction time (module
# import below), so .env must be loaded into os.environ before that import.
load_dotenv()

from app import diagnostics, engine_adapter, store
from app.auth import (
    auth_required,
    principal_for_request,
)
from app.auth import (
    router as auth_router,
)
from app.config import settings
from app.interviews import router as interviews_router
from app.logging_setup import configure_logging
from app.run_modes import (
    DEFAULT_RUN_TIER,
    RUN_TIER_DEFAULTS,
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


@asynccontextmanager
async def lifespan(
    app: FastAPI,
) -> AsyncGenerator[None, None]:
    """Manages FastAPI application startup and shutdown."""
    # Startup
    logger.info("Starting Co-Scientist server...")
    logger.info("Model: %s", settings.model_name)
    if settings.tools_config:
        logger.info("Tools config: %s", settings.tools_config)
    else:
        logger.info("Tools config: not set (generator defaults)")

    # Logged once at startup so ops can tell at a glance whether this process
    # will run the real engine or fall back to the deterministic mock.
    provider = engine_adapter.select_provider()
    logger.info("Workflow provider: %s", provider)

    # Fail loudly if a configured tools_config path is unreadable rather than
    # silently running the engine's default tools (the historical bug: the
    # setting was logged but never forwarded to the generator, so a bad path
    # went unnoticed). Gated to the real engine: the mock never uses tools, so
    # a stale env var must not break mock/dev boot. The generator is built per
    # run, so this is validated here at startup, once.
    if provider == "engine":
        engine_adapter.validate_tools_config(settings.tools_config)

    # Reconcile runs left non-terminal by a previous process: a fresh process
    # has no workflow tasks running, so anything still queued/running was
    # interrupted by a crash or restart and would otherwise be stuck forever.
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
        # Auto-resume launcher: relaunch each resumable run from its last
        # checkpoint so an interrupted run finishes rather than staying stuck.
        from app.runs import resume_interrupted_runs

        await resume_interrupted_runs(reconciled["resumable"])

    recovery_workers: list[asyncio.Task[None]] = []
    if os.getenv("COSCIENTIST_EMBEDDED_WORKER", "1") == "1":
        from app import task_worker

        for run_id in store.list_active_engine_task_run_ids():
            # A per-run recovery cohort waits out any unexpired lease and
            # then resumes the same durable queue. Scientific effects remain
            # exactly-once because every claim is lease- and checkpoint-gated.
            recovery_workers.append(
                asyncio.create_task(
                    task_worker.run_run_worker_pool(
                        run_id,
                        f"embedded-recovery:{os.getpid()}",
                    )
                )
            )

    # No-op after the first successful startup; see seed.py for the
    # per-goal skip/re-seed logic.
    await seed_demo_runs()

    try:
        yield
    finally:
        for worker in recovery_workers:
            worker.cancel()
        if recovery_workers:
            await asyncio.gather(*recovery_workers, return_exceptions=True)
        # Shutdown
        logger.info("Shutting down Co-Scientist server...")
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
    if (
        auth_required()
        and path.startswith("/api/")
        and not public_api
        and principal is None
    ):
        return JSONResponse(
            {"detail": "researcher access required"}, status_code=401
        )
    parts = request.url.path.strip("/").split("/")
    if len(parts) >= 3 and parts[:2] == ["api", "runs"]:
        run_id = parts[2]
        if run_id != "demo":
            run = store.get_run(run_id)
            if run is not None and run.client_id != store.DEMO_CLIENT_ID:
                client_id = principal.subject if principal else ""
                if client_id != run.client_id:
                    return JSONResponse(
                        {"detail": "run not found"}, status_code=404
                    )
    return cast(Response, await call_next(request))


# Mount the new run-lifecycle router (durable, persisted, SSE).
app.include_router(runs_router)
app.include_router(interviews_router)
app.include_router(shares_router)
app.include_router(auth_router)


class HealthCheckResult(BaseModel):
    """Outcome of one health check."""

    ok: bool = Field(..., description="whether the check passed")
    detail: str | None = Field(
        None, description="failure detail when the check did not pass"
    )


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(
        ..., description="derived health: healthy | degraded | unhealthy"
    )
    version: str
    model_name: str
    provider: str = Field(
        ..., description="active workflow provider: 'mock' | 'engine'"
    )
    checks: dict[str, HealthCheckResult] = Field(
        ..., description="individual check outcomes: store, engine"
    )


class ConfigResponse(BaseModel):
    """Configuration defaults response."""

    max_iterations: int
    initial_hypotheses_count: int
    evolution_max_count: int


class ProbeStatus(BaseModel):
    """Detailed outcome of one availability probe."""

    state: str = Field(
        ...,
        description=(
            "probe outcome: 'up' | 'down' (definitive answers) | 'error' "
            "(the probe itself failed; availability unknown)"
        ),
    )
    error: str | None = Field(
        None, description="probe failure detail when state is 'error'"
    )


class Connector(BaseModel):
    """One data-source connector shown in the composer's connectors menu."""

    id: str = Field(..., description="stable connector id")
    display: str = Field(..., description="human-readable connector name")


class SystemStatusResponse(BaseModel):
    """System availability status response."""

    mcp_available: bool = Field(
        ..., description="whether mcp server is available"
    )
    pubmed_available: bool = Field(
        ..., description="whether pubmed api is available"
    )
    literature_review_available: bool = Field(
        ...,
        description=(
            "whether literature review is available (requires both mcp "
            "and pubmed)"
        ),
    )
    probes: dict[str, ProbeStatus] = Field(
        ...,
        description=(
            "per-probe detail (mcp, pubmed), distinguishing a served "
            "'down' from a probe error"
        ),
    )
    mcp_server_url: str = Field(..., description="configured mcp server url")
    provider: str = Field(
        "mock", description="active workflow provider: 'mock' | 'engine'"
    )
    mock_mode: bool = Field(
        False, description="true when running deterministic mock workflow"
    )
    has_provider_key: bool = Field(
        False, description="any LLM provider key is set"
    )
    engine_importable: bool = Field(
        False, description="co_scientist package is importable"
    )
    model_name: str = Field("", description="configured worker model id")
    supervisor_model_name: str = Field(
        "", description="effective supervisor/meta-review model id"
    )
    tools_config: str | None = Field(
        None, description="configured tools YAML path/URL, or null for defaults"
    )
    tools_config_valid: bool = Field(
        True,
        description=(
            "false only when a configured local tools_config path is not "
            "readable"
        ),
    )
    enabled_tools: list[str] | None = Field(
        None,
        description=(
            "enabled tool ids for a readable local tools_config, else null "
            "(unset/URL/engine-default)"
        ),
    )
    connectors: list[Connector] = Field(
        default_factory=list,
        description=(
            "user-facing data-source connectors derived from availability and "
            "the configured tools YAML, for the composer's connectors menu"
        ),
    )


@app.get("/", tags=["root"])
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {
        "message": "Co-Scientist API",
        "version": API_VERSION,
        "docs": "/docs",
    }


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health(response: Response) -> HealthResponse:
    """Health check: store reachability, engine importability, derived status.

    Every check is local and fast (a SQLite round-trip and an import
    lookup) because ``make start`` polls this endpoint as its readiness
    gate. Responds 503 when unhealthy so ``curl -f``-style probes fail
    until the store is reachable.
    """
    store_check = diagnostics.check_store()
    engine_check = diagnostics.check_engine()
    status = diagnostics.derive_health_status(store_check, engine_check)
    if status == diagnostics.UNHEALTHY:
        response.status_code = 503
    return HealthResponse(
        status=status,
        version=API_VERSION,
        model_name=settings.model_name,
        provider=engine_adapter.select_provider(),
        checks={
            "store": HealthCheckResult(
                ok=store_check.ok, detail=store_check.detail
            ),
            "engine": HealthCheckResult(
                ok=engine_check.ok, detail=engine_check.detail
            ),
        },
    )


@app.get("/config", response_model=ConfigResponse, tags=["config"])
async def get_config() -> ConfigResponse:
    """Get default run configuration values (standard tier)."""
    defaults = RUN_TIER_DEFAULTS[DEFAULT_RUN_TIER]
    return ConfigResponse(
        max_iterations=defaults["max_iterations"],
        initial_hypotheses_count=defaults["initial_hypotheses_count"],
        evolution_max_count=defaults["evolution_max_count"],
    )


@app.get("/status", response_model=SystemStatusResponse, tags=["system"])
async def get_system_status() -> dict[str, Any]:
    """Checks system availability for literature review features.

    Returns availability status for mcp server and pubmed api, plus
    provider/mock-mode info from the engine adapter so the UI can render
    a "Mock Mode" banner. Probes run under a bounded timeout and are
    cached for a short TTL (see app/diagnostics.py); the ``probes`` field
    distinguishes a server that answered "down" from a probe that errored.
    """
    mcp, pubmed = await diagnostics.probe_literature_stack_cached()

    adapter_status = engine_adapter.system_status()

    # Both legs are required: the literature_review node needs the MCP server
    # up AND its PubMed-backed tools answering.
    literature_available = mcp.available and pubmed.available

    return {
        "mcp_available": mcp.available,
        "pubmed_available": pubmed.available,
        "literature_review_available": literature_available,
        "probes": {
            "mcp": {"state": mcp.state, "error": mcp.error},
            "pubmed": {"state": pubmed.state, "error": pubmed.error},
        },
        # User-facing data-source connectors for the composer menu, derived
        # from literature availability plus the configured tools YAML.
        "connectors": engine_adapter.connectors_report(
            literature_available=literature_available,
            enabled_tools=adapter_status.get("enabled_tools"),
        ),
        # provider/mock_mode/model_name/etc. from engine_adapter.system_status
        **adapter_status,
    }


if __name__ == "__main__":
    # Direct `python -m app.main` entry point; `make dev` instead invokes
    # uvicorn's own CLI directly against app.main:app, bypassing this block.
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
