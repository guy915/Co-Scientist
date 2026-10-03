"""Health checks and availability probes for the diagnostics endpoints.

Backs ``/health`` and ``/status`` in ``main.py``. ``/health`` is what a
deploy platform's healthcheck polls, and a failed healthcheck kills the
container mid-run (see AGENTS.md's healthcheck-failure-spiral incident),
so its checks split into two kinds: liveness (store reachability -- can
this process serve at all) and degraded-but-serving conditions (engine
importability, durable-queue health, free disk) that must never flip the
response to ``unhealthy``. All of them are local and fast -- a SQLite
round-trip, an importability lookup, a read-only queue aggregate, a stat
call -- so the ``make start`` readiness gate can poll them cheaply, and
the queue/disk pair is cached for a short TTL for the same reason the
probes below are: ``/health`` is polled continuously. The MCP/PubMed
probes are network round-trips against an external server, so each one
runs under a bounded timeout and the pair of results is cached for a
short TTL to keep repeated ``/status`` calls from hammering the server.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from dataclasses import dataclass
from typing import Any

from app import store
from app.config import any_provider_credential, settings
from app.engine_adapter import _engine_importable
from app.store.db import default_db_path
from app.store.tasks import queue_health_snapshot

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
    is ``unhealthy``. A missing engine is normal when no provider key is
    configured; it only degrades health when an LLM provider key is
    configured (the operator expects the real engine) but the package
    cannot be imported.

    Args:
        store_check: Outcome of the SQLite store check.
        engine_check: Outcome of the engine importability check.

    Returns:
        One of ``healthy``, ``degraded``, or ``unhealthy``.
    """
    if not store_check.ok:
        return UNHEALTHY
    if any_provider_credential() and not engine_check.ok:
        return DEGRADED
    return HEALTHY


def check_queue(db_path: str | None = None) -> HealthCheck:
    """Report whether the durable task queue is making progress.

    Read-only: one aggregate query over active runs' tasks (see
    :func:`app.store.tasks.queue_health_snapshot`), safe to run on every
    ``/health`` poll. Only a stalled run -- one with no queued, in-flight,
    or rescuable work, so nothing can ever advance it without operator
    intervention -- flips this to ``ok=False``. A nonzero queue depth is
    not itself a problem: a busy system is supposed to have one.

    Args:
        db_path: Optional override for the SQLite database path.

    Returns:
        The check outcome; ``detail`` names the stalled runs when it
        fails.
    """
    try:
        snapshot = queue_health_snapshot(db_path=db_path)
    except Exception as exc:
        logger.error("Queue health check failed: %s", exc)
        return HealthCheck(ok=False, detail=f"{type(exc).__name__}: {exc}")
    if not snapshot.stalled_run_ids:
        return HealthCheck(ok=True)
    ids = ", ".join(snapshot.stalled_run_ids[:5])
    return HealthCheck(
        ok=False,
        detail=(
            f"{len(snapshot.stalled_run_ids)} run(s) stalled with no "
            f"claimable work: {ids}"
        ),
    )


def check_disk(
    db_path: str | None = None,
    *,
    min_free_bytes: int | None = None,
) -> HealthCheck:
    """Report whether the database's volume has enough free disk space.

    Read-only and local (``shutil.disk_usage`` on the database file's
    directory; no I/O against the database itself). A volume filling
    silently while health stayed green is a recorded incident in this
    repo, so this check exists to surface it -- but low disk degrades
    rather than fails health: killing the container frees no space, and
    the process can still serve reads off a full disk.

    Args:
        db_path: Optional override for the SQLite database path.
        min_free_bytes: Free-space floor; defaults to
            ``settings.health_check_min_free_disk_bytes``.

    Returns:
        The check outcome; ``detail`` carries the free-space reading when
        it fails or the probe itself errors.
    """
    threshold = (
        settings.health_check_min_free_disk_bytes
        if min_free_bytes is None
        else min_free_bytes
    )
    target = db_path or default_db_path() or "./coscientist.db"
    directory = os.path.dirname(os.path.abspath(target)) or "."
    try:
        free = shutil.disk_usage(directory).free
    except Exception as exc:
        logger.error("Disk health check failed: %s", exc)
        return HealthCheck(ok=False, detail=f"{type(exc).__name__}: {exc}")
    if free < threshold:
        return HealthCheck(
            ok=False,
            detail=f"{free} bytes free on {directory} (floor {threshold})",
        )
    return HealthCheck(ok=True)


def derive_overall_health(
    store_check: HealthCheck,
    engine_check: HealthCheck,
    queue_check: HealthCheck,
    disk_check: HealthCheck,
) -> str:
    """Fold the queue and disk checks into the liveness verdict.

    ``derive_health_status`` alone decides whether this process can serve
    at all -- store reachability is its only ``unhealthy`` trigger.
    Durable-queue backlog and disk pressure are conditions the process can
    keep serving through, so they can only ever add ``degraded`` on top of
    an otherwise-healthy verdict, never flip it to ``unhealthy``: a failed
    healthcheck kills the container mid-run, which is exactly the outcome
    a stalled-run or low-disk signal must not cause.

    Args:
        store_check: Outcome of the SQLite store check.
        engine_check: Outcome of the engine importability check.
        queue_check: Outcome of the durable-queue health check.
        disk_check: Outcome of the free-disk-space check.

    Returns:
        One of ``healthy``, ``degraded``, or ``unhealthy``.
    """
    base = derive_health_status(store_check, engine_check)
    if base == UNHEALTHY:
        return UNHEALTHY
    if not queue_check.ok or not disk_check.ok:
        return DEGRADED
    return base


# TTL cache for the (queue, disk) health pair. Both checks are local and
# read-only, so the cache exists to bound query volume against the single
# SQLite writer on a continuously-polled endpoint, not to hide latency --
# mirrors the probe cache below in shape, not in what it protects.
_health_check_cache: tuple[float, tuple[HealthCheck, HealthCheck]] | None = None


def clear_health_check_cache() -> None:
    """Drop the cached queue/disk health pair (used by tests and reconfig)."""
    global _health_check_cache
    _health_check_cache = None


def queue_and_disk_health_cached(
    db_path: str | None = None,
) -> tuple[HealthCheck, HealthCheck]:
    """Return the ``(queue, disk)`` health pair, reusing a short-TTL cache.

    Args:
        db_path: Optional override for the SQLite database path.

    Returns:
        The cached or freshly computed ``(queue, disk)`` check pair, at
        most ``settings.health_check_cache_ttl_seconds`` old.
    """
    global _health_check_cache
    now = time.monotonic()
    if _health_check_cache is not None and now < _health_check_cache[0]:
        return _health_check_cache[1]
    result = (check_queue(db_path), check_disk(db_path))
    ttl = settings.health_check_cache_ttl_seconds
    _health_check_cache = (now + ttl, result)
    return result


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


async def _probe_literature_stack() -> tuple[
    ProbeResult, ProbeResult, ProbeResult
]:
    """Probe MCP server, PubMed, and web-search availability concurrently.

    The engine is an optional runtime dependency; when its probe helpers
    cannot be imported all probes report the ``error`` state instead of
    a misleading definitive ``down``. That fallback is load-bearing and it
    hides a typo well: importing a name the engine does not export failed
    all three probes at once, on every deployment, which reaches the
    scientist as a connectors menu with nothing in it. Import names here
    are checked by ``test_diagnostics_probe_imports``.

    Web search is probed by asking the MCP server whether a search
    issued now would reach a provider -- not whether it advertises
    ``search_web``, which it does whenever a key was set at boot. The two
    answers diverge the moment a provider refuses that key: the tool stays
    listed, every search returns an empty result set, and the connector
    reads as healthy while the runs get nothing.

    Returns:
        The ``(mcp, pubmed, web_search)`` probe outcomes.
    """
    try:
        from co_scientist.mcp_client import (
            check_literature_source_available,
            check_mcp_available,
            check_web_search_available,
        )
    except Exception as exc:
        unavailable = _probe_error(f"engine unavailable: {exc}")
        return unavailable, unavailable, unavailable

    timeout = settings.status_probe_timeout_seconds
    # The probes are independent network round-trips; overlap them.
    return await asyncio.gather(
        _run_probe(check_mcp_available(), timeout),
        _run_probe(check_literature_source_available(), timeout),
        _run_probe(check_web_search_available(), timeout),
    )


# TTL cache for the probe pair: (monotonic deadline, results). One entry
# suffices because the probes always run (and expire) together.
_probe_cache: (
    tuple[float, tuple[ProbeResult, ProbeResult, ProbeResult]] | None
) = None


def clear_probe_cache() -> None:
    """Drop the cached probe results (used by tests and reconfiguration)."""
    global _probe_cache
    _probe_cache = None


async def probe_literature_stack_cached() -> tuple[
    ProbeResult, ProbeResult, ProbeResult
]:
    """Return the MCP/PubMed/web-search probe triple, reusing a short cache.

    Returns:
        The ``(mcp, pubmed, web_search)`` probe outcomes, at most
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
