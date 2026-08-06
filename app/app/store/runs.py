"""Run CRUD and lifecycle helpers for the runs table.

Covers creating runs, reading them, status transitions (including
terminal-state timestamps), and the per-run summary counts. The enriched
list rollups and the derived-data resets live in ``app.store.runs_views``,
and the startup reconciliation of runs interrupted by a restart lives in
``app.store.runs_reconcile``; both are re-exported here so the module
namespace is unchanged.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any

from app.store.db import _now, _use_conn, connect, transaction
from app.store.models import (
    TERMINAL_STATUSES,
    RunRow,
    RunStatus,
    _row_to_run,
)
from app.store.runs_delete import count_run_rows as count_run_rows
from app.store.runs_delete import delete_run as delete_run
from app.store.runs_reconcile import (
    _ACTIVE_RUN_STATUSES as _ACTIVE_RUN_STATUSES,
)
from app.store.runs_reconcile import (
    _fail_interrupted_run as _fail_interrupted_run,
)
from app.store.runs_reconcile import (
    _reconcile_one_run as _reconcile_one_run,
)
from app.store.runs_reconcile import (
    _settle_run_for_failed_task as _settle_run_for_failed_task,
)
from app.store.runs_reconcile import (
    _settle_run_out_of_work as _settle_run_out_of_work,
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


def _resolve_llm_backend(provider: str, llm_backend: str | None) -> str:
    """Resolve the backend to persist, defaulting it from the provider."""
    if llm_backend is not None:
        return llm_backend
    return "offline" if provider == "mock" else "real"


@dataclass(frozen=True)
class _NewRunFields:
    """Fields needed to insert a run row and build its RunRow."""

    run_id: str
    research_goal: str
    title: str | None
    profile: str
    provider: str
    config: dict[str, Any]
    client_id: str
    now: float
    backend: str


def _insert_run_row(conn: sqlite3.Connection, f: _NewRunFields) -> None:
    """Insert a new run row in the DRAFT state on an open connection."""
    conn.execute(
        "INSERT INTO runs (id, research_goal, title, profile, status, "
        "provider, config_json, client_id, created_at, updated_at, "
        "llm_backend) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            f.run_id,
            f.research_goal,
            f.title,
            f.profile,
            RunStatus.DRAFT.value,
            f.provider,
            json.dumps(f.config),
            f.client_id,
            f.now,
            f.now,
            f.backend,
        ),
    )


def _run_row_from_insert(f: _NewRunFields) -> RunRow:
    """Build the RunRow for a just-inserted run."""
    return RunRow(
        id=f.run_id,
        research_goal=f.research_goal,
        title=f.title,
        profile=f.profile,
        status=RunStatus.DRAFT.value,
        provider=f.provider,
        config=f.config,
        client_id=f.client_id,
        created_at=f.now,
        updated_at=f.now,
        completed_at=None,
        error=None,
        llm_backend=f.backend,
    )


def _log_run_created(f: _NewRunFields) -> None:
    """Log creation of a new run at info level."""
    logger.info(
        "created run %s run_mode=%s provider=%s llm_backend=%s client_id=%s",
        f.run_id,
        f.profile,
        f.provider,
        f.backend,
        f.client_id,
    )


@dataclass(frozen=True)
class RunCreateOptions:
    """The optional inputs to a run creation, plus the db override.

    ``client_id`` is the owning client identifier used for run isolation.
    ``title`` is a short session heading, usually NULL at creation and
    filled in shortly after by a background title generator, but supplied
    directly for curated demo runs. ``llm_backend`` is the backend the run
    will execute against, "offline" or "real"; when omitted it is derived
    from the provider (the mock was always offline-backed), matching the
    legacy-row default. ``db_path`` overrides the SQLite database path.
    """

    client_id: str = ""
    title: str | None = None
    llm_backend: str | None = None
    db_path: str | None = None


def _create_run_impl(fields: _NewRunFields, db_path: str | None) -> RunRow:
    """Persist a new DRAFT run row and return it as a RunRow."""
    with connect(db_path) as conn:
        _insert_run_row(conn, fields)
    _log_run_created(fields)
    return _run_row_from_insert(fields)


def create_run(
    research_goal: str,
    profile: str,
    provider: str,
    config: dict[str, Any],
    options: RunCreateOptions | None = None,
) -> RunRow:
    """Insert a new run row in the DRAFT state and return it.

    Args:
        research_goal: The natural-language research goal for the run.
        profile: Canonical run mode. The column name is retained for
            compatibility with older clients.
        provider: The execution provider; every caller passes 'engine'
            today (see ``engine_adapter.select_provider``).
        config: Run configuration values serialized to JSON.
        options: Optional creation inputs and database override (see
            :class:`RunCreateOptions`).

    Returns:
        The newly created run as a RunRow.
    """
    opts = options or RunCreateOptions()
    fields = _NewRunFields(
        run_id=str(uuid.uuid4()),
        research_goal=research_goal,
        title=opts.title,
        profile=profile,
        provider=provider,
        config=config,
        client_id=opts.client_id,
        now=_now(),
        backend=_resolve_llm_backend(provider, opts.llm_backend),
    )
    return _create_run_impl(fields, opts.db_path)


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


def redact_run_goal(
    run_id: str, goal: str, title: str, db_path: str | None = None
) -> None:
    """Overwrite a run's goal and title with their redacted forms.

    An intake ``redact`` decision used to record the label and leave the
    original goal in the row, where it stayed readable through the run API,
    the run list, and every surface built from them. The title is rewritten
    in the same statement because it is generated from the goal and would
    otherwise carry the same span.

    Args:
        run_id: Identifier of the run to update.
        goal: The redacted research goal to persist.
        title: The redacted session title to persist.
        db_path: Optional override for the SQLite database path.
    """
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE runs SET research_goal = ?, title = ? WHERE id = ?",
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
    conn: sqlite3.Connection, run_id: str, now: float
) -> int:
    """Move a run to QUEUED if it is still in a startable status."""
    return conn.execute(
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


def reserve_run_capacity(
    run_id: str,
    *,
    client_id: str,
    limit: int,
    db_path: str | None = None,
) -> bool:
    """Atomically reserve one of the scientist's concurrency slots.

    One ceiling per identity, counted over every tier together: a caller
    that spreads its runs across tiers gets no extra allowance.

    Args:
        run_id: Draft run to transition to queued.
        client_id: Scientist ownership scope.
        limit: Maximum concurrent runs for the scientist.
        db_path: Optional override for the SQLite database path.

    Returns:
        True when the slot was reserved and the run queued; False when the
        quota was already full or the run was no longer startable.
    """
    with transaction(db_path) as conn:
        count = _count_other_active_runs(conn, run_id, client_id)
        if count >= limit:
            return False
        changed = _queue_run_if_startable(conn, run_id, _now())
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
