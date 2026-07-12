"""SQLite connection management, schema creation, and migrations.

Owns the connection/transaction context managers, the WAL and pragma
setup, the CREATE TABLE schema, and the idempotent in-place migrations.
The other ``app.store`` submodules build on the primitives defined here
instead of calling ``sqlite3.connect`` directly.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
import threading
import time
from collections.abc import Generator
from pathlib import Path

logger = logging.getLogger(__name__)

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


@contextlib.contextmanager
def connect(
    path: str | None = None,
) -> Generator[sqlite3.Connection, None, None]:
    """Yield a sqlite3 connection with WAL + row factory enabled."""
    db_path = _resolved_db_path(path)
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
    try:
        # Double-checked locking: skip the lock entirely once a db_path has
        # been initialized (the hot path), but still serialize the first
        # schema-creation race across concurrently-starting threads.
        if db_path not in _initialized:
            with _lock:
                if db_path not in _initialized:
                    _init_schema(conn)
                    _initialized.add(db_path)
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
    # run against an already-populated database on every process start.
    conn.executescript(_SCHEMA)
    conn.execute("PRAGMA journal_mode=WAL")  # Readers do not block writers.
    # NOTE: foreign_keys is a PER-CONNECTION pragma (unlike WAL, which is
    # sticky in the file). It is enabled here only on the one-time schema-init
    # connection, so the schema's `ON DELETE CASCADE` clauses are NOT enforced
    # on the ordinary connections `connect()` hands out afterwards. Any delete
    # of a parent row on a normal connection must remove its children
    # explicitly (see store/runs.py::clear_run_derived_data). Migrations that
    # delete parent rows run here, on this connection, so their cascades do
    # fire.
    conn.execute("PRAGMA foreign_keys=ON")
    _run_migrations(conn)


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
    """Apply idempotent in-place schema migrations to an open connection."""
    if _add_column_if_missing(
        conn, "runs", "client_id", "TEXT NOT NULL DEFAULT ''"
    ):
        # One-time purge of runs that predate client isolation. This MUST run
        # only when the column is first added -- running it on every startup
        # would silently delete every header-less (empty client_id) run on each
        # restart, e.g. runs created via the API without an X-Client-ID header.
        conn.execute("DELETE FROM runs WHERE client_id = ''")
        logger.info("migration: purged pre-client-isolation runs")

    # Short model-generated session title, distinct from research_goal.
    _add_column_if_missing(conn, "runs", "title", "TEXT")
    # DB-durable copy of the rendered report, independent of the on-disk file.
    _add_column_if_missing(conn, "reports", "markdown_text", "TEXT")
    # Structured metadata (e.g. Q&A cited sources) alongside message text.
    _add_column_if_missing(conn, "messages", "meta_json", "TEXT")
    # Short classification label surfaced as a breadcrumb in the viewer.
    _add_column_if_missing(conn, "hypotheses", "category", "TEXT")
    # Authorship provenance for scientist-contributed hypotheses (Milestone 7);
    # empty for agent-generated ones.
    _add_column_if_missing(conn, "hypotheses", "author", "TEXT")
    # Decisiveness class (upset|decisive|clear|narrow) for a tournament match.
    _add_column_if_missing(conn, "matches", "tier", "TEXT")
    # Debate depth for a match: 1 = single-turn comparison, >1 = multi-turn
    # scientific debate (Milestone 3). Default 1 keeps older rows single-turn.
    _add_column_if_missing(
        conn, "matches", "debate_turns", "INTEGER NOT NULL DEFAULT 1"
    )


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


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
-- Primary lifecycle record for a single hypothesis-generation run.
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    research_goal TEXT NOT NULL,
    -- short model-generated session heading, distinct from research_goal;
    -- NULL until generated (surfaces fall back to a clause of the goal)
    title TEXT,
    -- canonical run mode; column name kept for legacy clients
    profile TEXT NOT NULL,
    -- draft|queued|running|synthesizing|completed|failed|blocked|cancelled
    status TEXT NOT NULL,
    provider TEXT NOT NULL,          -- 'mock' | 'engine'
    -- JSON: initial_count, iterations, evolution_count, k_factor, ...
    config_json TEXT NOT NULL,
    client_id TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    completed_at REAL,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC);

-- Durable pre-run Agent interview. The structured fields are derived from the
-- append-only turn transcript and remain editable until finalized.
CREATE TABLE IF NOT EXISTS interviews (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    status TEXT NOT NULL,             -- active | completed | cancelled
    fields_json TEXT NOT NULL,
    current_question TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    completed_at REAL
);
CREATE INDEX IF NOT EXISTS idx_interviews_client
    ON interviews(client_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS interview_turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interview_id TEXT NOT NULL,
    role TEXT NOT NULL,               -- user | agent
    content TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (interview_id) REFERENCES interviews(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_interview_turns
    ON interview_turns(interview_id, id ASC);

-- Revocable capability links for read-only public Goal Reports. Tokens are
-- random and stored only as hashes so a database read cannot disclose links.
CREATE TABLE IF NOT EXISTS report_shares (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_by_client TEXT NOT NULL,
    created_at REAL NOT NULL,
    revoked_at REAL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_report_shares_run
    ON report_shares(run_id, created_at DESC);

-- Append-only timeline of everything that happened during a run. This is the
-- canonical source the SSE endpoint replays on client reconnect or restart.
CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,            -- per-run monotonic sequence number
    -- agent name, 'status', 'log', 'metric', ...
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_events_run_seq ON run_events(run_id, seq);

-- Durable global scientific task queue. A unique idempotency key prevents a
-- Supervisor retry or worker redelivery from duplicating scientific effects.
CREATE TABLE IF NOT EXISTS scientific_tasks (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    task_type TEXT NOT NULL,
    -- queued | leased | completed | failed | cancelled
    status TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    inputs_json TEXT NOT NULL,
    dependencies_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    budget_json TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    lease_owner TEXT,
    lease_expires_at REAL,
    result_json TEXT,
    error TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    started_at REAL,
    completed_at REAL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
    UNIQUE (run_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_tasks_ready
    ON scientific_tasks(status, priority DESC, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_tasks_run
    ON scientific_tasks(run_id, created_at ASC);

-- Append-only hypothesis records: `evolve` inserts a new row with parent_id
-- set rather than mutating the parent. Mutable fields (Elo, scores, status)
-- live in hypothesis_state below, keyed by hypothesis id.
CREATE TABLE IF NOT EXISTS hypotheses (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    parent_id TEXT,                  -- NULL for generation-0; set by evolve
    generation INTEGER NOT NULL DEFAULT 0,
    category TEXT,                   -- short classification label (breadcrumb)
    title TEXT NOT NULL,
    statement TEXT NOT NULL,
    mechanism TEXT,
    expected_effect TEXT,
    experimental_context TEXT,
    created_by_agent TEXT NOT NULL,  -- 'generation' | 'evolution'
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_id) REFERENCES hypotheses(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_hyp_run ON hypotheses(run_id);
CREATE INDEX IF NOT EXISTS idx_hyp_parent ON hypotheses(parent_id);

-- Mutable state for a hypothesis (Elo, scores, status). Kept separate from the
-- append-only `hypotheses` table so the original record is never overwritten.
CREATE TABLE IF NOT EXISTS hypothesis_state (
    hypothesis_id TEXT PRIMARY KEY,
    elo_rating INTEGER NOT NULL DEFAULT 1200,
    win_count INTEGER NOT NULL DEFAULT 0,
    loss_count INTEGER NOT NULL DEFAULT 0,
    novelty_score REAL,
    -- plausibility_score/testability_score/safety_status/status are reserved
    -- columns: update_hypothesis_state does not currently set them, and the
    -- underlying scores live on reviews instead (see reviews table below).
    plausibility_score REAL,
    testability_score REAL,
    safety_status TEXT DEFAULT 'pending',
    status TEXT NOT NULL DEFAULT 'active',
    cluster_id TEXT,               -- proximity/dedup cluster, set by evolve
    updated_at REAL NOT NULL,
    FOREIGN KEY (hypothesis_id) REFERENCES hypotheses(id) ON DELETE CASCADE
);

-- Literature/evidence items retrieved for a run; cited by hypotheses via the
-- citations table below.
CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    title TEXT NOT NULL,
    source TEXT,                     -- 'pubmed' | 'arxiv' | 'mock' | ...
    url TEXT,
    authors_json TEXT,
    year INTEGER,
    abstract TEXT,
    available INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_ev_run ON evidence(run_id);

-- Links one hypothesis claim to one supporting evidence row, classified by
-- the four-state citation model in app/citations.py (verified/partial/
-- unsupported/unavailable).
CREATE TABLE IF NOT EXISTS citations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    hypothesis_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    claim TEXT NOT NULL,
    -- verified | partial | unsupported | unavailable
    state TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
    FOREIGN KEY (hypothesis_id) REFERENCES hypotheses(id) ON DELETE CASCADE,
    FOREIGN KEY (evidence_id) REFERENCES evidence(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cit_hyp ON citations(hypothesis_id);

-- Reviewer critiques and scores for a hypothesis; one row per reviewing
-- agent pass (reflection, review, meta_review), never updated in place.
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    hypothesis_id TEXT NOT NULL,
    reviewer_agent TEXT NOT NULL,    -- 'reflection' | 'review' | 'meta_review'
    summary TEXT NOT NULL,
    critique TEXT NOT NULL,
    novelty REAL,
    plausibility REAL,
    testability REAL,
    overall REAL,
    created_at REAL NOT NULL,
    FOREIGN KEY (hypothesis_id) REFERENCES hypotheses(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_rv_hyp ON reviews(hypothesis_id);
CREATE INDEX IF NOT EXISTS idx_rv_run ON reviews(run_id);

-- One row per pairwise tournament match. Elo before/after snapshots are
-- denormalized here so match history stays reconstructable even though
-- hypothesis_state.elo_rating keeps moving forward.
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    iteration INTEGER NOT NULL,
    winner_id TEXT NOT NULL,
    loser_id TEXT NOT NULL,
    winner_elo_before INTEGER NOT NULL,
    winner_elo_after INTEGER NOT NULL,
    loser_elo_before INTEGER NOT NULL,
    loser_elo_after INTEGER NOT NULL,
    rationale TEXT,
    -- decisiveness class: upset|decisive|clear|narrow
    tier TEXT,
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_match_run ON matches(run_id);

-- Safety-gate outcomes at the intake and final-output checkpoints (see
-- app/safety.py); one row per gate invocation, kept for audit purposes.
CREATE TABLE IF NOT EXISTS safety_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL,             -- 'intake' | 'final'
    decision TEXT NOT NULL,          -- 'allow' | 'redact' | 'block'
    reason TEXT,
    matches_json TEXT,
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);

-- Rendered report snapshots for a run. Multiple rows may accumulate (a
-- report can be regenerated); get_latest_report picks the newest by
-- created_at, so older rows are kept only as history.
CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    -- structured report (Overview, Ideas, Tournament, Citations, Safety)
    payload_json TEXT NOT NULL,
    markdown_path TEXT,
    -- full markdown stored in DB for durability across restarts
    markdown_text TEXT,
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_reports_run ON reports(run_id);

-- Chat-style messages for a run: user steering requests and Q&A exchanges.
-- `kind` distinguishes 'steering' (consumed by the workflow, then marked
-- applied) from 'qa' (answered inline, never marked applied).
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL,
    sender     TEXT NOT NULL,
    content    TEXT NOT NULL,
    kind       TEXT NOT NULL,
    created_at REAL NOT NULL,
    applied    INTEGER NOT NULL DEFAULT 0,
    meta_json  TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_run ON messages(run_id, id);

-- Durable workflow checkpoints (Milestone 4). One row per saved checkpoint;
-- get_latest_checkpoint reads the newest by seq. `state_json` is the versioned
-- checkpoint envelope (curated workflow state + provider-specific resume data),
-- `last_event_seq` is the high-water mark a resumed run assigns new event seqs
-- above (idempotent replay), and `schema_version` gates fail-closed restore.
CREATE TABLE IF NOT EXISTS checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,            -- per-run monotonic checkpoint sequence
    stage TEXT NOT NULL,             -- provider stage/boundary label
    schema_version INTEGER NOT NULL,
    last_event_seq INTEGER NOT NULL,
    state_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_ckpt_run_seq ON checkpoints(run_id, seq DESC);

-- Final per-run execution metrics (LLM calls, phase timings). One row per
-- run, upserted at finalize; a resumed run that finalizes again replaces it.
CREATE TABLE IF NOT EXISTS run_metrics (
    run_id TEXT PRIMARY KEY,
    metrics_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);

-- Claim-level entailment graph (Milestone 5). One row per atomic claim of a
-- hypothesis, with its assessed entailment label against retrieved evidence and
-- the exact supporting/contradicting passages that drove the verdict. This is
-- the claim-evidence graph the publication gate reads; it is distinct from the
-- document-level four-state `citations` table.
CREATE TABLE IF NOT EXISTS claim_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    hypothesis_id TEXT NOT NULL,
    claim TEXT NOT NULL,
    -- supports | contradicts | insufficient
    label TEXT NOT NULL,
    supporting_json TEXT,            -- JSON list of supporting passages
    contradicting_json TEXT,         -- JSON list of contradicting passages
    assessor TEXT NOT NULL,          -- provenance id of the entailment assessor
    created_at REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
    FOREIGN KEY (hypothesis_id) REFERENCES hypotheses(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_claim_ev_hyp ON claim_evidence(hypothesis_id);
"""
