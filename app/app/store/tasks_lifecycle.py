"""Control-plane lifecycle operations over the durable task queue."""

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


def _persist_failed_attempt(
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


# The liveness invariant shared by the advisory probes and the claim's
# rescue UPDATE: an expired lease with retry budget left is claimable
# again. One fragment, interpolated everywhere it applies, so a probe can
# never say "no work" while the claim's rescue would have found some.
# Binds one parameter: the current time.
_EXPIRED_LEASE_RESCUABLE = (
    "status='leased' AND lease_expires_at<=? AND attempt<max_attempts"
)

# A queued row is only actually claimable once its not-before instant has
# passed (see store.tasks_lifecycle.park_task_for_rate_limit); NULL is
# every ordinarily-enqueued row, claimable immediately as it always was.
# Binds one parameter: the current time.
_QUEUED_AND_DUE = (
    "status='queued' AND (available_at IS NULL OR available_at<=?)"
)

# The complement of the fragment above, and the reason it needs a name: an
# expired lease whose retry budget is *spent* is claimable by nobody and
# owned by nobody. The worker that took it is provably gone (the lease
# outlived it), so no ``fail_task`` call is ever coming, and the rescue
# UPDATE skips it by design. Left untreated the row sits ``leased``
# forever, which counted as live work to both the cohort's idle tick and
# ``_settle_run_out_of_work`` -- so the cohort never exited and the run
# never settled, the exact "non-terminal with no claimable work" state
# ``F1`` was meant to make impossible. Call it dead, not active:
# ``abandon_dead_leases`` fails such rows explicitly and settles the run.
# A NULL expiry is not dead -- it is a lease that was never given a
# deadline, not one that outlived its owner.
_DEAD_LEASE = (
    "status='leased' AND lease_expires_at IS NOT NULL "
    "AND lease_expires_at<=? AND attempt>=max_attempts"
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
    """Return whether the run has a task of this type prefix and status.

    Read-only. With no supplied connection it opens no write transaction;
    callers may also join an existing transaction for an atomic decision.

    The prefix is compared literally, not as a LIKE pattern, so it matches
    a caller's ``task_type.startswith(prefix)`` exactly -- LIKE would treat
    ``_`` as a wildcard and match case-insensitively.

    Args:
        run_id: Identifier of the run whose tasks to probe.
        type_prefix: Literal prefix the task type must start with.
        status: Optional queue status the task must also be in.
        db_path: Optional override for the SQLite database path.
        conn: Optional transaction to join.

    Returns:
        True if the run has at least one matching task.
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

# Pausing a run stops engine workflow tasks while leaving independent work,
# such as a completion notification, eligible for the general task queue.
_ENGINE_RUN_STATUS_GUARD = (
    "(substr(task_type,1,7)<>'engine.' OR NOT EXISTS "
    "(SELECT 1 FROM runs WHERE runs.id=scientific_tasks.run_id "
    "AND runs.status='paused'))"
)


@dataclasses.dataclass(frozen=True)
class QueueHealthSnapshot:
    """Read-only ``/health`` snapshot of durable-queue health.

    Attributes:
        stalled_run_ids: Non-terminal runs with no queued task, no
            unexpired lease, and no rescuable expired lease -- nothing a
            fresh claim or a live worker cohort could pick up. See
            :func:`queue_health_snapshot` for why this is a real gap.
        queued_depth: Total queued tasks across active runs. Informational
            only: a busy system is supposed to have some, so this never by
            itself marks the check unhealthy.
        rescuable_leases: Expired leases with retry budget left, which the
            next ``claim_task`` call rescues automatically.
        failed_tasks: Terminally failed tasks belonging to a run that still
            has other active work and so has not settled yet.
    """

    stalled_run_ids: tuple[str, ...]
    queued_depth: int
    rescuable_leases: int
    failed_tasks: int


def _summarize_queue_rows(
    rows: list[sqlite3.Row],
) -> QueueHealthSnapshot:
    """Fold per-run aggregate rows into one queue health snapshot."""
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
    """Summarize durable-queue health across active runs for ``/health``.

    One read-only aggregate query, grouped per active run -- no write
    transaction, so it is as safe to run on every health poll as
    :func:`_has_claimable_task`. A run counts as stalled when it has no
    queued task, no lease with time left on it, and no expired lease still
    within its retry budget: nothing a worker cohort or a fresh claim
    could ever pick up.

    This used to describe a gap the F1 fix
    (``app.store.runs_views._settle_run_out_of_work``) left open: it
    only settles a run when ``fail_task`` explicitly marks a task
    ``failed``, and a lease that expires *after* its retry budget is spent
    is never explicitly failed -- nobody still holds it to call
    ``fail_task`` -- so the row stayed ``leased`` forever, counted as
    active work to ``_settle_run_out_of_work``'s own query, and left the
    run ``running`` with no worker that would ever touch it again.
    ``tasks_lifecycle.abandon_dead_leases`` closes it: the cohort now
    reaches idle-exit over such a row (see ``cohort_poll``) and fails it
    there. This probe stays as the independent check that it worked --
    a stalled run reported here is now a bug rather than a known state.

    Args:
        db_path: Optional override for the SQLite database path.

    Returns:
        The snapshot described above.
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
    """One idle-tick snapshot: (claimable, active lease, parked-until).

    The cohort's idle loop needs all three answers every tick -- "is there
    work to claim", "is a sibling still holding a lease that may fan out
    more", and "is the only remaining work a rate-limit park that will
    become claimable later". Asking them separately opened extra
    connections per tick per worker, sustained for the whole wall clock of
    every run; one read-only connection answers all three from a single
    consistent snapshot.

    A *dead* lease (see ``_DEAD_LEASE``) is excluded from the active
    answer. It is not a sibling that may fan out more work: its owner is
    provably gone and its retry budget is spent, so nothing will ever
    acknowledge it. Counting it as active kept every cohort member
    polling for the life of the process over a task none of them could
    ever claim -- the run neither progressed nor ended. Excluding it lets
    the cohort reach idle-exit, which is where ``abandon_dead_leases``
    settles the run.

    A row parked by ``park_task_for_rate_limit`` is neither claimable (its
    ``available_at`` is still in the future) nor an active lease (it was
    released back to ``queued``), so without the third answer the cohort
    reads it as no work at all and exits -- exactly the stranding this was
    built to avoid. ``parked_until`` is the soonest such row's not-before
    instant, so the idle loop knows how long it may safely sleep.
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
    """Revoke sibling work and publish one terminal unknown-outcome event."""
    cancel_run_tasks(run_id, conn=conn)
    from app.store.runs_views import _settle_run_for_failed_task

    _settle_run_for_failed_task(
        conn, run_id, task_type, failure, retryable=False
    )


# A campaign run's policy is persisted at creation and never weakens, and
# under it every provider request must pass the exact zero-price gate
# (``co_scientist.llm.admission.free_policy.enforce_free_request``) or it is
# refused before transport. So a lease such a run lost cannot have spent
# anything, provided no caller credential rode along -- the same evidence
# ``LLMTimeoutError.zero_cost_admitted`` carries for a live timeout. Those
# leases are left to the ordinary expired-lease rescue, which retries them
# within the task's attempt budget. Failing them instead stopped a healthy
# campaign run after a restart (run 34b29088, 2026-09-27: the verification
# item's lease outlived the process that held it, and the run failed with
# llm_timeout_unknown although every call it could have made was free).
_PROVABLY_FREE_RUN = (
    "runs.execution_policy='campaign' AND NOT EXISTS "
    "(SELECT 1 FROM run_credentials WHERE run_credentials.run_id=runs.id)"
)


def _ambiguous_expired_engine_leases(
    conn: sqlite3.Connection, now: float
) -> list[sqlite3.Row]:
    """Read active engine leases whose original request outcome is unknown."""
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
    """Fail one expired lease and stop its run in the caller's transaction."""
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
    """Fail each active run's first expired engine lease, transactionally."""
    failure = TaskFailure(UNKNOWN_PROVIDER_OUTCOME_ERROR, "llm_timeout_unknown")
    failed_runs: set[str] = set()
    failed_count = 0
    for row in _ambiguous_expired_engine_leases(conn, now):
        task = _decode(row)
        if task.run_id in failed_runs:
            continue
        if _fail_ambiguous_engine_lease(conn, task, failure, now):
            failed_runs.add(task.run_id)
            failed_count += 1
    return failed_count


def clamp_task_priority(priority: int) -> int:
    """Bound a Supervisor-proposed priority to its declared JSON range.

    The Supervisor's allocation schema promises 0-100 for both the next
    task's priority and each queued reprioritization
    (``supervisor_decision.py``'s ``_DECISION_SCHEMA``), but structured-
    output enforcement is not guaranteed by every provider, so every write
    path re-bounds the value defensively instead of trusting it. This is
    not a property of the ``scientific_tasks.priority`` column itself --
    ``notifications.py`` deliberately enqueues completion-email tasks at
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


def pause_run_tasks(
    run_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Make queued work non-claimable, joining a caller transaction if given."""
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


def resume_run_tasks(
    run_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Return paused queued work to the global ready queue.

    A caller may pass its existing write transaction to make unpausing
    atomic with the subsequent resume-work discovery and enqueue.
    """
    now = _now()
    with _use_conn(conn, db_path) as active:
        changed = active.execute(
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

    Engine attempt numbers also fence stale workers, so keep their sequence
    monotonic. Preserve the original retry ceiling and extend it by at most
    one when already exhausted; each owner recovery therefore authorizes no
    more than one extra attempt. An unexpired lease is left strictly alone:
    its owner may still be working, and reviving it would run the boundary
    twice at once.
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
