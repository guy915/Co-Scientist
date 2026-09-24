"""Control-plane lifecycle operations over the durable task queue.

Split out of ``app.store.tasks`` to keep that module within the size cap.
Holds the Supervisor's per-task controls (reprioritize/cancel/retry), the
run-scoped cancel/pause/resume transitions, and the resume path's revival of
terminally-dead tasks. The worker-side lease protocol (claim/complete/renew/
fail) stays in ``app.store.tasks``. Every public name is re-exported from
``app.store.tasks``, so callers and monkeypatching tests are unaffected.
"""

from __future__ import annotations

import json
import sqlite3

from app.store.db import _now, _use_conn, transaction
from app.store.tasks_attempts import _record_failed_attempt
from app.store.tasks_model import _decode
from app.store.tasks_probes import _DEAD_LEASE


def clamp_task_priority(priority: int) -> int:
    """Bound a Supervisor-proposed priority to its declared JSON range.

    The Supervisor's allocation schema promises 0-100 for both the next
    task's priority and each queued reprioritization
    (``supervisor_decision.py``'s ``_DECISION_SCHEMA``), but structured-
    output enforcement is not guaranteed by every provider, so every write
    path re-bounds the value defensively instead of trusting it. This is
    not a property of the ``scientific_tasks.priority`` column itself --
    ``report_notify.py`` deliberately enqueues completion-email tasks at
    priority -100, outside this range, to sink beneath all Supervisor-
    scheduled work.

    Args:
        priority: The proposed priority, from Supervisor JSON output.

    Returns:
        The priority clamped to [0, 100].
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
    """Change one queued task's claim priority and record Supervisor reason."""
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


def cancel_run_tasks(
    run_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Revoke every queued, leased, or paused task for a cancelled run."""
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


def park_task(
    task_id: str,
    worker_id: str,
    reason: str,
    *,
    db_path: str | None = None,
) -> bool:
    """Park one leased task as paused work awaiting an external release.

    The waiting half of the durable queue. A task that stops because a
    person has to decide something has neither failed (retrying cannot
    supply the decision) nor succeeded (its work is not done), and
    recording it as either strands the run: a succeeded row can never be
    revived -- ``revive_task_for_retry`` deliberately refuses it -- and the
    ``{task_type}:{checkpoint_seq}`` idempotency key cannot change while
    the run makes no progress, so re-enqueueing the boundary hits ON
    CONFLICT DO NOTHING and creates nothing to claim. Parking leaves the
    row exactly where ``resume_run_tasks`` finds it.

    The attempt counter is reset for the reason
    :func:`revive_task_for_retry` records: release is a fresh operator
    intent, not a continuation of a retry sequence. Spending the budget on
    holds instead would strand a run held more than twice at exactly the
    silent dead end this function exists to prevent, and the loop is
    bounded by how often a person adjudicates rather than by the worker.

    Args:
        task_id: The leased task to park.
        worker_id: Identity that must still own the lease.
        reason: Human-readable reason recorded on the row.
        db_path: Optional override for the SQLite database path.

    Returns:
        True when this worker still owned the lease and parked the task.
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
    """Return a leased task to the queue, not claimable before resume_at.

    Distinct from :func:`park_task`: that function is the *held-for-a-
    person* wait (a safety hold), which resets the attempt counter because
    release is a fresh operator intent, and leaves the row ``paused`` until
    someone explicitly calls :func:`resume_run_tasks`. This is the
    *waiting-for-a-clock* case -- an ``LLMRateLimitParkError`` from a
    platform-wide rate-limit cap -- so the row stays ``queued`` (the run
    keeps reading as making progress, and the ordinary cohort poll picks it
    back up on its own once ``available_at`` passes, needing no operator
    action) and the attempt this claim spent is undone rather than reset,
    since a park is not a retry and must not consume one -- undoing the
    increment ``_try_lease_task`` made at claim leaves the count exactly
    where it was before this attempt.

    The park is also recorded in the bounded attempt history
    (``retryable=True``) via the same builder ``fail_task`` uses, so
    ``GET /api/runs/{id}/tasks`` shows why the task is waiting.

    Args:
        task_id: The leased task to park.
        worker_id: Identity that must still own the lease.
        reason: Human-readable reason recorded on the row and in its
            attempt history.
        resume_at: Epoch seconds before which the row must not be claimed.
        db_path: Optional override for the SQLite database path.

    Returns:
        True when this worker still owned the lease and parked the task.
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
# redo work the run already committed -- and queued/paused tasks are either
# runnable already or owned by the paths above. A leased task is revivable
# too, but only once its lease has expired: see the query below.
_REVIVABLE_TASK_STATUSES = ("failed", "cancelled")


def _revive_task_row(
    conn: sqlite3.Connection, run_id: str, idempotency_key: str, now: float
) -> int:
    """Revive one terminally-dead or lease-expired task; return rows changed.

    A lease outlives the worker that took it. Once it has expired that
    worker is gone, and with its attempts spent claim_task will not take the
    task back either ("unless their retry budget is spent"), so it is
    stranded until something resets it. An unexpired lease is left strictly
    alone: its owner may still be working, and reviving it would run the
    boundary twice at once.
    """
    placeholders = ",".join("?" * len(_REVIVABLE_TASK_STATUSES))
    return conn.execute(
        "UPDATE scientific_tasks SET status='queued', attempt=0, "
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
        conn: Optional open connection to join an existing transaction.

    Returns:
        True if a dead task was revived, False if there was nothing to revive.
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
    """Mark this run's dead leases failed; return their task types.

    Ordinary failure runs through ``fail_task``, which requires the
    worker to still own the lease and call it. A dead lease is precisely
    the case where that never happens, so the transition is made here
    instead -- to the same ``failed`` status, with an error saying why.
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
    """Fail leases whose owner is gone and whose retries are spent.

    The missing half of ``F1``. ``fail_task`` settles a run when a task
    dies past its retry budget, but it can only run if someone still
    holds the lease to call it. When a worker dies holding a lease whose
    attempts are already spent, nobody calls it and ``claim_task``'s
    rescue skips the row by design -- so it stayed ``leased`` forever,
    blocked ``_settle_run_out_of_work`` (which treats any lease as live
    work), and left the run running with nothing that could advance it.

    Called once when a cohort reaches idle-exit, never on a poll tick:
    it opens a write transaction, and the single SQLite writer cannot
    afford one of those per tick per worker.

    Args:
        run_id: Run whose dead leases should be abandoned.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to join an existing transaction.

    Returns:
        The number of dead leases failed.
    """
    from app.store.runs_reconcile import _settle_run_for_failed_task

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
