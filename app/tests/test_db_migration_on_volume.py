"""Regression coverage for migrating a *populated* legacy-schema volume.

``app.store.db._init_schema`` runs the base ``_SCHEMA`` script (every
``CREATE TABLE``/``CREATE INDEX ... IF NOT EXISTS``) and then
``_run_migrations`` (idempotent ``ALTER TABLE ADD COLUMN`` plus backfills)
against every database on every process start -- fresh or already
populated. On a genuinely fresh database this is close to a no-op: the
current ``_SCHEMA`` already bakes in most historical migrations' columns
directly into the ``CREATE TABLE`` statements, so the column only needs
adding via ``ALTER`` on a database whose on-disk tables predate that.
The ordinary suite -- which always starts from ``isolated_db``, a brand
new file -- never exercises that case.

It is exactly the case that matters in production: a Railway volume is a
single on-disk file that has been through some prefix of the migration
history, never all of it retroactively. ``db.py``'s own comments document
the invariant this depends on -- an index built in ``_SCHEMA`` over a
column that only ``_run_migrations`` adds would abort ``executescript``
against a database that lacks the column yet, while a fresh database
(which gets the column straight from ``_SCHEMA``) sails through unaffected.
That asymmetry is exactly how a schema change can look safe locally (every
test starts fresh) and break the first migration against the deployed
volume. This module builds an "ancient" database by hand -- tables with
only the pre-migration columns, populated with rows a real old volume
would hold -- and asserts the current store starts against it cleanly and
the migrations do what they claim, using the two migrations ``db.py``
itself calls out as ordering-sensitive: ``app_logs.client_id`` (added,
then immediately indexed, in ``_run_migrations`` rather than ``_SCHEMA``
specifically to avoid this failure mode) and the ``runs`` table's
client-isolation purge plus ``llm_backend`` backfill.

Not a full replay of every ``_migrate_*`` function -- that would duplicate
the whole migration history as a second copy to keep in sync. Extend this
module's ancient-table fixtures when a new migration lands that shares the
same danger shape (a column added and then referenced by an index, a
default, or a backfill in the same or a later migration).
"""

from __future__ import annotations

import sqlite3

from app import store
from app.store import db as store_db


def _create_ancient_tables(conn: sqlite3.Connection) -> None:
    """Create ``runs``/``app_logs`` as they looked before recent migrations.

    Mirrors ``schema.py``'s current column list minus every column
    ``_run_migrations`` still adds via ``ALTER TABLE`` for these two
    tables, so this is exactly the shape a volume never yet migrated
    forward would present.
    """
    conn.executescript(
        """
        CREATE TABLE runs (
            id TEXT PRIMARY KEY,
            research_goal TEXT NOT NULL,
            profile TEXT NOT NULL,
            status TEXT NOT NULL,
            provider TEXT NOT NULL,
            config_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            completed_at REAL,
            error TEXT
        );
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
        """
    )


def _insert_ancient_run(
    conn: sqlite3.Connection, run_id: str, provider: str
) -> None:
    conn.execute(
        "INSERT INTO runs (id, research_goal, profile, status, provider, "
        "config_json, created_at, updated_at) "
        "VALUES (?, 'legacy goal', 'standard', 'completed', ?, '{}', 1, 1)",
        (run_id, provider),
    )


def test_migrating_a_pre_isolation_volume_purges_orphaned_runs(
    isolated_db: str,
) -> None:
    """A volume from before client isolation loses its unowned run rows.

    This is destructive by design (``_migrate_client_isolation``'s purge,
    documented in ``db.py``) -- unowned rows are invisible to every client
    once ownership exists, so keeping them serves no one. The point under
    test is that migrating this exact legacy shape does not raise, and
    ``app_logs`` -- which has no purge, only an added, indexed column --
    keeps its pre-existing row intact.
    """
    raw = sqlite3.connect(isolated_db)
    try:
        _create_ancient_tables(raw)
        _insert_ancient_run(raw, "legacy-run-1", "engine")
        raw.execute(
            "INSERT INTO app_logs (created_at, level, levelno, logger, "
            "message) VALUES (1, 'INFO', 20, 'app.test', 'legacy line')"
        )
        raw.commit()
    finally:
        raw.close()

    # Any store call establishes the connection and runs _init_schema.
    assert store.get_run("legacy-run-1", db_path=isolated_db) is None

    with store_db.connect(isolated_db) as conn:
        app_log_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(app_logs)")
        }
        assert "client_id" in app_log_cols
        indexes = {
            row[1] for row in conn.execute("PRAGMA index_list(app_logs)")
        }
        assert "idx_app_logs_client" in indexes
        rows = conn.execute(
            "SELECT message, client_id FROM app_logs"
        ).fetchall()
        assert [tuple(r) for r in rows] == [("legacy line", None)]


def test_migrating_a_client_isolated_volume_backfills_llm_backend(
    isolated_db: str,
) -> None:
    """A volume already carrying client_id still needs llm_backend backfilled.

    Simulates a volume that already went through client isolation (an
    earlier deploy) but predates the offline/real backend column -- so the
    purge above must not fire again (both rows survive) while the backfill
    still runs, keyed on each row's own provider.
    """
    raw = sqlite3.connect(isolated_db)
    try:
        _create_ancient_tables(raw)
        raw.execute(
            "ALTER TABLE runs ADD COLUMN client_id TEXT NOT NULL DEFAULT ''"
        )
        _insert_ancient_run(raw, "legacy-mock-run", "mock")
        _insert_ancient_run(raw, "legacy-engine-run", "engine")
        raw.execute(
            "UPDATE runs SET client_id = 'legacy-client' WHERE id IN "
            "('legacy-mock-run', 'legacy-engine-run')"
        )
        raw.commit()
    finally:
        raw.close()

    mock_run = store.get_run("legacy-mock-run", db_path=isolated_db)
    engine_run = store.get_run("legacy-engine-run", db_path=isolated_db)

    assert mock_run is not None and mock_run.llm_backend == "offline"
    assert engine_run is not None and engine_run.llm_backend == "real"


def test_migrating_a_volume_with_the_retired_feedback_table_drops_it(
    isolated_db: str,
) -> None:
    """A volume carrying the retired pilot-feedback table loses it cleanly.

    The current schema no longer creates ``feedback`` at all, so this is
    the one migration only a populated legacy volume exercises: build the
    table by hand, as an old deploy would still have it, and confirm the
    ``DROP TABLE IF EXISTS`` migration removes it without raising.
    """
    raw = sqlite3.connect(isolated_db)
    try:
        _create_ancient_tables(raw)
        raw.execute(
            "CREATE TABLE feedback (id INTEGER PRIMARY KEY, "
            "client_id TEXT NOT NULL, audience TEXT NOT NULL, "
            "category TEXT NOT NULL, message TEXT NOT NULL, "
            "created_at REAL NOT NULL)"
        )
        raw.execute(
            "INSERT INTO feedback (client_id, audience, category, message, "
            "created_at) VALUES ('c1', 'general', 'bug', 'old note', 1)"
        )
        raw.commit()
    finally:
        raw.close()

    # Any store call establishes the connection and runs _init_schema plus
    # _run_migrations, which is where the drop happens.
    assert store.get_run("does-not-exist", db_path=isolated_db) is None

    with store_db.connect(isolated_db) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "feedback" not in tables
