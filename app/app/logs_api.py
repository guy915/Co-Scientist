"""HTTP surface for persisted application logs (the ``app_logs`` table).

Owns ``GET /api/logs`` and the payload/filter logic that the run-scoped
``GET /api/runs/{id}/logs`` endpoint (in ``app.runs``) shares, so both
endpoints accept identical query parameters and return the same shape:
``{"logs": [...], "last_id": N, "total": N}``. ``last_id`` is the table's
high-water mark regardless of filters, letting pollers resume with
``after_id`` even when the newest rows did not match their filter;
``total`` is the size of the whole matching set, ignoring the window.
"""

from __future__ import annotations

import hmac
import logging
import sqlite3
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app import store
from app.auth import client_id
from app.config import settings
from app.logging_setup import level_to_number

router = APIRouter(tags=["logs"])

# Bounds for client-submitted records: enough for a burst of UI events,
# small enough that the open endpoint cannot be used to flood the table.
MAX_CLIENT_BATCH = 50
MAX_CLIENT_MESSAGE_CHARS = 2000

# Hosts whose requests are treated as operator access without a token:
# a local CLI/agent session is already inside the trust boundary.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _is_operator(request: Request) -> bool:
    """Return whether this caller may read or clear the app-wide log.

    The log carries other tenants' research goals and server internals,
    so remote callers are scoped to their own records. Operators are
    loopback callers (the local CLI) or holders of the configured admin
    token (ops against a remote deployment).
    """
    token = settings.logs_admin_token
    if token:
        supplied = request.headers.get("X-Logs-Token", "")
        if supplied and hmac.compare_digest(supplied, token):
            return True
    host = request.client.host if request.client else ""
    return host in _LOOPBACK_HOSTS


def _scope_for(request: Request) -> str | None:
    """Return the client scope to apply, or None for app-wide access."""
    if _is_operator(request):
        return None
    # An unidentified remote caller gets a scope that matches nothing
    # rather than the app-wide view.
    return client_id(request) or "\x00-anonymous"


def _sanitize(text: str) -> str:
    """Collapse control characters in submitted text to spaces.

    Ingestion is open by necessity, and a newline or tab in a message
    would let a caller forge extra lines in the CLI's tab-delimited
    output -- i.e. fabricate log entries that never happened.
    """
    return "".join(ch if ch.isprintable() else " " for ch in text).strip()


# Sliding-window ingest counters, keyed by client scope.
_ingest_hits: dict[str, list[float]] = {}


def _check_ingest_rate(scope: str) -> None:
    """Raise 429 once a client exceeds the per-minute ingest ceiling."""
    limit = settings.logs_ingest_per_minute
    if limit <= 0:
        return
    now = time.monotonic()
    # Evict scopes whose window has gone quiet, so one-off client ids do
    # not accumulate in this process-lifetime map.
    for stale in [
        key
        for key, times in _ingest_hits.items()
        if key != scope and (not times or now - times[-1] >= 60.0)
    ]:
        del _ingest_hits[stale]
    hits = [t for t in _ingest_hits.get(scope, []) if now - t < 60.0]
    if len(hits) >= limit:
        _ingest_hits[scope] = hits
        raise HTTPException(
            status_code=429, detail="log ingestion rate exceeded"
        )
    hits.append(now)
    _ingest_hits[scope] = hits


# High-volume logger prefixes hidden from the default view (below
# WARNING): per-request access records, per-click/-navigation UI
# records, and dependency chatter. Pass ``verbose=1`` (CLI: ``cosci logs
# --all``) for the full stream. The default keeps the log readable for
# humans and cheap in tokens for automated consumers.
#
# Hidden is not the same as absent: these stay persisted so ``--all`` can
# show them. The capture side separately refuses to persist a narrower set
# of pure third-party per-call chatter, which nothing can ask for -- see
# logging_setup.UNPERSISTED_LOGGERS.
NOISE_LOGGERS: tuple[str, ...] = (
    "uvicorn.access",
    "ui.interaction",
    "ui.navigation",
    "httpx",
    "httpcore",
    "urllib3",
    "litellm",
    # Availability probes repeat on every /status poll; their WARNINGs
    # (e.g. "MCP server unavailable") still surface.
    "co_scientist.mcp_client",
)


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


def _query_logs_payload(
    conn: sqlite3.Connection,
    *,
    after_id: int,
    limit: int,
    min_levelno: int,
    run_id: str | None,
    q: str | None,
    noise_loggers: tuple[str, ...] | None,
    scope_client_id: str | None,
) -> dict[str, Any]:
    """Run the three reads backing one logs response on an open connection."""
    rows = store.list_logs(
        after_id=after_id,
        min_levelno=min_levelno,
        run_id=run_id,
        contains=q,
        noise_loggers=noise_loggers,
        scope_client_id=scope_client_id,
        limit=limit,
        conn=conn,
    )
    # `total` counts the whole matching set (no cursor, no limit) so the
    # UI badge shows the true size even when the window is capped.
    total = store.count_logs(
        min_levelno=min_levelno,
        run_id=run_id,
        contains=q,
        noise_loggers=noise_loggers,
        scope_client_id=scope_client_id,
        conn=conn,
    )
    last_id = store.latest_log_id(conn=conn)
    return {"logs": rows, "last_id": last_id, "total": total}


def logs_payload(
    *,
    after_id: int,
    limit: int,
    min_level: str | None,
    run_id: str | None,
    q: str | None,
    verbose: bool = False,
    scope_client_id: str | None = None,
) -> dict[str, Any]:
    """Build the shared logs response for the given filters.

    Args:
        after_id: Only rows with an id strictly greater than this.
        limit: Maximum rows returned (the newest matches, oldest-first).
        min_level: Minimum level name, case-insensitive; None for all.
        run_id: Only rows bound to this run; None for app-wide.
        q: Case-insensitive message substring filter.
        verbose: Include high-volume noise records (HTTP access, UI
            clicks/navigation, dependency chatter) below WARNING.
        scope_client_id: One client's records only; None is the
            app-wide, operator-only view.

    Raises:
        HTTPException: 422 when ``min_level`` is not a known level name.
    """
    min_levelno = _min_levelno(min_level)
    noise_loggers = None if verbose else NOISE_LOGGERS
    # One connection for the three reads: the UI polls this continuously.
    with store.connect() as conn:
        return _query_logs_payload(
            conn,
            after_id=after_id,
            limit=limit,
            min_levelno=min_levelno,
            run_id=run_id,
            q=q,
            noise_loggers=noise_loggers,
            scope_client_id=scope_client_id,
        )


class ClientLogRecord(BaseModel):
    """One log record submitted by the frontend."""

    message: str
    level: str = "info"
    logger: str = "ui"
    run_id: str | None = None


class ClientLogBatch(BaseModel):
    """A batch of frontend log records."""

    records: list[ClientLogRecord] = Field(
        ..., min_length=1, max_length=MAX_CLIENT_BATCH
    )


@router.post("/api/logs")
async def post_logs(batch: ClientLogBatch, request: Request) -> dict[str, Any]:
    """Ingest frontend log records into the persisted app-wide log.

    Records are namespaced under the ``ui.`` logger prefix so their origin
    stays obvious next to backend records; unknown level names fall back
    to INFO and messages are truncated to a sane length.
    """
    owner = client_id(request)
    _check_ingest_rate(owner or "anonymous")
    # One transaction for the whole batch: up to 50 rows per POST, and the
    # single writer should pay one lock acquisition for them, not fifty.
    with store.transaction() as conn:
        for record in batch.records:
            levelno = level_to_number(record.level) or logging.INFO
            logger_name = _sanitize(
                record.logger
                if record.logger.startswith("ui")
                else f"ui.{record.logger}"
            )
            store.append_log(
                level=logging.getLevelName(levelno),
                levelno=levelno,
                logger_name=logger_name,
                message=_sanitize(record.message)[:MAX_CLIENT_MESSAGE_CHARS],
                run_id=record.run_id,
                client_id=owner or None,
                conn=conn,
            )
        last_id = store.latest_log_id(conn=conn)
    return {"added": len(batch.records), "last_id": last_id}


@router.delete("/api/logs")
async def delete_logs(request: Request) -> dict[str, Any]:
    """Delete persisted log records and report the count.

    Operators clear the whole log, restarting ids so it reads as new.
    Remote callers may only clear their own records, which leaves the
    shared id sequence alone.
    """
    return {"deleted": store.clear_logs(scope_client_id=_scope_for(request))}


@router.get("/api/logs")
async def get_logs(
    request: Request,
    after_id: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    min_level: str | None = None,
    run_id: str | None = None,
    q: str | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """Return persisted application log records, oldest-first.

    Operators (loopback callers, or holders of ``LOGS_ADMIN_TOKEN`` via
    the ``X-Logs-Token`` header) get the app-wide view. Every other
    caller sees only their own records: those they submitted and those
    belonging to runs they own. The default view also hides high-volume
    noise (HTTP access records, UI clicks/navigation, dependency
    chatter) below WARNING; ``verbose=1`` returns everything visible.
    """
    return logs_payload(
        after_id=after_id,
        limit=limit,
        min_level=min_level,
        run_id=run_id,
        q=q,
        verbose=verbose,
        scope_client_id=_scope_for(request),
    )
