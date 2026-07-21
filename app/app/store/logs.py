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

import logging
import sqlite3
import time
from collections.abc import Sequence
from typing import Any

from app.store.db import _use_conn

# Noise-logger records below this level are hidden when a noise filter
# is applied; warnings and errors always surface regardless of source.
NOISE_VISIBLE_LEVELNO = logging.WARNING


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
    client_id: str | None = None,
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
        client_id: Owning client for records ingested from a UI; None for
            server-side records, which only operators may read.
        created_at: Record timestamp; defaults to now.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse.

    Returns:
        The inserted row's id.
    """
    with _use_conn(conn, db_path) as c:
        cur = c.execute(
            "INSERT INTO app_logs (created_at, level, levelno, logger, "
            "message, run_id, exc_text, client_id) VALUES (?,?,?,?,?,?,?,?)",
            (
                created_at if created_at is not None else time.time(),
                level,
                levelno,
                logger_name,
                message,
                run_id,
                exc_text,
                client_id,
            ),
        )
        return int(cur.lastrowid or 0)


def _log_filters(
    *,
    after_id: int,
    min_levelno: int,
    run_id: str | None,
    contains: str | None,
    noise_loggers: Sequence[str] | None,
    scope_client_id: str | None = None,
) -> tuple[str, list[Any]]:
    """Build the shared WHERE clause and parameters for log queries."""
    where = ["id > ?", "levelno >= ?"]
    params: list[Any] = [after_id, min_levelno]
    if run_id is not None:
        where.append("run_id = ?")
        params.append(run_id)
    if contains:
        where.append("message LIKE ? ESCAPE '\\'")
        params.append(f"%{_escape_like(contains)}%")
    if noise_loggers:
        # Hide sub-WARNING records whose logger starts with any noise
        # prefix; WARNING+ from those loggers still matches.
        likes = " OR ".join(["logger LIKE ? ESCAPE '\\'"] * len(noise_loggers))
        where.append(f"NOT (levelno < ? AND ({likes}))")
        params.append(NOISE_VISIBLE_LEVELNO)
        params.extend(f"{_escape_like(name)}%" for name in noise_loggers)
    if scope_client_id is not None:
        # A client sees records it submitted plus records belonging to
        # runs it owns; un-owned server records stay operator-only.
        where.append(
            "(client_id = ? OR run_id IN "
            "(SELECT id FROM runs WHERE client_id = ?))"
        )
        params.extend([scope_client_id, scope_client_id])
    return " AND ".join(where), params


def list_logs(
    *,
    after_id: int = 0,
    min_levelno: int = 0,
    run_id: str | None = None,
    contains: str | None = None,
    noise_loggers: Sequence[str] | None = None,
    scope_client_id: str | None = None,
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
        noise_loggers: Logger-name prefixes whose sub-WARNING records are
            hidden; None disables the filter.
        scope_client_id: Restrict to one client's own records; None reads
            app-wide (operators only).
        limit: Maximum rows returned.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse.
    """
    where, params = _log_filters(
        after_id=after_id,
        min_levelno=min_levelno,
        run_id=run_id,
        contains=contains,
        noise_loggers=noise_loggers,
        scope_client_id=scope_client_id,
    )
    params.append(limit)
    query = (
        "SELECT * FROM (SELECT * FROM app_logs WHERE "
        + where
        + " ORDER BY id DESC LIMIT ?) ORDER BY id ASC"
    )
    with _use_conn(conn, db_path) as c:
        rows = c.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def count_logs(
    *,
    min_levelno: int = 0,
    run_id: str | None = None,
    contains: str | None = None,
    noise_loggers: Sequence[str] | None = None,
    scope_client_id: str | None = None,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Count every row matching the filters, ignoring paging.

    Unlike :func:`list_logs` there is no ``after_id`` or ``limit``: this
    is the size of the whole matching set, so the UI can show a true
    total next to a capped window.

    Args:
        min_levelno: Minimum numeric level (e.g. ``logging.WARNING``).
        run_id: Only rows bound to this run.
        contains: Case-insensitive message substring filter.
        noise_loggers: Logger-name prefixes whose sub-WARNING records are
            hidden; None disables the filter.
        scope_client_id: Restrict to one client's own records; None reads
            app-wide (operators only).
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse.
    """
    where, params = _log_filters(
        after_id=0,
        min_levelno=min_levelno,
        run_id=run_id,
        contains=contains,
        noise_loggers=noise_loggers,
        scope_client_id=scope_client_id,
    )
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
            after_id=0,
            min_levelno=0,
            run_id=None,
            contains=None,
            noise_loggers=None,
            scope_client_id=scope_client_id,
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
