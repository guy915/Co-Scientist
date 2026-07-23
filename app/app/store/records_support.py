"""Shared query helper for the per-run supporting-record modules.

Split out of ``app.store.records`` to keep that module within the size
cap. Holds the generic per-run listing query the per-concern record
modules (``records``, ``records_matches``, ``records_safety``,
``records_proximity``) share without importing one another. The helper
is re-exported from ``app.store.records``, so callers and monkeypatching
tests are unaffected.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.store.db import _use_conn


def _list_by_run(
    table: str,
    run_id: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return a run's rows from ``table`` (a trusted literal), oldest first."""
    with _use_conn(conn, db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM {table} WHERE run_id=? ORDER BY created_at ASC",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]
