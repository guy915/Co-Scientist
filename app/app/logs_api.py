"""HTTP surface for persisted application logs (the ``app_logs`` table).

Owns ``GET /api/logs`` and the payload/filter logic that the run-scoped
``GET /api/runs/{id}/logs`` endpoint (in ``app.runs``) shares, so both
endpoints accept identical query parameters and return the same shape:
``{"logs": [...], "last_id": N, "total": N, "session_total": N}``.
``last_id`` is the table's high-water mark regardless of filters, letting
pollers resume with ``after_id`` even when the newest rows did not match
their filter; ``total`` is the size of the whole matching set, ignoring
the window; ``session_total`` is the size of the set after ``after_id``,
for a poller that counts only what its own cursor has seen.
"""

from __future__ import annotations

import dataclasses
import hmac
import logging
import sqlite3
import time
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app import store
from app.auth import client_id
from app.config import settings
from app.logging_setup import level_to_number
from app.notifications import deliver_email, email_notifications_configured

logger = logging.getLogger(__name__)

router = APIRouter(tags=["logs"])

# Bounds for client-submitted records: enough for a burst of UI events,
# small enough that the open endpoint cannot be used to flood the table.
MAX_CLIENT_BATCH = 50
MAX_CLIENT_MESSAGE_CHARS = 2000

# Ceiling on one emailed diagnostic export. The panel exports its newest
# fifty entries plus a preamble, which lands far below this; the cap is
# here so the endpoint cannot be turned into a mail relay for bulk text.
MAX_REPORT_CHARS = 100_000

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


# Sliding-window counters, keyed by client scope. Ingestion and reporting
# keep separate buckets: one is a background stream of UI records, the other
# a deliberate click that sends mail, and a budget sized for the first would
# be no ceiling at all on the second.
_ingest_hits: dict[str, list[float]] = {}
_report_hits: dict[str, list[float]] = {}

# Reports per client per minute. One click is one report; anything beyond a
# handful is a mistake or an attempt to flood the operator's inbox.
REPORTS_PER_MINUTE = 5


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


def _check_ingest_rate(scope: str) -> None:
    """Raise 429 once a client exceeds the per-minute ingest ceiling."""
    _check_rate(
        _ingest_hits,
        scope,
        settings.logs_ingest_per_minute,
        "log ingestion rate exceeded",
    )


def _check_report_rate(scope: str) -> None:
    """Raise 429 once a client exceeds the per-minute report ceiling."""
    _check_rate(_report_hits, scope, REPORTS_PER_MINUTE, "report rate exceeded")


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
#
# The whole ``co_scientist`` engine namespace is hidden because its
# per-call INFO (per-source literature searches, per-agent tool init,
# per-match ranking) runs into the hundreds within minutes of one run and
# buried the readable stream. The run's narrative is not lost: every stage
# is mirrored into the ``app.run_stage`` logger (~21 records per run, not
# under this prefix, so it stays visible), and any engine WARNING+ still
# surfaces. ``verbose=1`` restores the raw per-call lines.
NOISE_LOGGERS: tuple[str, ...] = (
    "uvicorn.access",
    "ui.interaction",
    "ui.navigation",
    "httpx",
    "httpcore",
    "urllib3",
    "litellm",
    # The engine's per-call chatter, incl. its own availability probes
    # (co_scientist.mcp_client) whose WARNINGs still surface.
    "co_scientist",
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
        """Return the equivalent app-wide query pinned to one run."""
        return LogQuery(run_id=run_id, **self.model_dump())


def _query_logs_payload(
    conn: sqlite3.Connection,
    filters: store.LogFilters,
    limit: int,
) -> dict[str, Any]:
    """Run the four reads backing one logs response on an open connection.

    Args:
        conn: The open connection all four reads share.
        filters: The window and filters of the row query.
        limit: Maximum rows returned (the newest matches, oldest-first).

    Returns:
        The ``{"logs", "last_id", "total", "session_total"}`` payload.
    """
    rows = store.list_logs(filters=filters, limit=limit, conn=conn)
    # `total` counts the whole matching set (no cursor, no limit) so the
    # UI badge shows the true size even when the window is capped.
    total = store.count_logs(
        filters=dataclasses.replace(filters, after_id=0), conn=conn
    )
    # `session_total` keeps the cursor, so a caller polling from a fixed
    # anchor gets the size of its own slice as a first-class number. It is
    # counted here rather than left to the caller to derive by subtracting
    # a start-of-anchor snapshot from `total`: retention pruning and a
    # scoped clear both delete rows below the anchor, which drives such a
    # difference negative and reads as "nothing new" forever.
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
    """Build the shared logs response for the given query.

    Args:
        query: The query window and filters, as the caller sent them.
        scope_client_id: One client's records only; None is the app-wide,
            operator-only view. Derived from the request, never accepted
            as a query parameter.

    Returns:
        The ``{"logs", "last_id", "total", "session_total"}`` payload both
        endpoints return.

    Raises:
        HTTPException: 422 when ``min_level`` is not a known level name.
    """
    # Validated before a connection is opened, so an unknown level name
    # costs nothing but the 422.
    filters = store.LogFilters(
        after_id=query.after_id,
        min_levelno=_min_levelno(query.min_level),
        run_id=query.run_id,
        contains=query.q,
        noise_loggers=None if query.verbose else NOISE_LOGGERS,
        scope_client_id=scope_client_id,
    )
    # One connection for the three reads: the UI polls this continuously.
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
    """Subject line for one report, built entirely server-side.

    Nothing from the request body reaches the headers: the recipient is a
    setting and the subject is assembled here, so a submitted report is only
    ever a message body and cannot inject headers of its own.
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
    _check_report_rate(owner)
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
    # The body is not echoed into the log: it is a copy of the log.
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
