"""Run CRUD and lifecycle helpers for the runs table.

Covers creating runs, reading them, status transitions (including
terminal-state timestamps), startup reconciliation of runs interrupted by a
restart, and the per-run summary counts. The enriched list rollups and the
derived-data resets live in ``app.store.runs_views`` and are re-exported
here so the module namespace is unchanged.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from typing import Any

from app.store.checkpoints import has_checkpoint
from app.store.db import _now, _use_conn, connect, transaction
from app.store.events import _append_event
from app.store.models import (
    TERMINAL_STATUSES,
    RunRow,
    RunStatus,
    _row_to_run,
)
from app.store.runs_views import (
    clear_publication_artifacts as clear_publication_artifacts,
)
from app.store.runs_views import (
    clear_run_derived_data as clear_run_derived_data,
)
from app.store.runs_views import list_runs as list_runs

logger = logging.getLogger(__name__)

# Statuses that mark a run as occupying a concurrency slot / still in flight.
_ACTIVE_RUN_STATUSES: tuple[str, str, str] = (
    RunStatus.QUEUED.value,
    RunStatus.RUNNING.value,
    RunStatus.SYNTHESIZING.value,
)


def create_run(
    research_goal: str,
    profile: str,
    provider: str,
    config: dict[str, Any],
    client_id: str = "",
    title: str | None = None,
    llm_backend: str | None = None,
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
        title: Optional short session heading. Usually NULL at creation and
            filled in shortly after by a background title generator; may be
            supplied directly (e.g. curated demo runs).
        llm_backend: The LLM backend the run will execute against, "offline"
            or "real". When omitted it is derived from the provider (the mock
            was always offline-backed), matching the legacy-row default.
        db_path: Optional override for the SQLite database path.

    Returns:
        The newly created run as a RunRow.
    """
    run_id = str(uuid.uuid4())
    now = _now()
    backend = (
        llm_backend
        if llm_backend is not None
        else ("offline" if provider == "mock" else "real")
    )
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO runs (id, research_goal, title, profile, status, "
            "provider, config_json, client_id, created_at, updated_at, "
            "llm_backend) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                research_goal,
                title,
                profile,
                RunStatus.DRAFT.value,
                provider,
                json.dumps(config),
                client_id,
                now,
                now,
                backend,
            ),
        )
    logger.info(
        "created run %s run_mode=%s provider=%s llm_backend=%s client_id=%s",
        run_id,
        profile,
        provider,
        backend,
        client_id,
    )
    return RunRow(
        id=run_id,
        research_goal=research_goal,
        title=title,
        profile=profile,
        status=RunStatus.DRAFT.value,
        provider=provider,
        config=config,
        client_id=client_id,
        created_at=now,
        updated_at=now,
        completed_at=None,
        error=None,
        llm_backend=backend,
    )


def run_used_offline(run: RunRow) -> bool:
    """Return whether a run executed against the offline LLM backend.

    Reads the persisted ``llm_backend`` column. This is the per-run signal to
    key any decision about a *past* run's nature on, distinct from the
    process-level ``engine_adapter.offline_mode()`` request-time predicate.
    Rows created before the column existed fall back to the provider: the
    mock provider was always offline-backed, the real engine always real.

    Args:
        run: The run row to inspect.

    Returns:
        True when the run's backend is offline.
    """
    if run.llm_backend is None:
        return run.provider == "mock"
    return run.llm_backend == "offline"


def run_offline_backed(
    run_id: str,
    *,
    missing_run_fallback: bool = False,
    db_path: str | None = None,
) -> bool:
    """Resolve a run's offline/real backend by id, with a gone-row fallback.

    The by-id form of :func:`run_used_offline` for callers that do not hold
    the row. One home for the "load the run, then fall back when it has
    been deleted" policy the finalization and escalation gates share, so
    their gating cannot drift.

    Args:
        run_id: Identifier of the run to inspect.
        missing_run_fallback: What to report when the run row is gone.
        db_path: Optional override for the SQLite database path.

    Returns:
        True when the run's backend is offline.
    """
    run = get_run(run_id, db_path=db_path)
    if run is None:
        return missing_run_fallback
    return run_used_offline(run)


def set_run_llm_backend(
    run_id: str, llm_backend: str, db_path: str | None = None
) -> None:
    """Set a run's persisted LLM backend (idempotent; no-op if the run is gone).

    Written when a run's resolved config carries an explicit ``llm_backend``
    override (e.g. a demo run pinned to the offline engine backend), so
    ``run_used_offline`` reports the override rather than the value derived
    at creation time. The override must land here before/when the workflow
    starts, since every later reader (report finalization, hypothesis
    badging) re-fetches the row rather than reusing the resolved config.

    Args:
        run_id: Identifier of the run to update.
        llm_backend: The backend to persist, "offline" or "real".
        db_path: Optional override for the SQLite database path.
    """
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE runs SET llm_backend = ? WHERE id = ?",
            (llm_backend, run_id),
        )


def set_run_title(run_id: str, title: str, db_path: str | None = None) -> None:
    """Set a run's short session title (idempotent; no-op if the run is gone).

    Args:
        run_id: Identifier of the run to update.
        title: The generated short title to store.
        db_path: Optional override for the SQLite database path.
    """
    with connect(db_path) as conn:
        conn.execute("UPDATE runs SET title = ? WHERE id = ?", (title, run_id))


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


def reserve_run_capacity(
    run_id: str,
    *,
    profile: str,
    client_id: str,
    limit: int,
    db_path: str | None = None,
) -> bool:
    """Atomically reserve one Standard/Advanced concurrency slot.

    Args:
        run_id: Draft run to transition to queued.
        profile: Faithful run mode whose active rows consume the quota.
        client_id: Scientist ownership scope.
        limit: Maximum concurrent runs of this mode for the scientist.
        db_path: Optional override for the SQLite database path.

    Returns:
        True when the slot was reserved and the run queued; False when the
        quota was already full or the run was no longer startable.
    """
    with transaction(db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM runs WHERE client_id=? AND profile=? "
            "AND status IN (?,?,?) AND id!=?",
            (client_id, profile, *_ACTIVE_RUN_STATUSES, run_id),
        ).fetchone()[0]
        if int(count) >= limit:
            return False
        now = _now()
        changed = conn.execute(
            "UPDATE runs SET status=?, updated_at=?, completed_at=NULL, "
            "error=NULL WHERE id=? AND status IN (?,?,?,?)",
            (
                RunStatus.QUEUED.value,
                now,
                run_id,
                RunStatus.DRAFT.value,
                RunStatus.FAILED.value,
                RunStatus.BLOCKED.value,
                RunStatus.CANCELLED.value,
            ),
        ).rowcount
    return bool(changed)


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


def reconcile_interrupted_runs(
    db_path: str | None = None,
) -> dict[str, list[str]]:
    """Reconcile runs left non-terminal by a previous process (crash/restart).

    On startup no workflow tasks are running, so any run still marked queued,
    running, or synthesizing was interrupted. A run that has a durable
    checkpoint is *resumable* (Milestone 4): it is left for the resume path
    rather than failed, and a ``resumable`` status event is logged. A run with
    no checkpoint cannot be resumed and is transitioned to ``failed`` with a
    clear reason and a status event so the stream/UI reflect the interruption.

    Args:
        db_path: Optional override for the SQLite database path.

    Returns:
        ``{"failed": [...], "resumable": [...]}`` — the ids in each outcome.
    """
    now = _now()
    reason = "Run interrupted by a server restart."
    failed: list[str] = []
    resumable: list[str] = []
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id FROM runs WHERE status IN (?,?,?)",
            _ACTIVE_RUN_STATUSES,
        ).fetchall()
        for row in rows:
            rid = row["id"]
            if has_checkpoint(rid, conn=conn):
                _append_event(
                    conn,
                    rid,
                    "status",
                    {"status": "resumable", "detail": "checkpoint available"},
                    now,
                )
                resumable.append(rid)
            else:
                _fail_interrupted_run(conn, rid, now, reason)
                failed.append(rid)
    return {"failed": failed, "resumable": resumable}


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
