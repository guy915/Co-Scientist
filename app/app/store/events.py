"""Append-only run event log.

The run_events table is the canonical timeline the SSE endpoint replays
on client reconnect or restart; rows are only ever appended, with a
per-run monotonic sequence number assigned at insert time.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.store.db import _now, _use_conn, connect


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
    row = conn.execute(
        "INSERT INTO run_events (run_id, seq, type, payload_json, created_at) "
        "VALUES (?, 1 + MAX("
        "(SELECT COALESCE(MAX(seq), 0) FROM run_events WHERE run_id=?), "
        "(SELECT COALESCE(MAX(last_event_seq), 0) FROM checkpoints "
        "WHERE run_id=?)), ?, ?, ?) RETURNING seq",
        (run_id, run_id, run_id, type_, json.dumps(payload), created_at),
    ).fetchone()
    return int(row["seq"])


def append_event(
    run_id: str,
    type_: str,
    payload: dict[str, Any],
    db_path: str | None = None,
) -> int:
    """Append an event to a run's append-only event log.

    Args:
        run_id: Identifier of the run the event belongs to.
        type_: Event type, e.g. an agent name, 'status', or 'log'.
        payload: Event payload serialized to JSON.
        db_path: Optional override for the SQLite database path.

    Returns:
        The monotonically increasing sequence number assigned to the event.
    """
    with connect(db_path) as conn:
        return _append_event(conn, run_id, type_, payload, _now())


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
