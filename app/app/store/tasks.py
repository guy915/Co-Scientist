"""Durable scientific task queue with leases and idempotent completion.

The row <-> dataclass mapping (``ScientificTask``, ``_decode``) lives in
``app.store.tasks_model``, split out so ``app.store.tasks_attempts`` can
decode a task row without importing back from this module. The
lease-outcome writes for a completed or renewed task, and the bounded
failed-attempt history bookkeeping, live in ``app.store.tasks_attempts``.
``fail_task`` itself stays here: it also calls
``_settle_run_for_failed_task``, and a test monkeypatches that name on
this module to verify the whole write is transactional, which only holds
while the call site resolving it lives here too.

The control-plane lifecycle operations (Supervisor reprioritize/cancel/
retry, run-scoped cancel/pause/resume, and terminally-dead task revival)
live in ``app.store.tasks_lifecycle``, and the read-only cohort liveness
probes live in ``app.store.tasks_probes``. Ambiguous provider outcomes and
expired-lease recovery live in ``app.store.tasks_recovery``. The names from
those sibling modules that callers use are re-exported here.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from app.store import tasks_recovery
from app.store.db import _now, _use_conn, connect, transaction
from app.store.runs_reconcile import (
    _settle_run_for_failed_task as _settle_run_for_failed_task,
)
from app.store.tasks_attempts import (
    _MAX_STORED_ATTEMPTS as _MAX_STORED_ATTEMPTS,
)
from app.store.tasks_attempts import (
    _persist_failed_attempt as _persist_failed_attempt,
)
from app.store.tasks_attempts import complete_task as complete_task
from app.store.tasks_attempts import renew_task_lease as renew_task_lease
from app.store.tasks_lifecycle import (
    abandon_dead_leases as abandon_dead_leases,
)
from app.store.tasks_lifecycle import cancel_run_tasks as cancel_run_tasks
from app.store.tasks_lifecycle import cancel_task as cancel_task
from app.store.tasks_lifecycle import (
    clamp_task_priority as clamp_task_priority,
)
from app.store.tasks_lifecycle import park_task as park_task
from app.store.tasks_lifecycle import (
    park_task_for_rate_limit as park_task_for_rate_limit,
)
from app.store.tasks_lifecycle import pause_run_tasks as pause_run_tasks
from app.store.tasks_lifecycle import reprioritize_task as reprioritize_task
from app.store.tasks_lifecycle import resume_run_tasks as resume_run_tasks
from app.store.tasks_lifecycle import retry_task as retry_task
from app.store.tasks_lifecycle import (
    revive_task_for_retry as revive_task_for_retry,
)
from app.store.tasks_model import ScientificTask as ScientificTask
from app.store.tasks_model import TaskFailure as TaskFailure
from app.store.tasks_model import _decode as _decode
from app.store.tasks_probes import (
    _ENGINE_RUN_STATUS_GUARD as _ENGINE_RUN_STATUS_GUARD,
)
from app.store.tasks_probes import (
    _EXPIRED_LEASE_RESCUABLE as _EXPIRED_LEASE_RESCUABLE,
)
from app.store.tasks_probes import (
    QueueHealthSnapshot as QueueHealthSnapshot,
)
from app.store.tasks_probes import (
    _has_claimable_task as _has_claimable_task,
)
from app.store.tasks_probes import cohort_poll as cohort_poll
from app.store.tasks_probes import has_task_of_type as has_task_of_type
from app.store.tasks_probes import (
    queue_health_snapshot as queue_health_snapshot,
)

_fail_ambiguous_expired_leases = tasks_recovery._fail_ambiguous_expired_leases
_stop_run_after_unknown_provider_outcome = (
    tasks_recovery._stop_run_after_unknown_provider_outcome
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
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT t.run_id FROM scientific_tasks t "
            "JOIN runs r ON r.id=t.run_id "
            "WHERE t.task_type LIKE 'engine.%' "
            "AND t.status IN ('queued','leased') "
            "AND r.status IN ('queued','running','synthesizing') "
            "ORDER BY t.run_id"
        ).fetchall()
    return [str(row["run_id"]) for row in rows]


# Nothing enqueues the legacy "run.workflow" task type any more, but rows of
# that type may still exist in production databases created before the
# node-level durable executor. Such a lease is only a process boundary, not a
# disclosed scientific work budget, so it is excluded from every part of the
# rollup to keep progress determinate for any run that still carries one.
_LEGACY_TASK_TYPE = "run.workflow"

# One aggregate rather than decoding every task row: a fan-out item's
# inputs_json alone is kilobytes, and none of the four JSON columns a task
# carries contributes to these five scalars. This is read once per run on
# every run-list response and again on every run-detail poll, so the decode
# was paid over and over for numbers SQLite can count in place. The engine
# prefix is compared with substr rather than LIKE, matching
# ``has_task_of_type``: LIKE would treat "_" as a wildcard.
_PROGRESS_QUERY = (
    "SELECT COUNT(*) AS total,"
    " COALESCE(SUM(status IN ('completed','failed','cancelled')), 0)"
    " AS completed,"
    " COALESCE(SUM(status='queued'), 0) AS queued,"
    " COALESCE(MAX(substr(task_type,1,7)='engine.'), 0) AS dynamic_plan,"
    " (SELECT task_type FROM scientific_tasks WHERE run_id=? AND"
    "  task_type<>? AND status IN ('leased','running')"
    "  ORDER BY created_at ASC LIMIT 1) AS active_task"
    " FROM scientific_tasks WHERE run_id=? AND task_type<>?"
)


def task_progress(
    run_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Summarize monotonic execution progress from committed durable tasks."""
    with _use_conn(conn, db_path) as active:
        row = active.execute(
            _PROGRESS_QUERY,
            (run_id, _LEGACY_TASK_TYPE, run_id, _LEGACY_TASK_TYPE),
        ).fetchone()
    total = int(row["total"])
    completed = int(row["completed"])
    # A model-expanded plan has no honest denominator, so it reports neither
    # a fraction nor determinacy however many tasks have committed.
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
    """Fail ambiguous engine leases before rescuing other expired work."""
    _fail_ambiguous_expired_leases(conn, now)

    # Engine leases have no durable request-time admission receipt, so they
    # fail closed regardless of the current route configuration -- except on
    # a campaign run, whose persisted policy is that receipt (see
    # tasks_recovery._PROVABLY_FREE_RUN); those fall through to this rescue.
    conn.execute(
        "UPDATE scientific_tasks SET status='queued', lease_owner=NULL, "
        "lease_expires_at=NULL, updated_at=? "
        f"WHERE {_EXPIRED_LEASE_RESCUABLE} "
        f"AND ({_ENGINE_RUN_STATUS_GUARD})",
        (now, now),
    )


def _queued_tasks_query(
    run_id: str | None, now: float
) -> tuple[str, list[Any]]:
    """Build the ready-task query ordered by priority then age.

    Excludes a row parked with a future ``available_at`` (see
    ``tasks_lifecycle.park_task_for_rate_limit``) -- it is ``queued`` so
    the run reads as making progress, but not yet due.
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
    """Attempt to lease one ready task to worker_id; return it on success."""
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
        query, params = _queued_tasks_query(run_id, now)
        for row in conn.execute(query, params).fetchall():
            leased = _try_lease_task(
                conn, _decode(row), worker_id, now, lease_seconds
            )
            if leased is not None:
                return leased
    return None


def fail_task(  # noqa: PLR0913 -- retry timing stays atomic with failure.
    task_id: str,
    worker_id: str,
    error: str | TaskFailure,
    *,
    retryable: bool = True,
    retry_at: float | None = None,
    stop_run: bool = False,
    db_path: str | None = None,
) -> bool:
    """Record failure and requeue when the bounded retry budget permits.

    A failure that spends the task's last attempt (or is permanent) also
    settles the run when nothing claimable remains: the run transitions
    to failed and its terminal status event is appended inside this same
    transaction, so a run can never be left running with no work that
    could ever advance it (the SSE stream closes on that event).
    """
    failure = error if isinstance(error, TaskFailure) else TaskFailure(error)
    from app.credentials import redact_byok_text

    failure = TaskFailure(redact_byok_text(failure.error), failure.failure_kind)
    with transaction(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM scientific_tasks WHERE id=? AND status='leased' "
            "AND lease_owner=?",
            (task_id, worker_id),
        ).fetchone()
        if row is None:
            return False
        task = _decode(row)
        status = _persist_failed_attempt(
            conn, task, worker_id, failure.error, retryable, retry_at
        )
        if status == "failed":
            if stop_run:
                _stop_run_after_unknown_provider_outcome(
                    conn, task.run_id, task.task_type, failure
                )
            else:
                _settle_run_for_failed_task(
                    conn,
                    task.run_id,
                    task.task_type,
                    failure,
                    retryable=retryable,
                )
    return True
