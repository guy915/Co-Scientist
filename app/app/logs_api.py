from __future__ import annotations

import dataclasses
import logging
import sqlite3
import time
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.auth import client_id
from app.config import settings
from app.logging_setup import level_to_number
from app.operator_access import is_operator
from app.store import db, logs
from app.store.logs import LogFilters, NewLogRecord

# Process-local limit; assumes one API replica and needs shared storage when
# replicated.
_ingest_hits: dict[str, list[float]] = {}


def _rate_limit_keys(request: Request) -> tuple[str, str]:
    """Caller-controlled compatibility IDs can rotate freely; independently
    enforce connecting-host and verified identity budgets.
    """
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}", f"id:{client_id(request) or 'anonymous'}"


def _check_rate(
    hits_by_scope: dict[str, list[float]],
    scope: str,
    limit: int,
    detail: str,
) -> None:
    if limit <= 0:
        return
    now = time.monotonic()
    # Expire inactive rate scopes so rotated one-off client IDs cannot grow the
    # map forever.
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
    ip_key, id_key = _rate_limit_keys(request)
    _check_rate(hits_by_scope, ip_key, limit, detail)
    _check_rate(hits_by_scope, id_key, limit, detail)


def _check_ingest_rate(request: Request) -> None:
    _check_both_rates(
        _ingest_hits,
        request,
        settings.logs_ingest_per_minute,
        "log ingestion rate exceeded",
    )


router = APIRouter(tags=["logs"])

MAX_CLIENT_BATCH = 50
MAX_CLIENT_MESSAGE_CHARS = 2000


def _scope_for(request: Request) -> str | None:
    """Unidentified remote callers match no records; only operator access
    permits the app-wide view.
    """
    if is_operator(request):
        return None
    # Unidentified remote callers match no records, never the operator-wide
    # scope.
    return client_id(request) or "\x00-anonymous"


def _sanitize(text: str) -> str:
    # Open ingestion must not let control characters forge diagnostic entries.
    return "".join(ch if ch.isprintable() else " " for ch in text).strip()


def _min_levelno(min_level: str | None) -> int:
    if min_level is None:
        return 0
    levelno = level_to_number(min_level)
    if levelno is None:
        raise HTTPException(status_code=422, detail=f"unknown log level: {min_level}")
    return levelno


class LogQuery(BaseModel):
    """Query parameters of ``GET /api/logs``; the caller's scope is derived
    from the request, never accepted from it.
    """

    after_id: int = Field(0, ge=0)
    limit: int = Field(200, ge=1, le=1000)
    min_level: str | None = None


def _query_logs_payload(
    conn: sqlite3.Connection,
    filters: LogFilters,
    limit: int,
) -> dict[str, Any]:
    rows = logs.list_logs(filters=filters, limit=limit, conn=conn)
    # Count the full matching set so bounded display windows do not understate
    # totals.
    total = logs.count_logs(filters=dataclasses.replace(filters, after_id=0), conn=conn)
    # Count rows after the session anchor; subtracting snapshots breaks when
    # retention or scoped clears remove older rows.
    session_total = logs.count_logs(filters=filters, conn=conn)
    last_id = logs.latest_log_id(conn=conn)
    return {
        "logs": rows,
        "last_id": last_id,
        "total": total,
        "session_total": session_total,
    }


def logs_payload(query: LogQuery, *, scope_client_id: str | None = None) -> dict[str, Any]:
    filters = LogFilters(
        after_id=query.after_id,
        min_levelno=_min_levelno(query.min_level),
        scope_client_id=scope_client_id,
    )
    with db.connect() as conn:
        return _query_logs_payload(conn, filters, query.limit)


class ClientLogRecord(BaseModel):
    """One log record submitted by the frontend."""

    message: str
    level: str = "info"
    logger: str = "ui"
    run_id: str | None = None


class ClientLogBatch(BaseModel):
    """A batch of frontend log records."""

    records: list[ClientLogRecord] = Field(..., min_length=1, max_length=MAX_CLIENT_BATCH)


@router.post("/api/logs")
async def post_logs(batch: ClientLogBatch, request: Request) -> dict[str, Any]:
    """Ingest frontend log records into the persisted app-wide log.

    Records are namespaced under the ``ui.`` logger prefix so their origin
    stays obvious next to backend records; unknown level names fall back
    to INFO and messages are truncated to a sane length.
    """
    owner = client_id(request)
    _check_ingest_rate(request)
    # Batch ingestion acquires SQLite's writer once, not once per submitted
    # record.
    with db.transaction() as conn:
        for record in batch.records:
            levelno = level_to_number(record.level) or logging.INFO
            logger_name = _sanitize(
                record.logger if record.logger.startswith("ui") else f"ui.{record.logger}"
            )
            logs.append_log(
                NewLogRecord(
                    level=logging.getLevelName(levelno),
                    levelno=levelno,
                    logger_name=logger_name,
                    message=_sanitize(record.message)[:MAX_CLIENT_MESSAGE_CHARS],
                    run_id=record.run_id,
                    client_id=owner or None,
                ),
                conn=conn,
            )
        last_id = logs.latest_log_id(conn=conn)
    return {"added": len(batch.records), "last_id": last_id}


@router.get("/api/logs")
async def get_logs(
    request: Request,
    query: Annotated[LogQuery, Query()],
) -> dict[str, Any]:
    """Return persisted application log records, oldest-first.

    Operators (loopback callers, or holders of ``LOGS_ADMIN_TOKEN`` via
    the ``X-Logs-Token`` header) get the app-wide view. Every other
    caller sees only their own records: those they submitted and those
    belonging to runs they own.
    """
    return logs_payload(query, scope_client_id=_scope_for(request))


__all__ = ["_check_ingest_rate"]
