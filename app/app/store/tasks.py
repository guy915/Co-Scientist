"""Durable scientific task queue with leases and idempotent completion."""

from __future__ import annotations

import dataclasses
import json
import sqlite3
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from app.store.db import _now, _use_conn, transaction


@dataclasses.dataclass(frozen=True)
class ScientificTask:
    """One durable unit of specialist work."""

    id: str
    run_id: str
    task_type: str
    status: str
    priority: int
    inputs: dict[str, Any]
    dependencies: tuple[str, ...]
    provenance: dict[str, Any]
    idempotency_key: str
    budget: dict[str, Any]
    attempt: int
    max_attempts: int
    lease_owner: str | None
    lease_expires_at: float | None
    result: dict[str, Any] | None
    error: str | None
    created_at: float
    updated_at: float
    started_at: float | None
    completed_at: float | None


def _decode(row: sqlite3.Row) -> ScientificTask:
    """Decode a SQLite task row into its typed representation."""
    return ScientificTask(
        id=str(row["id"]),
        run_id=str(row["run_id"]),
        task_type=str(row["task_type"]),
        status=str(row["status"]),
        priority=int(row["priority"]),
        inputs=json.loads(row["inputs_json"]),
        dependencies=tuple(json.loads(row["dependencies_json"])),
        provenance=json.loads(row["provenance_json"]),
        idempotency_key=str(row["idempotency_key"]),
        budget=json.loads(row["budget_json"]),
        attempt=int(row["attempt"]),
        max_attempts=int(row["max_attempts"]),
        lease_owner=row["lease_owner"],
        lease_expires_at=row["lease_expires_at"],
        result=json.loads(row["result_json"]) if row["result_json"] else None,
        error=row["error"],
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
        started_at=row["started_at"],
        completed_at=row["completed_at"],
    )


def enqueue_task(
    run_id: str,
    task_type: str,
    inputs: Mapping[str, Any],
    *,
    idempotency_key: str,
    priority: int = 0,
    dependencies: Iterable[str] = (),
    provenance: Mapping[str, Any] | None = None,
    budget: Mapping[str, Any] | None = None,
    max_attempts: int = 3,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> ScientificTask:
    """Enqueue a task once and return the existing row on duplicate delivery."""
    if not idempotency_key.strip():
        raise ValueError("idempotency_key must not be empty")
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    task_id = str(uuid.uuid4())
    now = _now()
    values = (
        task_id,
        run_id,
        task_type,
        "queued",
        priority,
        json.dumps(dict(inputs), sort_keys=True),
        json.dumps(list(dependencies)),
        json.dumps(dict(provenance or {}), sort_keys=True),
        idempotency_key,
        json.dumps(dict(budget or {}), sort_keys=True),
        max_attempts,
        now,
        now,
    )
    with _use_conn(conn, db_path) as active:
        active.execute(
            "INSERT INTO scientific_tasks (id, run_id, task_type, status, "
            "priority, inputs_json, dependencies_json, provenance_json, "
            "idempotency_key, budget_json, max_attempts, created_at, "
            "updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(run_id, idempotency_key) DO NOTHING",
            values,
        )
        row = active.execute(
            "SELECT * FROM scientific_tasks WHERE run_id=? AND "
            "idempotency_key=?",
            (run_id, idempotency_key),
        ).fetchone()
    if row is None:
        raise RuntimeError("task enqueue did not persist a row")
    return _decode(row)


def list_tasks(
    run_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[ScientificTask]:
    """List a run's tasks in creation order."""
    with _use_conn(conn, db_path) as active:
        rows = active.execute(
            "SELECT * FROM scientific_tasks WHERE run_id=? "
            "ORDER BY created_at ASC",
            (run_id,),
        ).fetchall()
    return [_decode(row) for row in rows]


def get_task(
    task_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> ScientificTask | None:
    """Return one task by identifier, or None when it does not exist."""
    with _use_conn(conn, db_path) as active:
        row = active.execute(
            "SELECT * FROM scientific_tasks WHERE id=?", (task_id,)
        ).fetchone()
    return _decode(row) if row is not None else None


def _dependencies_complete(
    conn: sqlite3.Connection, task: ScientificTask
) -> bool:
    """Return whether every declared dependency completed successfully."""
    if not task.dependencies:
        return True
    placeholders = ",".join("?" for _ in task.dependencies)
    rows = conn.execute(
        f"SELECT id, status FROM scientific_tasks WHERE id IN ({placeholders})",
        task.dependencies,
    ).fetchall()
    return len(rows) == len(task.dependencies) and all(
        row["status"] == "completed" for row in rows
    )


def claim_task(
    worker_id: str,
    *,
    lease_seconds: float = 60.0,
    run_id: str | None = None,
    db_path: str | None = None,
) -> ScientificTask | None:
    """Atomically lease the highest-priority ready task to one worker."""
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")
    with transaction(db_path) as conn:
        now = _now()
        # Expired leases become ready again unless their retry budget is spent.
        conn.execute(
            "UPDATE scientific_tasks SET status='queued', lease_owner=NULL, "
            "lease_expires_at=NULL, updated_at=? WHERE status='leased' AND "
            "lease_expires_at<=? AND attempt<max_attempts",
            (now, now),
        )
        query = "SELECT * FROM scientific_tasks WHERE status='queued'"
        params: list[Any] = []
        if run_id is not None:
            query += " AND run_id=?"
            params.append(run_id)
        query += " ORDER BY priority DESC, created_at ASC"
        for row in conn.execute(query, params).fetchall():
            task = _decode(row)
            if not _dependencies_complete(conn, task):
                continue
            expires = now + lease_seconds
            changed = conn.execute(
                "UPDATE scientific_tasks SET status='leased', "
                "attempt=attempt+1, lease_owner=?, lease_expires_at=?, "
                "started_at=COALESCE("
                "started_at, ?), updated_at=? WHERE id=? AND status='queued'",
                (worker_id, expires, now, now, task.id),
            ).rowcount
            if changed:
                leased = conn.execute(
                    "SELECT * FROM scientific_tasks WHERE id=?", (task.id,)
                ).fetchone()
                return _decode(leased)
    return None


def complete_task(
    task_id: str,
    worker_id: str,
    result: Mapping[str, Any],
    *,
    db_path: str | None = None,
) -> bool:
    """Complete a currently owned lease exactly once."""
    now = _now()
    with transaction(db_path) as conn:
        changed = conn.execute(
            "UPDATE scientific_tasks SET status='completed', result_json=?, "
            "error=NULL, lease_owner=NULL, lease_expires_at=NULL, "
            "completed_at=?, updated_at=? WHERE id=? AND status='leased' "
            "AND lease_owner=?",
            (
                json.dumps(dict(result), sort_keys=True),
                now,
                now,
                task_id,
                worker_id,
            ),
        ).rowcount
    return bool(changed)


def fail_task(
    task_id: str,
    worker_id: str,
    error: str,
    *,
    retryable: bool = True,
    db_path: str | None = None,
) -> bool:
    """Record failure and requeue when the bounded retry budget permits."""
    with transaction(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM scientific_tasks WHERE id=? AND status='leased' "
            "AND lease_owner=?",
            (task_id, worker_id),
        ).fetchone()
        if row is None:
            return False
        task = _decode(row)
        status = (
            "queued"
            if retryable and task.attempt < task.max_attempts
            else "failed"
        )
        now = _now()
        conn.execute(
            "UPDATE scientific_tasks SET status=?, error=?, lease_owner=NULL, "
            "lease_expires_at=NULL, completed_at=?, updated_at=? WHERE id=?",
            (
                status,
                error,
                now if status == "failed" else None,
                now,
                task_id,
            ),
        )
    return True
