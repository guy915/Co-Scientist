"""Bound invite-code guessing by connecting IP on the single API process."""

import time

from fastapi import HTTPException, Request

from app.config import settings

# Production runs one API process. Replicated deployments need a shared
# limiter; caller-controlled client IDs and forwarded headers are not keys.
_exchange_hits: dict[str, list[float]] = {}
_MAX_SCOPES = 4096
_WINDOW_SECONDS = 60


def check_exchange_rate(request: Request) -> None:
    """Reject invite exchanges after the per-IP budget is spent.

    Raises:
        HTTPException: 429 with Retry-After when the window is full.
    """
    now = time.monotonic()
    host = request.client.host if request.client else "unknown"
    for stale in [
        key
        for key, hits in _exchange_hits.items()
        if not hits or now - hits[-1] >= _WINDOW_SECONDS
    ]:
        del _exchange_hits[stale]
    hits = [
        timestamp
        for timestamp in _exchange_hits.get(host, [])
        if now - timestamp < _WINDOW_SECONDS
    ]
    full = host not in _exchange_hits and len(_exchange_hits) >= _MAX_SCOPES
    if full or len(hits) >= settings.auth_exchange_per_minute:
        raise HTTPException(
            status_code=429,
            detail="access code exchange rate exceeded",
            headers={"Retry-After": str(_WINDOW_SECONDS)},
        )
    hits.append(now)
    _exchange_hits[host] = hits
