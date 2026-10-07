from __future__ import annotations

import dataclasses
import json
import sqlite3
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

import app.store.tasks_lifecycle as tasks_recovery
from app.store.db import _now, _use_conn, connect, transaction
from app.store.models import ScientificTask as ScientificTask
from app.store.models import TaskFailure as TaskFailure
from app.store.models import _decode as _decode
from app.store.runs_views import (
    _settle_run_for_failed_task as _settle_run_for_failed_task,
)
from app.store.tasks_lifecycle import (
    _ENGINE_RUN_STATUS_GUARD as _ENGINE_RUN_STATUS_GUARD,
)
from app.store.tasks_lifecycle import (
    _EXPIRED_LEASE_RESCUABLE as _EXPIRED_LEASE_RESCUABLE,
)
from app.store.tasks_lifecycle import _has_claimable_task as _has_claimable_task
from app.store.tasks_lifecycle import (
    _persist_failed_attempt as _persist_failed_attempt,
)
from app.store.tasks_lifecycle import (
    abandon_dead_leases as abandon_dead_leases,
)
from app.store.tasks_lifecycle import cancel_run_tasks as cancel_run_tasks
from app.store.tasks_lifecycle import cancel_task as cancel_task
from app.store.tasks_lifecycle import (
    clamp_task_priority as clamp_task_priority,
)
from app.store.tasks_lifecycle import cohort_poll as cohort_poll
from app.store.tasks_lifecycle import complete_task as complete_task
from app.store.tasks_lifecycle import has_task_of_type as has_task_of_type
from app.store.tasks_lifecycle import park_task as park_task
from app.store.tasks_lifecycle import (
    park_task_for_rate_limit as park_task_for_rate_limit,
)
from app.store.tasks_lifecycle import (
    queue_health_snapshot as queue_health_snapshot,
)
from app.store.tasks_lifecycle import renew_task_lease as renew_task_lease
from app.store.tasks_lifecycle import reprioritize_task as reprioritize_task
from app.store.tasks_lifecycle import resume_run_tasks as resume_run_tasks
from app.store.tasks_lifecycle import retry_task as retry_task
from app.store.tasks_lifecycle import (
    revive_task_for_retry as revive_task_for_retry,
)

_fail_ambiguous_expired_leases = tasks_recovery._fail_ambiguous_expired_leases
_stop_run_after_unknown_provider_outcome = tasks_recovery._stop_run_after_unknown_provider_outcome


def _insert_task_row(conn: sqlite3.Connection, values: tuple[Any, ...]) -> None:
    conn.execute(
        "INSERT INTO scientific_tasks (id, run_id, task_type, status, "
        "priority, inputs_json, dependencies_json, provenance_json, "
        "idempotency_key, budget_json, max_attempts, created_at, "
        "updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(run_id, idempotency_key) DO NOTHING",
        values,
    )


@dataclasses.dataclass(frozen=True)
class NewTask:
    run_id: str
    task_type: str
    inputs: Mapping[str, Any]
    idempotency_key: str
    priority: int = 0
    dependencies: Iterable[str] = ()
    provenance: Mapping[str, Any] | None = None
    budget: Mapping[str, Any] | None = None
    max_attempts: int = 3


def _task_row_values(task_id: str, task: NewTask, now: float) -> tuple[Any, ...]:
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
    if not task.idempotency_key.strip():
        raise ValueError("idempotency_key must not be empty")
    if task.max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    values = _task_row_values(str(uuid.uuid4()), task, _now())
    with _use_conn(conn, db_path) as active:
        _insert_task_row(active, values)
        row: sqlite3.Row | None = active.execute(
            "SELECT * FROM scientific_tasks WHERE run_id=? AND idempotency_key=?",
            (task.run_id, task.idempotency_key),
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
    with _use_conn(conn, db_path) as active:
        rows = active.execute(
            "SELECT * FROM scientific_tasks WHERE run_id=? ORDER BY created_at ASC",
            (run_id,),
        ).fetchall()
    return [_decode(row) for row in rows]


def list_active_engine_task_run_ids(
    db_path: str | None = None,
) -> list[str]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT t.run_id FROM scientific_tasks t "
            "JOIN runs r ON r.id=t.run_id "
            "WHERE t.task_type LIKE 'engine.%' "
            "AND t.status IN ('queued','leased') "
            "AND r.status IN ('queued','running','synthesizing') "
            "ORDER BY t.run_id"
        ).fetchall()
    from app import dbos_proto

    pending = dbos_proto.pending_review_run_ids(db_path)
    return sorted({str(row["run_id"]) for row in rows} | set(pending))


# Aggregate scalars in SQL without decoding kilobyte task payloads; literal
# substr prefixes avoid LIKE underscore wildcards.
_PROGRESS_QUERY = (
    "SELECT COUNT(*) AS total,"
    " COALESCE(SUM(status IN ('completed','failed','cancelled')), 0)"
    " AS completed,"
    " COALESCE(SUM(status='queued'), 0) AS queued,"
    " COALESCE(MAX(substr(task_type,1,7)='engine.'), 0) AS dynamic_plan,"
    " (SELECT task_type FROM scientific_tasks WHERE run_id=? AND"
    "  status IN ('leased','running')"
    "  ORDER BY created_at ASC LIMIT 1) AS active_task"
    " FROM scientific_tasks WHERE run_id=?"
)


def task_progress(
    run_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    with _use_conn(conn, db_path) as active:
        row = active.execute(
            _PROGRESS_QUERY,
            (run_id, run_id),
        ).fetchone()
    total = int(row["total"])
    completed = int(row["completed"])
    # Model-expanded plans have no honest denominator and must not report
    # determinate fractional progress.
    determinate = total > 0 and not row["dynamic_plan"]
    return {
        "determinate": determinate,
        "completed_tasks": completed,
        "total_tasks": total,
        "fraction": completed / total if determinate else None,
        "active_task": row["active_task"],
        "queued_tasks": int(row["queued"]),
    }


def get_task(
    task_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> ScientificTask | None:
    with _use_conn(conn, db_path) as active:
        row = active.execute("SELECT * FROM scientific_tasks WHERE id=?", (task_id,)).fetchone()
    return _decode(row) if row is not None else None


def _dependencies_complete(conn: sqlite3.Connection, task: ScientificTask) -> bool:
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
    return len(rows) == len(task.dependencies) and all(row["status"] in allowed for row in rows)


def _rescue_expired_leases(conn: sqlite3.Connection, now: float) -> None:
    _fail_ambiguous_expired_leases(conn, now)

    # Without durable request-time admission receipts, expired engine leases
    # fail closed; persisted zero-price admission is the exception.
    conn.execute(
        "UPDATE scientific_tasks SET status='queued', lease_owner=NULL, "
        "lease_expires_at=NULL, updated_at=? "
        f"WHERE {_EXPIRED_LEASE_RESCUABLE} "
        f"AND ({_ENGINE_RUN_STATUS_GUARD})",
        (now, now),
    )


def _queued_tasks_query(run_id: str | None, now: float) -> tuple[str, list[Any]]:
    """Future-due rows stay queued to represent progress, but must not be
    leased before their not-before instant.
    """
    query = (
        "SELECT * FROM scientific_tasks WHERE status='queued'"
        f" AND (available_at IS NULL OR available_at<=?)"
        f" AND ({_ENGINE_RUN_STATUS_GUARD})"
    )
    params: list[Any] = [now]
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
    if not _dependencies_complete(conn, task):
        return None
    expires = now + lease_seconds
    changed = conn.execute(
        "UPDATE scientific_tasks SET status='leased', "
        "attempt=attempt+1, lease_owner=?, lease_expires_at=?, "
        "started_at=COALESCE(started_at, ?), attempt_started_at=?, "
        "updated_at=? WHERE id=? AND status='queued'",
        (worker_id, expires, now, now, now, task.id),
    ).rowcount
    if not changed:
        return None
    leased = conn.execute("SELECT * FROM scientific_tasks WHERE id=?", (task.id,)).fetchone()
    return _decode(leased)


def claim_task(
    worker_id: str,
    *,
    lease_seconds: float = 60.0,
    run_id: str | None = None,
    db_path: str | None = None,
) -> ScientificTask | None:
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")
    if not _has_claimable_task(run_id, db_path):
        return None
    with transaction(db_path) as conn:
        now = _now()
        _rescue_expired_leases(conn, now)
        query, params = _queued_tasks_query(run_id, now)
        for row in conn.execute(query, params).fetchall():
            leased = _try_lease_task(conn, _decode(row), worker_id, now, lease_seconds)
            if leased is not None:
                return leased
    return None


def fail_task(
    task_id: str,
    worker_id: str,
    error: str | TaskFailure,
    *,
    retryable: bool = True,
    retry_at: float | None = None,
    stop_run: bool = False,
    db_path: str | None = None,
) -> bool:
    """Terminal task failure and run settlement share one transaction, so
    the stream cannot remain open with no recoverable work.
    """
    failure = error if isinstance(error, TaskFailure) else TaskFailure(error)
    from app.credentials import redact_byok_text

    failure = TaskFailure(redact_byok_text(failure.error), failure.failure_kind)
    with transaction(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM scientific_tasks WHERE id=? AND status='leased' AND lease_owner=?",
            (task_id, worker_id),
        ).fetchone()
        if row is None:
            return False
        task = _decode(row)
        status = _persist_failed_attempt(conn, task, worker_id, failure.error, retryable, retry_at)
        if status == "failed":
            if stop_run:
                _stop_run_after_unknown_provider_outcome(conn, task.run_id, task.task_type, failure)
            else:
                _settle_run_for_failed_task(
                    conn,
                    task.run_id,
                    task.task_type,
                    failure,
                    retryable=retryable,
                )
    return True
