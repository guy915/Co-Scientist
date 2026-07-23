"""Explainable proximity edges between a run's stored hypotheses.

Split out of ``app.store.records`` to keep that module within the size
cap. Holds the insert/list helpers for the weighted proximity landscape
the dedup agent persists. Every name is re-exported from
``app.store.records``, so callers and monkeypatching tests are
unaffected.

Every helper accepts ``db_path`` (override for the SQLite database path)
and ``conn`` (an open connection to reuse, e.g. from ``transaction``).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from app.store.db import _now, _use_conn
from app.store.records_support import _list_by_run


@dataclass(frozen=True)
class NewProximityEdge:
    """One explainable proximity edge between two stored hypotheses.

    ``similarity`` is the weight of the edge and ``degree`` its coarse
    label; ``cluster_id`` groups near-duplicates. ``method``, ``version``,
    and ``model`` record which dedup pass produced the edge, and
    ``updated_at`` is the provider's own timestamp for it.
    """

    run_id: str
    source_hypothesis_id: str
    target_hypothesis_id: str
    similarity: float
    degree: str | None = None
    cluster_id: str | None = None
    method: str | None = None
    version: str | None = None
    model: str | None = None
    updated_at: float | None = None


def add_proximity_edge(
    edge: NewProximityEdge,
    *,
    conn: sqlite3.Connection | None = None,
    db_path: str | None = None,
) -> None:
    """Persist one explainable proximity edge between stored hypotheses.

    Args:
        edge: The proximity edge to insert (see
            :class:`NewProximityEdge`).
        conn: Optional open connection to reuse (e.g. from ``transaction``).
        db_path: Optional override for the SQLite database path.
    """
    with _use_conn(conn, db_path) as active:
        active.execute(
            "INSERT INTO proximity_edges (run_id, source_hypothesis_id, "
            "target_hypothesis_id, similarity, degree, cluster_id, method, "
            "version, model, updated_at, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                edge.run_id,
                edge.source_hypothesis_id,
                edge.target_hypothesis_id,
                edge.similarity,
                edge.degree,
                edge.cluster_id,
                edge.method,
                edge.version,
                edge.model,
                edge.updated_at,
                _now(),
            ),
        )


def list_proximity_edges(
    run_id: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return a run's weighted proximity landscape edges."""
    return _list_by_run("proximity_edges", run_id, db_path, conn)
