"""An owner gets one private copy of each curated example."""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from app.store import db, interviews, runs
from app.store.models import DEMO_CLIENT_ID
from app.store.runs import RunCreateOptions

# Copy scientific artifacts only. No credentials, tasks or logs.
_TABLES = (
    "hypotheses",
    "hypothesis_state",
    "evidence",
    "citations",
    "reviews",
    "matches",
    "safety_decisions",
    "claim_evidence",
    "knowledge_facts",
    "proximity_edges",
    "run_metrics",
    "reports",
    "run_events",
    "messages",
    "supervisor_plan",
    "supervisor_allocations",
    "retrieval_calls",
)


def _remap(value: Any, identities: dict[str, str]) -> Any:
    if isinstance(value, str):
        for old, new in identities.items():
            value = value.replace(old, new)
    return value


def _insert_copy(
    conn: sqlite3.Connection,
    table: str,
    row: dict[str, Any],
    identities: dict[str, str],
) -> None:
    copied = {
        key: _remap(value, identities)
        for key, value in row.items()
        if key != "id" or not isinstance(value, int)
    }
    conn.execute(
        f"INSERT INTO {table} ({','.join(copied)}) VALUES ({','.join('?' for _ in copied)})",
        tuple(copied.values()),
    )


def _example_source(conn: sqlite3.Connection, source_id: str) -> tuple[sqlite3.Row, dict[str, Any]]:
    source_row = conn.execute(
        "SELECT * FROM runs WHERE id=? AND client_id=?",
        (source_id, DEMO_CLIENT_ID),
    ).fetchone()
    if source_row is None:
        raise ValueError("example not found")
    source_config = json.loads(source_row["config_json"])
    if source_row["status"] != "completed" or not source_config.get("example_chat_version"):
        raise ValueError("example chat is not available")
    interview = interviews.get_interview(str(source_config.get("interview_id") or ""), conn=conn)
    if interview is None or interview["client_id"] != DEMO_CLIENT_ID:
        raise ValueError("example chat is not available")
    return source_row, interview


def open_example_chat(source_id: str, owner: str, *, db_path: str | None = None) -> dict[str, Any]:
    if not owner or owner == DEMO_CLIENT_ID:
        raise ValueError("an owned example chat is required")
    # Reuse checks and the entire copy commit together. A double click or two
    # tabs cannot duplicate chats. No network occurs inside this lock.
    with db.transaction(db_path) as conn:
        conn.execute("PRAGMA defer_foreign_keys=ON")
        source_row, interview = _example_source(conn, source_id)
        existing = conn.execute(
            "SELECT id,config_json FROM runs WHERE client_id=? AND "
            "json_extract(config_json, '$.example_source_id')=?",
            (owner, source_id),
        ).fetchone()
        if existing:
            existing_config = json.loads(existing["config_json"])
            result = interviews.get_interview(existing_config["interview_id"], conn=conn)
            if result:
                opened_at = db._now()
                conn.execute(
                    "UPDATE interviews SET updated_at=? WHERE id=?",
                    (opened_at, result["id"]),
                )
                conn.execute(
                    "UPDATE runs SET updated_at=? WHERE id=?",
                    (opened_at, existing["id"]),
                )
                return {**result, "updated_at": opened_at}
        interview_id = str(uuid.uuid4())
        config = {
            **json.loads(source_row["config_json"]),
            "interview_id": interview_id,
            "example_source_id": source_id,
        }
        target = runs.create_run(
            source_row["research_goal"],
            source_row["profile"],
            source_row["provider"],
            config,
            RunCreateOptions(
                client_id=owner,
                title=source_row["title"],
                llm_backend="offline",
                conn=conn,
            ),
        )
        identities = {source_id: target.id, interview["id"]: interview_id}
        rows: dict[str, list[dict[str, Any]]] = {}
        for table in _TABLES:
            predicate = (
                "hypothesis_id IN (SELECT id FROM hypotheses WHERE run_id=?)"
                if table == "hypothesis_state"
                else "run_id=?"
            )
            rows[table] = [
                dict(row)
                for row in conn.execute(f"SELECT * FROM {table} WHERE {predicate}", (source_id,))
            ]
            for row in rows[table]:
                if isinstance(row.get("id"), str):
                    identities[row["id"]] = str(uuid.uuid4())
        interview_row = dict(
            conn.execute("SELECT * FROM interviews WHERE id=?", (interview["id"],)).fetchone()
        )
        interview_row.update(
            client_id=owner,
            created_at=target.created_at,
            updated_at=target.updated_at,
            completed_at=target.updated_at,
        )
        _insert_copy(conn, "interviews", interview_row, identities)
        for turn in conn.execute(
            "SELECT * FROM interview_turns WHERE interview_id=? ORDER BY id",
            (interview["id"],),
        ).fetchall():
            _insert_copy(conn, "interview_turns", dict(turn), identities)
        for table, table_rows in rows.items():
            for row in table_rows:
                _insert_copy(conn, table, row, identities)
        conn.execute(
            "UPDATE runs SET status='completed',created_at=?,completed_at=?,"
            "goal_restatement=? WHERE id=?",
            (
                source_row["created_at"],
                source_row["completed_at"],
                source_row["goal_restatement"],
                target.id,
            ),
        )
        result = interviews.get_interview(interview_id, conn=conn)
        assert result is not None
        return result
