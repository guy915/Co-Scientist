"""HTTP surface for persisted application logs (the ``app_logs`` table).

Owns ``GET /api/logs`` and the payload/filter logic that the run-scoped
``GET /api/runs/{id}/logs`` endpoint (in ``app.runs``) shares, so both
endpoints accept identical query parameters and return the same shape:
``{"logs": [...], "last_id": N}``. ``last_id`` is the table's high-water
mark regardless of filters, letting pollers resume with ``after_id`` even
when the newest rows did not match their filter.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app import store
from app.logging_setup import level_to_number

router = APIRouter(tags=["logs"])


def _min_levelno(min_level: str | None) -> int:
    """Map a level name to its numeric value; 422 on unknown names."""
    if min_level is None:
        return 0
    levelno = level_to_number(min_level)
    if levelno is None:
        raise HTTPException(
            status_code=422, detail=f"unknown log level: {min_level}"
        )
    return levelno


def logs_payload(
    *,
    after_id: int,
    limit: int,
    min_level: str | None,
    run_id: str | None,
    q: str | None,
) -> dict[str, Any]:
    """Build the shared logs response for the given filters.

    Args:
        after_id: Only rows with an id strictly greater than this.
        limit: Maximum rows returned (the newest matches, oldest-first).
        min_level: Minimum level name, case-insensitive; None for all.
        run_id: Only rows bound to this run; None for app-wide.
        q: Case-insensitive message substring filter.

    Raises:
        HTTPException: 422 when ``min_level`` is not a known level name.
    """
    rows = store.list_logs(
        after_id=after_id,
        min_levelno=_min_levelno(min_level),
        run_id=run_id,
        contains=q,
        limit=limit,
    )
    return {"logs": rows, "last_id": store.latest_log_id()}


@router.get("/api/logs")
async def get_logs(
    after_id: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    min_level: str | None = None,
    run_id: str | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    """Return persisted application log records, oldest-first.

    App-wide: includes records emitted outside any run context. Filter to
    one run with ``run_id`` (or use ``GET /api/runs/{id}/logs``).
    """
    return logs_payload(
        after_id=after_id,
        limit=limit,
        min_level=min_level,
        run_id=run_id,
        q=q,
    )
