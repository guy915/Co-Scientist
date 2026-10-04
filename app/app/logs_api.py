from __future__ import annotations

import dataclasses
import logging
import sqlite3
import time
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

import app.store as store
from app.auth import client_id
from app.config import settings
from app.logging_setup import level_to_number
from app.notifications import deliver_email, email_notifications_configured
from app.operator_access import is_operator

logger = logging.getLogger(__name__)

# Ingest and email need separate budgets; process-local limits assume one API
# replica and need shared storage when replicated.
_ingest_hits: dict[str, list[float]] = {}
_report_hits: dict[str, list[float]] = {}

# A deliberate report click needs a far smaller ceiling than background log
# ingestion.
REPORTS_PER_MINUTE = 5


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


def _check_report_rate(request: Request) -> None:
    _check_both_rates(
        _report_hits, request, REPORTS_PER_MINUTE, "report rate exceeded"
    )


router = APIRouter(tags=["logs"])

MAX_CLIENT_BATCH = 50
MAX_CLIENT_MESSAGE_CHARS = 2000

# Bound emailed diagnostics so an open report endpoint cannot relay bulk text.
MAX_REPORT_CHARS = 100_000


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


# Verbose reads reveal hidden records; capture-time dropping is a different
# boundary.
NOISE_LOGGERS: tuple[str, ...] = (
    "uvicorn.access",
    "ui.interaction",
    "ui.navigation",
    "httpx",
    "httpcore",
    "urllib3",
    "litellm",
    "co_scientist",
)


def _min_levelno(min_level: str | None) -> int:
    if min_level is None:
        return 0
    levelno = level_to_number(min_level)
    if levelno is None:
        raise HTTPException(
            status_code=422, detail=f"unknown log level: {min_level}"
        )
    return levelno


class LogQuery(BaseModel):
    """The query parameters ``GET /api/logs`` accepts.

    A Pydantic query-parameter model: FastAPI expands its fields back into
    the same query-string names, defaults, and validation the handler used
    to declare one by one, so the HTTP contract and the generated OpenAPI
    schema are unchanged. The caller's visibility scope is deliberately
    absent -- it is derived from the request, never accepted from it.

    Attributes:
        after_id: Only rows with an id strictly greater than this.
        limit: Maximum rows returned (the newest matches, oldest-first).
        min_level: Minimum level name, case-insensitive; None for all.
        run_id: Only rows bound to this run; None for app-wide.
        q: Case-insensitive message substring filter.
        verbose: Include high-volume noise records (HTTP access, UI
            clicks/navigation, dependency chatter) below WARNING.
    """

    after_id: int = Field(0, ge=0)
    limit: int = Field(200, ge=1, le=1000)
    min_level: str | None = None
    run_id: str | None = None
    q: str | None = None
    verbose: bool = False


class RunLogQuery(BaseModel):
    """The query parameters the run-scoped logs endpoint accepts.

    :class:`LogQuery` minus ``run_id``, which that endpoint reads from the
    path instead of the query string.
    """

    after_id: int = Field(0, ge=0)
    limit: int = Field(200, ge=1, le=1000)
    min_level: str | None = None
    q: str | None = None
    verbose: bool = False

    def for_run(self, run_id: str) -> LogQuery:
        return LogQuery(run_id=run_id, **self.model_dump())


def _query_logs_payload(
    conn: sqlite3.Connection,
    filters: store.LogFilters,
    limit: int,
) -> dict[str, Any]:
    rows = store.list_logs(filters=filters, limit=limit, conn=conn)
    # Count the full matching set so bounded display windows do not understate
    # totals.
    total = store.count_logs(
        filters=dataclasses.replace(filters, after_id=0), conn=conn
    )
    # Count rows after the session anchor; subtracting snapshots breaks when
    # retention or scoped clears remove older rows.
    session_total = store.count_logs(filters=filters, conn=conn)
    last_id = store.latest_log_id(conn=conn)
    return {
        "logs": rows,
        "last_id": last_id,
        "total": total,
        "session_total": session_total,
    }


def logs_payload(
    query: LogQuery, *, scope_client_id: str | None = None
) -> dict[str, Any]:
    filters = store.LogFilters(
        after_id=query.after_id,
        min_levelno=_min_levelno(query.min_level),
        run_id=query.run_id,
        contains=query.q,
        noise_loggers=None if query.verbose else NOISE_LOGGERS,
        scope_client_id=scope_client_id,
    )
    # Share one connection across the continuously polled response's queries.
    with store.connect() as conn:
        return _query_logs_payload(conn, filters, query.limit)


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
    _check_ingest_rate(request)
    # Batch ingestion acquires SQLite's writer once, not once per submitted
    # record.
    with store.transaction() as conn:
        for record in batch.records:
            levelno = level_to_number(record.level) or logging.INFO
            logger_name = _sanitize(
                record.logger
                if record.logger.startswith("ui")
                else f"ui.{record.logger}"
            )
            store.append_log(
                store.NewLogRecord(
                    level=logging.getLevelName(levelno),
                    levelno=levelno,
                    logger_name=logger_name,
                    message=_sanitize(record.message)[
                        :MAX_CLIENT_MESSAGE_CHARS
                    ],
                    run_id=record.run_id,
                    client_id=owner or None,
                ),
                conn=conn,
            )
        last_id = store.latest_log_id(conn=conn)
    return {"added": len(batch.records), "last_id": last_id}


class LogReportRequest(BaseModel):
    """One diagnostic export a scientist chose to send to the operator."""

    report: str = Field(min_length=1, max_length=MAX_REPORT_CHARS)


def _report_subject(request: Request) -> str:
    """Request text reaches the body only; subject and recipient stay
    server-controlled to prevent header injection.
    """
    return (
        "Co-Scientist diagnostic report "
        f"({client_id(request) or 'unidentified client'})"
    )


@router.post("/api/logs/report", status_code=202)
async def report_logs(
    req: LogReportRequest, request: Request
) -> dict[str, Any]:
    """Email one diagnostic export to the configured operator address.

    The Logs panel's Copy button already produces a self-describing export
    (context preamble, tallies, field legend, newest entries); this sends
    that same document rather than a link, so a report arrives complete
    even from a browser the operator can never reach.

    The export is submitted rather than rebuilt from the caller's scoped
    logs on purpose: the panel's view is anchored to the browsing session
    and renumbered for display, so re-deriving it server-side would report
    something subtly different from what the scientist was looking at when
    they decided to report it.

    Open to any caller, like log ingestion, because a browser in trouble
    has to be able to say so. The blast radius is bounded on every side:
    the recipient is fixed in configuration, the body is capped, and each
    client gets its own small per-minute budget.

    Raises:
        HTTPException: 503 when no SMTP transport (or no recipient) is
            configured, so an undeliverable report fails visibly at the
            button instead of vanishing; 502 when the send itself fails.
    """
    owner = client_id(request) or "anonymous"
    _check_report_rate(request)
    recipient = settings.log_report_email
    if not (recipient and email_notifications_configured()):
        raise HTTPException(
            status_code=503, detail="email delivery is not configured"
        )
    try:
        await deliver_email(recipient, _report_subject(request), req.report)
    except Exception as exc:
        logger.warning("Diagnostic report could not be sent: %s", exc)
        raise HTTPException(
            status_code=502, detail="the report could not be sent"
        ) from exc
    # Do not echo the emailed body into logs: it already contains a copy of
    # them.
    logger.info(
        "Diagnostic report sent to the operator (%s chars) from %s",
        len(req.report),
        owner,
    )
    return {"status": "sent", "chars": len(req.report)}


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
    query: Annotated[LogQuery, Query()],
) -> dict[str, Any]:
    """Return persisted application log records, oldest-first.

    Operators (loopback callers, or holders of ``LOGS_ADMIN_TOKEN`` via
    the ``X-Logs-Token`` header) get the app-wide view. Every other
    caller sees only their own records: those they submitted and those
    belonging to runs they own. The default view also hides high-volume
    noise (HTTP access records, UI clicks/navigation, dependency
    chatter) below WARNING; ``verbose=1`` returns everything visible.
    """
    return logs_payload(query, scope_client_id=_scope_for(request))


__all__ = ["_check_ingest_rate", "_check_report_rate"]
