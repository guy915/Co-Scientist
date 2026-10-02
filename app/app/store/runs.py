"""Run CRUD and lifecycle helpers for the runs table.

Covers creation, reads, atomic capacity admission, status transitions and
summary counts. Enriched list rollups and derived-data resets live in
``runs_views``; crash recovery and lease fencing have their own modules.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any

from app.store.db import _now, _use_conn, connect
from app.store.models import (
    TERMINAL_STATUSES,
    RunRow,
    RunStatus,
    _row_to_run,
)
from app.store.runs_bootstrap import (
    bootstrap_task_lease_matches as bootstrap_task_lease_matches,
)
from app.store.runs_bootstrap import (
    mark_bootstrap_running as mark_bootstrap_running,
)
from app.store.runs_delete import count_run_rows as count_run_rows
from app.store.runs_delete import delete_run as delete_run
from app.store.runs_reconcile import (
    _ACTIVE_RUN_STATUSES,
)
from app.store.runs_reconcile import (
    reconcile_interrupted_runs as reconcile_interrupted_runs,
)
from app.store.runs_views import (
    clear_publication_artifacts as clear_publication_artifacts,
)
from app.store.runs_views import (
    clear_run_derived_data as clear_run_derived_data,
)
from app.store.runs_views import (
    list_expired_terminal_runs as list_expired_terminal_runs,
)
from app.store.runs_views import list_runs as list_runs

logger = logging.getLogger(__name__)


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


def redact_run_goal(
    run_id: str,
    goal: str,
    title: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Overwrite a run's goal and title with their redacted forms.

    An intake ``redact`` decision used to record the label and leave the
    original goal in the row, where it stayed readable through the run API,
    the run list, and every surface built from them. The title is rewritten
    in the same statement because it is generated from the goal and would
    otherwise carry the same span; ``goal_restatement`` is cleared for the
    same reason — it is a paraphrase of the goal, stamped at create before
    the intake screen runs, so leaving it would leak the redacted goal in
    other words at the head of the report's top-hypotheses section.

    Args:
        run_id: Identifier of the run to update.
        goal: The redacted research goal to persist.
        title: The redacted session title to persist.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse within a transaction.
    """
    with _use_conn(conn, db_path) as active:
        active.execute(
            "UPDATE runs SET research_goal = ?, title = ?, "
            "goal_restatement = NULL WHERE id = ?",
            (goal, title, run_id),
        )


def set_run_config(
    run_id: str, config: dict[str, Any], db_path: str | None = None
) -> None:
    """Replace one run's persisted configuration.

    Startup fixtures use this when a new fixture revision adds displayable
    setup fields. Existing demo rows must receive the same configuration as a
    newly created row; otherwise their Goal Details retain the old empty data.
    """
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE runs SET config_json=?, updated_at=? WHERE id=?",
            (json.dumps(config), _now(), run_id),
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


def update_run_status(
    run_id: str,
    status: RunStatus,
    error: str | None = None,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Update a run's status, timestamps, and optional error message.

    Args:
        run_id: Identifier of the run to update.
        status: The new lifecycle status to persist.
        error: Optional error message to store when the run failed.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to join an existing transaction.
    """
    now = _now()
    completed_at = now if status in TERMINAL_STATUSES else None
    with _use_conn(conn, db_path) as active:
        active.execute(
            "UPDATE runs SET status=?, error=?, updated_at=?, "
            "completed_at=? WHERE id=?",
            (status.value, error, now, completed_at, run_id),
        )


def update_run_status_if_current(
    conn: sqlite3.Connection,
    run_id: str,
    status: RunStatus,
    expected_statuses: tuple[RunStatus, ...],
    error: str | None = None,
) -> bool:
    """Change status only if the current row is in an allowed state."""
    if not expected_statuses:
        return False
    now = _now()
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


def set_run_timing(
    run_id: str,
    duration_seconds: float,
    db_path: str | None = None,
) -> None:
    """Set a completed run's synthetic start and finish times.

    Curated demos are reconstructed at startup, including ones created by an
    older release. Resetting both endpoints prevents the elapsed-time UI from
    treating the period between releases as compute time.
    """
    completed_at = _now()
    created_at = completed_at - max(duration_seconds, 1.0)
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE runs SET created_at=?, updated_at=?, completed_at=? "
            "WHERE id=?",
            (created_at, completed_at, completed_at, run_id),
        )


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


def set_run_title(run_id: str, title: str, db_path: str | None = None) -> None:
    """Set a run's short session title (idempotent; no-op if the run is gone).

    Args:
        run_id: Identifier of the run to update.
        title: The generated short title to store.
        db_path: Optional override for the SQLite database path.
    """
    with connect(db_path) as conn:
        conn.execute("UPDATE runs SET title = ? WHERE id = ?", (title, run_id))


def set_run_goal_restatement(
    run_id: str, restatement: str, db_path: str | None = None
) -> None:
    """Set a run's narrative goal restatement (idempotent; no-op if gone).

    GOAL-RESTATEMENT-001: a background generator fills this shortly after
    create, and the report reads it from the run row at finalize.

    Args:
        run_id: Identifier of the run to update.
        restatement: The synthesized narrative restatement to store.
        db_path: Optional override for the SQLite database path.
    """
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE runs SET goal_restatement = ? WHERE id = ?",
            (restatement, run_id),
        )


@dataclass(frozen=True)
class RunCreateOptions:
    """Optional run creation inputs and database override."""

    client_id: str = ""
    title: str | None = None
    llm_backend: str | None = None
    execution_policy: str = "standard"
    db_path: str | None = None
    conn: sqlite3.Connection | None = None
    log_created: bool | None = None


def log_run_created(run: RunRow) -> None:
    """Mirror a committed run creation in the application log."""
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
    """Insert a new DRAFT row and return it.

    Caller-owned transactions defer the creation log until their commit,
    unless ``log_created`` explicitly overrides that behavior.
    """
    opts = options or RunCreateOptions()
    now = _now()
    backend = opts.llm_backend
    if backend is None:
        backend = "offline" if provider == "mock" else "real"
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
        execution_policy=opts.execution_policy,
    )
    with _use_conn(opts.conn, opts.db_path) as active:
        active.execute(
            "INSERT INTO runs (id, research_goal, title, profile, status, "
            "provider, config_json, client_id, created_at, updated_at, "
            "llm_backend, execution_policy) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
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
                run.execution_policy,
            ),
        )
    should_log = (
        opts.conn is None if opts.log_created is None else opts.log_created
    )
    if should_log:
        log_run_created(run)
    return run


def _count_other_active_runs(
    conn: sqlite3.Connection, run_id: str, client_id: str
) -> int:
    """Count the client's other in-flight runs, whatever tier they are.

    Deliberately blind to ``profile``: the quota is one ceiling per
    identity. Partitioning the count by tier as well made the effective
    allowance ``max_concurrent_runs`` per tier -- four times what is
    advertised, and reachable simply by naming a different tier each time.
    """
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM runs WHERE client_id=? "
            "AND status IN (?,?,?) AND id!=?",
            (client_id, *_ACTIVE_RUN_STATUSES, run_id),
        ).fetchone()[0]
    )


def _queue_run_if_startable(
    conn: sqlite3.Connection, run_id: str, now: float, expected_status: str
) -> int:
    """Move a run to QUEUED only from the status this start request read."""
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
    """Reserve a client's run slot using the caller's active transaction."""
    count = _count_other_active_runs(conn, run_id, client_id)
    if count >= limit:
        return False
    changed = _queue_run_if_startable(conn, run_id, _now(), expected_status)
    return bool(changed)
