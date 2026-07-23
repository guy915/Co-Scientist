"""Durable Agent-interview sessions and append-only transcript turns."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.store.db import _now, _use_conn, connect


@dataclass(frozen=True)
class _NewInterviewFields:
    """Fields needed to insert an interview and its opening turn."""

    interview_id: str
    client_id: str
    challenge: str
    audience: str | None
    fields: dict[str, Any]
    now: float


def _insert_interview_rows(
    conn: sqlite3.Connection, f: _NewInterviewFields
) -> None:
    """Insert the interview row and its opening transcript turn."""
    conn.execute(
        "INSERT INTO interviews (id, client_id, status, fields_json, "
        "audience, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        (
            f.interview_id,
            f.client_id,
            "active",
            json.dumps(f.fields),
            f.audience,
            f.now,
            f.now,
        ),
    )
    conn.execute(
        "INSERT INTO interview_turns (interview_id, role, content, "
        "created_at) VALUES (?,?,?,?)",
        (f.interview_id, "user", f.challenge.strip(), f.now),
    )


def create_interview(
    client_id: str,
    challenge: str,
    *,
    audience: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Create an active interview seeded with the scientist's challenge.

    Args:
        client_id: The owning client.
        challenge: The scientist's opening research challenge.
        audience: The self-declared audience, stored so every turn of this
            interview is conducted with the same injected lab context.
        db_path: Optional database override.

    Returns:
        The created interview row.
    """
    interview_id = str(uuid.uuid4())
    now = _now()
    fields: dict[str, Any] = {
        "research_challenge": challenge.strip(),
        "focus_area": [],
        "preferences": [],
        "title": None,
    }
    with connect(db_path) as conn:
        _insert_interview_rows(
            conn,
            _NewInterviewFields(
                interview_id=interview_id,
                client_id=client_id,
                challenge=challenge,
                audience=audience,
                fields=fields,
                now=now,
            ),
        )
    result = get_interview(interview_id, db_path=db_path)
    assert result is not None
    return result


def get_interview(
    interview_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any] | None:
    """Return one interview with its decoded fields and full transcript."""
    with _use_conn(conn, db_path) as active:
        row = active.execute(
            "SELECT * FROM interviews WHERE id=?", (interview_id,)
        ).fetchone()
        if row is None:
            return None
        turns = active.execute(
            "SELECT id, role, content, created_at FROM interview_turns "
            "WHERE interview_id=? ORDER BY id ASC",
            (interview_id,),
        ).fetchall()
    result = dict(row)
    result["fields"] = json.loads(result.pop("fields_json"))
    result["turns"] = [dict(turn) for turn in turns]
    return result


def append_interview_turn(
    interview_id: str,
    role: str,
    content: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Append one immutable interview turn."""
    now = _now()
    with _use_conn(conn, db_path) as active:
        active.execute(
            "INSERT INTO interview_turns (interview_id, role, content, "
            "created_at) VALUES (?,?,?,?)",
            (interview_id, role, content.strip(), now),
        )
        active.execute(
            "UPDATE interviews SET updated_at=? WHERE id=?", (now, interview_id)
        )


def update_interview(
    interview_id: str,
    fields: Mapping[str, Any],
    current_question: str | None,
    *,
    completed: bool = False,
    db_path: str | None = None,
) -> None:
    """Persist the latest structured derivation and interview state."""
    now = _now()
    status = "completed" if completed else "active"
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE interviews SET fields_json=?, current_question=?, "
            "status=?, updated_at=?, completed_at=? WHERE id=?",
            (
                json.dumps(dict(fields)),
                current_question,
                status,
                now,
                now if completed else None,
                interview_id,
            ),
        )
