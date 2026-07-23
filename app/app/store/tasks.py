"""Durable scientific task queue with leases and idempotent completion.

The control-plane lifecycle operations (Supervisor reprioritize/cancel/
retry, run-scoped cancel/pause/resume, and terminally-dead task revival)
live in ``app.store.tasks_lifecycle``, and the read-only cohort liveness
probes live in ``app.store.tasks_probes``; both are re-exported here so
the module namespace is unchanged.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from app.store.db import _now, _use_conn, transaction
from app.store.tasks_lifecycle import cancel_run_tasks as cancel_run_tasks
from app.store.tasks_lifecycle import cancel_task as cancel_task
from app.store.tasks_lifecycle import pause_run_tasks as pause_run_tasks
from app.store.tasks_lifecycle import reprioritize_task as reprioritize_task
from app.store.tasks_lifecycle import resume_run_tasks as resume_run_tasks
from app.store.tasks_lifecycle import retry_task as retry_task
from app.store.tasks_lifecycle import (
    revive_task_for_retry as revive_task_for_retry,
)
from app.store.tasks_probes import (
    _EXPIRED_LEASE_RESCUABLE as _EXPIRED_LEASE_RESCUABLE,
)
from app.store.tasks_probes import (
    _has_claimable_task as _has_claimable_task,
)
from app.store.tasks_probes import cohort_poll as cohort_poll
from app.store.tasks_probes import has_active_lease as has_active_lease


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


def _insert_task_row(conn: sqlite3.Connection, values: tuple[Any, ...]) -> None:
    """Insert a task row, ignoring duplicate idempotency-key delivery."""
    conn.execute(
        "INSERT INTO scientific_tasks (id, run_id, task_type, status, "
        "priority, inputs_json, dependencies_json, provenance_json, "
        "idempotency_key, budget_json, max_attempts, created_at, "
        "updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(run_id, idempotency_key) DO NOTHING",
        values,
    )


def _fetch_task_by_idempotency_key(
    conn: sqlite3.Connection, run_id: str, idempotency_key: str
) -> sqlite3.Row | None:
    """Return the (possibly pre-existing) task row for this idempotency key."""
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM scientific_tasks WHERE run_id=? AND idempotency_key=?",
        (run_id, idempotency_key),
    ).fetchone()
    return row


@dataclasses.dataclass(frozen=True)
class NewTask:
    """One durable task to enqueue, mirroring the scientific_tasks row.

    ``idempotency_key`` is unique per run and makes duplicate delivery a
    no-op. ``priority`` orders the queue, ``dependencies`` names the task
    ids that must finish first, ``provenance`` records who enqueued it,
    ``budget`` caps its resource use, and ``max_attempts`` is its retry
    budget.
    """

    run_id: str
    task_type: str
    inputs: Mapping[str, Any]
    idempotency_key: str
    priority: int = 0
    dependencies: Iterable[str] = ()
    provenance: Mapping[str, Any] | None = None
    budget: Mapping[str, Any] | None = None
    max_attempts: int = 3


def _task_row_values(
    task_id: str, task: NewTask, now: float
) -> tuple[Any, ...]:
    """Build the bound values tuple for a new task row."""
    return (
        task_id,
        task.run_id,
        task.task_type,
        "queued",
        task.priority,
        json.dumps(dict(task.inputs), sort_keys=True),
        json.dumps(list(task.dependencies)),
        json.dumps(dict(task.provenance or {}), sort_keys=True),
        task.idempotency_key,
        json.dumps(dict(task.budget or {}), sort_keys=True),
        task.max_attempts,
        now,
        now,
    )


def enqueue_task(
    task: NewTask,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> ScientificTask:
    """Enqueue a task once and return the existing row on duplicate delivery.

    Args:
        task: The task to enqueue (see :class:`NewTask`).
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse.

    Returns:
        The enqueued task, or the pre-existing row on duplicate delivery.

    Raises:
        ValueError: If the idempotency key is blank or max_attempts < 1.
        RuntimeError: If the row could not be read back after insert.
    """
    if not task.idempotency_key.strip():
        raise ValueError("idempotency_key must not be empty")
    if task.max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    values = _task_row_values(str(uuid.uuid4()), task, _now())
    with _use_conn(conn, db_path) as active:
        _insert_task_row(active, values)
        row = _fetch_task_by_idempotency_key(
            active, task.run_id, task.idempotency_key
        )
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


def list_active_engine_task_run_ids(
    db_path: str | None = None,
) -> list[str]:
    """Return non-terminal runs whose durable engine work needs a worker."""
    with _use_conn(None, db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT t.run_id FROM scientific_tasks t "
            "JOIN runs r ON r.id=t.run_id "
            "WHERE t.task_type LIKE 'engine.%' "
            "AND t.status IN ('queued','leased') "
            "AND r.status IN ('queued','running','synthesizing') "
            "ORDER BY t.run_id"
        ).fetchall()
    return [str(row["run_id"]) for row in rows]


def task_progress(
    run_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Summarize monotonic execution progress from committed durable tasks."""
    tasks = list_tasks(run_id, db_path=db_path, conn=conn)
    # A single workflow lease is only a durable process boundary, not a
    # disclosed scientific work budget. Treat it as indeterminate until the
    # supervisor has materialized independently countable specialist tasks.
    scientific_tasks = [
        task for task in tasks if task.task_type != "run.workflow"
    ]
    total = len(scientific_tasks)
    terminal = {"completed", "failed", "cancelled"}
    completed = sum(task.status in terminal for task in scientific_tasks)
    active = next(
        (
            task
            for task in scientific_tasks
            if task.status in {"leased", "running"}
        ),
        None,
    )
    dynamic_plan = any(
        task.task_type.startswith("engine.") for task in scientific_tasks
    )
    return {
        "determinate": total > 0 and not dynamic_plan,
        "completed_tasks": completed,
        "total_tasks": total,
        "fraction": completed / total if total and not dynamic_plan else None,
        "active_task": active.task_type if active else None,
        "queued_tasks": sum(
            task.status == "queued" for task in scientific_tasks
        ),
    }


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
    allowed = (
        {"completed", "failed", "cancelled"}
        if task.provenance.get("allow_failed_dependencies")
        else {"completed"}
    )
    return len(rows) == len(task.dependencies) and all(
        row["status"] in allowed for row in rows
    )


def _rescue_expired_leases(conn: sqlite3.Connection, now: float) -> None:
    """Requeue leased tasks whose lease expired with retry budget left."""
    conn.execute(
        "UPDATE scientific_tasks SET status='queued', lease_owner=NULL, "
        "lease_expires_at=NULL, updated_at=? "
        f"WHERE {_EXPIRED_LEASE_RESCUABLE}",
        (now, now),
    )


def _queued_tasks_query(run_id: str | None) -> tuple[str, list[Any]]:
    """Build the ready-task query ordered by priority then age."""
    query = "SELECT * FROM scientific_tasks WHERE status='queued'"
    params: list[Any] = []
    if run_id is not None:
        query += " AND run_id=?"
        params.append(run_id)
    query += " ORDER BY priority DESC, created_at ASC"
    return query, params


def _try_lease_task(
    conn: sqlite3.Connection,
    task: ScientificTask,
    worker_id: str,
    now: float,
    lease_seconds: float,
) -> ScientificTask | None:
    """Attempt to lease one ready task to worker_id; return it on success."""
    if not _dependencies_complete(conn, task):
        return None
    expires = now + lease_seconds
    changed = conn.execute(
        "UPDATE scientific_tasks SET status='leased', "
        "attempt=attempt+1, lease_owner=?, lease_expires_at=?, "
        "started_at=COALESCE("
        "started_at, ?), updated_at=? WHERE id=? AND status='queued'",
        (worker_id, expires, now, now, task.id),
    ).rowcount
    if not changed:
        return None
    leased = conn.execute(
        "SELECT * FROM scientific_tasks WHERE id=?", (task.id,)
    ).fetchone()
    return _decode(leased)


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
    if not _has_claimable_task(run_id, db_path):
        return None
    with transaction(db_path) as conn:
        now = _now()
        # Expired leases become ready again unless their retry budget is spent.
        _rescue_expired_leases(conn, now)
        query, params = _queued_tasks_query(run_id)
        for row in conn.execute(query, params).fetchall():
            leased = _try_lease_task(
                conn, _decode(row), worker_id, now, lease_seconds
            )
            if leased is not None:
                return leased
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


def renew_task_lease(
    task_id: str,
    worker_id: str,
    lease_seconds: float,
    *,
    db_path: str | None = None,
) -> bool:
    """Extend an owned lease so long scientific work cannot be redelivered."""
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")
    now = _now()
    with transaction(db_path) as conn:
        changed = conn.execute(
            "UPDATE scientific_tasks SET lease_expires_at=?, updated_at=? "
            "WHERE id=? AND status='leased' AND lease_owner=?",
            (now + lease_seconds, now, task_id, worker_id),
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
