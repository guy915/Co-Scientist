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


def reprioritize_task(
    task_id: str,
    priority: int,
    *,
    reason: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> bool:
    """Change one queued task's claim priority and record Supervisor reason."""
    bounded = max(0, min(100, priority))
    with _use_conn(conn, db_path) as active:
        row = active.execute(
            "SELECT provenance_json FROM scientific_tasks "
            "WHERE id=? AND status='queued'",
            (task_id,),
        ).fetchone()
        if row is None:
            return False
        provenance = json.loads(row["provenance_json"])
        provenance["supervisor_reprioritization"] = reason
        active.execute(
            "UPDATE scientific_tasks SET priority=?, provenance_json=?, "
            "updated_at=? WHERE id=? AND status='queued'",
            (bounded, json.dumps(provenance, sort_keys=True), _now(), task_id),
        )
    return True


def cancel_task(
    task_id: str,
    *,
    reason: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> bool:
    """Cancel one not-yet-leased task without disturbing unrelated work."""
    now = _now()
    with _use_conn(conn, db_path) as active:
        changed = active.execute(
            "UPDATE scientific_tasks SET status='cancelled', error=?, "
            "completed_at=?, updated_at=? WHERE id=? "
            "AND status IN ('queued','paused')",
            (f"Supervisor cancelled: {reason}", now, now, task_id),
        ).rowcount
    return bool(changed)


def retry_task(
    task_id: str,
    *,
    reason: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> bool:
    """Requeue one failed task with one explicit additional attempt."""
    now = _now()
    with _use_conn(conn, db_path) as active:
        row = active.execute(
            "SELECT provenance_json FROM scientific_tasks "
            "WHERE id=? AND status='failed'",
            (task_id,),
        ).fetchone()
        if row is None:
            return False
        provenance = json.loads(row["provenance_json"])
        provenance["supervisor_retry"] = reason
        active.execute(
            "UPDATE scientific_tasks SET status='queued', "
            "max_attempts=max_attempts+1, error=NULL, completed_at=NULL, "
            "provenance_json=?, updated_at=? WHERE id=? AND status='failed'",
            (json.dumps(provenance, sort_keys=True), now, task_id),
        )
    return True


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


def cancel_run_tasks(
    run_id: str,
    *,
    db_path: str | None = None,
) -> int:
    """Revoke every queued/leased task for a cancelled run."""
    now = _now()
    with transaction(db_path) as conn:
        changed = conn.execute(
            "UPDATE scientific_tasks SET status='cancelled', "
            "lease_owner=NULL, lease_expires_at=NULL, completed_at=?, "
            "updated_at=? WHERE run_id=? AND status IN ('queued','leased')",
            (now, now, run_id),
        ).rowcount
    return int(changed)


def pause_run_tasks(run_id: str, *, db_path: str | None = None) -> int:
    """Make queued work non-claimable while an in-flight lease checkpoints."""
    now = _now()
    with transaction(db_path) as conn:
        changed = conn.execute(
            "UPDATE scientific_tasks SET status='paused', updated_at=? "
            "WHERE run_id=? AND status='queued'",
            (now, run_id),
        ).rowcount
    return int(changed)


def resume_run_tasks(run_id: str, *, db_path: str | None = None) -> int:
    """Return paused queued work to the global ready queue."""
    now = _now()
    with transaction(db_path) as conn:
        changed = conn.execute(
            "UPDATE scientific_tasks SET status='queued', updated_at=? "
            "WHERE run_id=? AND status='paused'",
            (now, run_id),
        ).rowcount
    return int(changed)


# Only these. A succeeded task must never be revived -- rerunning it would
# redo work the run already committed -- and queued/leased/paused tasks are
# either runnable already or owned by the paths above.
_REVIVABLE_TASK_STATUSES = ("failed", "cancelled")


def revive_task_for_retry(
    run_id: str,
    idempotency_key: str,
    *,
    db_path: str | None = None,
) -> bool:
    """Return one terminally-dead task to the queue with a fresh budget.

    Enqueueing is idempotent on ``(run_id, idempotency_key)``, which is what a
    resume needs when a boundary is merely already queued -- but it also meant
    a boundary whose task had *died* could never be retried: the insert hit
    ON CONFLICT DO NOTHING, so the resume enqueued nothing and the worker had
    nothing to claim. The run then announced that it was resuming and sat
    silent forever. Neither existing recovery path reaches such a task:
    ``resume_run_tasks`` only requeues ``paused``, and ``claim_task``'s
    expired-lease rescue skips tasks whose attempts are spent.

    The attempt counter is reset because a resume is a fresh intent rather
    than a continuation of the old retry sequence -- the earlier attempts may
    have been spent on a condition since repaired (a full disk, a dead
    provider). Resumes are operator- or startup-initiated, so this is bounded
    by how often they happen rather than by the worker's own retry loop.

    Args:
        run_id: The run whose task should be revived.
        idempotency_key: Key identifying the task within the run.
        db_path: Optional override for the SQLite database path.

    Returns:
        True if a dead task was revived, False if there was nothing to revive.
    """
    placeholders = ",".join("?" * len(_REVIVABLE_TASK_STATUSES))
    with transaction(db_path) as conn:
        changed = conn.execute(
            "UPDATE scientific_tasks SET status='queued', attempt=0, "
            "error=NULL, completed_at=NULL, lease_owner=NULL, "
            "lease_expires_at=NULL, updated_at=? WHERE run_id=? AND "
            f"idempotency_key=? AND status IN ({placeholders})",
            (_now(), run_id, idempotency_key, *_REVIVABLE_TASK_STATUSES),
        ).rowcount
    return int(changed) > 0


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
