"""Run chat messages: user steering requests and Q&A exchanges.

The messages table stores both kinds of chat rows; `kind` distinguishes
'steering' (consumed by the workflow between iterations, then marked
applied) from 'qa' (answered inline, never marked applied).
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.store.db import _now, _use_conn, connect
from app.store.models import MessageRow, _row_to_message


def append_message(
    run_id: str,
    sender: str,
    content: str,
    kind: str,
    db_path: str | None = None,
    meta: dict[str, Any] | None = None,
) -> MessageRow:
    """Append a message to a run and return the stored row.

    Args:
        run_id: Identifier of the run the message belongs to.
        sender: Identifier of the message sender.
        content: Message body text.
        kind: Message kind, e.g. 'steering'.
        db_path: Optional override for the SQLite database path.
        meta: Optional structured metadata persisted as JSON (e.g. the cited
            sources for a Q&A answer) so it survives reloads and restarts.

    Returns:
        The newly inserted message as a MessageRow.
    """
    now = _now()
    meta_json = json.dumps(meta) if meta is not None else None
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO messages (run_id, sender, content, kind, "
            "created_at, applied, meta_json) VALUES (?,?,?,?,?,0,?)",
            (run_id, sender, content, kind, now, meta_json),
        )
        msg_id = cur.lastrowid or 0
    return MessageRow(
        id=msg_id,
        run_id=run_id,
        sender=sender,
        content=content,
        kind=kind,
        created_at=now,
        applied=False,
        meta=meta,
    )


# Explicit column list shared by the message queries below, so they stay in
# lockstep with what _row_to_message reads.
_MESSAGE_COLUMNS = (
    "id, run_id, sender, content, kind, created_at, applied, meta_json"
)


def list_messages(
    run_id: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[MessageRow]:
    """Return all of a run's messages in insertion (chronological) order."""
    with _use_conn(conn, db_path) as conn:
        rows = conn.execute(
            f"SELECT {_MESSAGE_COLUMNS} FROM messages "
            "WHERE run_id=? ORDER BY id ASC",
            (run_id,),
        ).fetchall()
        return [_row_to_message(r) for r in rows]


def get_pending_steering(
    run_id: str, db_path: str | None = None
) -> list[MessageRow]:
    """Return unapplied steering messages, oldest first.

    The workflow polls this between iterations to pick up user guidance,
    then acknowledges via ``mark_steering_applied``.
    """
    with connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT {_MESSAGE_COLUMNS} FROM messages "
            "WHERE run_id=? AND kind='steering' AND applied=0 ORDER BY id ASC",
            (run_id,),
        ).fetchall()
        return [_row_to_message(r) for r in rows]


def mark_steering_applied(ids: list[int], db_path: str | None = None) -> None:
    """Mark steering messages as consumed so they are not applied twice."""
    if not ids:
        return
    # Message ids are integers from our own DB, so building the IN list via
    # placeholders (one '?' per id) stays fully parameterized.
    placeholders = ",".join("?" * len(ids))
    with connect(db_path) as conn:
        conn.execute(
            f"UPDATE messages SET applied=1 WHERE id IN ({placeholders})", ids
        )
