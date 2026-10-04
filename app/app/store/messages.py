from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from app.store.db import _now, _use_conn, connect, transaction
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


def rewind_qa(
    run_id: str,
    message_id: int,
    question: str | None,
    db_path: str | None = None,
) -> MessageRow:
    """Rewind only Q&A; run inputs and scientific state are immutable here."""
    with transaction(db_path) as conn:
        target = conn.execute(
            "SELECT sender, content, kind FROM messages "
            "WHERE run_id=? AND id=?",
            (run_id, message_id),
        ).fetchone()
        if target is None or target["kind"] != "qa":
            raise ValueError("Only Q&A turns can be revised")
        if question is not None:
            if target["sender"] != "user":
                raise ValueError("Only user questions can be edited")
            question_id = message_id
            text = question
        else:
            if target["sender"] != "system":
                raise ValueError("Only answers can be retried")
            previous = conn.execute(
                "SELECT id, content FROM messages WHERE run_id=? AND kind='qa' "
                "AND sender='user' AND id<? ORDER BY id DESC LIMIT 1",
                (run_id, message_id),
            ).fetchone()
            if previous is None:
                raise ValueError("Answer has no preceding question")
            question_id, text = previous["id"], previous["content"]
        conn.execute(
            "DELETE FROM messages WHERE run_id=? AND kind='qa' AND id>=?",
            (run_id, question_id),
        )
        cursor = conn.execute(
            "INSERT INTO messages "
            "(run_id,sender,content,kind,created_at,applied) "
            "VALUES (?,'user',?,'qa',?,0)",
            (run_id, text, _now()),
        )
        row = conn.execute(
            f"SELECT {_MESSAGE_COLUMNS} FROM messages WHERE id=?",
            (cursor.lastrowid,),
        ).fetchone()
        return _row_to_message(row)


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
