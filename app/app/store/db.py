"""SQLite connection management, schema creation, and migrations."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sqlite3
import threading
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any

from app.store.schema import SCHEMA as _SCHEMA

logger = logging.getLogger(__name__)


def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, coltype: str
) -> bool:
    """Adds a column to a table when absent, idempotently.

    Args:
        conn: Open SQLite connection.
        table: Table to alter.
        column: Column name to ensure exists.
        coltype: Column type/constraint clause for the ADD COLUMN statement.

    Returns:
        True if the column was added, False if it already existed.
    """
    cols = {
        row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column in cols:
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
    logger.info("migration: added %s column to %s", column, table)
    return True


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Apply the historical schema upgrades in order."""
    # Add client-id ownership columns and purge pre-isolation rows.
    # Records ingested before client isolation stay un-owned, so they are
    # visible only to operators -- failing closed for existing rows.
    _add_column_if_missing(conn, "app_logs", "client_id", "TEXT")
    # Indexed here rather than in _SCHEMA: the column above may have just been
    # added, and _SCHEMA runs first (see the note beside idx_app_logs_run).
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_app_logs_client "
        "ON app_logs(client_id, id)"
    )
    if _add_column_if_missing(
        conn, "runs", "client_id", "TEXT NOT NULL DEFAULT ''"
    ):
        # One-time purge of runs that predate client isolation. This MUST run
        # only when the column is first added -- running it on every startup
        # would silently delete every header-less (empty client_id) run on each
        # restart, e.g. runs created via the API without an X-Client-ID header.
        conn.execute("DELETE FROM runs WHERE client_id = ''")
        logger.info("migration: purged pre-client-isolation runs")

    # Add run title/backend columns and the durable report-text column.
    # Short model-generated session title, distinct from research_goal.
    _add_column_if_missing(conn, "runs", "title", "TEXT")
    # Freshly synthesized narrative restatement of the goal in different
    # words, rendered at the head of the report's top-hypotheses section
    # (GOAL-RESTATEMENT-001). NULL until a background generator fills it, and
    # NULL on offline/keyless runs and on rows predating this column.
    _add_column_if_missing(conn, "runs", "goal_restatement", "TEXT")
    # Per-run LLM backend: 'offline' (deterministic router) or 'real'. Legacy
    # rows are backfilled from the provider -- the mock was always offline.
    if _add_column_if_missing(conn, "runs", "llm_backend", "TEXT"):
        conn.execute(
            "UPDATE runs SET llm_backend = "
            "CASE WHEN provider = 'mock' THEN 'offline' ELSE 'real' END"
        )
    # DB-durable copy of the rendered report, independent of the on-disk file.
    _add_column_if_missing(conn, "reports", "markdown_text", "TEXT")
    # R14-11's second document column, from the two-document split reversed
    # 2026-09-04 -- see store/reports.py's module docstring. Left in place
    # (nullable, never written) rather than dropped: not reversible against
    # the production SQLite volume.
    _add_column_if_missing(conn, "reports", "markdown_text_ranking", "TEXT")

    # Add the durable goal interview's own metadata columns.
    _add_column_if_missing(
        conn,
        "interviews",
        "execution_policy",
        "TEXT NOT NULL DEFAULT 'standard'",
    )
    # The Agent's chain of thought for one interview turn. Persisted rather
    # than relayed and dropped: a chat is short enough to carry its own
    # thinking back into the next turn's context, and a resumed chat that
    # replayed only the answers would ask its follow-up from less than the
    # scientist can see on screen.
    _add_column_if_missing(conn, "interview_turns", "reasoning", "TEXT")
    # Fallback provenance for one interview turn: 1 when the deterministic
    # recovery path authored the turn because no model could be reached, so
    # the UI can signal scripted questions instead of silently passing them
    # off as model output. Default 0 leaves older rows read as model-driven.
    _add_column_if_missing(
        conn, "interview_turns", "fallback", "INTEGER NOT NULL DEFAULT 0"
    )
    # The structured multiple-choice questions one Agent turn offered, as a
    # JSON array. NULL leaves every pre-existing turn reading as "asked
    # nothing choosable", which is what those turns did.
    _add_column_if_missing(conn, "interview_turns", "questions_json", "TEXT")

    # Default legacy runs to the ordinary execution policy.
    _add_column_if_missing(
        conn,
        "runs",
        "execution_policy",
        "TEXT NOT NULL DEFAULT 'standard'",
    )

    # Add the BYOK supervisor model and the free-run ledger.
    # No run FK: deleting a run must not refund its free-usage slot.
    _add_column_if_missing(conn, "run_credentials", "supervisor_model", "TEXT")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS free_run_usage ("
        "run_id TEXT PRIMARY KEY, client_id TEXT NOT NULL, "
        "created_at REAL NOT NULL)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_free_run_usage_client "
        "ON free_run_usage(client_id, created_at)"
    )

    # Add message, hypothesis, review, and verification-state columns.
    # Structured metadata (e.g. Q&A cited sources) alongside message text.
    _add_column_if_missing(conn, "messages", "meta_json", "TEXT")
    # Short classification label surfaced as a breadcrumb in the viewer.
    _add_column_if_missing(conn, "hypotheses", "category", "TEXT")
    # Authorship provenance for scientist-contributed hypotheses (Milestone 7);
    # empty for agent-generated ones.
    _add_column_if_missing(conn, "hypotheses", "author", "TEXT")
    # The same two facts for a scientist-contributed *review*. They were
    # previously readable only by scanning the summary prose for a verdict
    # word, which the engine round trip then dropped entirely -- so a human
    # review came back out of the drain as an anonymous agent review. Empty
    # on every agent-authored row.
    _add_column_if_missing(conn, "reviews", "author", "TEXT")
    _add_column_if_missing(conn, "reviews", "verdict", "TEXT")
    # Deep verification's per-hypothesis verdict (holds | weakened |
    # undermined | unverified). Persisted as state rather than left inside
    # the review row because it is now the *only* record that an undermined
    # idea is undermined: the verdict stopped excluding such ideas, so the
    # lifecycle status no longer carries the fact and a published idea would
    # otherwise reach the reader looking sound. NULL on rows written before
    # this column, and on ideas verification never reached.
    _add_column_if_missing(
        conn, "hypothesis_state", "verification_verdict", "TEXT"
    )

    # Add claim-role, match-tier, and safety-decision columns.
    # Source-role metadata keeps insufficient novel proposals distinct from
    # unsupported categorical background without changing entailment labels.
    _add_column_if_missing(
        conn,
        "claim_evidence",
        "claim_role",
        "TEXT NOT NULL DEFAULT 'categorical'",
    )
    # Decisiveness class (upset|decisive|clear|narrow) for a tournament match.
    _add_column_if_missing(conn, "matches", "tier", "TEXT")
    # Debate depth for a match: 1 = single-turn comparison, >1 = multi-turn
    # scientific debate (Milestone 3). Default 1 keeps older rows single-turn.
    _add_column_if_missing(
        conn, "matches", "debate_turns", "INTEGER NOT NULL DEFAULT 1"
    )
    # Versioned contextual safety provenance and human-review routing.
    _add_column_if_missing(conn, "safety_decisions", "category", "TEXT")
    _add_column_if_missing(conn, "safety_decisions", "policy_version", "TEXT")
    _add_column_if_missing(
        conn, "safety_decisions", "risk_domains_json", "TEXT"
    )
    _add_column_if_missing(
        conn,
        "safety_decisions",
        "requires_review",
        "INTEGER NOT NULL DEFAULT 0",
    )
    _add_column_if_missing(conn, "safety_decisions", "assessor", "TEXT")
    _add_column_if_missing(conn, "safety_decisions", "resolution", "TEXT")
    _add_column_if_missing(conn, "safety_decisions", "resolved_by", "TEXT")
    _add_column_if_missing(conn, "safety_decisions", "resolved_at", "REAL")

    # Add proximity-edge timestamps and evidence-attachment metadata.
    _add_column_if_missing(
        conn, "proximity_edges", "created_at", "REAL NOT NULL DEFAULT 0"
    )
    _add_column_if_missing(conn, "evidence", "mime_type", "TEXT")
    _add_column_if_missing(conn, "evidence", "sha256", "TEXT")
    _add_column_if_missing(conn, "evidence", "byte_size", "INTEGER")
    _add_column_if_missing(conn, "evidence", "document_version", "TEXT")
    _add_column_if_missing(conn, "evidence", "extraction_tool", "TEXT")

    # Add the multi-parent lineage column to hypotheses.
    _add_column_if_missing(conn, "hypotheses", "parent_ids", "TEXT")

    # Add evidence identity/passage/retrieval-time columns (G12).
    _add_column_if_missing(conn, "evidence", "doi", "TEXT")
    _add_column_if_missing(conn, "evidence", "pmid", "TEXT")
    _add_column_if_missing(conn, "evidence", "passage_text", "TEXT")
    _add_column_if_missing(conn, "evidence", "retrieved_at", "REAL")

    # Add persisted hybrid-retrieval scoring columns to evidence (G5).
    _add_column_if_missing(conn, "evidence", "retrieval_score", "REAL")
    _add_column_if_missing(conn, "evidence", "retrieval_rationale", "TEXT")
    _add_column_if_missing(conn, "evidence", "retriever_version", "TEXT")

    # Add the retrieval-provenance link to evidence.
    _add_column_if_missing(conn, "evidence", "retrieval_call_id", "TEXT")

    # Add the per-failed-attempt history column to scientific_tasks.
    _add_column_if_missing(
        conn, "scientific_tasks", "attempts_json", "TEXT NOT NULL DEFAULT '[]'"
    )
    # Nullable: NULL on a row that has never been leased under the new
    # code, and _try_lease_task sets it fresh on every claim thereafter.
    _add_column_if_missing(
        conn, "scientific_tasks", "attempt_started_at", "REAL"
    )

    # Drop the retired pilot-feedback table.
    conn.execute("DROP TABLE IF EXISTS feedback")

    # Add the published proposal's scene-setting columns (MO-6).
    _add_column_if_missing(conn, "hypotheses", "introduction", "TEXT")
    _add_column_if_missing(conn, "hypotheses", "recent_findings", "TEXT")

    # Add the proposer's own safety-and-toxicity column (MO-10).
    _add_column_if_missing(conn, "hypotheses", "safety_and_toxicity", "TEXT")

    # Add the reviews table's structured-detail column (R14-22/R14-15).
    _add_column_if_missing(conn, "reviews", "detail_json", "TEXT")

    # Add the evidence table's retraction flag, separate from ``available``.
    _add_column_if_missing(conn, "evidence", "retracted", "INTEGER")

    # Add the evidence table's source-type classification.
    _add_column_if_missing(conn, "evidence", "source_type", "TEXT")

    # Add the not-before scheduling column to scientific_tasks.
    _add_column_if_missing(conn, "scientific_tasks", "available_at", "REAL")

    # Add the matches table's turn-by-turn debate transcript column.
    _add_column_if_missing(conn, "matches", "debate_transcript", "TEXT")

    # Add the steering-acknowledgement timestamp and decision columns.
    _add_column_if_missing(conn, "messages", "applied_at", "REAL")
    _add_column_if_missing(conn, "messages", "applied_decision", "TEXT")

    # Add the authoring-cycle ordinal to hypotheses (EVAL-SCALING-001).
    _add_column_if_missing(conn, "hypotheses", "creation_iteration", "INTEGER")

    # Keep pre-existing assessments explicit about missing provenance.
    _add_column_if_missing(
        conn,
        "claim_evidence",
        "verification_method",
        "TEXT NOT NULL DEFAULT 'legacy_unknown'",
    )

    # Keep the action's child lineage on databases created during 01b.
    _add_column_if_missing(
        conn,
        "outcome_refinement_actions",
        "child_hypothesis_id",
        "TEXT",
    )


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

_lock = threading.RLock()
_initialized: set[str] = set()


# Single clock used for every created_at/updated_at column so writers agree
# on "now" instead of each call site calling time.time() independently.
def _now() -> float:
    return time.time()


def default_db_path() -> str | None:
    """Return the DB path from the environment, or None for the store default.

    Single home for the ``COSCIENTIST_DB_PATH`` environment-variable
    knowledge. A None result means "use the store default".

    Returns:
        The configured database path, or None when unset.
    """
    return os.getenv("COSCIENTIST_DB_PATH") or None


def _resolved_db_path(path: str | None = None) -> str:
    # Read env on every call so test fixtures and runtime overrides are
    # picked up.
    return path or default_db_path() or "./coscientist.db"


def _reports_dir() -> Path:
    # Directory for the on-disk Markdown report copies; overridable via env
    # for deployments that mount a persistent volume elsewhere.
    p = Path(os.getenv("COSCIENTIST_REPORTS_DIR") or "./reports")
    p.mkdir(parents=True, exist_ok=True)  # No-op if the directory exists.
    return p


def _open_raw_connection(db_path: str) -> sqlite3.Connection:
    """Open a sqlite3 connection with the pragmas this store relies on."""
    # The parent dir only needs creating before the first connect for a path.
    # A db_path already in `_initialized` was connected before, so its dir
    # exists; skipping the syscall keeps hot read paths (SSE poll, endpoints)
    # off a per-call mkdir.
    if db_path not in _initialized:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    # timeout=30: wait on WAL lock contention instead of raising immediately.
    # isolation_level=None: autocommit; explicit transactions are scoped with
    # BEGIN/COMMIT in `transaction()` below rather than via the DB-API's
    # implicit ones. check_same_thread=False: connections may be created on
    # one async task and used from another.
    conn = sqlite3.connect(
        db_path, timeout=30, isolation_level=None, check_same_thread=False
    )
    conn.row_factory = sqlite3.Row  # Rows behave like dicts: row["col"].
    # The durability setting WAL is meant to be paired with, and per-
    # connection (like foreign_keys) rather than sticky in the file, so it
    # belongs here rather than in _init_schema. At the default every commit
    # pays its own fsync, and on network-attached storage that fsync is what
    # a writer holds the single write lock for: under a wide worker cohort
    # the lock stayed saturated and ordinary API writes exhausted their
    # 30-second busy timeout, failing with "database is locked". NORMAL
    # still fsyncs the log at checkpoints, so a crashed process loses
    # nothing; only an OS-level failure can cost the most recent
    # transactions, which a run reconstructs from its checkpoint anyway.
    conn.execute("PRAGMA synchronous=NORMAL")
    # foreign_keys is per-connection (never sticky in the file), so it must be
    # enabled on every connection this factory hands out for the schema's
    # ON DELETE CASCADE clauses to be enforced at all. Without it, deleting a
    # parent row silently strands its children.
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _ensure_schema_initialized(db_path: str, conn: sqlite3.Connection) -> None:
    """Run one-time schema init for db_path, serialized across threads."""
    # Double-checked locking: skip the lock entirely once a db_path has
    # been initialized (the hot path), but still serialize the first
    # schema-creation race across concurrently-starting threads.
    if db_path not in _initialized:
        with _lock:
            if db_path not in _initialized:
                _init_schema(conn)
                _initialized.add(db_path)


@contextlib.contextmanager
def connect(
    path: str | None = None,
) -> Generator[sqlite3.Connection, None, None]:
    """Yield a sqlite3 connection with WAL + row factory enabled."""
    db_path = _resolved_db_path(path)
    conn = _open_raw_connection(db_path)
    try:
        _ensure_schema_initialized(db_path, conn)
        yield conn
    finally:
        conn.close()


@contextlib.contextmanager
def transaction(
    path: str | None = None,
) -> Generator[sqlite3.Connection, None, None]:
    """Yield a connection whose writes commit as a single transaction.

    Pass the yielded connection to the store helpers' ``conn`` parameter to
    batch many writes into one fsync'd transaction instead of one per call.

    Args:
        path: Optional override for the SQLite database path.
    """
    with connect(path) as conn:
        # IMMEDIATE grabs the write lock upfront, failing fast on contention
        # instead of upgrading (and possibly deadlocking) mid-transaction.
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")


@contextlib.contextmanager
def _use_conn(
    conn: sqlite3.Connection | None,
    path: str | None,
) -> Generator[sqlite3.Connection, None, None]:
    """Yield the caller-supplied connection, or open (and close) a fresh one."""
    if conn is not None:
        yield conn
    else:
        with connect(path) as fresh:
            yield fresh


def _init_schema(conn: sqlite3.Connection) -> None:
    """Create tables/indexes if absent, enable WAL, then run migrations."""
    # Every statement is CREATE TABLE/INDEX IF NOT EXISTS, so this is safe to
    # run against an already-populated database on every process start --
    # with one constraint: because CREATE TABLE IF NOT EXISTS does NOT alter
    # an existing table, no statement here may reference a column added by
    # _run_migrations. Such a statement would raise, aborting executescript
    # mid-way (and, since the path is only marked initialized on success,
    # failing every later connect too). Index those columns in
    # _run_migrations, after the ALTER that adds them.
    conn.executescript(_SCHEMA)
    conn.execute("PRAGMA journal_mode=WAL")  # Readers do not block writers.
    # NOTE: foreign_keys is a PER-CONNECTION pragma (unlike WAL, which is
    # sticky in the file). `_open_raw_connection` enables it on every
    # connection, so the schema's `ON DELETE CASCADE` clauses are enforced
    # everywhere, including here. The explicit child deletes in
    # store/runs_views.py (clear_run_derived_data and friends) are retained
    # deliberately: they are redundant-but-harmless under enforced cascades
    # and document exactly which derived rows a resume reconstructs.
    _run_migrations(conn)


def checkpoint_wal(db_path: str | None = None) -> None:
    """Merge the write-ahead log into the main database file.

    Called on graceful shutdown so a clean stop leaves committed data in the
    main DB file rather than only in the ``-wal`` sidecar.

    Args:
        db_path: Optional override for the SQLite database path.
    """
    try:
        with connect(db_path) as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error as exc:
        logger.warning("WAL checkpoint failed: %s", exc)


def _list_by_run(
    table: str,
    run_id: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
    *,
    json_fields: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Read a trusted table's run rows and decode its list-valued JSON."""
    with _use_conn(conn, db_path) as active:
        rows = active.execute(
            f"SELECT * FROM {table} WHERE run_id=? ORDER BY created_at ASC",
            (run_id,),
        ).fetchall()
    result = [dict(row) for row in rows]
    for row in result:
        for field in json_fields:
            row[field] = json.loads(row.pop(f"{field}_json", None) or "[]")
    return result


__all__ = ["_run_migrations"]
