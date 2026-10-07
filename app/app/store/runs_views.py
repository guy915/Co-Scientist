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
    conn.execute(
        "UPDATE runs SET status=?, error=?, updated_at=?, completed_at=? WHERE id=?",
        (RunStatus.FAILED.value, reason, now, now, run_id),
    )
    _append_event(conn, run_id, "status", {"status": "failed", "error": reason}, now)


def _settle_run_out_of_work(
    conn: sqlite3.Connection,
    run_id: str,
    error: str,
    now: float,
    failure_kind: str | None = None,
) -> bool:
    """Guard settlement and append its terminal event in the failing task's
    transaction; sibling work may still produce successors.
    """
    row = conn.execute(
        "SELECT 1 FROM scientific_tasks WHERE run_id=? AND status IN ('queued','leased') LIMIT 1",
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
    """Run settlement shares the terminal task-failure transaction,
    preventing active runs with no recoverable work.
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
        logger.info("Run %s failed: no claimable work remains (%s)", run_id, reason)


def _reconcile_one_run(conn: sqlite3.Connection, run_id: str, now: float, reason: str) -> str:
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


def _fail_ambiguous_expired_provider_leases(db_path: str | None, now: float) -> None:
    from app.store.tasks import _fail_ambiguous_expired_leases

    with transaction(db_path) as conn:
        _fail_ambiguous_expired_leases(conn, now)


def reconcile_interrupted_runs(
    db_path: str | None = None,
) -> dict[str, list[str]]:
    """Startup has no live previous-process workers; checkpoints make
    interrupted runs resumable rather than permanently failed.
    """
    now = _now()
    reason = "Run interrupted by a server restart."
    failed: list[str] = []
    resumable: list[str] = []
    _fail_ambiguous_expired_provider_leases(db_path, now)
    with connect(db_path) as conn:
        # A process can die after report commit but before task success; startup
        # settles only that published finalizer boundary.
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


_TOP_HYPOTHESES_CAP = 3

# Curated seeds emit these stages; durable live progress instead comes from
# leased tasks, and cross-cutting events are excluded.
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

# Reset derived facts with their claim edges or stale facts survive a failed
# replay; allocations and metrics are rebuilt too.
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


def _top_hypotheses_by_run(conn: sqlite3.Connection, run_ids: list[str]) -> dict[str, list[str]]:
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


def _latest_stage_by_run(conn: sqlite3.Connection, run_ids: list[str]) -> dict[str, str]:
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


def list_expired_terminal_runs(cutoff: float) -> list[RunRow]:
    placeholders = ",".join("?" for _ in TERMINAL_STATUSES)
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM runs WHERE status IN "
            f"({placeholders}) AND COALESCE(completed_at, updated_at) < ? "
            "ORDER BY COALESCE(completed_at, updated_at) ASC",
            (*(status.value for status in TERMINAL_STATUSES), cutoff),
        ).fetchall()
    return [_row_to_run(row) for row in rows]


def list_runs(client_id: str = "", limit: int = 100, db_path: str | None = None) -> list[RunRow]:
    with connect(db_path) as conn:
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
        top_hypotheses = _top_hypotheses_by_run(conn, run_ids)
        latest_stage = _latest_stage_by_run(conn, run_ids)
    for run in runs:
        # Listed runs without hypotheses use []; single reads retain the
        # unenriched None default.
        run.top_hypotheses = top_hypotheses.get(run.id, [])
        run.latest_stage = latest_stage.get(run.id)
    return runs


# Replay preserves scientist hypotheses, reviews and attachments; leaf-store
# sentinel values must match their producer modules.
_HUMAN_HYPOTHESIS_ORIGIN = "scientist_manual"
_HUMAN_REVIEWER = "scientist"
_HUMAN_EVIDENCE_SOURCE = "attachment"


def _delete_agent_derived_rows(conn: sqlite3.Connection, run_id: str) -> None:
    """Scientist contributions survive replay; delete hypothesis state
    before the agent hypotheses it references.
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


def _reset_retained_hypothesis_state(conn: sqlite3.Connection, run_id: str) -> None:
    """Drain counters are deltas, so replay must clear retained scientist
    counters to avoid counting the same tournament twice.
    """
    conn.execute(
        "UPDATE hypothesis_state SET win_count=0, loss_count=0 "
        "WHERE hypothesis_id IN (SELECT id FROM hypotheses WHERE run_id=?)",
        (run_id,),
    )


def clear_run_derived_data(run_id: str, conn: sqlite3.Connection | None = None) -> None:
    """Replay retains scientist input and lifecycle revisions; reviews of
    removed agent hypotheses still cascade with their parent.
    """
    run_scoped = (
        "run_events",
        "reports",
        "safety_decisions",
        *_REPLAYABLE_ARTIFACT_TABLES,
    )
    with _use_conn(conn, None) as conn:
        _delete_agent_derived_rows(conn, run_id)
        for table in run_scoped:
            if table == "run_events":
                # Keep scientist and lifecycle audit sequences: status/lifecycle
                # high-water marks reject stale resume admission.
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
    """Finalizer replay retains tasks, checkpoints, lifecycle/safety audit,
    reports and scientist input while rebuilding only derived rows.
    """
    with _use_conn(conn, db_path) as active:
        _delete_agent_derived_rows(active, run_id)
        for table in _REPLAYABLE_ARTIFACT_TABLES:
            active.execute(f"DELETE FROM {table} WHERE run_id=?", (run_id,))
        active.execute(
            "DELETE FROM safety_decisions WHERE run_id=? AND stage='hypothesis'",
            (run_id,),
        )
