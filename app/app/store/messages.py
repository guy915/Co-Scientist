from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from app.store.db import _now, _use_conn, connect
from app.store.models import MessageRow, _row_to_message


@dataclass(frozen=True)
class NewMessage:
    run_id: str
    sender: str
    content: str
    kind: str
    meta: dict[str, Any] | None = None


def append_message(
    message: NewMessage, db_path: str | None = None
) -> MessageRow:
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


_MESSAGE_COLUMNS = (
    "id, run_id, sender, content, kind, created_at, applied, meta_json, "
    "applied_at, applied_decision"
)


def list_messages(
    run_id: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[MessageRow]:
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
    """Acknowledge guidance in the checkpoint transaction; a separate commit
    could mark input applied before its state survives.
    """
    if not ids:
        return
    placeholders = ",".join("?" * len(ids))
    with _use_conn(conn, db_path) as conn:
        conn.execute(
            "UPDATE messages SET applied=1, applied_at=?, applied_decision=? "
            f"WHERE id IN ({placeholders})",
            (_now(), decision, *ids),
        )
