"""Durable outbox records for owner-authorized outcome refinement."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, cast

from app.store.db import _now, _use_conn, transaction
from app.store.events import _append_event


class OutcomeRefinementConflictError(ValueError):
    """An outcome action or request key already belongs to another intent."""


@dataclass(frozen=True)
class NewOutcomeRefinementAction:
    """One immutable request to use an outcome in a targeted follow-up."""

    action_id: str
    run_id: str
    outcome_id: str
    hypothesis_id: str
    owner_id: str
    request_idempotency_key: str
    task_idempotency_key: str
    checkpoint_seq: int
    context_snapshot: str


def _decode_action(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    """Return a durable action row without reinterpreting its snapshot."""
    action = dict(row)
    action["context_codepoints"] = len(action["context_snapshot"])
    return action


def _fetch_by_key(
    conn: sqlite3.Connection, run_id: str, request_idempotency_key: str
) -> sqlite3.Row | None:
    row = conn.execute(
        "SELECT * FROM outcome_refinement_actions "
        "WHERE run_id=? AND request_idempotency_key=?",
        (run_id, request_idempotency_key),
    ).fetchone()
    return cast(sqlite3.Row | None, row)


def _fetch_by_outcome(
    conn: sqlite3.Connection, run_id: str, outcome_id: str
) -> sqlite3.Row | None:
    row = conn.execute(
        "SELECT * FROM outcome_refinement_actions "
        "WHERE run_id=? AND outcome_id=?",
        (run_id, outcome_id),
    ).fetchone()
    return cast(sqlite3.Row | None, row)


def _matches_request(
    action: dict[str, Any], intent: NewOutcomeRefinementAction
) -> bool:
    return bool(
        action["outcome_id"] == intent.outcome_id
        and action["hypothesis_id"] == intent.hypothesis_id
        and action["owner_id"] == intent.owner_id
    )


def _append_requested_event(
    conn: sqlite3.Connection, intent: NewOutcomeRefinementAction, now: float
) -> None:
    _append_event(
        conn,
        intent.run_id,
        "scientist.outcome_refinement_requested",
        {
            "action_id": intent.action_id,
            "outcome_id": intent.outcome_id,
            "hypothesis_id": intent.hypothesis_id,
            "task_idempotency_key": intent.task_idempotency_key,
        },
        now,
    )


def _insert_action(
    conn: sqlite3.Connection, intent: NewOutcomeRefinementAction
) -> dict[str, Any]:
    now = _now()
    conn.execute(
        "INSERT INTO outcome_refinement_actions (action_id, run_id, "
        "outcome_id, hypothesis_id, owner_id, request_idempotency_key, "
        "task_idempotency_key, checkpoint_seq, context_snapshot, status, "
        "created_at, updated_at) VALUES "
        "(?,?,?,?,?,?,?,?,?,'pending_executor',?,?)",
        (
            intent.action_id,
            intent.run_id,
            intent.outcome_id,
            intent.hypothesis_id,
            intent.owner_id,
            intent.request_idempotency_key,
            intent.task_idempotency_key,
            intent.checkpoint_seq,
            intent.context_snapshot,
            now,
            now,
        ),
    )
    _append_requested_event(conn, intent, now)
    row = conn.execute(
        "SELECT * FROM outcome_refinement_actions WHERE action_id=?",
        (intent.action_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError("outcome refinement intent was not persisted")
    return _decode_action(row)


def _persist_action(
    conn: sqlite3.Connection, intent: NewOutcomeRefinementAction
) -> tuple[dict[str, Any], bool]:
    by_key = _fetch_by_key(conn, intent.run_id, intent.request_idempotency_key)
    if by_key is not None:
        existing = _decode_action(by_key)
        if not _matches_request(existing, intent):
            raise OutcomeRefinementConflictError
        return existing, True
    by_outcome = _fetch_by_outcome(conn, intent.run_id, intent.outcome_id)
    if by_outcome is not None:
        raise OutcomeRefinementConflictError
    try:
        return _insert_action(conn, intent), False
    except sqlite3.IntegrityError as exc:
        # Unique constraints still fence callers that share a connection
        # without using this function's outer transaction.
        raise OutcomeRefinementConflictError from exc


def create_outcome_refinement_action(
    intent: NewOutcomeRefinementAction,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> tuple[dict[str, Any], bool]:
    """Persist one intent/event atomically, replaying the same request key.

    Returns the action and whether it was already present. A distinct request
    key cannot authorize the same outcome a second time.
    """
    if not intent.request_idempotency_key.strip():
        raise ValueError("request idempotency key must not be blank")
    if not intent.task_idempotency_key.strip():
        raise ValueError("task idempotency key must not be blank")
    if len(intent.context_snapshot) > 6_000:
        raise ValueError("outcome refinement context exceeds 6000 codepoints")

    if conn is not None:
        return _persist_action(conn, intent)
    with transaction(db_path) as active:
        return _persist_action(active, intent)


def get_outcome_refinement_action(
    run_id: str,
    action_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any] | None:
    """Fetch one outbox intent by its stable action id."""
    with _use_conn(conn, db_path) as active:
        row = active.execute(
            "SELECT * FROM outcome_refinement_actions "
            "WHERE run_id=? AND action_id=?",
            (run_id, action_id),
        ).fetchone()
        return _decode_action(row) if row is not None else None


def get_outcome_refinement_action_by_key(
    run_id: str,
    request_idempotency_key: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any] | None:
    """Fetch the same intent after an owner retries its request."""
    with _use_conn(conn, db_path) as active:
        row = _fetch_by_key(active, run_id, request_idempotency_key)
        return _decode_action(row) if row is not None else None


def get_outcome_refinement_action_for_outcome(
    run_id: str,
    outcome_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any] | None:
    """Fetch the one intent allowed for an outcome-parent pair."""
    with _use_conn(conn, db_path) as active:
        row = _fetch_by_outcome(active, run_id, outcome_id)
        return _decode_action(row) if row is not None else None


def list_pending_outcome_refinement_actions(
    run_id: str | None = None,
    *,
    limit: int = 25,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Read intents not yet materialized into claimable executor tasks."""
    bounded_limit = min(max(int(limit), 1), 100)
    with _use_conn(conn, db_path) as active:
        if run_id is None:
            rows = active.execute(
                "SELECT * FROM outcome_refinement_actions "
                "WHERE status='pending_executor' "
                "ORDER BY created_at, action_id LIMIT ?",
                (bounded_limit,),
            ).fetchall()
        else:
            rows = active.execute(
                "SELECT * FROM outcome_refinement_actions "
                "WHERE run_id=? AND status='pending_executor' "
                "ORDER BY created_at, action_id LIMIT ?",
                (run_id, bounded_limit),
            ).fetchall()
        return [_decode_action(row) for row in rows]


def update_outcome_refinement_action(
    action_id: str,
    *,
    status: str,
    child_hypothesis_id: str | None = None,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any] | None:
    """Set execution state and its optional child under the caller's commit."""
    with _use_conn(conn, db_path) as active:
        row = active.execute(
            "SELECT child_hypothesis_id FROM outcome_refinement_actions "
            "WHERE action_id=?",
            (action_id,),
        ).fetchone()
        if row is None:
            return None
        existing_child = row["child_hypothesis_id"]
        if (
            existing_child is not None
            and child_hypothesis_id is not None
            and existing_child != child_hypothesis_id
        ):
            raise OutcomeRefinementConflictError
        active.execute(
            "UPDATE outcome_refinement_actions SET status=?, "
            "child_hypothesis_id=COALESCE(child_hypothesis_id, ?), "
            "updated_at=? WHERE action_id=?",
            (status, child_hypothesis_id, _now(), action_id),
        )
        updated = active.execute(
            "SELECT * FROM outcome_refinement_actions WHERE action_id=?",
            (action_id,),
        ).fetchone()
        return _decode_action(updated) if updated is not None else None
