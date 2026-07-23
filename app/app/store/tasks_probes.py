"""Read-only liveness probes over the durable scientific task queue.

Split out of ``app.store.tasks`` to keep that module within the size cap.
Holds the advisory, read-only questions idle cohort workers ask on every
tick -- "is anyone still working?" and "could a claim attempt find
work?" -- plus the shared expired-lease liveness fragment those probes
and the claim's rescue UPDATE interpolate. The worker-side lease
protocol (claim/complete/renew/fail) stays in ``app.store.tasks``.
Every name is re-exported from ``app.store.tasks``, so callers and
monkeypatching tests are unaffected.
"""

from __future__ import annotations

from app.store.db import _now, connect


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
