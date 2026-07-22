"""Durable scientific task queue with leases and idempotent completion.

The control-plane lifecycle operations (Supervisor reprioritize/cancel/
retry, run-scoped cancel/pause/resume, and terminally-dead task revival)
live in ``app.store.tasks_lifecycle`` and are re-exported here so the
module namespace is unchanged.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from app.store.db import _now, _use_conn, connect, transaction
from app.store.tasks_lifecycle import cancel_run_tasks as cancel_run_tasks
from app.store.tasks_lifecycle import cancel_task as cancel_task
from app.store.tasks_lifecycle import pause_run_tasks as pause_run_tasks
from app.store.tasks_lifecycle import reprioritize_task as reprioritize_task
from app.store.tasks_lifecycle import resume_run_tasks as resume_run_tasks
from app.store.tasks_lifecycle import retry_task as retry_task
from app.store.tasks_lifecycle import (
    revive_task_for_retry as revive_task_for_retry,
)


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


def has_active_lease(run_id: str, db_path: str | None = None) -> bool:
    """Return whether any of a run's tasks is currently leased.

    Answers the cohort's idle question -- "is anyone still working?" -- with
    a single existence check. Listing and decoding every row of the run's
    task table to compute the same boolean costs more the further a run
    gets, and every idle worker asks twenty times a second.

    Args:
        run_id: Identifier of the run whose cohort is waiting.
        db_path: Optional override for the SQLite database path.

    Returns:
        True when at least one task of the run is leased.
    """
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM scientific_tasks WHERE run_id=? AND status='leased'"
            " LIMIT 1",
            (run_id,),
        ).fetchone()
    return row is not None


# The liveness invariant shared by the advisory probes and the claim's
# rescue UPDATE: an expired lease with retry budget left is claimable
# again. One fragment, interpolated everywhere it applies, so a probe can
# never say "no work" while the claim's rescue would have found some.
# Binds one parameter: the current time.
_EXPIRED_LEASE_RESCUABLE = (
    "status='leased' AND lease_expires_at<=? AND attempt<max_attempts"
)


def _has_claimable_task(run_id: str | None, db_path: str | None) -> bool:
    """Return whether a claim attempt could plausibly find work.

    Read-only and advisory. Every worker in every run's cohort polls for
    work several times a second, and opening a write transaction just to
    discover the queue is empty turned an idle cohort into a write-lock
    storm: hundreds of no-op BEGIN IMMEDIATEs a second against a database
    with a single writer, changing no rows. The database looked idle while
    ordinary API writes exhausted their 30-second busy timeout and run
    creation returned 500. In WAL a reader takes no write lock, so asking
    first costs nothing and the common answer is "no".

    The claim itself re-checks everything under the write lock, so a race
    here only risks a wasted attempt, never a double lease.
    """
    query = (
        "SELECT 1 FROM scientific_tasks WHERE status='queued'"
        " AND (? IS NULL OR run_id=?)"
        " UNION ALL "
        "SELECT 1 FROM scientific_tasks WHERE (? IS NULL OR run_id=?)"
        f" AND {_EXPIRED_LEASE_RESCUABLE}"
        " LIMIT 1"
    )
    with connect(db_path) as conn:
        row = conn.execute(
            query, (run_id, run_id, run_id, run_id, _now())
        ).fetchone()
    return row is not None


def cohort_poll(run_id: str, db_path: str | None = None) -> tuple[bool, bool]:
    """One idle-tick snapshot for a cohort worker: (claimable, active lease).

    The cohort's idle loop needs both answers every tick -- "is there work
    to claim" and "is a sibling still holding a lease that may fan out
    more". Asking them separately opened two connections per tick per
    worker, sustained for the whole wall clock of every run; one read-only
    connection answers both from a single consistent snapshot.
    """
    query = (
        "SELECT"
        " EXISTS(SELECT 1 FROM scientific_tasks"
        "        WHERE run_id=? AND status='queued')"
        " OR EXISTS(SELECT 1 FROM scientific_tasks WHERE run_id=?"
        f"        AND {_EXPIRED_LEASE_RESCUABLE}) AS claimable,"
        " EXISTS(SELECT 1 FROM scientific_tasks"
        "        WHERE run_id=? AND status='leased') AS active"
    )
    with connect(db_path) as conn:
        row = conn.execute(query, (run_id, run_id, _now(), run_id)).fetchone()
    return bool(row["claimable"]), bool(row["active"])


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
        conn.execute(
            "UPDATE scientific_tasks SET status='queued', lease_owner=NULL, "
            "lease_expires_at=NULL, updated_at=? "
            f"WHERE {_EXPIRED_LEASE_RESCUABLE}",
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
