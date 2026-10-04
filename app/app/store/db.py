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
    cols = {
        row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column in cols:
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
    logger.info("migration: added %s column to %s", column, table)
    return True


def _run_migrations(conn: sqlite3.Connection) -> None:
    # Legacy ownerless logs fail closed: only operators may read them.
    _add_column_if_missing(conn, "app_logs", "client_id", "TEXT")
    # Indexes on added columns must follow their ALTER TABLE migrations, not the
    # initial schema script.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_app_logs_client "
        "ON app_logs(client_id, id)"
    )
    if _add_column_if_missing(
        conn, "runs", "client_id", "TEXT NOT NULL DEFAULT ''"
    ):
        # Purge incompatible snapshots only when introducing ownership; doing it
        # on every startup would erase retained legacy records.
        conn.execute("DELETE FROM runs WHERE client_id = ''")
        logger.info("migration: purged pre-client-isolation runs")

    _add_column_if_missing(conn, "runs", "title", "TEXT")
    # Legacy and offline rows legitimately have NULL restatements;
    # background generation fills only real-backed runs.
    _add_column_if_missing(conn, "runs", "goal_restatement", "TEXT")
    # The retired mock provider was always offline; preserve that fact when
    # backfilling historical provenance.
    if _add_column_if_missing(conn, "runs", "llm_backend", "TEXT"):
        conn.execute(
            "UPDATE runs SET llm_backend = "
            "CASE WHEN provider = 'mock' THEN 'offline' ELSE 'real' END"
        )
    _add_column_if_missing(conn, "reports", "markdown_text", "TEXT")
    # Keep the nullable legacy overview column until verified production export
    # and reset.
    _add_column_if_missing(conn, "reports", "markdown_text_ranking", "TEXT")

    _add_column_if_missing(
        conn,
        "interviews",
        "execution_policy",
        "TEXT NOT NULL DEFAULT 'standard'",
    )
    # Persist emitted reasoning so resumed interview context matches what the
    # scientist already saw.
    _add_column_if_missing(conn, "interview_turns", "reasoning", "TEXT")
    # Legacy turns lack fallback provenance; newer turns distinguish scripted
    # recovery from model output.
    _add_column_if_missing(
        conn, "interview_turns", "fallback", "INTEGER NOT NULL DEFAULT 0"
    )
    # NULL questions preserve legacy turns that offered no structured choices.
    _add_column_if_missing(conn, "interview_turns", "questions_json", "TEXT")

    _add_column_if_missing(
        conn,
        "runs",
        "execution_policy",
        "TEXT NOT NULL DEFAULT 'standard'",
    )

    # Free-use slots have no run FK: deletion must not refund the allowance.
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

    _add_column_if_missing(conn, "messages", "meta_json", "TEXT")
    _add_column_if_missing(conn, "hypotheses", "category", "TEXT")
    _add_column_if_missing(conn, "hypotheses", "author", "TEXT")
    # Persist scientist author and verdict through checkpoint round-trips
    # without turning human input into anonymous agent reviews.
    _add_column_if_missing(conn, "reviews", "author", "TEXT")
    _add_column_if_missing(conn, "reviews", "verdict", "TEXT")
    # Verification verdict is independent of publication status; legacy NULL
    # means unknown, not a negative result.
    _add_column_if_missing(
        conn, "hypothesis_state", "verification_verdict", "TEXT"
    )

    # Speculative proposals and categorical claims retain distinct entailment
    # roles.
    _add_column_if_missing(
        conn,
        "claim_evidence",
        "claim_role",
        "TEXT NOT NULL DEFAULT 'categorical'",
    )
    _add_column_if_missing(conn, "matches", "tier", "TEXT")
    # Legacy matches predate multi-turn debates and retain depth one.
    _add_column_if_missing(
        conn, "matches", "debate_turns", "INTEGER NOT NULL DEFAULT 1"
    )
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

    _add_column_if_missing(
        conn, "proximity_edges", "created_at", "REAL NOT NULL DEFAULT 0"
    )
    _add_column_if_missing(conn, "evidence", "mime_type", "TEXT")
    _add_column_if_missing(conn, "evidence", "sha256", "TEXT")
    _add_column_if_missing(conn, "evidence", "byte_size", "INTEGER")
    _add_column_if_missing(conn, "evidence", "document_version", "TEXT")
    _add_column_if_missing(conn, "evidence", "extraction_tool", "TEXT")

    _add_column_if_missing(conn, "hypotheses", "parent_ids", "TEXT")

    _add_column_if_missing(conn, "evidence", "doi", "TEXT")
    _add_column_if_missing(conn, "evidence", "pmid", "TEXT")
    _add_column_if_missing(conn, "evidence", "passage_text", "TEXT")
    _add_column_if_missing(conn, "evidence", "retrieved_at", "REAL")

    _add_column_if_missing(conn, "evidence", "retrieval_score", "REAL")
    _add_column_if_missing(conn, "evidence", "retrieval_rationale", "TEXT")
    _add_column_if_missing(conn, "evidence", "retriever_version", "TEXT")

    _add_column_if_missing(conn, "evidence", "retrieval_call_id", "TEXT")

    _add_column_if_missing(
        conn, "scientific_tasks", "attempts_json", "TEXT NOT NULL DEFAULT '[]'"
    )
    # Legacy tasks have no attempt start timestamp until a fresh claim.
    _add_column_if_missing(
        conn, "scientific_tasks", "attempt_started_at", "REAL"
    )

    conn.execute("DROP TABLE IF EXISTS feedback")

    _add_column_if_missing(conn, "hypotheses", "introduction", "TEXT")
    _add_column_if_missing(conn, "hypotheses", "recent_findings", "TEXT")

    _add_column_if_missing(conn, "hypotheses", "safety_and_toxicity", "TEXT")

    _add_column_if_missing(conn, "reviews", "detail_json", "TEXT")

    _add_column_if_missing(conn, "evidence", "retracted", "INTEGER")

    _add_column_if_missing(conn, "evidence", "source_type", "TEXT")

    _add_column_if_missing(conn, "scientific_tasks", "available_at", "REAL")

    _add_column_if_missing(conn, "matches", "debate_transcript", "TEXT")

    _add_column_if_missing(conn, "messages", "applied_at", "REAL")
    _add_column_if_missing(conn, "messages", "applied_decision", "TEXT")

    _add_column_if_missing(conn, "hypotheses", "creation_iteration", "INTEGER")

    # Absent verification provenance stays explicitly unknown on legacy
    # assessments.
    _add_column_if_missing(
        conn,
        "claim_evidence",
        "verification_method",
        "TEXT NOT NULL DEFAULT 'legacy_unknown'",
    )

    # Keep outcome-action child lineage readable on databases predating this
    # column.
    _add_column_if_missing(
        conn,
        "outcome_refinement_actions",
        "child_hypothesis_id",
        "TEXT",
    )


_lock = threading.RLock()
_initialized: set[str] = set()


def _now() -> float:
    return time.time()


def default_db_path() -> str | None:
    return os.getenv("COSCIENTIST_DB_PATH") or None


def _resolved_db_path(path: str | None = None) -> str:
    # Resolve the path at call time so explicit environment overrides apply
    # without reimporting this module.
    return path or default_db_path() or "./coscientist.db"


def _open_raw_connection(db_path: str) -> sqlite3.Connection:
    # Once initialized, hot reads need no parent-directory syscall.
    if db_path not in _initialized:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    # Autocommit permits explicit transaction ownership; connections can cross
    # the asynchronous caller's thread boundary.
    conn = sqlite3.connect(
        db_path, timeout=30, isolation_level=None, check_same_thread=False
    )
    conn.row_factory = sqlite3.Row  # Rows behave like dicts: row["col"].
    # WAL NORMAL avoids per-commit fsync saturation; checkpoints sync
    # durability, with recent transactions vulnerable only to OS failure.
    conn.execute("PRAGMA synchronous=NORMAL")
    # Foreign-key enforcement is per connection, not file-wide; otherwise
    # deletes silently leave orphan rows.
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _ensure_schema_initialized(db_path: str, conn: sqlite3.Connection) -> None:
    """Serialize first-use schema setup, but keep initialized hot paths free
    of the setup lock.
    """
    # Serialize initial schema setup without locking every initialized
    # connection.
    if db_path not in _initialized:
        with _lock:
            if db_path not in _initialized:
                _init_schema(conn)
                _initialized.add(db_path)


@contextlib.contextmanager
def connect(
    path: str | None = None,
) -> Generator[sqlite3.Connection, None, None]:
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
    """Batch related writes under one commit and fsync; never hold this
    writer lock over network I/O.
    """
    with connect(path) as conn:
        # Acquire the writer at BEGIN to avoid a mid-transaction reader-to-
        # writer upgrade deadlock.
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
    if conn is not None:
        yield conn
    else:
        with connect(path) as fresh:
            yield fresh


def _init_schema(conn: sqlite3.Connection) -> None:
    # CREATE IF NOT EXISTS cannot add columns; migrations must precede indexes
    # referencing those columns.
    conn.executescript(_SCHEMA)
    conn.execute("PRAGMA journal_mode=WAL")  # Readers do not block writers.
    _run_migrations(conn)


def checkpoint_wal(db_path: str | None = None) -> None:
    """Graceful shutdown flushes WAL transactions into the main database
    file for file-only copies.
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
