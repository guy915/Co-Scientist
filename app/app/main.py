"""FastAPI application main module."""

import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Load .env file before importing settings
# pydantic-settings reads env vars at Settings() construction time (module
# import below), so .env must be loaded into os.environ before that import.
load_dotenv()

from app import engine_adapter, store  # pylint: disable=wrong-import-position
from app.config import settings  # pylint: disable=wrong-import-position
from app.run_modes import (  # pylint: disable=wrong-import-position
    DEFAULT_RUN_TIER,
    RUN_TIER_DEFAULTS,
)
from app.runs import (
    router as runs_router,  # pylint: disable=wrong-import-position
)
from app.seed import seed_demo_runs  # pylint: disable=wrong-import-position

# Configure logging
# Set root logger to INFO to suppress DEBUG logs from dependencies (httpx, etc.)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
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
    app: FastAPI,  # pylint: disable=redefined-outer-name,unused-argument
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

    # Reconcile runs left non-terminal by a previous process: a fresh process
    # has no workflow tasks running, so anything still queued/running was
    # interrupted by a crash or restart and would otherwise be stuck forever.
    interrupted = store.reconcile_interrupted_runs()
    if interrupted:
        logger.info(
            "Reconciled %s interrupted run(s) to failed: %s",
            len(interrupted),
            ", ".join(r[:8] for r in interrupted),
        )

    # No-op after the first successful startup; see seed.py for the
    # per-goal skip/re-seed logic.
    await seed_demo_runs()

    yield

    # Shutdown
    logger.info("Shutting down Co-Scientist server...")
    # Merge the WAL into the main DB so a clean stop leaves no -wal sidecar.
    store.checkpoint_wal()


app = FastAPI(
    title="Co-Scientist API",
    description="FastAPI server for AI hypothesis generation",
    version="0.1.0",
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

# Mount the new run-lifecycle router (durable, persisted, SSE).
app.include_router(runs_router)


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str
    model_name: str


class ConfigResponse(BaseModel):
    """Configuration defaults response."""

    max_iterations: int
    initial_hypotheses_count: int
    evolution_max_count: int


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


@app.get("/", tags=["root"])
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {
        "message": "Co-Scientist API",
        "version": "0.1.0",
        "docs": "/docs",
    }


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        version="0.1.0",
        model_name=settings.model_name,
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
    a "Mock Mode" banner.
    """
    mcp_available = False
    pubmed_available = False
    try:
        from co_scientist.mcp_client import (  # type: ignore[import-not-found, unused-ignore]  # pylint: disable=import-outside-toplevel
            check_mcp_available,
            check_pubmed_available_via_mcp,
        )

        # The two probes are independent network round-trips; overlap them.
        mcp_available, pubmed_available = await asyncio.gather(
            check_mcp_available(), check_pubmed_available_via_mcp()
        )
    # pylint: disable-next=broad-exception-caught
    except Exception:  # pragma: no cover - engine optional in mock mode
        pass  # both probes default to False (set above)

    adapter_status = engine_adapter.system_status()

    return {
        "mcp_available": mcp_available,
        "pubmed_available": pubmed_available,
        # Gated on mcp_available alone: an MCP server that is up is assumed
        # to serve literature review even if the pubmed sub-check fails.
        "literature_review_available": mcp_available,
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
