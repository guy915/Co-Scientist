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
