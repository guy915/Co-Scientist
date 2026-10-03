"""Enriched run-list queries and replayable artifact resets."""

from __future__ import annotations

import logging
import sqlite3

from app.store.checkpoints import has_checkpoint
from app.store.db import _now, _use_conn, connect, transaction
from app.store.events import _append_event
from app.store.models import (
    TERMINAL_STATUSES,
    RunRow,
    RunStatus,
    TaskFailure,
    _row_to_run,
)

logger = logging.getLogger(__name__)

# Statuses that mark a run as occupying a concurrency slot / still in flight.
_ACTIVE_RUN_STATUSES: tuple[str, str, str] = (
    RunStatus.QUEUED.value,
    RunStatus.RUNNING.value,
    RunStatus.SYNTHESIZING.value,
)


def _fail_interrupted_run(
    conn: sqlite3.Connection,
    run_id: str,
    now: float,
    reason: str,
) -> None:
    """Transition one interrupted run to failed and log a status event.

    Args:
        conn: Open connection to run the update and event append on.
        run_id: Identifier of the run to fail.
        now: Timestamp to record as the update and completion time.
        reason: Human-readable interruption reason to store and log.
    """
    conn.execute(
        "UPDATE runs SET status=?, error=?, updated_at=?, "
        "completed_at=? WHERE id=?",
        (RunStatus.FAILED.value, reason, now, now, run_id),
    )
    _append_event(
        conn, run_id, "status", {"status": "failed", "error": reason}, now
    )


def _settle_run_out_of_work(
    conn: sqlite3.Connection,
    run_id: str,
    error: str,
    now: float,
    failure_kind: str | None = None,
) -> bool:
    """Fail an active run durably because no claimable work remains.

    The in-process mirror of the startup sweep's fail outcome, called
    inside the same transaction that just failed a task past its retry
    budget (or permanently), so the probe sees exactly the state the run
    is left in. Any queued or leased task blocks settlement: a queued
    task is claimable, and a live lease may still fan out more work. The
    run update is conditional on an active status, so two workers failing
    one run's last tasks concurrently cannot both settle it -- only the
    first UPDATE lands, and only its transaction appends the terminal
    status event the SSE stream closes on. Unlike
    :func:`_fail_interrupted_run` the transition is guarded: at startup
    nothing executes, while in-process another writer may be mid-flight.

    Args:
        conn: Connection carrying the failing task's transaction.
        run_id: Identifier of the run the failed task belongs to.
        error: Failure reason to persist on the run and its status event.
        now: Timestamp recorded for the transition and the event.
        failure_kind: Optional exact provider failure type to persist.

    Returns:
        True when this call transitioned the run to failed.
    """
    row = conn.execute(
        "SELECT 1 FROM scientific_tasks WHERE run_id=? "
        "AND status IN ('queued','leased') LIMIT 1",
        (run_id,),
    ).fetchone()
    if row is not None:
        return False
    placeholders = ",".join("?" for _ in _ACTIVE_RUN_STATUSES)
    changed = conn.execute(
        "UPDATE runs SET status=?, error=?, updated_at=?, completed_at=? "
        f"WHERE id=? AND status IN ({placeholders})",
        (
            RunStatus.FAILED.value,
            error,
            now,
            now,
            run_id,
            *_ACTIVE_RUN_STATUSES,
        ),
    ).rowcount
    if not changed:
        return False
    payload = {"status": "failed", "error": error}
    if failure_kind is not None:
        payload["failure_kind"] = failure_kind
    _append_event(conn, run_id, "status", payload, now)
    return True


def _settle_run_for_failed_task(
    conn: sqlite3.Connection,
    run_id: str,
    task_type: str,
    error: str | TaskFailure,
    *,
    retryable: bool,
) -> None:
    """Settle a run whose task just failed terminally, if no work remains.

    Builds the run-level failure reason from the task outcome and
    delegates to :func:`_settle_run_out_of_work`; called inside the
    failing task's own transaction so settlement is atomic with it.

    Args:
        conn: Connection carrying the failing task's transaction.
        run_id: Identifier of the run the failed task belongs to.
        task_type: Task type name used in the persisted failure reason.
        error: The task's raw failure, optionally with its exact kind.
        retryable: False for a permanent failure, True when the retry
            budget was just exhausted.
    """
    failure = error if isinstance(error, TaskFailure) else TaskFailure(error)
    reason = (
        f"Task {task_type} failed permanently: {failure.error}"
        if not retryable
        else f"Task {task_type} exhausted its retry budget: {failure.error}"
    )
    if _settle_run_out_of_work(
        conn,
        run_id,
        reason,
        _now(),
        failure_kind=failure.failure_kind,
    ):
        logger.info(
            "Run %s failed: no claimable work remains (%s)", run_id, reason
        )


def _reconcile_one_run(
    conn: sqlite3.Connection, run_id: str, now: float, reason: str
) -> str:
    """Reconcile one interrupted run and return its outcome.

    Args:
        conn: Open connection to run the resumability checks and update
            on.
        run_id: Identifier of the interrupted run.
        now: Timestamp to record for any status change.
        reason: Human-readable interruption reason for a failed outcome.

    Returns:
        ``"resumable"`` when a checkpoint exists, else ``"failed"``.
    """
    if has_checkpoint(run_id, conn=conn):
        _append_event(
            conn,
            run_id,
            "status",
            {"status": "resumable", "detail": "checkpoint available"},
            now,
        )
        return "resumable"
    _fail_interrupted_run(conn, run_id, now, reason)
    return "failed"


def _fail_ambiguous_expired_provider_leases(
    db_path: str | None, now: float
) -> None:
    """Commit unknown lease outcomes before a generic restart event."""
    from app.store.tasks import _fail_ambiguous_expired_leases

    with transaction(db_path) as conn:
        _fail_ambiguous_expired_leases(conn, now)


def reconcile_interrupted_runs(
    db_path: str | None = None,
) -> dict[str, list[str]]:
    """Reconcile runs left non-terminal by a previous process (crash/restart).

    On startup no workflow tasks are running, so any run still marked queued,
    running, or synthesizing was interrupted. A run that has a durable
    checkpoint is *resumable* (Milestone 4): it is left for the resume path
    rather than failed, and a ``resumable`` status event is logged. A run
    without one cannot be resumed and is transitioned to ``failed`` with a
    clear reason and a status event so the stream/UI reflect the
    interruption.

    Args:
        db_path: Optional override for the SQLite database path.

    Returns:
        ``{"failed": [...], "resumable": [...]}`` — the ids in each outcome.
    """
    now = _now()
    reason = "Run interrupted by a server restart."
    failed: list[str] = []
    resumable: list[str] = []
    _fail_ambiguous_expired_provider_leases(db_path, now)
    with connect(db_path) as conn:
        # A finalize task can commit its report and then lose the process
        # before the worker records task success. At startup all prior
        # process leases are orphaned, so settle only that already-published
        # boundary; no active run or other task type is eligible here.
        recovered = conn.execute(
            "UPDATE scientific_tasks SET status='completed', "
            "result_json=COALESCE(result_json, '{}'), error=NULL, "
            "lease_owner=NULL, lease_expires_at=NULL, completed_at=?, "
            "updated_at=? WHERE task_type='engine.finalize' "
            "AND status='leased' "
            "AND EXISTS (SELECT 1 FROM runs WHERE "
            "runs.id=scientific_tasks.run_id AND runs.status=?) "
            "AND EXISTS (SELECT 1 FROM reports WHERE "
            "reports.run_id=scientific_tasks.run_id)",
            (now, now, RunStatus.COMPLETED.value),
        ).rowcount
        if recovered:
            logger.info(
                "Reconciled %d finalize task(s) whose reports were already "
                "published before restart.",
                recovered,
            )
        rows = conn.execute(
            "SELECT id FROM runs WHERE status IN (?,?,?)",
            _ACTIVE_RUN_STATUSES,
        ).fetchall()
        for row in rows:
            rid = row["id"]
            outcome = _reconcile_one_run(conn, rid, now, reason)
            (resumable if outcome == "resumable" else failed).append(rid)
    return {"failed": failed, "resumable": resumable}


# Number of top hypotheses surfaced per run on list endpoints.
_TOP_HYPOTHESES_CAP = 3

# Event types that mark a pipeline stage, used to report a run's
# ``latest_stage`` for the live progress indicator. Cross-cutting events
# (safety.*, citation.*, status, lifecycle, report) are excluded so the
# reported stage tracks the linear agent pipeline. The durable engine path
# never appends one of these -- its live signal is the leased task on
# ``execution_progress.active_task`` instead. The curated demo-seed path
# (``seed/scenario.py``) is what actually emits this vocabulary, appending
# the whole set at once when a run is seeded rather than progressively.
_STAGE_EVENT_TYPES: tuple[str, ...] = (
    "supervisor.plan",
    "literature_review",
    "generate",
    "reflection",
    "proximity",
    "ranking",
    "evolve",
    "meta_review",
    "deep_verification",
    "research_overview",
)

# Run-scoped tables whose rows are all deterministically reconstructed by the
# final drain, so both the full and publication-only resets delete them
# wholesale. knowledge_facts is derived from claim_evidence at report
# finalize (audit G14) rather than by the drain itself, but the shape is the
# same: without it here, a reset that clears claim_evidence but never
# reaches a fresh finalize would leave knowledge_facts pointing at claims
# that no longer exist. supervisor_plan/supervisor_allocations (audit E19)
# are reconstructed from the final checkpoint state the same way run_metrics
# is, so a re-finalized resumed run replaces rather than accumulates them.
_REPLAYABLE_ARTIFACT_TABLES: tuple[str, ...] = (
    "matches",
    "citations",
    "claim_evidence",
    "proximity_edges",
    "run_metrics",
    "knowledge_facts",
    "supervisor_plan",
    "supervisor_allocations",
)


def _top_hypotheses_by_run(
    conn: sqlite3.Connection, run_ids: list[str]
) -> dict[str, list[str]]:
    """Return each run's top hypothesis titles by Elo, capped per run.

    Uses one windowed query over the given run ids rather than a per-run
    fetch, matching ``list_hypotheses``' ``elo DESC, created_at ASC`` ordering
    (with the row id as a final deterministic tiebreak).

    Args:
        conn: Open database connection.
        run_ids: Run ids to fetch top hypotheses for.

    Returns:
        Mapping of run id to its ordered list of top hypothesis titles. Runs
        with no hypotheses are absent from the mapping.
    """
    if not run_ids:
        return {}
    placeholders = ",".join("?" for _ in run_ids)
    rows = conn.execute(
        "SELECT run_id, title FROM ("
        " SELECT h.run_id AS run_id, h.title AS title, ROW_NUMBER() OVER ("
        "  PARTITION BY h.run_id"
        "  ORDER BY s.elo_rating DESC, h.created_at ASC, h.id"
        " ) AS rn"
        " FROM hypotheses h"
        " JOIN hypothesis_state s ON s.hypothesis_id = h.id"
        f" WHERE h.run_id IN ({placeholders})"
        ") WHERE rn <= ? ORDER BY run_id, rn",
        (*run_ids, _TOP_HYPOTHESES_CAP),
    ).fetchall()
    by_run: dict[str, list[str]] = {}
    for row in rows:
        by_run.setdefault(row["run_id"], []).append(row["title"])
    return by_run


def _latest_stage_by_run(
    conn: sqlite3.Connection, run_ids: list[str]
) -> dict[str, str]:
    """Return each run's most recent pipeline-stage event type.

    Args:
        conn: Open database connection.
        run_ids: Run ids to fetch the latest stage for.

    Returns:
        Mapping of run id to its latest ``_STAGE_EVENT_TYPES`` event type. Runs
        with no such event are absent from the mapping.
    """
    if not run_ids:
        return {}
    run_placeholders = ",".join("?" for _ in run_ids)
    stage_placeholders = ",".join("?" for _ in _STAGE_EVENT_TYPES)
    rows = conn.execute(
        "SELECT run_id, type FROM ("
        " SELECT run_id, type, ROW_NUMBER() OVER ("
        "  PARTITION BY run_id ORDER BY seq DESC"
        " ) AS rn"
        " FROM run_events"
        f" WHERE run_id IN ({run_placeholders})"
        f" AND type IN ({stage_placeholders})"
        ") WHERE rn = 1",
        (*run_ids, *_STAGE_EVENT_TYPES),
    ).fetchall()
    return {row["run_id"]: row["type"] for row in rows}


def list_expired_terminal_runs(
    cutoff: float, db_path: str | None = None
) -> list[RunRow]:
    """Return every terminal run last settled before ``cutoff``.

    Used by the retention sweep (``app.retention``), not by any live
    endpoint: a run in a non-terminal status is never returned, regardless
    of age, since it still has an active or resumable workflow.

    Args:
        cutoff: Unix timestamp; a run's ``completed_at`` (falling back to
            ``updated_at`` for legacy rows with no completion timestamp)
            must be older than this to be returned.
        db_path: Optional override for the SQLite database path.

    Returns:
        Matching run rows, oldest settled first.
    """
    placeholders = ",".join("?" for _ in TERMINAL_STATUSES)
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM runs WHERE status IN "
            f"({placeholders}) AND COALESCE(completed_at, updated_at) < ? "
            "ORDER BY COALESCE(completed_at, updated_at) ASC",
            (*(status.value for status in TERMINAL_STATUSES), cutoff),
        ).fetchall()
    return [_row_to_run(row) for row in rows]


def list_runs(
    client_id: str = "", limit: int = 100, db_path: str | None = None
) -> list[RunRow]:
    """Return a client's runs, newest first, each enriched for list surfaces.

    Alongside the run rows, each is populated with its top hypothesis Elo
    (``top_elo``), its top hypothesis titles (``top_hypotheses``), and the type
    of its most recent pipeline-stage event (``latest_stage``), so home/list
    surfaces render real data without fetching each run's hypotheses or events.
    """
    with connect(db_path) as conn:
        # One grouped aggregate joined in, rather than a correlated subquery
        # re-run per run row.
        # The subquery computes each run's best hypothesis Elo (MAX over the
        # joined mutable state); the LEFT JOIN keeps runs with no hypotheses
        # (top_elo comes back NULL for those).
        rows = conn.execute(
            "SELECT r.*, t.top_elo FROM runs r "
            "LEFT JOIN ("
            " SELECT h.run_id, MAX(s.elo_rating) AS top_elo "
            " FROM hypotheses h "
            " JOIN hypothesis_state s ON s.hypothesis_id = h.id "
            " GROUP BY h.run_id) t ON t.run_id = r.id "
            "WHERE r.client_id = ? "
            "ORDER BY r.created_at DESC LIMIT ?",
            (client_id, limit),
        ).fetchall()
        runs = [_row_to_run(r) for r in rows]
        run_ids = [run.id for run in runs]
        # Two windowed lookups over just the listed ids, rather than per-run.
        top_hypotheses = _top_hypotheses_by_run(conn, run_ids)
        latest_stage = _latest_stage_by_run(conn, run_ids)
    for run in runs:
        # Absent from the map means no hypotheses yet -> an explicit empty list
        # so clients can distinguish "none" from the None single-read default.
        run.top_hypotheses = top_hypotheses.get(run.id, [])
        run.latest_stage = latest_stage.get(run.id)
    return runs


# Human-contributed rows survive clear_run_derived_data: the deterministic
# replay only re-derives *agent* artifacts, so deleting these would silently
# discard the scientist's input on every resume. The store is the bottom
# layer, so the values are pinned here rather than imported from the modules
# that own them; test_resume asserts they stay in sync with
# human_input.SCIENTIST_MANUAL_ORIGIN, runs.add_human_review's reviewer, and
# run_corpus.ATTACHMENT_SOURCE.
_HUMAN_HYPOTHESIS_ORIGIN = "scientist_manual"
_HUMAN_REVIEWER = "scientist"
_HUMAN_EVIDENCE_SOURCE = "attachment"


def _delete_agent_derived_rows(conn: sqlite3.Connection, run_id: str) -> None:
    """Delete a run's agent-authored hypotheses/reviews/evidence rows.

    Scientist contributions (manual hypotheses, human reviews, attachments)
    are preserved. ``hypothesis_state`` is keyed by hypothesis_id (no run_id),
    so it is cleared via the run's hypotheses before those rows are removed.
    """
    conn.execute(
        "DELETE FROM hypothesis_state WHERE hypothesis_id IN "
        "(SELECT id FROM hypotheses WHERE run_id=? AND "
        "created_by_agent != ?)",
        (run_id, _HUMAN_HYPOTHESIS_ORIGIN),
    )
    conn.execute(
        "DELETE FROM hypotheses WHERE run_id=? AND created_by_agent != ?",
        (run_id, _HUMAN_HYPOTHESIS_ORIGIN),
    )
    conn.execute(
        "DELETE FROM reviews WHERE run_id=? AND reviewer_agent != ?",
        (run_id, _HUMAN_REVIEWER),
    )
    conn.execute(
        "DELETE FROM evidence WHERE run_id=? AND source != ?",
        (run_id, _HUMAN_EVIDENCE_SOURCE),
    )
    _reset_retained_hypothesis_state(conn, run_id)


def _reset_retained_hypothesis_state(
    conn: sqlite3.Connection, run_id: str
) -> None:
    """Zero the tournament counters on the hypothesis rows that survive.

    An agent hypothesis is deleted and re-inserted by the next drain, so its
    counters start from zero on their own. A scientist hypothesis is kept,
    and the drain adds the run's win/loss counts as *deltas* (relative
    updates, so concurrent match writers cannot clobber each other) -- which
    on a replayed finalize would add the same tournament twice. Resetting
    here, at the point the replay is being prepared, keeps the retained row
    on exactly the same footing as the re-inserted ones. safety_status and
    Elo are left alone: the drain writes Elo absolutely, and the screen
    re-runs over every persisted row.
    """
    conn.execute(
        "UPDATE hypothesis_state SET win_count=0, loss_count=0 "
        "WHERE hypothesis_id IN (SELECT id FROM hypotheses WHERE run_id=?)",
        (run_id,),
    )


def clear_run_derived_data(
    run_id: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Delete a run's derived pipeline data for a clean deterministic resume.

    Removes generated run events, report, safety decisions, evidence,
    matches, reviews, citations, claim-evidence, execution metrics, and
    hypotheses (plus the per-hypothesis state rows). Status and lifecycle
    events remain as the admission audit and monotonic resume revision. The
    run row itself, its
    checkpoints, its messages
    (steering/Q&A history), and the scientist's contributions (manual
    hypotheses, human reviews, attachments) are kept, so a resumed run
    reconstructs identical agent artifacts from the same seed without
    duplicating rows or events and without discarding human input. One
    exception: a human review of a deleted *agent* hypothesis is removed with
    it -- ``foreign_keys`` is now enforced on every store connection, so a
    review row cannot outlive the hypothesis it references (its FK is
    ``ON DELETE CASCADE``).

    Every child table is still deleted explicitly even though the enforced
    cascades would remove most of these rows on their own: the explicit
    deletes are redundant-but-harmless, cover rows a cascade would miss
    (e.g. reviews of *surviving* scientist hypotheses written by agents),
    and document exactly which derived rows a resume reconstructs.

    Args:
        run_id: Identifier of the run whose derived data to clear.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).
    """
    # Tables keyed by run_id whose rows are all derived, deleted wholesale.
    run_scoped = (
        "run_events",
        "reports",
        "safety_decisions",
        *_REPLAYABLE_ARTIFACT_TABLES,
    )
    with _use_conn(conn, db_path) as conn:
        _delete_agent_derived_rows(conn, run_id)
        for table in run_scoped:
            if table == "run_events":
                # Keep scientist and lifecycle audit rows with their original
                # sequences; status/lifecycle seqs reject stale resume admits.
                # Generated timeline entries, including logs, are cleared.
                conn.execute(
                    "DELETE FROM run_events WHERE run_id=? "
                    "AND type NOT IN "
                    "('scientist.outcome', 'status', 'lifecycle')",
                    (run_id,),
                )
            else:
                conn.execute(f"DELETE FROM {table} WHERE run_id=?", (run_id,))


def clear_publication_artifacts(
    run_id: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Clear replayable final-drain rows while retaining task/event history.

    This narrower reset is used by the idempotent finalizer. It preserves
    checkpoints, scientific tasks, lifecycle events, intake/final safety audit,
    messages, reports, and scientist contributions while removing rows that
    `persist_final_state` deterministically reconstructs.
    """
    with _use_conn(conn, db_path) as active:
        _delete_agent_derived_rows(active, run_id)
        for table in _REPLAYABLE_ARTIFACT_TABLES:
            active.execute(f"DELETE FROM {table} WHERE run_id=?", (run_id,))
        active.execute(
            "DELETE FROM safety_decisions WHERE run_id=? "
            "AND stage='hypothesis'",
            (run_id,),
        )
