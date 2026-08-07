"""Read-only liveness probes over the durable scientific task queue.

Split out of ``app.store.tasks`` to keep that module within the size cap.
Holds the advisory, read-only questions idle cohort workers ask on every
tick -- "is anyone still working?" and "could a claim attempt find
work?" -- plus the endpoint-side existence checks and the shared
expired-lease liveness fragment those probes and the claim's rescue
UPDATE interpolate. The worker-side lease protocol
(claim/complete/renew/fail) stays in ``app.store.tasks``.
Every name is re-exported from ``app.store.tasks``, so callers and
monkeypatching tests are unaffected.

An existence check belongs here rather than in a caller's ``any(...)``
over ``list_tasks``: decoding every row of a late-stage run's task table
to compute one boolean is work that grows as the run does.
"""

from __future__ import annotations

import dataclasses
import sqlite3

from app.store.db import _now, connect

# The liveness invariant shared by the advisory probes and the claim's
# rescue UPDATE: an expired lease with retry budget left is claimable
# again. One fragment, interpolated everywhere it applies, so a probe can
# never say "no work" while the claim's rescue would have found some.
# Binds one parameter: the current time.
_EXPIRED_LEASE_RESCUABLE = (
    "status='leased' AND lease_expires_at<=? AND attempt<max_attempts"
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


def has_task_of_type(
    run_id: str,
    type_prefix: str,
    *,
    status: str | None = None,
    db_path: str | None = None,
) -> bool:
    """Return whether the run has a task of this type prefix and status.

    Read-only, like every probe here: it opens no write transaction, so it
    can never queue behind (or ahead of) the single writer.

    The prefix is compared literally, not as a LIKE pattern, so it matches
    a caller's ``task_type.startswith(prefix)`` exactly -- LIKE would treat
    ``_`` as a wildcard and match case-insensitively.

    Args:
        run_id: Identifier of the run whose tasks to probe.
        type_prefix: Literal prefix the task type must start with.
        status: Optional queue status the task must also be in.
        db_path: Optional override for the SQLite database path.

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
    with connect(db_path) as conn:
        row = conn.execute(query, params).fetchone()
    return row is not None


_ACTIVE_RUN_STATUSES = ("queued", "running", "synthesizing")


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
    (``app.store.runs_reconcile._settle_run_out_of_work``) left open: it
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


def cohort_poll(run_id: str, db_path: str | None = None) -> tuple[bool, bool]:
    """One idle-tick snapshot for a cohort worker: (claimable, active lease).

    The cohort's idle loop needs both answers every tick -- "is there work
    to claim" and "is a sibling still holding a lease that may fan out
    more". Asking them separately opened two connections per tick per
    worker, sustained for the whole wall clock of every run; one read-only
    connection answers both from a single consistent snapshot.

    A *dead* lease (see ``_DEAD_LEASE``) is excluded from the active
    answer. It is not a sibling that may fan out more work: its owner is
    provably gone and its retry budget is spent, so nothing will ever
    acknowledge it. Counting it as active kept every cohort member
    polling for the life of the process over a task none of them could
    ever claim -- the run neither progressed nor ended. Excluding it lets
    the cohort reach idle-exit, which is where ``abandon_dead_leases``
    settles the run.
    """
    query = (
        "SELECT"
        " EXISTS(SELECT 1 FROM scientific_tasks"
        "        WHERE run_id=? AND status='queued')"
        " OR EXISTS(SELECT 1 FROM scientific_tasks WHERE run_id=?"
        f"        AND {_EXPIRED_LEASE_RESCUABLE}) AS claimable,"
        " EXISTS(SELECT 1 FROM scientific_tasks"
        "        WHERE run_id=? AND status='leased'"
        "        AND (lease_expires_at IS NULL OR lease_expires_at>?"
        "             OR attempt<max_attempts)) AS active"
    )
    now = _now()
    with connect(db_path) as conn:
        row = conn.execute(query, (run_id, run_id, now, run_id, now)).fetchone()
    return bool(row["claimable"]), bool(row["active"])
