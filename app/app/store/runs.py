"""Run CRUD and lifecycle helpers for the runs table.

Covers creating runs, reading and listing them, status transitions
(including terminal-state timestamps), startup reconciliation of runs
interrupted by a restart, and the per-run summary counts.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from typing import Any

from app.store.db import _now, _use_conn, connect
from app.store.events import _append_event
from app.store.models import (
    TERMINAL_STATUSES,
    RunRow,
    RunStatus,
    _row_to_run,
)

logger = logging.getLogger(__name__)


def create_run(
    research_goal: str,
    profile: str,
    provider: str,
    config: dict[str, Any],
    client_id: str = "",
    db_path: str | None = None,
) -> RunRow:
    """Insert a new run row in the DRAFT state and return it.

    Args:
        research_goal: The natural-language research goal for the run.
        profile: Canonical run mode. The column name is retained for
            compatibility with older clients.
        provider: The execution provider, e.g. 'mock' or 'engine'.
        config: Run configuration values serialized to JSON.
        client_id: Owning client identifier used for run isolation.
        db_path: Optional override for the SQLite database path.

    Returns:
        The newly created run as a RunRow.
    """
    run_id = str(uuid.uuid4())
    now = _now()
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO runs (id, research_goal, profile, status, "
            "provider, config_json, client_id, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                research_goal,
                profile,
                RunStatus.DRAFT.value,
                provider,
                json.dumps(config),
                client_id,
                now,
                now,
            ),
        )
    logger.info(
        "created run %s run_mode=%s provider=%s client_id=%s",
        run_id,
        profile,
        provider,
        client_id,
    )
    return RunRow(
        id=run_id,
        research_goal=research_goal,
        profile=profile,
        status=RunStatus.DRAFT.value,
        provider=provider,
        config=config,
        client_id=client_id,
        created_at=now,
        updated_at=now,
        completed_at=None,
        error=None,
    )


def get_run(
    run_id: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> RunRow | None:
    """Return a single run by id, or None when no such run exists."""
    with _use_conn(conn, db_path) as conn:
        row = conn.execute(
            "SELECT * FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        return _row_to_run(row) if row else None


def run_exists(run_id: str, db_path: str | None = None) -> bool:
    """Return whether a run exists, without materializing the row.

    Cheaper than ``get_run`` for endpoints that only need a 404 guard: it skips
    the ``SELECT *`` and the ``config_json`` decode that ``_row_to_run`` does.

    Args:
        run_id: Identifier of the run to probe.
        db_path: Optional override for the SQLite database path.

    Returns:
        True if a run row with this id exists.
    """
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        return row is not None


def list_runs(
    client_id: str = "", limit: int = 100, db_path: str | None = None
) -> list[RunRow]:
    """Return a client's runs, newest first, each with its top Elo."""
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
        return [_row_to_run(r) for r in rows]


def update_run_status(
    run_id: str,
    status: RunStatus,
    error: str | None = None,
    db_path: str | None = None,
) -> None:
    """Update a run's status, timestamps, and optional error message.

    Args:
        run_id: Identifier of the run to update.
        status: The new lifecycle status to persist.
        error: Optional error message to store when the run failed.
        db_path: Optional override for the SQLite database path.
    """
    now = _now()
    completed_at = now if status in TERMINAL_STATUSES else None
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE runs SET status=?, error=?, updated_at=?, "
            "completed_at=? WHERE id=?",
            (status.value, error, now, completed_at, run_id),
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


def reconcile_interrupted_runs(db_path: str | None = None) -> list[str]:
    """Fail runs left non-terminal by a previous process (crash/restart).

    On startup no workflow tasks are running, so any run still marked queued,
    running, or synthesizing was interrupted and would otherwise be stuck
    forever -- and un-startable, since ``start_run`` rejects in-progress runs.
    Transition each to ``failed`` with a clear reason and append a status event
    so the event stream and UI reflect the interruption.

    Args:
        db_path: Optional override for the SQLite database path.

    Returns:
        The ids of the runs that were reconciled.
    """
    interrupted = (
        RunStatus.QUEUED.value,
        RunStatus.RUNNING.value,
        RunStatus.SYNTHESIZING.value,
    )
    now = _now()
    reason = "Run interrupted by a server restart."
    reconciled: list[str] = []
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id FROM runs WHERE status IN (?,?,?)",
            interrupted,
        ).fetchall()
        for row in rows:
            rid = row["id"]
            _fail_interrupted_run(conn, rid, now, reason)
            reconciled.append(rid)
    return reconciled


def summary_counts(
    run_id: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, int]:
    """Return per-table row counts for a run in a single connection.

    Uses COUNT(*) per table rather than materializing and parsing whole tables.

    Args:
        run_id: Identifier of the run to summarize.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).

    Returns:
        Mapping of summary field name to row count.
    """
    tables = {
        "events": "run_events",
        "hypotheses": "hypotheses",
        "evidence": "evidence",
        "matches": "matches",
        "reviews": "reviews",
    }
    with _use_conn(conn, db_path) as conn:
        return {
            field: conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE run_id=?",
                (run_id,),
            ).fetchone()[0]
            for field, table in tables.items()
        }
