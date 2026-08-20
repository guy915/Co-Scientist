"""Store I/O for retrieval provenance.

The ``retrieval_calls`` table (schema in ``schema_retrieval_calls.py``):
one row per query, against one source, serving one question. See
``app.research_provenance`` for how a research run's in-memory ledger
becomes these rows.

Writes are idempotent on ``(run_id, id)`` because a call's id is derived
from its content -- a resumed run re-issuing the same searches must
recognize the ones it already paid for rather than duplicating them, and
``INSERT OR IGNORE`` is what makes replaying a partial ledger safe.

Every helper accepts ``db_path`` (override for the SQLite database path)
and ``conn`` (an open connection to reuse, e.g. from ``transaction``).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.store.db import _now, _use_conn
from app.store.records_support import _list_by_run


@dataclass(frozen=True)
class NewRetrievalCall:
    """One search to persist, mirroring the retrieval_calls table.

    Attributes:
        run_id: Owning run.
        id: Content id of the call, from
            ``co_scientist.research.artifacts.SearchCall.id``. Unique only
            within a run, since the hash carries no run.
        question: The question the search was serving.
        question_id: Content id of that question.
        query: The query as issued to the source.
        source: Which source was searched.
        depth: Level of the descent the call was made at, from 1.
        status: How the call ended -- ``ok``, ``empty`` or ``failed``.
        hits: The ranked result set as the source returned it, each a
            plain dict of the hit's fields.
        admitted: Locators the evidence budget funded and read.
        dropped: Locators it refused. Together with ``admitted`` these
            partition ``hits``.
        error: Failure text, when ``status`` is ``failed``.
        duration_seconds: Wall time for the call.
    """

    run_id: str
    id: str
    question: str
    question_id: str
    query: str
    source: str
    depth: int
    status: str
    hits: Sequence[dict[str, Any]] = field(default_factory=tuple)
    admitted: Sequence[str] = field(default_factory=tuple)
    dropped: Sequence[str] = field(default_factory=tuple)
    error: str | None = None
    duration_seconds: float | None = None


def _row(call: NewRetrievalCall, now: float) -> tuple[Any, ...]:
    """Order one search's fields the way the INSERT below names them."""
    return (
        call.id,
        call.run_id,
        call.question,
        call.question_id,
        call.query,
        call.source,
        call.depth,
        call.status,
        json.dumps(list(call.hits)),
        json.dumps(list(call.admitted)),
        json.dumps(list(call.dropped)),
        call.error,
        call.duration_seconds,
        now,
    )


def add_retrieval_calls(
    calls: Sequence[NewRetrievalCall],
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Persist a batch of searches, skipping ones already recorded.

    Args:
        calls: The searches to insert (see :class:`NewRetrievalCall`).
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from
            ``transaction``).

    Returns:
        How many rows were actually inserted, which is fewer than
        ``len(calls)`` whenever a resumed run re-offered work it had
        already paid for.
    """
    if not calls:
        return 0
    now = _now()
    rows = [_row(call, now) for call in calls]
    with _use_conn(conn, db_path) as active:
        # total_changes is this connection's own running total, so it
        # counts what this batch inserted and nothing another run's
        # worker wrote concurrently -- which a COUNT(*) either side of
        # the write would pick up. It also does not count a row that OR
        # IGNORE skipped, which is exactly the number wanted.
        before = active.total_changes
        active.executemany(
            "INSERT OR IGNORE INTO retrieval_calls (id, run_id, question, "
            "question_id, query, source, depth, status, hits_json, "
            "admitted_json, dropped_json, error, duration_seconds, "
            "created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        return active.total_changes - before


def list_retrieval_calls(
    run_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return a run's searches, oldest first, with their JSON decoded.

    Args:
        run_id: Identifier of the run whose searches to list.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from
            ``transaction``).

    Returns:
        One dict per search, with ``hits``, ``admitted`` and ``dropped``
        decoded from their stored JSON.
    """
    out = []
    for row in _list_by_run("retrieval_calls", run_id, db_path, conn):
        row["hits"] = json.loads(row.pop("hits_json") or "[]")
        row["admitted"] = json.loads(row.pop("admitted_json") or "[]")
        row["dropped"] = json.loads(row.pop("dropped_json") or "[]")
        out.append(row)
    return out
