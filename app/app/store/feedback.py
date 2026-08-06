"""Pilot feedback notes submitted from the workspace.

Rows are standalone: a note is not attached to a run, since testers send
them from the header while doing anything at all. `audience` records the
mode the sender was in, so SBI/UCD pilot notes stay distinguishable from
anything submitted in another mode.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.store.db import _now, _use_conn, connect


def append_feedback(
    client_id: str,
    audience: str,
    category: str,
    message: str,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Store one feedback note and return the stored row.

    Args:
        client_id: Browser identity of the sender, for grouping notes from
            one tester without requiring an account.
        audience: The sender's declared audience at submission time.
        category: Note category, e.g. 'bug'.
        message: The note body.
        db_path: Optional override for the SQLite database path.

    Returns:
        The newly inserted note, including its assigned id.
    """
    now = _now()
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO feedback (client_id, audience, category, message, "
            "created_at) VALUES (?,?,?,?,?)",
            (client_id, audience, category, message, now),
        )
        note_id = cur.lastrowid or 0
    return {
        "id": note_id,
        "client_id": client_id,
        "audience": audience,
        "category": category,
        "message": message,
        "created_at": now,
    }


def list_feedback(
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return all feedback notes, newest first."""
    with _use_conn(conn, db_path) as conn:
        rows = conn.execute(
            "SELECT id, client_id, audience, category, message, created_at "
            "FROM feedback ORDER BY id DESC"
        ).fetchall()
        return [dict(row) for row in rows]


def list_feedback_for_client(
    client_id: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return one caller's own feedback notes, newest first.

    Feedback has always been write-only from the submitter's side (see the
    module docstring); this is the read half a submitter can use to see
    what they sent, ahead of deleting it.
    """
    with _use_conn(conn, db_path) as active:
        rows = active.execute(
            "SELECT id, client_id, audience, category, message, created_at "
            "FROM feedback WHERE client_id=? ORDER BY id DESC",
            (client_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_feedback(
    feedback_id: int, client_id: str, db_path: str | None = None
) -> bool:
    """Delete one feedback note the caller submitted.

    Args:
        feedback_id: Id of the note to delete.
        client_id: Submitting identity; a mismatched row is not deleted.
        db_path: Optional override for the SQLite database path.

    Returns:
        True if a row was deleted, False if unknown or submitted by
        another client.
    """
    with connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM feedback WHERE id=? AND client_id=?",
            (feedback_id, client_id),
        )
    return cur.rowcount > 0


def delete_feedback_older_than(
    cutoff: float, db_path: str | None = None
) -> int:
    """Delete every feedback note submitted before ``cutoff``.

    Used by the retention sweep (``app.retention``).

    Returns:
        How many rows were deleted.
    """
    with connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM feedback WHERE created_at < ?", (cutoff,)
        )
    return cur.rowcount
