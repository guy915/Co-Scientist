"""Durable Agent-interview sessions and append-only transcript turns."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.store.db import _now, _use_conn, connect


@dataclass(frozen=True)
class _NewInterviewFields:
    """Fields needed to insert an interview and its opening turn."""

    interview_id: str
    client_id: str
    challenge: str
    fields: dict[str, Any]
    now: float


def _insert_interview_rows(
    conn: sqlite3.Connection, f: _NewInterviewFields
) -> None:
    """Insert the interview row and its opening transcript turn."""
    conn.execute(
        "INSERT INTO interviews (id, client_id, status, fields_json, "
        "created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (
            f.interview_id,
            f.client_id,
            "active",
            json.dumps(f.fields),
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
    db_path: str | None = None,
) -> dict[str, Any]:
    """Create an active interview seeded with the scientist's challenge.

    Args:
        client_id: The owning client.
        challenge: The scientist's opening research challenge.
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
        # K5: lab constraints are elicited during the interview; the empty
        # list is the "none declared" state and threads to the engine as
        # "no constraints" (the prompts render unchanged).
        "lab_constraints": [],
        "title": None,
    }
    with connect(db_path) as conn:
        _insert_interview_rows(
            conn,
            _NewInterviewFields(
                interview_id=interview_id,
                client_id=client_id,
                challenge=challenge,
                fields=fields,
                now=now,
            ),
        )
        # Read back on the same connection: the write is already committed
        # (the store connects in autocommit), so opening a second one only
        # bought another connect/pragma round trip.
        result = get_interview(interview_id, conn=conn)
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
            "SELECT id, role, content, reasoning, fallback, questions_json, "
            "created_at FROM interview_turns WHERE interview_id=? "
            "ORDER BY id ASC",
            (interview_id,),
        ).fetchall()
    result = dict(row)
    result["fields"] = json.loads(result.pop("fields_json"))
    # Normalize the stored 0/1 into a JSON boolean so every payload the
    # frontend reads (interview GET, streamed turn frames) carries a real
    # true/false marker.
    result["turns"] = [_decoded_turn(turn) for turn in turns]
    return result


def _decoded_turn(turn: sqlite3.Row) -> dict[str, Any]:
    """Render one stored turn as the payload every client reads.

    The stored 0/1 fallback marker becomes a real JSON boolean, and the
    questions column becomes a list -- empty rather than null, so the
    frontend maps over it without a null branch. Both the interview GET and
    the streamed turn's closing frame go through here, so the two can never
    describe the same turn differently.
    """
    row = dict(turn)
    raw = row.pop("questions_json", None)
    return {
        **row,
        "fallback": bool(turn["fallback"]),
        "questions": json.loads(raw) if raw else [],
    }


def _interview_run_ids(
    conn: sqlite3.Connection, client_id: str
) -> dict[str, str]:
    """Map interview id to the run started from it, for one client.

    The link lives in the run's config blob (``config["interview_id"]``,
    written by ``app.runs_crud``), so it is resolved in Python rather than
    with json_extract -- one client's runs are a handful of rows, and this
    keeps the listing free of a JSON1 build dependency.
    """
    rows = conn.execute(
        "SELECT id, config_json FROM runs WHERE client_id=? "
        "ORDER BY created_at ASC",
        (client_id,),
    ).fetchall()
    links: dict[str, str] = {}
    for row in rows:
        try:
            config = json.loads(row["config_json"])
        except (TypeError, ValueError):
            continue
        interview_id = config.get("interview_id") if config else None
        if interview_id:
            links[str(interview_id)] = str(row["id"])
    return links


def run_id_for_interview(
    interview_id: str,
    client_id: str,
    *,
    db_path: str | None = None,
) -> str | None:
    """Return the run started from one interview, or None.

    Kept out of ``get_interview`` deliberately: that reader is on the
    per-turn and engine-adapter paths, and the link costs a scan of the
    client's runs (see ``_interview_run_ids``). Only the chat-reopening
    endpoint needs the answer, and it asks once.
    """
    if not client_id:
        return None
    with connect(db_path) as conn:
        return _interview_run_ids(conn, client_id).get(str(interview_id))


def _chat_summary(row: sqlite3.Row, run_id: str | None) -> dict[str, Any]:
    """Build one chat-list entry from an interview row and its run link."""
    fields = json.loads(row["fields_json"])
    return {
        "id": row["id"],
        "title": str(fields.get("title") or "").strip() or None,
        "challenge": str(fields.get("research_challenge") or ""),
        "status": row["status"],
        "run_id": run_id,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_interviews(
    client_id: str,
    *,
    limit: int = 200,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    """Return one client's chats, newest first, without their transcripts.

    Args:
        client_id: The owning client; rows are never returned across clients.
        limit: Maximum chats returned.
        db_path: Optional database override.

    Returns:
        Chat summaries carrying the run each chat started, when it started
        one, so the sidebar can link a chat through to its run.
    """
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, status, fields_json, created_at, updated_at "
            "FROM interviews WHERE client_id=? "
            "ORDER BY updated_at DESC LIMIT ?",
            (client_id, limit),
        ).fetchall()
        links = _interview_run_ids(conn, client_id)
    return [_chat_summary(row, links.get(str(row["id"]))) for row in rows]


@dataclass(frozen=True)
class NewInterviewTurn:
    """One turn to append to an interview transcript.

    Attributes:
        role: ``user`` or ``agent``.
        content: The turn's visible text.
        reasoning: The Agent's chain of thought for this turn, when the
            model emitted one. Stored so a resumed chat replays the thinking
            it showed and the next turn is derived from it.
        fallback: True when the deterministic recovery path authored this
            Agent turn because no model could be reached. Persisted per
            turn so the UI can signal exactly which turns are scripted;
            always False for user turns.
        questions: The structured multiple-choice questions this Agent turn
            offered the scientist, if any. Persisted with the turn that
            asked them so a reopened chat re-offers the pending one rather
            than showing a question with no way to answer it.
    """

    role: str
    content: str
    reasoning: str | None = None
    fallback: bool = False
    questions: list[dict[str, Any]] = field(default_factory=list)


def append_interview_turn(
    interview_id: str,
    turn: NewInterviewTurn,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Append one immutable interview turn.

    Args:
        interview_id: The interview the turn belongs to.
        turn: The role, text, reasoning, and fallback provenance to record.
        db_path: Optional database override.
        conn: Optional open connection to reuse.
    """
    now = _now()
    with _use_conn(conn, db_path) as active:
        active.execute(
            "INSERT INTO interview_turns (interview_id, role, content, "
            "reasoning, fallback, questions_json, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                interview_id,
                turn.role,
                turn.content.strip(),
                turn.reasoning or None,
                int(turn.fallback),
                json.dumps(turn.questions) if turn.questions else None,
                now,
            ),
        )
        active.execute(
            "UPDATE interviews SET updated_at=? WHERE id=?", (now, interview_id)
        )


def rewind_interview(
    interview_id: str,
    turn_id: int,
    *,
    db_path: str | None = None,
) -> int:
    """Discard one turn and every turn after it.

    The transcript is otherwise append-only, and stays so for the ordinary
    path: this exists for the two places a scientist revises the
    conversation itself rather than adding to it -- editing an earlier
    prompt, and retrying an answer. Both mean "the conversation did not go
    this way", so the turns downstream of the edited one were derived from
    something that no longer exists and cannot be kept.

    The interview's own status is left to the caller, which re-derives the
    four fields from what remains (see ``interviews._reset_derivation``).

    Args:
        interview_id: The interview to rewind.
        turn_id: The first turn to discard; it goes too.
        db_path: Optional database override.

    Returns:
        How many turns were discarded; zero when the turn did not belong to
        this interview.
    """
    now = _now()
    with connect(db_path) as conn:
        removed = conn.execute(
            "DELETE FROM interview_turns WHERE interview_id=? AND id>=?",
            (interview_id, turn_id),
        ).rowcount
        if removed:
            conn.execute(
                "UPDATE interviews SET updated_at=? WHERE id=?",
                (now, interview_id),
            )
    return int(removed)


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


def delete_interview(
    interview_id: str, *, db_path: str | None = None
) -> dict[str, int]:
    """Permanently delete a chat and its transcript.

    ``interview_turns`` declares ``ON DELETE CASCADE`` against this table
    and foreign keys are enforced on every connection this store hands out
    (see ``app.store.db._open_raw_connection``), so deleting the interview
    row is enough to take the transcript with it.

    ``staged_documents`` deliberately carries no foreign key -- a document
    is staged before any interview or run exists (see
    ``app.store.documents``) -- so a deleted chat's reference is cleared
    explicitly rather than left dangling. The document itself survives: it
    may be the caller's only copy, it is deletable on its own, and a chat
    that was carried into a run left that run holding the same document.

    Args:
        interview_id: Identifier of the chat to delete.
        db_path: Optional override for the SQLite database path.

    Returns:
        Table name -> rows removed, so a caller can prove the cascade ran.
    """
    with connect(db_path) as conn:
        turns = conn.execute(
            "SELECT COUNT(*) FROM interview_turns WHERE interview_id=?",
            (interview_id,),
        ).fetchone()[0]
        detached = conn.execute(
            "UPDATE staged_documents SET interview_id=NULL "
            "WHERE interview_id=?",
            (interview_id,),
        ).rowcount
        removed = conn.execute(
            "DELETE FROM interviews WHERE id=?", (interview_id,)
        ).rowcount
    return {
        "interviews": int(removed),
        "interview_turns": int(turns),
        "staged_documents_detached": int(detached),
    }
