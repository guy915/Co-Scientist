"""Pairwise tournament match rows for a run.

Split out of ``app.store.records`` to keep that module within the size
cap. Holds the insert/list helpers for the outcome rows of Elo tournament
matches. Every name is re-exported from ``app.store.records``, so callers
and monkeypatching tests are unaffected.

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
class NewMatch:
    """One pairwise tournament match row to insert.

    Carries the winner's and loser's Elo before/after the match, the
    judge's rationale for why the winner prevailed, the decisiveness
    ``tier`` (upset|decisive|clear|narrow), the debate depth in turns
    (1 = single-turn comparison, >1 = multi-turn scientific debate), and
    the turn-by-turn debate transcript as a JSON document (None when the
    judge recorded no turns -- see ``_migrate_match_debate_transcript``).
    """

    run_id: str
    iteration: int
    winner_id: str
    loser_id: str
    winner_before: int
    winner_after: int
    loser_before: int
    loser_after: int
    rationale: str
    tier: str | None = None
    debate_turns: int = 1
    debate_transcript: str | None = None


def _insert_match_row(conn: sqlite3.Connection, f: NewMatch) -> None:
    """Insert the outcome row for a pairwise tournament match."""
    conn.execute(
        "INSERT INTO matches (run_id, iteration, winner_id, loser_id, "
        "winner_elo_before, winner_elo_after, loser_elo_before, "
        "loser_elo_after, rationale, tier, debate_turns, "
        "debate_transcript, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            f.run_id,
            f.iteration,
            f.winner_id,
            f.loser_id,
            f.winner_before,
            f.winner_after,
            f.loser_before,
            f.loser_after,
            f.rationale,
            f.tier,
            f.debate_turns,
            f.debate_transcript,
            _now(),
        ),
    )


def add_match(
    match: NewMatch,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Record the outcome of a pairwise tournament match.

    Args:
        match: The match outcome to insert (see :class:`NewMatch`).
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).
    """
    with _use_conn(conn, db_path) as conn:
        _insert_match_row(conn, match)


def list_matches(
    run_id: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return a run's tournament match rows ordered by creation time."""
    return _list_by_run("matches", run_id, db_path, conn)


def count_matches(
    run_id: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Return how many tournament match rows a run has.

    One COUNT(*), for the callers that want this number alone: materializing
    the rows to length them reads the whole table, and ``summary_counts``
    charges four more COUNT(*) queries for tables they never look at.

    Args:
        run_id: Identifier of the run to count matches for.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).

    Returns:
        The run's match row count.
    """
    with _use_conn(conn, db_path) as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM matches WHERE run_id=?",
                (run_id,),
            ).fetchone()[0]
        )
