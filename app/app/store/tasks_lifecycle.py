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
# redo work the run already committed -- and queued/paused tasks are either
# runnable already or owned by the paths above. A leased task is revivable
# too, but only once its lease has expired: see the query below.
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
    now = _now()
    with transaction(db_path) as conn:
        changed = conn.execute(
            "UPDATE scientific_tasks SET status='queued', attempt=0, "
            "error=NULL, completed_at=NULL, lease_owner=NULL, "
            "lease_expires_at=NULL, updated_at=? WHERE run_id=? AND "
            f"idempotency_key=? AND (status IN ({placeholders}) OR "
            # A lease outlives the worker that took it. Once it has expired
            # that worker is gone, and with its attempts spent claim_task will
            # not take the task back either ("unless their retry budget is
            # spent"), so it is stranded until something resets it. An
            # unexpired lease is left strictly alone: its owner may still be
            # working, and reviving it would run the boundary twice at once.
            "(status='leased' AND lease_expires_at IS NOT NULL AND "
            "lease_expires_at<=?))",
            (now, run_id, idempotency_key, *_REVIVABLE_TASK_STATUSES, now),
        ).rowcount
    return int(changed) > 0
