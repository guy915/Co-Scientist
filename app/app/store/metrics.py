"""Per-run execution metrics (LLM calls, phase timings).

One row per run holding the final ``ExecutionMetrics``-shaped dict the
workflow produced (see the engine's ``models.ExecutionMetrics``); the
mock provider persists an equivalent deterministic dict. The row is
upserted, so a resumed run that finalizes again simply replaces it.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.store.db import _now, _use_conn, connect


def save_run_metrics(
    run_id: str,
    metrics: dict[str, Any],
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Persist (or replace) a run's execution metrics.

    Args:
        run_id: Identifier of the run the metrics belong to.
        metrics: ExecutionMetrics-shaped dict serialized to JSON.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).
    """
    now = _now()
    with _use_conn(conn, db_path) as conn:
        conn.execute(
            "INSERT INTO run_metrics (run_id, metrics_json, created_at, "
            "updated_at) VALUES (?,?,?,?) "
            "ON CONFLICT(run_id) DO UPDATE SET "
            "metrics_json=excluded.metrics_json, "
            "updated_at=excluded.updated_at",
            (run_id, json.dumps(metrics), now, now),
        )


def get_run_metrics(
    run_id: str,
    db_path: str | None = None,
) -> dict[str, Any] | None:
    """Return a run's persisted execution metrics, or None if absent.

    Args:
        run_id: Identifier of the run whose metrics to read.
        db_path: Optional override for the SQLite database path.

    Returns:
        The ExecutionMetrics-shaped dict, or None when the run has not
        finalized (or does not exist).
    """
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT metrics_json FROM run_metrics WHERE run_id=?",
            (run_id,),
        ).fetchone()
    if row is None:
        return None
    metrics: dict[str, Any] = json.loads(row["metrics_json"])
    return metrics
