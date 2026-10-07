from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from co_scientist.platform.db import connect, use_conn


@dataclass(frozen=True)
class NewLogRecord:
    level: str
    levelno: int
    logger_name: str
    message: str
    run_id: str | None = None
    exc_text: str | None = None
    client_id: str | None = None
    created_at: float | None = None


def append_log(
    record: NewLogRecord,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    created_at = record.created_at
    with use_conn(conn, db_path) as active:
        cursor = active.execute(
            "INSERT INTO app_logs (created_at, level, levelno, logger, "
            "message, run_id, exc_text, client_id) VALUES (?,?,?,?,?,?,?,?)",
            (
                created_at if created_at is not None else time.time(),
                record.level,
                record.levelno,
                record.logger_name,
                record.message,
                record.run_id,
                record.exc_text,
                record.client_id,
            ),
        )
    return int(cursor.lastrowid or 0)


@dataclass(frozen=True)
class LogFilters:
    after_id: int = 0
    min_levelno: int = 0
    scope_client_id: str | None = None


def _log_filters(filters: LogFilters) -> tuple[str, list[Any]]:
    where = ["id > ?", "levelno >= ?"]
    params: list[Any] = [filters.after_id, filters.min_levelno]
    if filters.scope_client_id is not None:
        # Clients see their submitted logs and owned-run logs; ownerless server
        # records remain operator-only.
        where.append("(client_id = ? OR run_id IN (SELECT id FROM runs WHERE client_id = ?))")
        params.extend([filters.scope_client_id, filters.scope_client_id])
    return " AND ".join(where), params


def _fetch_log_page(
    conn: sqlite3.Connection, filters: LogFilters, limit: int
) -> list[dict[str, Any]]:
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
    """Keep the newest capped window but return it chronologically so the
    last row is the polling cursor.
    """
    with use_conn(conn, db_path) as c:
        return _fetch_log_page(c, filters or LogFilters(), limit)


def count_logs(*, filters: LogFilters | None = None, conn: sqlite3.Connection | None = None) -> int:
    """Retention and scoped clears invalidate arithmetic against stale
    totals; count the matching set independently of its window.
    """
    where, params = _log_filters(filters or LogFilters())
    query = "SELECT COUNT(*) AS n FROM app_logs WHERE " + where
    with use_conn(conn, None) as c:
        row = c.execute(query, params).fetchone()
    return int(row["n"])


def prune_logs(*, max_rows: int, db_path: str | None = None) -> int:
    with connect(db_path) as c:
        # A primary-key cutoff avoids materializing and scanning the surviving
        # keep-set under SQLite's single writer lock.
        row = c.execute(
            "SELECT id FROM app_logs ORDER BY id DESC LIMIT 1 OFFSET ?",
            (max_rows,),
        ).fetchone()
        if row is None:
            return 0
        cur = c.execute("DELETE FROM app_logs WHERE id <= ?", (row["id"],))
        return int(cur.rowcount or 0)


def latest_log_id(*, conn: sqlite3.Connection | None = None) -> int:
    with use_conn(conn, None) as c:
        row = c.execute("SELECT MAX(id) AS max_id FROM app_logs").fetchone()
    return int(row["max_id"] or 0)


def count_logs_for_run(
    run_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Logs intentionally lack a run FK so ordinary run deletion preserves
    history; permanent deletion accounts for them explicitly.
    """
    with use_conn(conn, db_path) as c:
        row = c.execute("SELECT COUNT(*) AS n FROM app_logs WHERE run_id=?", (run_id,)).fetchone()
    return int(row["n"])


def delete_logs_for_run(run_id: str, *, conn: sqlite3.Connection | None = None) -> int:
    with use_conn(conn, None) as c:
        cur = c.execute("DELETE FROM app_logs WHERE run_id=?", (run_id,))
        return int(cur.rowcount or 0)
