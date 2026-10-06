from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, NamedTuple

from app.store.db import _list_by_run, _now, _use_conn, connect

if TYPE_CHECKING:
    from co_scientist.research import ResearchResult


def save_run_metrics(
    run_id: str,
    metrics: dict[str, Any],
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
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
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT metrics_json FROM run_metrics WHERE run_id=?",
            (run_id,),
        ).fetchone()
    if row is None:
        return None
    metrics: dict[str, Any] = json.loads(row["metrics_json"])
    return metrics


@dataclass(frozen=True)
class NewRetrievalCall:
    """Call IDs hash no run identity and are unique only within a run;
    admitted and dropped locators partition the returned hits.
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
    if not calls:
        return 0
    now = _now()
    rows = [_row(call, now) for call in calls]
    with _use_conn(conn, db_path) as active:
        # Connection-local total_changes counts only this batch's inserts,
        # excluding ignored duplicates and concurrent workers.
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
    return _list_by_run(
        "retrieval_calls",
        run_id,
        db_path,
        conn,
        json_fields=("hits", "admitted", "dropped"),
    )


class _Origin(NamedTuple):
    """Question IDs and depth come from the thread, not the call's hashed
    text; depth zero means unknown rather than first level.
    """

    depth: int
    question_id: str


_UNKNOWN = _Origin(depth=0, question_id="")


def retrieval_call_rows(run_id: str, result: ResearchResult) -> list[NewRetrievalCall]:
    """Persist failures and empty searches separately; otherwise coverage
    cannot distinguish an unreachable source from no results.
    """
    origins = _origin_by_call(result)
    return [
        NewRetrievalCall(
            run_id=run_id,
            id=call.id,
            question=call.question,
            question_id=origins.get(call.id, _UNKNOWN).question_id,
            query=call.query,
            source=call.source,
            depth=origins.get(call.id, _UNKNOWN).depth,
            status=call.status.value,
            hits=[
                {
                    "locator": hit.locator,
                    "title": hit.title,
                    "snippet": hit.snippet,
                    "rank": hit.rank,
                    "score": hit.score,
                    "metadata": dict(hit.metadata),
                }
                for hit in call.hits
            ],
            admitted=list(call.admitted),
            dropped=list(call.dropped),
            error=call.error,
            duration_seconds=call.duration_seconds,
        )
        for call in result.calls
    ]


def _origin_by_call(result: ResearchResult) -> dict[str, _Origin]:
    return {
        call_id: _Origin(depth=thread.depth, question_id=thread.question.id)
        for thread in result.threads
        for call_id in thread.call_ids
    }
