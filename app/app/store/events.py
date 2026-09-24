"""Append-only run event log.

The run_events table is the canonical timeline the SSE endpoint replays
on client reconnect or restart; rows are only ever appended, with a
per-run monotonic sequence number assigned at insert time.

Every appended event is also mirrored into the persisted application log
as a compact ``app.run_stage`` record, so a run's stage narrative
(generate, reflection, ranking, ...) is readable from the Logs panel and
``cosci logs`` — the event stream itself is only reachable over SSE.
Payloads are summarized rather than serialized: the mirrored line must
stay cheap to read, since the whole point is that following a run should
not cost what replaying its events does.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
from typing import Any

from app.store.db import _now, _use_conn, connect
from app.store.event_activity import activity_for_event

_stage_logger = logging.getLogger("app.run_stage")

# Caps for the mirrored line: bulk collections become their size, long
# strings are clipped, and the whole message is bounded.
_STAGE_MAX_CHARS = 200
_STAGE_VALUE_MAX_CHARS = 60


def _summarize_string_value(key: str, value: str) -> str | None:
    """Render a string payload entry compactly, or None to omit it."""
    text = " ".join(value.split())
    if not text:
        return None
    if len(text) > _STAGE_VALUE_MAX_CHARS:
        text = text[:_STAGE_VALUE_MAX_CHARS] + "..."
    return f"{key}={text}"


def _summarize_value(key: str, value: Any) -> str | None:
    """Render one payload entry compactly, or None to omit it."""
    if isinstance(value, (bool, int, float)):
        return f"{key}={value}"
    if isinstance(value, str):
        return _summarize_string_value(key, value)
    if isinstance(value, (list, dict)):
        # Size, never contents: payloads carry whole hypothesis and
        # match collections.
        return f"{key}={len(value)}"
    return None


def summarize_stage_payload(payload: dict[str, Any]) -> str:
    """Summarize an event payload as a short ``key=value`` string.

    Whole pairs are dropped once the budget is spent rather than cutting
    mid-pair, which would read as a key whose value went missing.
    """
    parts: list[str] = []
    used = 0
    for key, value in payload.items():
        rendered = _summarize_value(key, value)
        if rendered is None:
            continue
        cost = len(rendered) + (1 if parts else 0)
        if used + cost > _STAGE_MAX_CHARS:
            parts.append("...")
            break
        parts.append(rendered)
        used += cost
    return " ".join(parts)


def _log_stage(run_id: str, type_: str, payload: dict[str, Any]) -> None:
    """Mirror one event into the app log as an ``app.run_stage`` record.

    Imported lazily because ``app.logging_setup`` imports ``app.store``;
    binding the run id through ``run_log_context`` keeps the record
    run-scoped even when the caller is outside a run context.
    """
    from app.logging_setup import run_log_context

    summary = summarize_stage_payload(payload)
    message = f"{type_} {summary}".strip()
    # Both bindings are needed: `extra` makes the record self-describing
    # for any handler, while the context satisfies the RunIdFilter that
    # handlers attach (it would otherwise overwrite run_id with None).
    with run_log_context(run_id):
        _stage_logger.info("%s", message, extra={"run_id": run_id})


def _append_event(
    conn: sqlite3.Connection,
    run_id: str,
    type_: str,
    payload: dict[str, Any],
    created_at: float,
) -> int:
    """Insert an event row on an open connection and return its seq.

    Assigns the next per-run sequence number and inserts in a single statement,
    so the run's hottest write path makes one round-trip instead of a separate
    SELECT then INSERT. The sequence floor also covers the checkpoints table's
    ``last_event_seq`` high-water mark: a resume clears ``run_events``, so
    without it a resumed run would restart at seq 1 and break clients
    reconnecting with ``?after=`` (both indexed lookups; the scalar ``MAX(a,
    b)`` picks the higher floor).
    """
    # The activity discriminator is computed once here -- the single seam
    # every event write passes through -- and merged into the payload
    # rather than a new column, so replay/SSE/the schema are untouched.
    payload = {**payload, "activity": activity_for_event(type_, payload)}
    row = conn.execute(
        "INSERT INTO run_events (run_id, seq, type, payload_json, created_at) "
        "VALUES (?, 1 + MAX("
        "(SELECT COALESCE(MAX(seq), 0) FROM run_events WHERE run_id=?), "
        "(SELECT COALESCE(MAX(last_event_seq), 0) FROM checkpoints "
        "WHERE run_id=?)), ?, ?, ?) RETURNING seq",
        (run_id, run_id, run_id, type_, json.dumps(payload), created_at),
    ).fetchone()
    # Mirroring is best-effort: this is the canonical timeline, and a
    # logging failure must never take its write down.
    with contextlib.suppress(Exception):
        _log_stage(run_id, type_, payload)
    return int(row["seq"])


def append_event(
    run_id: str,
    type_: str,
    payload: dict[str, Any],
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Append an event to a run's append-only event log.

    Args:
        run_id: Identifier of the run the event belongs to.
        type_: Event type, e.g. an agent name, 'status', or 'log'.
        payload: Event payload serialized to JSON.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to join an existing transaction.

    Returns:
        The monotonically increasing sequence number assigned to the event.
    """
    with _use_conn(conn, db_path) as active:
        return _append_event(active, run_id, type_, payload, _now())


def latest_event_seq(
    run_id: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Return the highest event sequence for a run, or 0 if it has none.

    Used as the ``last_event_seq`` high-water mark when checkpointing a run,
    so a resumed run assigns new event seqs strictly above it.
    """
    with _use_conn(conn, db_path) as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM run_events WHERE run_id=?",
            (run_id,),
        ).fetchone()
    return int(row[0])


def latest_status_event(
    run_id: str,
    conn: sqlite3.Connection | None = None,
    db_path: str | None = None,
) -> dict[str, Any] | None:
    """Return the newest persisted status payload for a run, if any."""
    with _use_conn(conn, db_path) as active:
        row = active.execute(
            "SELECT payload_json FROM run_events "
            "WHERE run_id=? AND type='status' ORDER BY seq DESC LIMIT 1",
            (run_id,),
        ).fetchone()
    return json.loads(row["payload_json"]) if row is not None else None


def list_events(
    run_id: str,
    after_seq: int = 0,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    """Return a run's events ordered by sequence number.

    Args:
        run_id: Identifier of the run whose events to list.
        after_seq: Only return events with a sequence number greater than this.
        db_path: Optional override for the SQLite database path.

    Returns:
        A list of event dicts with seq, type, payload, and created_at keys.
    """
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT seq, type, payload_json, created_at FROM run_events "
            "WHERE run_id=? AND seq > ? ORDER BY seq ASC",
            (run_id, after_seq),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "seq": r["seq"],
                    "type": r["type"],
                    "payload": json.loads(r["payload_json"]),
                    "created_at": r["created_at"],
                }
            )
        return out


def recent_events(
    run_id: str,
    limit: int,
    conn: sqlite3.Connection | None = None,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    """Return a run's most recent events, oldest-first within the window.

    Bounded counterpart to :func:`list_events`, which returns every event a
    run ever emitted. A long run emits thousands, and the Q&A prompt only
    ever renders the tail, so reading (and JSON-decoding) the whole log per
    question is work with nowhere to go.

    Args:
        run_id: Identifier of the run whose events to read.
        limit: Maximum number of events to return, counted from the newest.
        conn: Optional open connection to reuse.
        db_path: Optional override for the SQLite database path.

    Returns:
        Up to ``limit`` event dicts (seq, type, payload, created_at),
        ordered oldest-first so callers read them as a narrative.
    """
    with _use_conn(conn, db_path) as active:
        rows = active.execute(
            "SELECT seq, type, payload_json, created_at FROM run_events "
            "WHERE run_id=? ORDER BY seq DESC LIMIT ?",
            (run_id, limit),
        ).fetchall()
    return [
        {
            "seq": r["seq"],
            "type": r["type"],
            "payload": json.loads(r["payload_json"]),
            "created_at": r["created_at"],
        }
        for r in reversed(rows)
    ]


def run_execution_started_at(
    run_id: str,
    conn: sqlite3.Connection | None = None,
    db_path: str | None = None,
) -> float | None:
    """Return when a run began executing, or None if it never started.

    The run row's ``created_at`` is when the *draft* was created, which can
    precede the start by any amount -- a plan reviewed over lunch and then
    started reports hours of "elapsed" that nothing was working for. The
    first ``lifecycle`` event is appended by the start endpoint (``queued``),
    so its timestamp is the honest clock start.

    Args:
        run_id: Identifier of the run.
        conn: Optional open connection to reuse.
        db_path: Optional override for the SQLite database path.

    Returns:
        The epoch seconds the run was queued for execution, or None.
    """
    with _use_conn(conn, db_path) as active:
        row = active.execute(
            "SELECT MIN(created_at) AS started FROM run_events "
            "WHERE run_id=? AND type='lifecycle'",
            (run_id,),
        ).fetchone()
    started = row["started"] if row is not None else None
    return float(started) if started is not None else None
