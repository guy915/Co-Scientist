from __future__ import annotations

import dataclasses
import json
import sqlite3
from collections.abc import Mapping
from typing import Any

from app.store.db import _now, _use_conn, connect, transaction
from app.store.models import (
    UNKNOWN_PROVIDER_OUTCOME_ERROR,
    ScientificTask,
    TaskFailure,
    _decode,
)


def complete_task(
    task_id: str,
    worker_id: str,
    result: Mapping[str, Any],
    *,
    db_path: str | None = None,
) -> bool:
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


# Bound history above configured retry ceilings while keeping the hot task
# column finite.
_MAX_STORED_ATTEMPTS = 10

# Tracebacks can be arbitrarily large and are decoded on every task read; bound
# each stored attempt.
_ATTEMPT_ERROR_MAX_CHARS = 2000


def _record_failed_attempt(
    task: ScientificTask,
    worker_id: str,
    error: str,
    retryable: bool,
    now: float,
) -> str:
    """Lease claim time is stable; heartbeat-updated timestamps would hide
    the duration of slow failed attempts.
    """
    record = {
        "attempt": task.attempt,
        "error": error[:_ATTEMPT_ERROR_MAX_CHARS],
        "retryable": retryable,
        "worker": worker_id,
        "started_at": task.attempt_started_at,
        "ended_at": now,
    }
    attempts = [*task.attempts, record][-_MAX_STORED_ATTEMPTS:]
    return json.dumps(attempts)


def _persist_failed_attempt(
    conn: sqlite3.Connection,
    task: ScientificTask,
    worker_id: str,
    error: str,
    retryable: bool,
    retry_at: float | None = None,
) -> str:
    """Join the caller's transaction so a failed settlement also rolls back
    the attempt and retry-state write.
    """
    now = _now()
    retry_left = retryable and task.attempt < task.max_attempts
    status = "queued" if retry_left else "failed"
    attempts_json = _record_failed_attempt(
        task, worker_id, error, retryable, now
    )
    conn.execute(
        "UPDATE scientific_tasks SET status=?, error=?, "
        "attempts_json=?, lease_owner=NULL, lease_expires_at=NULL, "
        "available_at=?, completed_at=?, updated_at=? WHERE id=?",
        (
            status,
            error,
            attempts_json,
            retry_at if status == "queued" else None,
            now if status == "failed" else None,
            now,
            task.id,
        ),
    )
    return status


# Share the rescue predicate with advisory probes so liveness checks cannot
# disagree with what a claim can recover.
_EXPIRED_LEASE_RESCUABLE = (
    "status='leased' AND lease_expires_at<=? AND attempt<max_attempts"
)

# Ordinary queued rows have NULL availability and are immediately due; parked
# rows carry their not-before instant.
_QUEUED_AND_DUE = (
    "status='queued' AND (available_at IS NULL OR available_at<=?)"
)

# Spent expired leases cannot be reclaimed or acknowledged and must not count as
# live work; NULL expiry is not proof of abandonment.
_DEAD_LEASE = (
    "status='leased' AND lease_expires_at IS NOT NULL "
    "AND lease_expires_at<=? AND attempt>=max_attempts"
)


def _has_claimable_task(run_id: str | None, db_path: str | None) -> bool:
    """Read-only polling avoids empty BEGIN IMMEDIATE storms; claim rechecks
    under the writer lock, so advisory races cannot double-lease.
    """
    now = _now()
    query = (
        "SELECT 1 FROM scientific_tasks WHERE "
        f"{_ENGINE_RUN_STATUS_GUARD} AND {_QUEUED_AND_DUE}"
        " AND (? IS NULL OR run_id=?)"
        " UNION ALL "
        "SELECT 1 FROM scientific_tasks WHERE "
        f"{_ENGINE_RUN_STATUS_GUARD} AND (? IS NULL OR run_id=?)"
        f" AND {_EXPIRED_LEASE_RESCUABLE}"
        " LIMIT 1"
    )
    with connect(db_path) as conn:
        row = conn.execute(
            query, (now, run_id, run_id, run_id, run_id, now)
        ).fetchone()
    return row is not None


def has_task_of_type(
    run_id: str,
    type_prefix: str,
    *,
    status: str | None = None,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> bool:
    """Literal prefixes match startswith semantics; SQL LIKE would wildcard
    underscores and ignore case.
    """
    query = (
        "SELECT 1 FROM scientific_tasks WHERE run_id=?"
        " AND substr(task_type,1,?)=?"
        " AND (? IS NULL OR status=?)"
        " LIMIT 1"
    )
    params = (run_id, len(type_prefix), type_prefix, status, status)
    with _use_conn(conn, db_path) as active:
        row = active.execute(query, params).fetchone()
    return row is not None


_ACTIVE_RUN_STATUSES = ("queued", "running", "synthesizing")

# Run pause stops engine work without withholding independent completion
# notifications.
_ENGINE_RUN_STATUS_GUARD = (
    "(substr(task_type,1,7)<>'engine.' OR NOT EXISTS "
    "(SELECT 1 FROM runs WHERE runs.id=scientific_tasks.run_id "
    "AND runs.status='paused'))"
)


@dataclasses.dataclass(frozen=True)
class QueueHealthSnapshot:
    stalled_run_ids: tuple[str, ...]
    queued_depth: int
    rescuable_leases: int
    failed_tasks: int


def _summarize_queue_rows(
    rows: list[sqlite3.Row],
) -> QueueHealthSnapshot:
    stalled: list[str] = []
    queued_depth = 0
    rescuable_leases = 0
    failed_tasks = 0
    for row in rows:
        queued_depth += int(row["queued"])
        rescuable_leases += int(row["rescuable"])
        failed_tasks += int(row["failed"])
        if not (row["queued"] or row["active_leases"] or row["rescuable"]):
            stalled.append(str(row["run_id"]))
    return QueueHealthSnapshot(
        stalled_run_ids=tuple(stalled),
        queued_depth=queued_depth,
        rescuable_leases=rescuable_leases,
        failed_tasks=failed_tasks,
    )


def queue_health_snapshot(
    db_path: str | None = None,
) -> QueueHealthSnapshot:
    """A stalled run has no queued, live or rescuable work; this independent
    read-only probe detects broken settlement.
    """
    now = _now()
    placeholders = ",".join("?" for _ in _ACTIVE_RUN_STATUSES)
    query = (
        "SELECT r.id AS run_id,"
        " COALESCE(SUM(t.status='queued'), 0) AS queued,"
        " COALESCE(SUM(t.status='leased' AND t.lease_expires_at>?), 0)"
        " AS active_leases,"
        " COALESCE(SUM(t.status='leased' AND t.lease_expires_at<=?"
        " AND t.attempt<t.max_attempts), 0) AS rescuable,"
        " COALESCE(SUM(t.status='failed'), 0) AS failed"
        " FROM runs r LEFT JOIN scientific_tasks t ON t.run_id = r.id"
        f" WHERE r.status IN ({placeholders})"
        " GROUP BY r.id"
    )
    with connect(db_path) as conn:
        rows = conn.execute(query, (now, now, *_ACTIVE_RUN_STATUSES)).fetchall()
    return _summarize_queue_rows(rows)


def cohort_poll(
    run_id: str, db_path: str | None = None
) -> tuple[bool, bool, float | None]:
    """One read snapshot avoids repeated idle connections; future-due queued
    work keeps the cohort alive, while spent dead leases cannot.
    """
    query = (
        "SELECT"
        f" EXISTS(SELECT 1 FROM scientific_tasks"
        f"        WHERE run_id=? AND {_ENGINE_RUN_STATUS_GUARD}"
        f"        AND {_QUEUED_AND_DUE})"
        " OR EXISTS(SELECT 1 FROM scientific_tasks WHERE run_id=?"
        f"        AND {_ENGINE_RUN_STATUS_GUARD}"
        f"        AND {_EXPIRED_LEASE_RESCUABLE}) AS claimable,"
        " EXISTS(SELECT 1 FROM scientific_tasks"
        "        WHERE run_id=? AND status='leased'"
        "        AND (lease_expires_at IS NULL OR lease_expires_at>?"
        "             OR (attempt<max_attempts AND "
        f"{_ENGINE_RUN_STATUS_GUARD})))"
        " AS active,"
        " (SELECT MIN(available_at) FROM scientific_tasks"
        f"        WHERE run_id=? AND {_ENGINE_RUN_STATUS_GUARD}"
        "        AND status='queued'"
        "        AND available_at IS NOT NULL"
        "        AND available_at>?) AS parked_until"
    )
    now = _now()
    with connect(db_path) as conn:
        row = conn.execute(
            query, (run_id, now, run_id, now, run_id, now, run_id, now)
        ).fetchone()
    parked_until = row["parked_until"]
    return (
        bool(row["claimable"]),
        bool(row["active"]),
        float(parked_until) if parked_until is not None else None,
    )


def _stop_run_after_unknown_provider_outcome(
    conn: sqlite3.Connection,
    run_id: str,
    task_type: str,
    failure: TaskFailure,
) -> None:
    # Fanout aggregates explicitly admit failed siblings. Never replay the item,
    # but preserve the rest of the run and its already-funded work.
    if task_type not in {
        "engine.fanout.review.item",
        "engine.fanout.reflection.item",
        "engine.fanout.verification.item",
        "engine.fanout.generation.strategy",
    }:
        cancel_run_tasks(run_id, conn=conn)
    from app.store.runs_views import _settle_run_for_failed_task

    _settle_run_for_failed_task(
        conn, run_id, task_type, failure, retryable=False
    )


# Persisted campaign policy or zero-cost stamp proves zero-price admission only
# without caller credentials; those expired leases may safely use ordinary
# rescue.
_PROVABLY_FREE_RUN = (
    "(runs.execution_policy='campaign' OR CASE "
    "WHEN json_valid(runs.config_json) "
    "THEN json_extract(runs.config_json,'$.zero_cost_admission') IS 1"
    " ELSE 0 END)"
    " AND NOT EXISTS "
    "(SELECT 1 FROM run_credentials WHERE run_credentials.run_id=runs.id)"
)


def _ambiguous_expired_engine_leases(
    conn: sqlite3.Connection, now: float
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM scientific_tasks WHERE status='leased' "
        "AND lease_expires_at IS NOT NULL AND lease_expires_at<=? "
        f"AND ({_ENGINE_RUN_STATUS_GUARD}) "
        "AND substr(task_type,1,7)='engine.' "
        "AND EXISTS (SELECT 1 FROM runs WHERE runs.id=scientific_tasks.run_id "
        "            AND runs.status IN ('queued','running','synthesizing') "
        f"           AND NOT ({_PROVABLY_FREE_RUN}))",
        (now,),
    ).fetchall()


def _fail_ambiguous_engine_lease(
    conn: sqlite3.Connection,
    task: ScientificTask,
    failure: TaskFailure,
    now: float,
) -> bool:
    attempts_json = _record_failed_attempt(
        task,
        task.lease_owner or "unknown-worker",
        failure.error,
        False,
        now,
    )
    changed = conn.execute(
        "UPDATE scientific_tasks SET status='failed', error=?, "
        "attempts_json=?, lease_owner=NULL, lease_expires_at=NULL, "
        "completed_at=?, updated_at=? WHERE id=? AND status='leased'",
        (failure.error, attempts_json, now, now, task.id),
    ).rowcount
    if not changed:
        return False
    _stop_run_after_unknown_provider_outcome(
        conn, task.run_id, task.task_type, failure
    )
    return True


def _fail_ambiguous_expired_leases(conn: sqlite3.Connection, now: float) -> int:
    failure = TaskFailure(UNKNOWN_PROVIDER_OUTCOME_ERROR, "llm_timeout_unknown")
    failed_runs: set[str] = set()
    failed_count = 0
    for row in _ambiguous_expired_engine_leases(conn, now):
        task = _decode(row)
        if task.run_id in failed_runs:
            continue
        if _fail_ambiguous_engine_lease(conn, task, failure, now):
            row = conn.execute(
                "SELECT status FROM runs WHERE id=?", (task.run_id,)
            ).fetchone()
            if row["status"] == "failed":
                failed_runs.add(task.run_id)
            failed_count += 1
    return failed_count


def clamp_task_priority(priority: int) -> int:
    """Provider schema enforcement is not universal; clamp Supervisor
    priorities only, leaving independent low-priority notifications
    unchanged.
    """
    return max(0, min(100, priority))


def reprioritize_task(
    task_id: str,
    priority: int,
    *,
    reason: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> bool:
    bounded = clamp_task_priority(priority)
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


def cancel_run_tasks(
    run_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    now = _now()
    with _use_conn(conn, db_path) as active:
        changed = active.execute(
            "UPDATE scientific_tasks SET status='cancelled', "
            "lease_owner=NULL, lease_expires_at=NULL, completed_at=?, "
            "updated_at=? WHERE run_id=? "
            "AND status IN ('queued','leased','paused')",
            (now, now, run_id),
        ).rowcount
    return int(changed)


def pause_run_tasks(
    run_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    now = _now()
    with _use_conn(conn, db_path) as active:
        changed = active.execute(
            "UPDATE scientific_tasks SET status='paused', updated_at=? "
            "WHERE run_id=? AND status='queued'",
            (now, run_id),
        ).rowcount
    return int(changed)


def park_task(
    task_id: str,
    worker_id: str,
    reason: str,
    *,
    db_path: str | None = None,
) -> bool:
    """Human holds are neither completion nor failed retries; reset their
    attempts so repeated adjudications cannot strand the same idempotent
    boundary.
    """
    now = _now()
    with transaction(db_path) as conn:
        changed = conn.execute(
            "UPDATE scientific_tasks SET status='paused', attempt=0, "
            "lease_owner=NULL, lease_expires_at=NULL, error=?, updated_at=? "
            "WHERE id=? AND lease_owner=? AND status='leased'",
            (reason, now, task_id, worker_id),
        ).rowcount
    return bool(changed)


def park_task_for_rate_limit(
    task_id: str,
    worker_id: str,
    reason: str,
    resume_at: float,
    *,
    db_path: str | None = None,
) -> bool:
    """Clock waits release the lease without spending an attempt; keep work
    queued so the cohort resumes it without operator action.
    """
    now = _now()
    with transaction(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM scientific_tasks WHERE id=? AND status='leased' "
            "AND lease_owner=?",
            (task_id, worker_id),
        ).fetchone()
        if row is None:
            return False
        task = _decode(row)
        attempts_json = _record_failed_attempt(
            task, worker_id, reason, True, now
        )
        changed = conn.execute(
            "UPDATE scientific_tasks SET status='queued', "
            "attempt=MAX(attempt-1, 0), lease_owner=NULL, "
            "lease_expires_at=NULL, available_at=?, attempts_json=?, "
            "error=?, updated_at=? WHERE id=? AND lease_owner=? "
            "AND status='leased'",
            (resume_at, attempts_json, reason, now, task_id, worker_id),
        ).rowcount
    return bool(changed)


def resume_run_tasks(
    run_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Join lifecycle admission's transaction so unpause and continuation
    discovery cannot race another resume.
    """
    now = _now()
    with _use_conn(conn, db_path) as active:
        changed = active.execute(
            "UPDATE scientific_tasks SET status='queued', updated_at=? "
            "WHERE run_id=? AND status='paused'",
            (now, run_id),
        ).rowcount
    return int(changed)


# Never revive succeeded work or a live lease: either would repeat an already
# committed or still executing boundary.
_REVIVABLE_TASK_STATUSES = ("failed", "cancelled")


def _revive_task_row(
    conn: sqlite3.Connection, run_id: str, idempotency_key: str, now: float
) -> int:
    """Engine attempts fence stale workers and stay monotonic; owner
    recovery extends an exhausted ceiling by at most one, never reviving
    live leases.
    """
    placeholders = ",".join("?" * len(_REVIVABLE_TASK_STATUSES))
    return conn.execute(
        "UPDATE scientific_tasks SET status='queued', "
        "attempt=CASE WHEN substr(task_type,1,7)='engine.' "
        "THEN attempt ELSE 0 END, "
        "max_attempts=CASE WHEN substr(task_type,1,7)='engine.' "
        "THEN MAX(max_attempts, attempt+1) ELSE max_attempts END, "
        "error=NULL, completed_at=NULL, lease_owner=NULL, "
        "lease_expires_at=NULL, updated_at=? WHERE run_id=? AND "
        f"idempotency_key=? AND (status IN ({placeholders}) OR "
        "(status='leased' AND lease_expires_at IS NOT NULL AND "
        "lease_expires_at<=?))",
        (now, run_id, idempotency_key, *_REVIVABLE_TASK_STATUSES, now),
    ).rowcount


def revive_task_for_retry(
    run_id: str,
    idempotency_key: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> bool:
    """Idempotent enqueue cannot resurrect a dead boundary; explicit
    recovery authorizes fresh work without replaying completed tasks.
    """
    now = _now()
    with _use_conn(conn, db_path) as active:
        changed = _revive_task_row(active, run_id, idempotency_key, now)
    return changed > 0


_DEAD_LEASE_ERROR = (
    "The worker holding this task's lease stopped responding, and the "
    "task's retry budget was already spent."
)


def _fail_dead_lease_rows(
    conn: sqlite3.Connection, run_id: str, now: float
) -> list[str]:
    """An expired owner cannot call fail_task; exhausted abandoned leases
    need an explicit terminal transition.
    """
    rows = conn.execute(
        f"SELECT id, task_type FROM scientific_tasks WHERE run_id=? "
        f"AND {_DEAD_LEASE}",
        (run_id, now),
    ).fetchall()
    for row in rows:
        conn.execute(
            "UPDATE scientific_tasks SET status='failed', error=?, "
            "lease_owner=NULL, lease_expires_at=NULL, completed_at=?, "
            "updated_at=? WHERE id=?",
            (_DEAD_LEASE_ERROR, now, now, row["id"]),
        )
    return [str(row["task_type"]) for row in rows]


def abandon_dead_leases(
    run_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Settle spent orphaned leases once at cohort idle exit, never by
    taking the SQLite write lock on every poll tick.
    """
    from app.store.runs_views import _settle_run_for_failed_task

    now = _now()
    with _use_conn(conn, db_path) as active:
        task_types = _fail_dead_lease_rows(active, run_id, now)
        if not task_types:
            return 0
        _settle_run_for_failed_task(
            active,
            run_id,
            task_types[0],
            _DEAD_LEASE_ERROR,
            retryable=True,
        )
    return len(task_types)
