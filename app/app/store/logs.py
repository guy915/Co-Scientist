"""Append-only persisted application log records (``app_logs`` table).

Rows are written by the capture handler installed in
``app.logging_setup`` and read by the ``/api/logs`` endpoints. The table
is app-wide: ``run_id`` is NULL for records emitted outside any run
context, and there is deliberately no foreign key to ``runs`` so log
history survives run deletion. Retention is enforced by
:func:`prune_logs` rather than by trigger, keeping the write path a
single INSERT.

Every helper accepts ``db_path`` (override for the SQLite database path)
and ``conn`` (an open connection to reuse).
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.store.db import _use_conn

# Noise-logger records below this level are hidden when a noise filter
# is applied; warnings and errors always surface regardless of source.
NOISE_VISIBLE_LEVELNO = logging.WARNING


def _escape_like(text: str) -> str:
    """Escape LIKE wildcards so a filter matches them literally."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass(frozen=True)
class NewLogRecord:
    """One log record to persist, mirroring the app_logs row.

    ``levelno`` is kept alongside the level name for range filtering;
    ``exc_text`` carries pre-formatted traceback text when one was
    attached; ``client_id`` is the owning client for records ingested
    from a UI (None for server-side records, which only operators may
    read); ``created_at`` defaults to now when None.
    """

    level: str
    levelno: int
    logger_name: str
    message: str
    run_id: str | None = None
    exc_text: str | None = None
    client_id: str | None = None
    created_at: float | None = None


def _insert_log_row(
    conn: sqlite3.Connection, record: NewLogRecord, created_at: float
) -> int:
    """Insert one log row on an open connection and return its row id."""
    cur = conn.execute(
        "INSERT INTO app_logs (created_at, level, levelno, logger, "
        "message, run_id, exc_text, client_id) VALUES (?,?,?,?,?,?,?,?)",
        (
            created_at,
            record.level,
            record.levelno,
            record.logger_name,
            record.message,
            record.run_id,
            record.exc_text,
            record.client_id,
        ),
    )
    return int(cur.lastrowid or 0)


def append_log(
    record: NewLogRecord,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Persist one log record and return its row id.

    Args:
        record: The record to persist (see :class:`NewLogRecord`).
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse.

    Returns:
        The row id assigned to the persisted record.
    """
    created_at = record.created_at
    with _use_conn(conn, db_path) as c:
        return _insert_log_row(
            c, record, created_at if created_at is not None else time.time()
        )


@dataclass(frozen=True)
class LogFilters:
    """The filters narrowing a log query.

    Rows must have an id strictly above ``after_id`` and a level at or
    above ``min_levelno``. ``run_id`` and ``contains`` restrict to one run
    and to a message substring; ``noise_loggers`` lists logger-name
    prefixes whose sub-WARNING records are hidden (None disables), and
    ``scope_client_id`` restricts to one client's own records (None reads
    app-wide, operators only).
    """

    after_id: int = 0
    min_levelno: int = 0
    run_id: str | None = None
    contains: str | None = None
    noise_loggers: Sequence[str] | None = None
    scope_client_id: str | None = None


def _log_filters(filters: LogFilters) -> tuple[str, list[Any]]:
    """Build the shared WHERE clause and parameters for log queries."""
    where = ["id > ?", "levelno >= ?"]
    params: list[Any] = [filters.after_id, filters.min_levelno]
    if filters.run_id is not None:
        where.append("run_id = ?")
        params.append(filters.run_id)
    if filters.contains:
        where.append("message LIKE ? ESCAPE '\\'")
        params.append(f"%{_escape_like(filters.contains)}%")
    noise_loggers = filters.noise_loggers
    if noise_loggers:
        # Hide sub-WARNING records whose logger starts with any noise
        # prefix; WARNING+ from those loggers still matches.
        likes = " OR ".join(["logger LIKE ? ESCAPE '\\'"] * len(noise_loggers))
        where.append(f"NOT (levelno < ? AND ({likes}))")
        params.append(NOISE_VISIBLE_LEVELNO)
        params.extend(f"{_escape_like(name)}%" for name in noise_loggers)
    if filters.scope_client_id is not None:
        # A client sees records it submitted plus records belonging to
        # runs it owns; un-owned server records stay operator-only.
        where.append(
            "(client_id = ? OR run_id IN "
            "(SELECT id FROM runs WHERE client_id = ?))"
        )
        params.extend([filters.scope_client_id, filters.scope_client_id])
    return " AND ".join(where), params


def _fetch_log_page(
    conn: sqlite3.Connection, filters: LogFilters, limit: int
) -> list[dict[str, Any]]:
    """Run the filtered, newest-first-capped log query and return rows."""
    where, params = _log_filters(filters)
    params.append(limit)
    query = (
        "SELECT * FROM (SELECT * FROM app_logs WHERE "
        + where
        + " ORDER BY id DESC LIMIT ?) ORDER BY id ASC"
    )
    rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def list_logs(
    *,
    filters: LogFilters | None = None,
    limit: int = 200,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return matching log rows in ascending id order.

    The ``limit`` keeps the NEWEST matching rows (the useful tail), still
    returned oldest-first so callers can print them in order and resume
    with ``after_id`` set to the last row's id.

    Args:
        filters: Which rows to match (see :class:`LogFilters`); None
            matches every row.
        limit: Maximum number of rows to keep, newest first.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse.

    Returns:
        The matching rows as dicts, oldest first.
    """
    with _use_conn(conn, db_path) as c:
        return _fetch_log_page(c, filters or LogFilters(), limit)


def count_logs(
    *,
    filters: LogFilters | None = None,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Count every row matching the filters, ignoring the window cap.

    Unlike :func:`list_logs` there is no ``limit``: the count covers the
    whole matching set, so the UI can show a true total next to a capped
    window. ``after_id`` is honored like every other filter -- pass
    ``after_id=0`` for the whole-table count, or keep a poller's cursor
    to count only the rows it has not yet seen. The two are separate
    numbers, not one derivable from the other: rows below the cursor are
    deleted by retention pruning and by a scoped clear, so a difference
    taken against a stale whole-table count goes negative.

    Args:
        filters: Which rows to match (see :class:`LogFilters`); None
            matches every row.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse.

    Returns:
        The number of matching rows.
    """
    where, params = _log_filters(filters or LogFilters())
    query = "SELECT COUNT(*) AS n FROM app_logs WHERE " + where
    with _use_conn(conn, db_path) as c:
        row = c.execute(query, params).fetchone()
    return int(row["n"])


def prune_logs(
    *,
    max_rows: int,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Delete the oldest rows beyond ``max_rows`` and return the count."""
    with _use_conn(conn, db_path) as c:
        # Find the cutoff with a pure primary-key walk, then delete the
        # doomed range directly. The NOT IN anti-join this replaces
        # materialized the whole keep-set and scanned every surviving row
        # while holding the write lock, even when nothing needed deleting.
        row = c.execute(
            "SELECT id FROM app_logs ORDER BY id DESC LIMIT 1 OFFSET ?",
            (max_rows,),
        ).fetchone()
        if row is None:
            return 0
        cur = c.execute("DELETE FROM app_logs WHERE id <= ?", (row["id"],))
        return int(cur.rowcount or 0)


def clear_logs(
    *,
    scope_client_id: str | None = None,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Delete every persisted log row and return the deleted count.

    A clear is a fresh start: the AUTOINCREMENT sequence is reset so the
    next record gets id 1 and the id-numbered UI badge reads as a count
    again. Followers holding an ``after_id`` cursor detect the reset by
    ``last_id`` dropping below their cursor and start over from 0.
    """
    if scope_client_id is not None:
        # Scoped clears must not reset the shared id sequence, which
        # other clients' cursors and numbering depend on.
        where, params = _log_filters(
            LogFilters(scope_client_id=scope_client_id)
        )
        with _use_conn(conn, db_path) as c:
            cur = c.execute(f"DELETE FROM app_logs WHERE {where}", params)
            return int(cur.rowcount or 0)
    with _use_conn(conn, db_path) as c:
        cur = c.execute("DELETE FROM app_logs")
        c.execute("DELETE FROM sqlite_sequence WHERE name = 'app_logs'")
        return int(cur.rowcount or 0)


def latest_log_id(
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Return the highest log row id, or 0 for an empty table."""
    with _use_conn(conn, db_path) as c:
        row = c.execute("SELECT MAX(id) AS max_id FROM app_logs").fetchone()
    return int(row["max_id"] or 0)


def count_logs_for_run(
    run_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Count log rows bound to ``run_id``, for a run-deletion accounting.

    ``app_logs`` carries no foreign key to ``runs`` (log history survives
    run deletion by default), so a permanent deletion must count and clear
    this table itself rather than relying on ``ON DELETE CASCADE``.
    """
    with _use_conn(conn, db_path) as c:
        row = c.execute(
            "SELECT COUNT(*) AS n FROM app_logs WHERE run_id=?", (run_id,)
        ).fetchone()
    return int(row["n"])


def delete_logs_for_run(
    run_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Delete every log row bound to ``run_id`` and return the count.

    Scoped by ``run_id`` alone, like :func:`clear_logs`'s ``scope_client_id``
    branch: the shared ``id`` sequence and every other tenant's rows are
    left untouched.
    """
    with _use_conn(conn, db_path) as c:
        cur = c.execute("DELETE FROM app_logs WHERE run_id=?", (run_id,))
        return int(cur.rowcount or 0)
