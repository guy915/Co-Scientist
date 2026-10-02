"""Run chat messages: user steering requests and Q&A exchanges.

The messages table stores both kinds of chat rows; `kind` distinguishes
'steering' (consumed by the workflow between iterations, then marked
applied) from 'qa' (answered inline, never marked applied).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from app.store.db import _now, _use_conn, connect
from app.store.models import MessageRow, _row_to_message


@dataclass(frozen=True)
class NewMessage:
    """One chat message to append to a run.

    ``kind`` distinguishes 'steering' from 'qa'; ``meta`` is optional
    structured metadata persisted as JSON (e.g. the cited sources for a
    Q&A answer) so it survives reloads and restarts.
    """

    run_id: str
    sender: str
    content: str
    kind: str
    meta: dict[str, Any] | None = None


def append_message(
    message: NewMessage, db_path: str | None = None
) -> MessageRow:
    """Append a message to a run and return the stored row.

    Args:
        message: The message to append (see :class:`NewMessage`).
        db_path: Optional override for the SQLite database path.

    Returns:
        The newly inserted message as a MessageRow.
    """
    now = _now()
    with connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO messages (run_id, sender, content, kind, "
            "created_at, applied, meta_json) VALUES (?,?,?,?,?,0,?)",
            (
                message.run_id,
                message.sender,
                message.content,
                message.kind,
                now,
                json.dumps(message.meta) if message.meta is not None else None,
            ),
        )
        msg_id = cursor.lastrowid or 0
    return MessageRow(
        id=msg_id,
        run_id=message.run_id,
        sender=message.sender,
        content=message.content,
        kind=message.kind,
        created_at=now,
        applied=False,
        meta=message.meta,
    )


# Explicit column list shared by the message queries below, so they stay in
# lockstep with what _row_to_message reads.
_MESSAGE_COLUMNS = (
    "id, run_id, sender, content, kind, created_at, applied, meta_json, "
    "applied_at, applied_decision"
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


def mark_steering_applied(
    ids: list[int],
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
    *,
    decision: str | None = None,
) -> None:
    """Mark steering messages as consumed so they are not applied twice.

    ``conn`` exists so the acknowledgement can join the transaction that
    commits the checkpoint carrying the guidance. Acknowledging on its own
    connection meant the two committed separately: a worker that died
    between them left the message applied and its guidance in a state that
    was never written, so the scientist's steer was silently dropped.

    ``decision`` is the scheduling decision this acknowledgement fed (the
    orchestrator's ``next_task``, e.g. "generate") -- HITL-STEERING-001's
    "how it changed the plan", recorded on the message row itself rather
    than left for a reader to correlate against the event stream. Optional
    because the only caller that can supply it (``_ack_consumed_steering``)
    sometimes has nothing fresh to report (a pause ahead of a decision).
    """
    if not ids:
        return
    # Message ids are integers from our own DB, so building the IN list via
    # placeholders (one '?' per id) stays fully parameterized.
    placeholders = ",".join("?" * len(ids))
    with _use_conn(conn, db_path) as conn:
        conn.execute(
            "UPDATE messages SET applied=1, applied_at=?, applied_decision=? "
            f"WHERE id IN ({placeholders})",
            (_now(), decision, *ids),
        )
