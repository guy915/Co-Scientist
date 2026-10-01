"""Per-process rate limiting for the open log-ingestion and report endpoints.

Split out of ``app.logs_api``, which re-exports the names callers use so
``logs_api._report_hits`` (mutated directly by ``test_logs_report.py``)
and ``logs_api.REPORTS_PER_MINUTE`` keep resolving. Both endpoints this
guards are open to unauthenticated callers by necessity -- a browser in
trouble has to be able to say so -- so the budget here is the only thing
standing between that openness and a flood.
"""

from __future__ import annotations

import time

from fastapi import HTTPException, Request

from app.auth import client_id
from app.config import settings

# Sliding-window counters, keyed by rate-limit key (see `_rate_limit_keys`).
# Ingestion and reporting keep separate buckets: one is a background stream
# of UI records, the other a deliberate click that sends mail, and a budget
# sized for the first would be no ceiling at all on the second.
#
# Per-process, not shared across replicas (N13): production runs one `api`
# process today (COSCIENTIST_EMBEDDED_WORKER, no evidence of horizontal
# scaling -- see AGENTS.md), so a process-local budget is the whole ceiling
# that exists. If this deployment ever scales to multiple replicas, each
# would enforce its own budget independently, multiplying the effective
# limit by the replica count -- move these buckets to a shared store
# (Redis, or the SQLite store if the write volume stays low; see the
# write-lock-across-network-I/O gotcha in AGENTS.md before choosing SQLite
# for a per-request check) if and when that becomes true.
_ingest_hits: dict[str, list[float]] = {}
_report_hits: dict[str, list[float]] = {}

# Reports per client per minute. One click is one report; anything beyond a
# handful is a mistake or an attempt to flood the operator's inbox.
REPORTS_PER_MINUTE = 5


def _rate_limit_keys(request: Request) -> tuple[str, str]:
    """Return the two identities a rate limiter must check.

    The client id alone is not a security boundary: in the default
    compatibility auth mode it is a caller-supplied ``X-Client-ID`` header,
    so a caller can spend a fresh budget on every request just by sending a
    new one -- the id-keyed bucket by itself never fills. The connecting
    host is what closes that: a single caller cannot cheaply rotate its
    source IP per request the way it can a header, so it is checked as a
    second, independent bucket. Both are enforced (see `_check_rate`
    callers), so defeating either one alone is not enough -- only rotating
    the source IP too would work, which is a materially different, more
    expensive attack than sending a different header.

    The id bucket is kept alongside the IP one (not replaced) because a
    verified researcher session's id is not spoofable, and several
    legitimate clients can share one IP behind a NAT or corporate proxy;
    keeping both buckets means an honest client sharing an IP is not solely
    at the mercy of a noisy neighbor's budget.

    Args:
        request: The incoming request.

    Returns:
        ``(ip_key, id_key)``, each namespaced so they can share one hits
        dict without colliding.
    """
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}", f"id:{client_id(request) or 'anonymous'}"


def _check_rate(
    hits_by_scope: dict[str, list[float]],
    scope: str,
    limit: int,
    detail: str,
) -> None:
    """Raise 429 once a client exceeds a per-minute ceiling.

    Raises:
        HTTPException: 429 when this scope has spent its budget.
    """
    if limit <= 0:
        return
    now = time.monotonic()
    # Evict scopes whose window has gone quiet, so one-off client ids do
    # not accumulate in this process-lifetime map.
    for stale in [
        key
        for key, times in hits_by_scope.items()
        if key != scope and (not times or now - times[-1] >= 60.0)
    ]:
        del hits_by_scope[stale]
    hits = [t for t in hits_by_scope.get(scope, []) if now - t < 60.0]
    hits_by_scope[scope] = hits
    if len(hits) >= limit:
        raise HTTPException(status_code=429, detail=detail)
    hits.append(now)


def _check_both_rates(
    hits_by_scope: dict[str, list[float]],
    request: Request,
    limit: int,
    detail: str,
) -> None:
    """Enforce both the IP-keyed and the id-keyed bucket for one request.

    Raises:
        HTTPException: 429 when either bucket has spent its budget.
    """
    ip_key, id_key = _rate_limit_keys(request)
    _check_rate(hits_by_scope, ip_key, limit, detail)
    _check_rate(hits_by_scope, id_key, limit, detail)


def _check_ingest_rate(request: Request) -> None:
    """Raise 429 once a client exceeds the per-minute ingest ceiling."""
    _check_both_rates(
        _ingest_hits,
        request,
        settings.logs_ingest_per_minute,
        "log ingestion rate exceeded",
    )


def _check_report_rate(request: Request) -> None:
    """Raise 429 once a client exceeds the per-minute report ceiling."""
    _check_both_rates(
        _report_hits, request, REPORTS_PER_MINUTE, "report rate exceeded"
    )
