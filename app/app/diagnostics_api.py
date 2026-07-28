"""Diagnostics HTTP surface: root, health, config, and status endpoints.

Response models and handlers for the app-level diagnostics endpoints
(``/``, ``/health``, ``/config``, ``/status``), mounted by ``app.main``.
Probe logic lives in ``app.diagnostics``; this module only shapes the
HTTP responses.
"""

from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from app import diagnostics, engine_adapter, paper_corpus
from app.config import settings
from app.notifications import email_notifications_configured
from app.run_modes import (
    DEFAULT_RUN_TIER,
    RUN_TIER_DEFAULTS,
)
from app.version import API_VERSION

router = APIRouter()


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
        ..., description="active workflow provider (always 'engine')"
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
    web_search_available: bool = Field(
        False,
        description=(
            "whether the mcp server advertises its web search tool, which "
            "it does only when a search-provider api key is configured"
        ),
    )
    email_notifications_available: bool = Field(
        False,
        description=(
            "whether an SMTP transport is configured, so a run can actually "
            "be opted in to a completion email"
        ),
    )
    probes: dict[str, ProbeStatus] = Field(
        ...,
        description=(
            "per-probe detail (mcp, pubmed, web_search), distinguishing a "
            "served 'down' from a probe error"
        ),
    )
    mcp_server_url: str = Field(..., description="configured mcp server url")
    provider: str = Field(
        "engine", description="active workflow provider (always 'engine')"
    )
    llm_backend: str = Field(
        "real",
        description="active LLM backend: 'offline' (deterministic) | 'real'",
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


@router.get("/", tags=["root"])
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {
        "message": "Co-Scientist API",
        "version": API_VERSION,
        "docs": "/docs",
    }


@router.get("/health", response_model=HealthResponse, tags=["health"])
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


@router.get("/config", response_model=ConfigResponse, tags=["config"])
async def get_config() -> ConfigResponse:
    """Get default run configuration values (standard tier)."""
    defaults = RUN_TIER_DEFAULTS[DEFAULT_RUN_TIER]
    return ConfigResponse(
        max_iterations=defaults["max_iterations"],
        initial_hypotheses_count=defaults["initial_hypotheses_count"],
        evolution_max_count=defaults["evolution_max_count"],
    )


def _build_status_payload(
    mcp: diagnostics.ProbeResult,
    pubmed: diagnostics.ProbeResult,
    web_search: diagnostics.ProbeResult,
    literature_available: bool,
    adapter_status: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the ``/status`` response from probe and adapter results."""
    return {
        "mcp_available": mcp.available,
        "pubmed_available": pubmed.available,
        "literature_review_available": literature_available,
        # True only when the MCP server advertises its web search tool, which
        # requires a search-provider API key on that server.
        "web_search_available": web_search.available,
        # Local, not probed: an SMTP transport is either configured on this
        # process or it is not, and the plan card's completion-email opt-in
        # is gated on the answer.
        "email_notifications_available": email_notifications_configured(),
        "probes": {
            "mcp": {"state": mcp.state, "error": mcp.error},
            "pubmed": {"state": pubmed.state, "error": pubmed.error},
            "web_search": {
                "state": web_search.state,
                "error": web_search.error,
            },
        },
        # User-facing data-source connectors for the composer menu, derived
        # from live availability plus the configured tools YAML.
        "connectors": engine_adapter.connectors_report(
            literature_available=literature_available,
            enabled_tools=adapter_status.get("enabled_tools"),
            web_search_available=web_search.available,
            paper_corpus_available=bool(paper_corpus.load_catalog()),
        ),
        # provider/llm_backend/model_name/etc. from engine_adapter.system_status
        **adapter_status,
    }


@router.get("/status", response_model=SystemStatusResponse, tags=["system"])
async def get_system_status() -> dict[str, Any]:
    """Checks system availability for literature review features.

    Returns availability status for mcp server and pubmed api, plus
    provider/llm-backend info from the engine adapter so the UI can render
    an "Offline mode" chip. Probes run under a bounded timeout and are
    cached for a short TTL (see app/diagnostics.py); the ``probes`` field
    distinguishes a server that answered "down" from a probe that errored.
    """
    mcp, pubmed, web_search = await diagnostics.probe_literature_stack_cached()

    adapter_status = engine_adapter.system_status()

    # Both legs are required: the literature_review node needs the MCP server
    # up AND its PubMed-backed tools answering.
    literature_available = mcp.available and pubmed.available

    return _build_status_payload(
        mcp, pubmed, web_search, literature_available, adapter_status
    )
