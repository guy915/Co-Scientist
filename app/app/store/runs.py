from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any

from co_scientist.platform.db import connect, current_time, transaction, use_conn
from co_scientist.platform.db.models import (
    DEMO_CLIENT_ID,
    TERMINAL_STATUSES,
    RunRow,
    RunStatus,
    row_to_run,
)

from app.store.logs import count_logs_for_run, delete_logs_for_run
from app.store.runs_views import _ACTIVE_RUN_STATUSES

logger = logging.getLogger(__name__)


def _bootstrap_lease_matches(row: sqlite3.Row, worker_id: str | None, attempt: int) -> bool:
    return all(
        (
            row["task_status"] == "leased",
            row["lease_owner"] == worker_id,
            row["attempt"] == attempt,
            row["task_type"] == "engine.bootstrap",
            row["lease_expires_at"] is not None,
            float(row["lease_expires_at"] or 0) > current_time(),
        )
    )


def bootstrap_task_lease_matches(
    conn: sqlite3.Connection,
    run_id: str,
    task_id: str,
    worker_id: str | None,
    attempt: int,
) -> bool:
    row = conn.execute(
        "SELECT status AS task_status, lease_owner, attempt, task_type, "
        "lease_expires_at FROM scientific_tasks WHERE id=? AND run_id=?",
        (task_id, run_id),
    ).fetchone()
    return row is not None and _bootstrap_lease_matches(row, worker_id, attempt)


def _allowed_terminal_bootstrap_status(
    status: str,
    row: sqlite3.Row,
    worker_id: str | None,
    attempt: int,
) -> str | None:
    if status == RunStatus.PAUSED.value and not _bootstrap_lease_matches(row, worker_id, attempt):
        return None
    terminal_or_paused = {
        RunStatus.COMPLETED.value,
        RunStatus.CANCELLED.value,
        RunStatus.FAILED.value,
        RunStatus.BLOCKED.value,
        RunStatus.PAUSED.value,
    }
    return status if status in terminal_or_paused else None


def _advance_bootstrap_status(conn: sqlite3.Connection, run_id: str, status: str) -> bool:
    if status not in {
        RunStatus.RUNNING.value,
        RunStatus.DRAFT.value,
        RunStatus.QUEUED.value,
    }:
        return False
    if status != RunStatus.RUNNING.value:
        now = current_time()
        conn.execute(
            "UPDATE runs SET status=?, error=NULL, updated_at=?, "
            "completed_at=NULL WHERE id=? AND status=?",
            (RunStatus.RUNNING.value, now, run_id, status),
        )
    return True


def mark_bootstrap_running(
    run_id: str,
    task_id: str,
    worker_id: str | None,
    attempt: int,
    db_path: str | None = None,
) -> str | None:
    with transaction(db_path) as conn:
        row = conn.execute(
            "SELECT runs.status AS run_status, task.status AS task_status, "
            "task.lease_owner, task.attempt, task.task_type, "
            "task.lease_expires_at "
            "FROM runs LEFT JOIN scientific_tasks AS task "
            "ON task.id=? AND task.run_id=runs.id WHERE runs.id=?",
            (task_id, run_id),
        ).fetchone()
        if row is None:
            return None
        status = str(row["run_status"])
        terminal_status = _allowed_terminal_bootstrap_status(status, row, worker_id, attempt)
        if terminal_status is not None:
            return terminal_status
        if not _bootstrap_lease_matches(row, worker_id, attempt):
            return None
        if not _advance_bootstrap_status(conn, run_id, status):
            return None
    return RunStatus.RUNNING.value


# Cascade row accounting spans direct run children and FK descendants so
# deletion can be verified.
_RUN_ID_TABLES: tuple[str, ...] = (
    "run_credentials",
    "run_events",
    "scientific_tasks",
    "hypotheses",
    "evidence",
    "citations",
    "reviews",
    "matches",
    "safety_decisions",
    "reports",
    "messages",
    "checkpoints",
    "run_metrics",
    "claim_evidence",
    "knowledge_facts",
    "proximity_edges",
)

# Hypothesis state has no run_id; account for its transitive cascade through the
# hypothesis join.
_HYPOTHESIS_SCOPED_TABLES: tuple[str, ...] = ("hypothesis_state",)


def count_run_rows(run_id: str, *, db_path: str | None = None) -> dict[str, int]:
    with connect(db_path) as conn:
        counts = {
            "runs": conn.execute("SELECT COUNT(*) FROM runs WHERE id=?", (run_id,)).fetchone()[0]
        }
        for table in _RUN_ID_TABLES:
            counts[table] = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE run_id=?", (run_id,)
            ).fetchone()[0]
        for table in _HYPOTHESIS_SCOPED_TABLES:
            counts[table] = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE hypothesis_id IN "
                "(SELECT id FROM hypotheses WHERE run_id=?)",
                (run_id,),
            ).fetchone()[0]
        counts["staged_documents"] = conn.execute(
            "SELECT COUNT(*) FROM staged_documents WHERE run_id=?", (run_id,)
        ).fetchone()[0]
        counts["app_logs"] = count_logs_for_run(run_id, conn=conn)
    return counts


def delete_run(run_id: str) -> dict[str, int]:
    before = count_run_rows(run_id)
    with connect() as conn:
        conn.execute(
            "UPDATE staged_documents SET run_id=NULL WHERE run_id=?",
            (run_id,),
        )
        delete_logs_for_run(run_id, conn=conn)
        conn.execute("DELETE FROM runs WHERE id=?", (run_id,))
    return before


def run_used_offline(run: RunRow) -> bool:
    """Historical backend comes from the run row, not current process
    configuration.
    """
    return run.llm_backend == "offline"


def run_offline_backed(run_id: str, *, db_path: str | None = None) -> bool:
    run = get_run(run_id, db_path=db_path)
    return run is not None and run_used_offline(run)


def set_run_llm_backend(run_id: str, llm_backend: str, db_path: str | None = None) -> None:
    """Persist resolved overrides before execution because later publication
    and badging readers reload the run row.
    """
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE runs SET llm_backend = ? WHERE id = ?",
            (llm_backend, run_id),
        )


def redact_run_goal(
    run_id: str,
    goal: str,
    title: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Redact title and clear restatement with the goal: both are derived
    text that could otherwise disclose the same sensitive span.
    """
    with use_conn(conn, db_path) as active:
        active.execute(
            "UPDATE runs SET research_goal = ?, title = ?, goal_restatement = NULL WHERE id = ?",
            (goal, title, run_id),
        )


def set_run_config(run_id: str, config: dict[str, Any], db_path: str | None = None) -> None:
    """Older demo rows need revised setup fields too; startup reconstruction
    must match newly created fixtures.
    """
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE runs SET config_json=?, updated_at=? WHERE id=?",
            (json.dumps(config), current_time(), run_id),
        )


def get_run(
    run_id: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> RunRow | None:
    with use_conn(conn, db_path) as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return row_to_run(row) if row else None


def run_exists(run_id: str) -> bool:
    with connect() as conn:
        row = conn.execute("SELECT 1 FROM runs WHERE id = ?", (run_id,)).fetchone()
        return row is not None


def update_run_status(
    run_id: str,
    status: RunStatus,
    error: str | None = None,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    now = current_time()
    completed_at = now if status in TERMINAL_STATUSES else None
    with use_conn(conn, db_path) as active:
        active.execute(
            "UPDATE runs SET status=?, error=?, updated_at=?, completed_at=? WHERE id=?",
            (status.value, error, now, completed_at, run_id),
        )


def update_run_status_if_current(
    conn: sqlite3.Connection,
    run_id: str,
    status: RunStatus,
    expected_statuses: tuple[RunStatus, ...],
    error: str | None = None,
) -> bool:
    if not expected_statuses:
        return False
    now = current_time()
    completed_at = now if status in TERMINAL_STATUSES else None
    placeholders = ",".join("?" for _ in expected_statuses)
    changed = conn.execute(
        "UPDATE runs SET status=?, error=?, updated_at=?, completed_at=? "
        f"WHERE id=? AND status IN ({placeholders})",
        (
            status.value,
            error,
            now,
            completed_at,
            run_id,
            *(item.value for item in expected_statuses),
        ),
    ).rowcount
    return bool(changed)


def set_run_timing(run_id: str, duration_seconds: float) -> None:
    """Reconstructed demos must not report the interval between releases as
    scientific compute time.
    """
    completed_at = current_time()
    created_at = completed_at - max(duration_seconds, 1.0)
    with connect() as conn:
        conn.execute(
            "UPDATE runs SET created_at=?, updated_at=?, completed_at=? WHERE id=?",
            (created_at, completed_at, completed_at, run_id),
        )


def summary_counts(run_id: str, conn: sqlite3.Connection | None = None) -> dict[str, int]:
    tables = {
        "events": "run_events",
        "hypotheses": "hypotheses",
        "evidence": "evidence",
        "matches": "matches",
        "reviews": "reviews",
    }
    with use_conn(conn, None) as conn:
        return {
            field: conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE run_id=?",
                (run_id,),
            ).fetchone()[0]
            for field, table in tables.items()
        }


def set_run_title(run_id: str, title: str, db_path: str | None = None) -> None:
    with connect(db_path) as conn:
        conn.execute("UPDATE runs SET title = ? WHERE id = ?", (title, run_id))


def set_run_goal_restatement(run_id: str, restatement: str, db_path: str | None = None) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE runs SET goal_restatement = ? WHERE id = ?",
            (restatement, run_id),
        )


@dataclass(frozen=True)
class RunCreateOptions:
    client_id: str = ""
    title: str | None = None
    llm_backend: str | None = None
    db_path: str | None = None
    conn: sqlite3.Connection | None = None
    log_created: bool | None = None


def log_run_created(run: RunRow) -> None:
    logger.info(
        "created run %s run_mode=%s provider=%s llm_backend=%s client_id=%s",
        run.id,
        run.profile,
        run.provider,
        run.llm_backend,
        run.client_id,
    )


def create_run(
    research_goal: str,
    profile: str,
    provider: str,
    config: dict[str, Any],
    options: RunCreateOptions | None = None,
) -> RunRow:
    """Caller-owned transactions defer logging until commit so rolled-back
    creation cannot appear in the log.
    """
    opts = options or RunCreateOptions()
    if opts.client_id == DEMO_CLIENT_ID:
        raise ValueError("the demo identity is reserved for seeded examples")
    now = current_time()
    backend = opts.llm_backend or "real"
    run = RunRow(
        id=str(uuid.uuid4()),
        research_goal=research_goal,
        title=opts.title,
        profile=profile,
        status=RunStatus.DRAFT.value,
        provider=provider,
        config=config,
        client_id=opts.client_id,
        created_at=now,
        updated_at=now,
        completed_at=None,
        error=None,
        llm_backend=backend,
    )
    with use_conn(opts.conn, opts.db_path) as active:
        active.execute(
            "INSERT INTO runs (id, research_goal, title, profile, status, "
            "provider, config_json, client_id, created_at, updated_at, "
            "llm_backend) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                run.id,
                run.research_goal,
                run.title,
                run.profile,
                run.status,
                run.provider,
                json.dumps(run.config),
                run.client_id,
                now,
                now,
                run.llm_backend,
            ),
        )
    should_log = opts.conn is None if opts.log_created is None else opts.log_created
    if should_log:
        log_run_created(run)
    return run


def _count_other_active_runs(conn: sqlite3.Connection, run_id: str, client_id: str) -> int:
    """The concurrency allowance spans every tier for one identity; counting
    per tier would multiply the advertised limit.
    """
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM runs WHERE client_id=? AND status IN (?,?,?) AND id!=?",
            (client_id, *_ACTIVE_RUN_STATUSES, run_id),
        ).fetchone()[0]
    )


def _queue_run_if_startable(
    conn: sqlite3.Connection, run_id: str, now: float, expected_status: str
) -> int:
    if expected_status not in {
        RunStatus.DRAFT.value,
        RunStatus.FAILED.value,
        RunStatus.BLOCKED.value,
        RunStatus.CANCELLED.value,
    }:
        return 0
    return conn.execute(
        "UPDATE runs SET status=?, updated_at=?, completed_at=NULL, "
        "error=NULL WHERE id=? AND status=?",
        (
            RunStatus.QUEUED.value,
            now,
            run_id,
            expected_status,
        ),
    ).rowcount


def reserve_run_capacity_in_transaction(
    conn: sqlite3.Connection,
    run_id: str,
    client_id: str,
    limit: int,
    expected_status: str,
) -> bool:
    count = _count_other_active_runs(conn, run_id, client_id)
    if count >= limit:
        return False
    changed = _queue_run_if_startable(conn, run_id, current_time(), expected_status)
    return bool(changed)
