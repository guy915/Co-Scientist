"""Tests for the upgrade path against databases created by older builds.

The rest of the suite runs against freshly created databases, where every
table is built from the current ``_SCHEMA`` and so already carries the
columns the migrations add. That shape cannot catch ordering bugs between
``_SCHEMA`` and ``_run_migrations``. These tests start from an *old-shape*
database instead, which is what a deployed volume actually holds.
"""

from __future__ import annotations

import sqlite3

from app.store import db

# The app_logs table exactly as builds before the client-isolation change
# created it: no client_id column, and no index over it.
_OLD_APP_LOGS = """
CREATE TABLE app_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    level TEXT NOT NULL,
    levelno INTEGER NOT NULL,
    logger TEXT NOT NULL,
    message TEXT NOT NULL,
    run_id TEXT,
    exc_text TEXT
);
CREATE INDEX idx_app_logs_run ON app_logs(run_id, id);
"""


def _old_shape_db(tmp_path: object) -> str:
    """Create a database holding a pre-client-isolation app_logs table."""
    path = str(tmp_path / "old.db")  # type: ignore[operator]
    conn = sqlite3.connect(path)
    conn.executescript(_OLD_APP_LOGS)
    conn.commit()
    conn.close()
    return path


def _columns(path: str, table: str) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def _indexes(path: str, table: str) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA index_list({table})")}
    finally:
        conn.close()


def test_connect_upgrades_an_old_app_logs_table(tmp_path: object) -> None:
    """Opening a pre-client-isolation database migrates it instead of raising.

    A schema-level index over a migration-added column would abort
    ``executescript`` here, leaving the path uninitialized and every later
    connect failing the same way -- i.e. the server would not start.
    """
    path = _old_shape_db(tmp_path)

    with db.connect(path) as conn:
        conn.execute("SELECT client_id FROM app_logs").fetchall()

    assert "client_id" in _columns(path, "app_logs")
    # The index must still end up present, not merely be dropped to dodge
    # the ordering problem.
    assert "idx_app_logs_client" in _indexes(path, "app_logs")


def test_connect_is_idempotent_over_an_upgraded_database(
    tmp_path: object,
) -> None:
    """A second process opening the same file re-runs migrations cleanly."""
    path = _old_shape_db(tmp_path)
    with db.connect(path):
        pass
    # Drop the module-level cache so this connect redoes the init work a
    # fresh process would, rather than skipping it.
    db._initialized.discard(path)

    with db.connect(path) as conn:
        conn.execute("SELECT client_id FROM app_logs").fetchall()

    assert "idx_app_logs_client" in _indexes(path, "app_logs")


# The interview_turns table exactly as builds before the fallback-provenance
# change created it: no fallback column.
_OLD_INTERVIEW_TURNS = """
CREATE TABLE interview_turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interview_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    reasoning TEXT,
    created_at REAL NOT NULL
);
"""


def test_connect_upgrades_old_interview_turns_table(
    tmp_path: object,
) -> None:
    """Turns written before the fallback marker open unmarked, not broken.

    A deployed volume holds transcripts whose turns predate the marker; the
    upgrade must add the column and read those rows as model-driven (the
    default), since a missing marker can only mean "written before the
    signal existed", never "known to be scripted".
    """
    path = str(tmp_path / "old_turns.db")  # type: ignore[operator]
    conn = sqlite3.connect(path)
    conn.executescript(_OLD_INTERVIEW_TURNS)
    conn.execute(
        "INSERT INTO interview_turns (interview_id, role, content, "
        "created_at) VALUES ('iv-1', 'agent', 'Which focus area?', 1.0)"
    )
    conn.commit()
    conn.close()

    with db.connect(path) as conn:
        rows = conn.execute("SELECT fallback FROM interview_turns").fetchall()

    assert "fallback" in _columns(path, "interview_turns")
    assert [row[0] for row in rows] == [0]


# The hypotheses table exactly as builds before the multi-parent lineage
# change created it: no parent_ids column.
_OLD_HYPOTHESES = """
CREATE TABLE hypotheses (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    parent_id TEXT,
    generation INTEGER NOT NULL DEFAULT 0,
    category TEXT,
    title TEXT NOT NULL,
    statement TEXT NOT NULL,
    mechanism TEXT,
    expected_effect TEXT,
    experimental_context TEXT,
    created_by_agent TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""


def test_connect_upgrades_old_hypotheses_table(tmp_path: object) -> None:
    """Hypotheses written before multi-parent lineage open with NULL parents.

    A deployed volume holds hypotheses predating the combination operator;
    the upgrade adds the column and those rows read back as NULL parent_ids,
    since a missing column can only mean single-parent lineage.
    """
    path = str(tmp_path / "old_hyps.db")  # type: ignore[operator]
    conn = sqlite3.connect(path)
    conn.executescript(_OLD_HYPOTHESES)
    conn.execute(
        "INSERT INTO hypotheses (id, run_id, title, statement, "
        "created_by_agent, created_at) "
        "VALUES ('h1', 'r1', 'T', 'S', 'generation', 1.0)"
    )
    conn.commit()
    conn.close()

    with db.connect(path) as conn:
        rows = conn.execute("SELECT parent_ids FROM hypotheses").fetchall()

    assert "parent_ids" in _columns(path, "hypotheses")
    assert [row[0] for row in rows] == [None]


def test_connect_adds_scene_setting_columns_to_old_hypotheses(
    tmp_path: object,
) -> None:
    """A pre-MO-6 hypotheses table gains introduction/recent_findings.

    A deployed volume holds hypotheses written before the published
    proposal's scene-setting sections were carried at all; those rows
    read back with NULL in both new columns rather than failing the
    upgrade.
    """
    path = str(tmp_path / "old_hyps_scene.db")  # type: ignore[operator]
    conn = sqlite3.connect(path)
    conn.executescript(_OLD_HYPOTHESES)
    conn.execute(
        "INSERT INTO hypotheses (id, run_id, title, statement, "
        "created_by_agent, created_at) "
        "VALUES ('h1', 'r1', 'T', 'S', 'generation', 1.0)"
    )
    conn.commit()
    conn.close()

    with db.connect(path) as conn:
        rows = conn.execute(
            "SELECT introduction, recent_findings FROM hypotheses"
        ).fetchall()

    columns = _columns(path, "hypotheses")
    assert {"introduction", "recent_findings"} <= columns
    assert [tuple(row) for row in rows] == [(None, None)]


def test_connect_adds_safety_and_toxicity_column_to_old_hypotheses(
    tmp_path: object,
) -> None:
    """A pre-MO-10 hypotheses table gains safety_and_toxicity.

    A deployed volume holds hypotheses written before the proposer's own
    safety-and-toxicity assessment was carried at all; those rows read
    back with NULL rather than failing the upgrade.
    """
    path = str(tmp_path / "old_hyps_safety.db")  # type: ignore[operator]
    conn = sqlite3.connect(path)
    conn.executescript(_OLD_HYPOTHESES)
    conn.execute(
        "INSERT INTO hypotheses (id, run_id, title, statement, "
        "created_by_agent, created_at) "
        "VALUES ('h1', 'r1', 'T', 'S', 'generation', 1.0)"
    )
    conn.commit()
    conn.close()

    with db.connect(path) as conn:
        rows = conn.execute(
            "SELECT safety_and_toxicity FROM hypotheses"
        ).fetchall()

    assert "safety_and_toxicity" in _columns(path, "hypotheses")
    assert [row[0] for row in rows] == [None]


# The evidence table exactly as builds before retrieval provenance created
# it: scoring columns present, but nothing naming the search behind a row.
_OLD_EVIDENCE = """
CREATE TABLE evidence (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    title TEXT NOT NULL,
    source TEXT,
    url TEXT,
    authors_json TEXT,
    year INTEGER,
    abstract TEXT,
    available INTEGER NOT NULL DEFAULT 1,
    mime_type TEXT,
    sha256 TEXT,
    byte_size INTEGER,
    document_version TEXT,
    extraction_tool TEXT,
    doi TEXT,
    pmid TEXT,
    passage_text TEXT,
    retrieved_at REAL,
    retrieval_score REAL,
    retrieval_rationale TEXT,
    retriever_version TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX idx_ev_run ON evidence(run_id);
"""


def test_connect_upgrades_evidence_for_retrieval_provenance(
    tmp_path: object,
) -> None:
    """Evidence written before provenance opens with a NULL search link.

    The column is added by migration rather than by ``_SCHEMA``, whose
    ``CREATE TABLE IF NOT EXISTS`` is a no-op against the table a deployed
    volume already holds. Existing rows read back NULL, which is the only
    state they could represent: nothing recorded what was asked.
    """
    path = str(tmp_path / "old_evidence.db")  # type: ignore[operator]
    conn = sqlite3.connect(path)
    conn.executescript(_OLD_EVIDENCE)
    conn.execute(
        "INSERT INTO evidence (id, run_id, title, created_at) "
        "VALUES ('e1', 'r1', 'A paper', 1.0)"
    )
    conn.commit()
    conn.close()

    with db.connect(path) as conn:
        rows = conn.execute("SELECT retrieval_call_id FROM evidence").fetchall()
        # The new table arrives on the same open, from _SCHEMA.
        conn.execute("SELECT COUNT(*) FROM retrieval_calls").fetchone()

    assert "retrieval_call_id" in _columns(path, "evidence")
    assert [row[0] for row in rows] == [None]
