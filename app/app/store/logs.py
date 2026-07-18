"""Append-only persisted application log records (``app_logs`` table).

Rows are written by the capture handler installed in
``app.logging_setup`` and read by the ``/api/logs`` endpoints. The table
is app-wide: ``run_id`` is NULL for records emitted outside any run
context, and there is deliberately no foreign key to ``runs`` so log
history survives run deletion. Retention is enforced by
:func:`prune_logs` rather than by trigger, keeping the write path a
single INSERT.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any

from app.store.db import _use_conn


def _escape_like(text: str) -> str:
    """Escape LIKE wildcards so a filter matches them literally."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def append_log(
    *,
    level: str,
    levelno: int,
    logger_name: str,
    message: str,
    run_id: str | None = None,
    exc_text: str | None = None,
    created_at: float | None = None,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Persist one log record and return its row id.

    Args:
        level: Level name (e.g. ``"INFO"``).
        levelno: Numeric level, kept for range filtering.
        logger_name: Dotted name of the emitting logger.
        message: The fully formatted log message.
        run_id: Run the record belongs to, if it was run-scoped.
        exc_text: Pre-formatted traceback text, when one was attached.
        created_at: Record timestamp; defaults to now.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse.

    Returns:
        The inserted row's id.
    """
    with _use_conn(conn, db_path) as c:
        cur = c.execute(
            "INSERT INTO app_logs (created_at, level, levelno, logger, "
            "message, run_id, exc_text) VALUES (?,?,?,?,?,?,?)",
            (
                created_at if created_at is not None else time.time(),
                level,
                levelno,
                logger_name,
                message,
                run_id,
                exc_text,
            ),
        )
        return int(cur.lastrowid or 0)


def list_logs(
    *,
    after_id: int = 0,
    min_levelno: int = 0,
    run_id: str | None = None,
    contains: str | None = None,
    limit: int = 200,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return matching log rows in ascending id order.

    The ``limit`` keeps the NEWEST matching rows (the useful tail), still
    returned oldest-first so callers can print them in order and resume
    with ``after_id`` set to the last row's id.

    Args:
        after_id: Only rows with an id strictly greater than this.
        min_levelno: Minimum numeric level (e.g. ``logging.WARNING``).
        run_id: Only rows bound to this run.
        contains: Case-insensitive message substring filter.
        limit: Maximum rows returned.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse.
    """
    where = ["id > ?", "levelno >= ?"]
    params: list[Any] = [after_id, min_levelno]
    if run_id is not None:
        where.append("run_id = ?")
        params.append(run_id)
    if contains:
        where.append("message LIKE ? ESCAPE '\\'")
        params.append(f"%{_escape_like(contains)}%")
    params.append(limit)
    query = (
        "SELECT * FROM (SELECT * FROM app_logs WHERE "
        + " AND ".join(where)
        + " ORDER BY id DESC LIMIT ?) ORDER BY id ASC"
    )
    with _use_conn(conn, db_path) as c:
        rows = c.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def prune_logs(
    *,
    max_rows: int,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Delete the oldest rows beyond ``max_rows`` and return the count."""
    with _use_conn(conn, db_path) as c:
        cur = c.execute(
            "DELETE FROM app_logs WHERE id NOT IN "
            "(SELECT id FROM app_logs ORDER BY id DESC LIMIT ?)",
            (max_rows,),
        )
        return int(cur.rowcount or 0)


def clear_logs(
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Delete every persisted log row and return the deleted count.

    Ids stay monotonic across a clear (AUTOINCREMENT), so pollers'
    ``after_id`` cursors and the UI's consecutive numbering never regress.
    """
    with _use_conn(conn, db_path) as c:
        cur = c.execute("DELETE FROM app_logs")
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
