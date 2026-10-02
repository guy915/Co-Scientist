"""Recording a leased task's outcome: completion, renewal, and failure.

Split out of ``app.store.tasks`` to keep that module within the size cap.
Holds the two simple lease-outcome writes (``complete_task``,
``renew_task_lease``) plus the bounded failed-attempt history --
``_record_failed_attempt`` builds the JSON blob, and
``_persist_failed_attempt`` writes it alongside the task's resulting
status inside the caller's own transaction. ``fail_task`` itself stays in
``app.store.tasks``: it also calls ``_settle_run_for_failed_task``, and a
test monkeypatches that name on ``app.store.tasks`` to verify the whole
write is transactional, which only holds while the call site resolving it
lives in that module. The names callers use are re-exported from
``app.store.tasks``, so callers and monkeypatching tests
(``store_tasks._MAX_STORED_ATTEMPTS``) are unaffected.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from typing import Any

from app.store.db import _now, transaction
from app.store.tasks_model import ScientificTask


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


# The largest max_attempts any caller in this codebase configures is 3
# (the NewTask default; notifications.py's own retry task uses it too).
# Capped well above that for headroom against a future caller raising its
# own budget, while still bounding this column's size on a hot table.
_MAX_STORED_ATTEMPTS = 10

# A traceback-carrying error can be arbitrarily large, and this column is
# decoded on every task read -- cap per-attempt storage the same way
# store/events.py caps its own free-text fields.
_ATTEMPT_ERROR_MAX_CHARS = 2000


def _record_failed_attempt(
    task: ScientificTask,
    worker_id: str,
    error: str,
    retryable: bool,
    now: float,
) -> str:
    """Append this attempt's failure to the task's bounded history.

    ``task.attempt_started_at`` is set once per lease, at claim time
    (``_try_lease_task``) -- deliberately not ``task.updated_at``, which
    a long attempt's heartbeat renewal (``renew_task_lease``) also bumps,
    and would otherwise report only the most recent renewal as the
    attempt's start for exactly the slow failures this history exists to
    diagnose.

    Returns:
        The updated ``attempts_json`` value, capped at
        :data:`_MAX_STORED_ATTEMPTS` entries, newest last.
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


def _persist_failed_attempt(  # noqa: PLR0913 -- writes retry timing atomically.
    conn: sqlite3.Connection,
    task: ScientificTask,
    worker_id: str,
    error: str,
    retryable: bool,
    retry_at: float | None = None,
) -> str:
    """Record one failed attempt and write the resulting task state.

    Computes retry eligibility, appends the attempt to the bounded
    history, and writes both in the caller's own transaction (never
    opens one of its own), so a caller that rolls back afterwards --
    e.g. because settlement raises -- undoes this write too.

    Returns:
        The resulting task status, ``"queued"`` or ``"failed"``.
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
