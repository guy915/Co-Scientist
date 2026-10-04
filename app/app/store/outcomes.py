from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from typing import Any, cast

from app.store.db import _now, _use_conn, transaction
from app.store.events import _append_event


class OutcomeRefinementConflictError(ValueError):
    """An outcome action or request key already belongs to another intent."""


@dataclass(frozen=True)
class NewOutcomeRefinementAction:
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
        # Unique constraints also fence callers sharing a connection outside
        # this helper's outer transaction.
        raise OutcomeRefinementConflictError from exc


def create_outcome_refinement_action(
    intent: NewOutcomeRefinementAction,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> tuple[dict[str, Any], bool]:
    """A request-key replay is idempotent; a different key cannot authorize
    the same outcome-parent intent again.
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


class InvalidOutcomeReferencesError(ValueError):
    """A hypothesis or evidence reference does not belong to the run."""


@dataclass(frozen=True)
class NewHypothesisOutcome:
    run_id: str
    hypothesis_id: str
    method_protocol: str
    conditions: str
    measured_observation: str
    units: str | None
    controls: str
    interpretation: str
    referenced_evidence_ids: list[str]
    author: str


def _decode_outcome(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    outcome = dict(row)
    outcome["referenced_evidence_ids"] = json.loads(
        outcome.pop("referenced_evidence_ids_json")
    )
    outcome["hypothesis_snapshot"] = json.loads(
        outcome.pop("hypothesis_snapshot_json", "{}")
    )
    outcome["referenced_evidence"] = json.loads(
        outcome.pop("referenced_evidence_snapshots_json", "[]")
    )
    return outcome


def _hypothesis_snapshot(
    conn: sqlite3.Connection, outcome: NewHypothesisOutcome
) -> dict[str, str]:
    row = conn.execute(
        "SELECT title, statement FROM hypotheses WHERE id=? AND run_id=?",
        (outcome.hypothesis_id, outcome.run_id),
    ).fetchone()
    if row is None:
        raise InvalidOutcomeReferencesError
    return {"title": row["title"], "statement": row["statement"]}


def _evidence_snapshots(
    conn: sqlite3.Connection, run_id: str, evidence_ids: list[str]
) -> list[dict[str, Any]]:
    if not evidence_ids:
        return []
    placeholders = ",".join("?" for _ in evidence_ids)
    rows = conn.execute(
        "SELECT id, title, source, url, doi, pmid, sha256 FROM evidence "
        f"WHERE run_id=? AND id IN ({placeholders})",
        (run_id, *evidence_ids),
    ).fetchall()
    evidence_by_id = {row["id"]: row for row in rows}
    if set(evidence_by_id) != set(evidence_ids):
        raise InvalidOutcomeReferencesError
    fields = ("id", "title", "source", "url", "doi", "pmid", "sha256")
    return [
        {key: evidence_by_id[evidence_id][key] for key in fields}
        for evidence_id in evidence_ids
    ]


def _insert_outcome(
    conn: sqlite3.Connection,
    record: dict[str, Any],
) -> None:
    conn.execute(
        "INSERT INTO hypothesis_outcomes (id, run_id, hypothesis_id, "
        "method_protocol, conditions, measured_observation, units, "
        "controls, interpretation, referenced_evidence_ids_json, "
        "hypothesis_snapshot_json, referenced_evidence_snapshots_json, "
        "author, recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            record["id"],
            record["run_id"],
            record["hypothesis_id"],
            record["method_protocol"],
            record["conditions"],
            record["measured_observation"],
            record["units"],
            record["controls"],
            record["interpretation"],
            json.dumps(record["referenced_evidence_ids"]),
            json.dumps(record["hypothesis_snapshot"]),
            json.dumps(record["referenced_evidence"]),
            record["author"],
            record["recorded_at"],
        ),
    )


def add_hypothesis_outcome(
    outcome: NewHypothesisOutcome,
    *,
    db_path: str | None = None,
) -> dict[str, Any]:
    outcome_id = str(uuid.uuid4())
    recorded_at = _now()
    with transaction(db_path) as conn:
        record = {
            **asdict(outcome),
            "id": outcome_id,
            "recorded_at": recorded_at,
            "hypothesis_snapshot": _hypothesis_snapshot(conn, outcome),
            "referenced_evidence": _evidence_snapshots(
                conn, outcome.run_id, outcome.referenced_evidence_ids
            ),
        }
        _insert_outcome(conn, record)
        # Replay logs contain metadata only; private observations stay out of
        # the event stream.
        _append_event(
            conn,
            outcome.run_id,
            "scientist.outcome",
            {
                "outcome_id": outcome_id,
                "hypothesis_id": outcome.hypothesis_id,
                "author": outcome.author,
                "recorded_at": recorded_at,
            },
            recorded_at,
        )
    return record


def list_hypothesis_outcomes(
    run_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    with _use_conn(conn, db_path) as conn:
        rows = conn.execute(
            "SELECT id, run_id, hypothesis_id, method_protocol, conditions, "
            "measured_observation, units, controls, interpretation, "
            "referenced_evidence_ids_json, hypothesis_snapshot_json, "
            "referenced_evidence_snapshots_json, author, recorded_at "
            "FROM hypothesis_outcomes WHERE run_id=? "
            "ORDER BY recorded_at ASC, id ASC",
            (run_id,),
        ).fetchall()
        return [_decode_outcome(row) for row in rows]


def get_hypothesis_outcome(
    run_id: str,
    outcome_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any] | None:
    with _use_conn(conn, db_path) as active:
        row = active.execute(
            "SELECT id, run_id, hypothesis_id, method_protocol, conditions, "
            "measured_observation, units, controls, interpretation, "
            "referenced_evidence_ids_json, hypothesis_snapshot_json, "
            "referenced_evidence_snapshots_json, author, recorded_at "
            "FROM hypothesis_outcomes WHERE run_id=? AND id=?",
            (run_id, outcome_id),
        ).fetchone()
        return _decode_outcome(row) if row is not None else None
