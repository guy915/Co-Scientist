"""Idempotent in-place schema migrations for the SQLite store.

Split out of ``app.store.db`` to keep that module within the size cap.
Holds every ``_migrate_*`` step plus the ``_add_column_if_missing``
primitive they share, run in order by
``_run_migrations`` against an already-``CREATE TABLE IF NOT EXISTS``'d
connection. Connection management, transactions, and the one-time schema
bootstrap that calls into here stay in ``app.store.db``. Every name is
re-exported from ``app.store.db``, so callers and monkeypatching tests
(e.g. ``store_db._run_migrations``) are unaffected.

Migrations are ordered and append-only: each one is safe to run against an
already-migrated database (idempotent), and the order recorded in
``_run_migrations`` is the history of this schema -- never reorder or
renumber an existing step.
"""

import logging
import sqlite3

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


def _migrate_client_isolation(conn: sqlite3.Connection) -> None:
    """Add client-id ownership columns and purge pre-isolation rows."""
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


def _migrate_run_and_report_columns(conn: sqlite3.Connection) -> None:
    """Add run title/backend columns and the durable report-text column."""
    # Short model-generated session title, distinct from research_goal.
    _add_column_if_missing(conn, "runs", "title", "TEXT")
    # Per-run LLM backend: 'offline' (deterministic router) or 'real'. Legacy
    # rows are backfilled from the provider -- the mock was always offline.
    if _add_column_if_missing(conn, "runs", "llm_backend", "TEXT"):
        conn.execute(
            "UPDATE runs SET llm_backend = "
            "CASE WHEN provider = 'mock' THEN 'offline' ELSE 'real' END"
        )
    # DB-durable copy of the rendered report, independent of the on-disk file.
    _add_column_if_missing(conn, "reports", "markdown_text", "TEXT")


def _migrate_interview_columns(conn: sqlite3.Connection) -> None:
    """Add the durable goal interview's own metadata columns."""
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


def _migrate_message_and_hypothesis_columns(
    conn: sqlite3.Connection,
) -> None:
    """Add message, hypothesis, review, and verification-state columns."""
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


def _migrate_match_and_safety_columns(conn: sqlite3.Connection) -> None:
    """Add claim-role, match-tier, and safety-decision columns."""
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


def _migrate_proximity_and_evidence_columns(
    conn: sqlite3.Connection,
) -> None:
    """Add proximity-edge timestamps and evidence-attachment metadata."""
    _add_column_if_missing(
        conn, "proximity_edges", "created_at", "REAL NOT NULL DEFAULT 0"
    )
    _add_column_if_missing(conn, "evidence", "mime_type", "TEXT")
    _add_column_if_missing(conn, "evidence", "sha256", "TEXT")
    _add_column_if_missing(conn, "evidence", "byte_size", "INTEGER")
    _add_column_if_missing(conn, "evidence", "document_version", "TEXT")
    _add_column_if_missing(conn, "evidence", "extraction_tool", "TEXT")


def _migrate_evidence_identity_columns(conn: sqlite3.Connection) -> None:
    """Add evidence identity/passage/retrieval-time columns (G12).

    ``doi``/``pmid`` are the canonical identifiers a live availability check
    dereferences; ``passage_text`` is the exact stored text a claim-evidence
    span's offsets index (title + abstract, materialized at insert time
    rather than reconstructed per read); ``retrieved_at`` is when the engine
    retrieved the article, distinct from ``created_at`` (the drain's insert
    time, which can trail retrieval by the rest of a run's duration).
    """
    _add_column_if_missing(conn, "evidence", "doi", "TEXT")
    _add_column_if_missing(conn, "evidence", "pmid", "TEXT")
    _add_column_if_missing(conn, "evidence", "passage_text", "TEXT")
    _add_column_if_missing(conn, "evidence", "retrieved_at", "REAL")


def _migrate_evidence_retrieval_scoring_columns(
    conn: sqlite3.Connection,
) -> None:
    """Add persisted hybrid-retrieval scoring columns to evidence (G5).

    ``retrieval_score`` combines the deterministic lexical heuristic with a
    model-judged relevance pass (see ``search_support.py``'s hybrid scorer);
    ``retrieval_rationale`` is the semantic pass's stated reason;
    ``retriever_version`` names and versions the algorithm that produced
    them, so a persisted score can always be traced to the method that made
    it.
    """
    _add_column_if_missing(conn, "evidence", "retrieval_score", "REAL")
    _add_column_if_missing(conn, "evidence", "retrieval_rationale", "TEXT")
    _add_column_if_missing(conn, "evidence", "retriever_version", "TEXT")


def _migrate_evidence_retrieval_call_id(conn: sqlite3.Connection) -> None:
    """Add the retrieval-provenance link to evidence.

    ``retrieval_call_id`` names the search that found a piece of evidence
    (``retrieval_calls.id``), which is the one fact this store never kept:
    a row recorded how well a source scored, never what was asked of it.
    Nullable, and NULL is a real state rather than a gap to backfill --
    an uploaded document and a directly fetched corpus paper have no
    search behind them, and neither does any run written before the
    deep-research capability existed.
    """
    _add_column_if_missing(conn, "evidence", "retrieval_call_id", "TEXT")


def _migrate_hypothesis_parent_ids(conn: sqlite3.Connection) -> None:
    """Add the multi-parent lineage column to hypotheses.

    Evolution's combination operator merges several parents into one child.
    ``parent_id`` keeps the primary parent so existing lineage consumers are
    unaffected; this column records the full parent list as a JSON array.
    Rows written before the column existed read back as NULL (single-parent
    lineage), which is the only state they could represent.
    """
    _add_column_if_missing(conn, "hypotheses", "parent_ids", "TEXT")


def _migrate_task_attempts_history(conn: sqlite3.Connection) -> None:
    """Add the per-failed-attempt history column to scientific_tasks.

    A volume created before this column existed has none, so
    ``store.tasks._decode`` must never see it missing -- the default
    backfills every pre-existing row to an empty history rather than
    NULL, which is what "no failures recorded yet" actually means for a
    row written before this migration ever ran.
    """
    _add_column_if_missing(
        conn, "scientific_tasks", "attempts_json", "TEXT NOT NULL DEFAULT '[]'"
    )
    # Nullable: NULL on a row that has never been leased under the new
    # code, and _try_lease_task sets it fresh on every claim thereafter.
    _add_column_if_missing(
        conn, "scientific_tasks", "attempt_started_at", "REAL"
    )


def _migrate_drop_feedback_table(conn: sqlite3.Connection) -> None:
    """Drop the retired pilot-feedback table.

    Idempotent (``IF EXISTS``): a database built from the current schema
    never created this table at all, and one built from an older schema
    drops it exactly once.
    """
    conn.execute("DROP TABLE IF EXISTS feedback")


def _migrate_hypothesis_scene_setting_columns(conn: sqlite3.Connection) -> None:
    """Add the published proposal's scene-setting columns (MO-6).

    Every published proposal opens with an Introduction and a Recent
    findings and related research section before the mechanism; a
    hypothesis row written before this carried neither.
    """
    _add_column_if_missing(conn, "hypotheses", "introduction", "TEXT")
    _add_column_if_missing(conn, "hypotheses", "recent_findings", "TEXT")


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Apply idempotent in-place schema migrations to an open connection."""
    _migrate_client_isolation(conn)
    _migrate_run_and_report_columns(conn)
    _migrate_interview_columns(conn)
    _migrate_message_and_hypothesis_columns(conn)
    _migrate_match_and_safety_columns(conn)
    _migrate_proximity_and_evidence_columns(conn)
    _migrate_hypothesis_parent_ids(conn)
    _migrate_evidence_identity_columns(conn)
    _migrate_evidence_retrieval_scoring_columns(conn)
    _migrate_evidence_retrieval_call_id(conn)
    _migrate_task_attempts_history(conn)
    _migrate_drop_feedback_table(conn)
    _migrate_hypothesis_scene_setting_columns(conn)
