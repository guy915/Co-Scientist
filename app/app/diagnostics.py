"""Health checks and availability probes for the diagnostics endpoints.

Backs ``/health`` and ``/status`` in ``main.py``. Health checks are
local and fast (a SQLite round-trip and an importability lookup), so the
``make dev`` readiness gate can poll them cheaply. The MCP/PubMed probes
are network round-trips against an external server, so each one runs
under a bounded timeout and the pair of results is cached for a short
TTL to keep repeated ``/status`` calls from hammering the server.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from app import store
from app.config import settings
from app.engine_adapter.provider import _engine_importable, _has_provider_key

logger = logging.getLogger(__name__)

HEALTHY = "healthy"
DEGRADED = "degraded"
UNHEALTHY = "unhealthy"

# Probe states for /status: "up" and "down" are definitive answers from a
# completed probe; "error" means the probe itself failed (engine import
# failure, timeout) so availability is unknown rather than known-false.
PROBE_UP = "up"
PROBE_DOWN = "down"
PROBE_ERROR = "error"


@dataclass
class HealthCheck:
    """Outcome of one local health check."""

    ok: bool
    detail: str | None = None


def check_store(db_path: str | None = None) -> HealthCheck:
    """Verify the SQLite store accepts a connection and a trivial query.

    Args:
        db_path: Optional override for the SQLite database path.

    Returns:
        The check outcome; ``detail`` carries the error when it fails.
    """
    try:
        with store.connect(db_path) as conn:
            conn.execute("SELECT 1").fetchone()
        return HealthCheck(ok=True)
    except Exception as exc:
        logger.error("Store health check failed: %s", exc)
        return HealthCheck(ok=False, detail=f"{type(exc).__name__}: {exc}")


def check_engine() -> HealthCheck:
    """Report whether the co_scientist engine package is importable."""
    if _engine_importable():
        return HealthCheck(ok=True)
    return HealthCheck(ok=False, detail="co_scientist package not importable")


def derive_health_status(
    store_check: HealthCheck, engine_check: HealthCheck
) -> str:
    """Derive the overall health value from the individual checks.

    The store is load-bearing for every endpoint, so an unreachable store
    is ``unhealthy``. A missing engine is normal in mock mode; it only
    degrades health when an LLM provider key is configured (the operator
    expects the real engine) but the package cannot be imported.

    Args:
        store_check: Outcome of the SQLite store check.
        engine_check: Outcome of the engine importability check.

    Returns:
        One of ``healthy``, ``degraded``, or ``unhealthy``.
    """
    if not store_check.ok:
        return UNHEALTHY
    if _has_provider_key() and not engine_check.ok:
        return DEGRADED
    return HEALTHY


@dataclass
class ProbeResult:
    """Outcome of one availability probe against the MCP server.

    ``available`` is the boolean the legacy /status fields expose;
    ``state`` distinguishes a served "no" (``down``) from a probe that
    could not run or finish (``error``), with ``error`` carrying detail.
    """

    available: bool
    state: str
    error: str | None = None


def _probe_result_from(available: bool) -> ProbeResult:
    """Wrap a completed probe's boolean answer in a ProbeResult."""
    return ProbeResult(
        available=available, state=PROBE_UP if available else PROBE_DOWN
    )


def _probe_error(detail: str) -> ProbeResult:
    """Build the ProbeResult for a probe that itself failed."""
    return ProbeResult(available=False, state=PROBE_ERROR, error=detail)


async def _run_probe(coro: Any, timeout: float) -> ProbeResult:
    """Run one availability coroutine under a bounded timeout.

    Args:
        coro: The engine probe coroutine to await.
        timeout: Seconds before the probe is abandoned.

    Returns:
        The probe outcome; timeouts and unexpected errors map to the
        ``error`` state rather than a definitive ``down``.
    """
    try:
        return _probe_result_from(
            bool(await asyncio.wait_for(coro, timeout=timeout))
        )
    except asyncio.TimeoutError:
        # asyncio.TimeoutError spelled explicitly: on Python 3.10 it is not
        # yet an alias of the builtin TimeoutError.
        return _probe_error(f"probe timed out after {timeout:g}s")
    except Exception as exc:
        return _probe_error(f"{type(exc).__name__}: {exc}")


async def _probe_literature_stack() -> tuple[ProbeResult, ProbeResult]:
    """Probe MCP server and PubMed availability concurrently.

    The engine is an optional runtime dependency; when its probe helpers
    cannot be imported both probes report the ``error`` state instead of
    a misleading definitive ``down``.

    Returns:
        The ``(mcp, pubmed)`` probe outcomes.
    """
    try:
        from co_scientist.mcp_client import (  # type: ignore[import-not-found, unused-ignore]
            check_mcp_available,
            check_pubmed_available_via_mcp,
        )
    except Exception as exc:
        unavailable = _probe_error(f"engine unavailable: {exc}")
        return unavailable, unavailable

    timeout = settings.status_probe_timeout_seconds
    # The two probes are independent network round-trips; overlap them.
    return await asyncio.gather(
        _run_probe(check_mcp_available(), timeout),
        _run_probe(check_pubmed_available_via_mcp(), timeout),
    )


# TTL cache for the probe pair: (monotonic deadline, results). One entry
# suffices because both probes always run (and expire) together.
_probe_cache: tuple[float, tuple[ProbeResult, ProbeResult]] | None = None


def clear_probe_cache() -> None:
    """Drop the cached probe results (used by tests and reconfiguration)."""
    global _probe_cache
    _probe_cache = None


async def probe_literature_stack_cached() -> tuple[ProbeResult, ProbeResult]:
    """Return the MCP/PubMed probe pair, reusing a short-lived cache.

    Returns:
        The ``(mcp, pubmed)`` probe outcomes, at most
        ``settings.status_probe_cache_ttl_seconds`` old.
    """
    global _probe_cache
    now = time.monotonic()
    if _probe_cache is not None and now < _probe_cache[0]:
        return _probe_cache[1]
    results = await _probe_literature_stack()
    ttl = settings.status_probe_cache_ttl_seconds
    _probe_cache = (now + ttl, results)
    return results
