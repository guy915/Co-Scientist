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

from app.store.checkpoints import has_checkpoint
from app.store.db import _now, _use_conn, connect, transaction
from app.store.events import _append_event
from app.store.models import (
    TERMINAL_STATUSES,
    RunRow,
    RunStatus,
    _row_to_run,
)

logger = logging.getLogger(__name__)

# Statuses that mark a run as occupying a concurrency slot / still in flight.
_ACTIVE_RUN_STATUSES: tuple[str, str, str] = (
    RunStatus.QUEUED.value,
    RunStatus.RUNNING.value,
    RunStatus.SYNTHESIZING.value,
)

# Run-scoped tables whose rows are all deterministically reconstructed by the
# final drain, so both the full and publication-only resets delete them
# wholesale.
_REPLAYABLE_ARTIFACT_TABLES: tuple[str, ...] = (
    "matches",
    "citations",
    "claim_evidence",
    "proximity_edges",
    "run_metrics",
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


# Number of top hypotheses surfaced per run on list endpoints.
_TOP_HYPOTHESES_CAP = 3

# Event types that mark a pipeline stage, used to report a run's
# ``latest_stage`` for the live progress indicator. Cross-cutting events
# (safety.*, citation.*, status, lifecycle, report) are excluded so the
# reported stage tracks the linear agent pipeline. Both providers emit these
# canonical types.
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


def clear_run_derived_data(
    run_id: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Delete a run's derived pipeline data for a clean deterministic resume.

    Removes the run's events, report, safety decisions, evidence, matches,
    reviews, citations, claim-evidence, execution metrics, and hypotheses
    (plus the per-hypothesis state rows). The run row itself, its
    checkpoints, its messages
    (steering/Q&A history), and the scientist's contributions (manual
    hypotheses, human reviews, attachments) are kept, so a resumed run
    reconstructs identical agent artifacts from the same seed without
    duplicating rows or events and without discarding human input. A kept
    human review of a deleted agent hypothesis may reference a re-derived (new)
    hypothesis id; retaining the scientist's words beats deleting them.

    Every child table is deleted explicitly rather than via ``ON DELETE
    CASCADE``: the SQLite ``foreign_keys`` pragma is per-connection and is only
    enabled on the one-time schema-init connection, so later connections do not
    enforce cascades. Relying on the cascade would leave stale reviews/
    citations/claim_evidence rows behind after a resume.

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
    `_persist_final_state` deterministically reconstructs.
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
