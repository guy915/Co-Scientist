"""SQLite connection management, schema creation, and migrations.

Owns the connection/transaction context managers, the WAL and pragma
setup, and the one-time schema bootstrap; the CREATE TABLE script itself
lives in ``app.store.schema`` and the idempotent in-place migration steps
live in ``app.store.db_migrations``. The other ``app.store`` submodules
build on the primitives defined here instead of calling
``sqlite3.connect`` directly.
"""

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

from app.store.db_migrations import _run_migrations as _run_migrations
from app.store.schema import SCHEMA as _SCHEMA

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
