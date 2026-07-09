"""Per-run supporting records: evidence, citations, reviews, matches, safety.

Groups the simple insert/list helpers for the tables that hang off a run:
literature evidence and the claim-to-evidence citation links, reviewer
critiques, pairwise tournament matches, and safety-gate decisions.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterable
from typing import Any

from app.citations import CitationState
from app.store.db import _now, _use_conn, connect

# ---------------------------------------------------------------------------
# Evidence / citations
# ---------------------------------------------------------------------------


def add_evidence(
    run_id: str,
    title: str,
    *,
    source: str = "mock",
    url: str = "",
    authors: Iterable[str] | None = None,
    year: int | None = None,
    abstract: str = "",
    available: bool = True,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> str:
    """Insert an evidence row for a run and return its identifier.

    Args:
        run_id: Identifier of the run the evidence belongs to.
        title: Title of the evidence item.
        source: Evidence source, e.g. 'pubmed', 'arxiv', or 'mock'.
        url: Optional URL pointing to the evidence.
        authors: Optional iterable of author names.
        year: Optional publication year.
        abstract: Optional abstract text for the evidence.
        available: Whether the evidence full text is available.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).

    Returns:
        The identifier of the newly inserted evidence row.
    """
    ev_id = str(uuid.uuid4())
    with _use_conn(conn, db_path) as conn:
        conn.execute(
            "INSERT INTO evidence (id, run_id, title, source, url, "
            "authors_json, year, abstract, available, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                ev_id,
                run_id,
                title,
                source,
                url,
                json.dumps(list(authors or [])),
                year,
                abstract,
                1 if available else 0,
                _now(),
            ),
        )
    return ev_id


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


def list_evidence(
    run_id: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return a run's evidence rows ordered by creation time.

    Args:
        run_id: Identifier of the run whose evidence to list.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).

    Returns:
        A list of evidence dicts with decoded authors and available fields.
    """
    out = []
    for d in _list_by_run("evidence", run_id, db_path, conn):
        d["authors"] = json.loads(d.pop("authors_json") or "[]")
        d["available"] = bool(d["available"])
        out.append(d)
    return out


def add_citation(
    run_id: str,
    hypothesis_id: str,
    evidence_id: str,
    claim: str,
    state: CitationState,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Insert a classified claim-to-evidence citation link."""
    with _use_conn(conn, db_path) as conn:
        conn.execute(
            "INSERT INTO citations (run_id, hypothesis_id, evidence_id, "
            "claim, state, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (run_id, hypothesis_id, evidence_id, claim, state.value, _now()),
        )


def list_citations(
    run_id: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return a run's citation rows ordered by creation time."""
    return _list_by_run("citations", run_id, db_path, conn)


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------


def add_review(
    run_id: str,
    hypothesis_id: str,
    reviewer_agent: str,
    summary: str,
    critique: str,
    *,
    novelty: float | None = None,
    plausibility: float | None = None,
    testability: float | None = None,
    overall: float | None = None,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Insert a reviewer's assessment of a hypothesis.

    Args:
        run_id: Identifier of the run the review belongs to.
        hypothesis_id: Identifier of the reviewed hypothesis.
        reviewer_agent: Agent that produced the review, e.g. 'reflection'.
        summary: Short summary of the review.
        critique: Full critique text.
        novelty: Optional novelty score assigned by the reviewer.
        plausibility: Optional plausibility score assigned by the reviewer.
        testability: Optional testability score assigned by the reviewer.
        overall: Optional overall score assigned by the reviewer.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).
    """
    with _use_conn(conn, db_path) as conn:
        conn.execute(
            "INSERT INTO reviews (run_id, hypothesis_id, "
            "reviewer_agent, summary, critique, "
            "novelty, plausibility, testability, overall, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                hypothesis_id,
                reviewer_agent,
                summary,
                critique,
                novelty,
                plausibility,
                testability,
                overall,
                _now(),
            ),
        )


def list_reviews(
    run_id: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return a run's review rows ordered by creation time."""
    return _list_by_run("reviews", run_id, db_path, conn)


# ---------------------------------------------------------------------------
# Matches
# ---------------------------------------------------------------------------


def add_match(
    run_id: str,
    iteration: int,
    winner_id: str,
    loser_id: str,
    winner_before: int,
    winner_after: int,
    loser_before: int,
    loser_after: int,
    rationale: str,
    tier: str | None = None,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Record the outcome of a pairwise tournament match.

    Args:
        run_id: Identifier of the run the match belongs to.
        iteration: Tournament iteration in which the match occurred.
        winner_id: Identifier of the winning hypothesis.
        loser_id: Identifier of the losing hypothesis.
        winner_before: Winner's Elo rating before the match.
        winner_after: Winner's Elo rating after the match.
        loser_before: Loser's Elo rating before the match.
        loser_after: Loser's Elo rating after the match.
        rationale: Explanation of why the winner prevailed.
        tier: Decisiveness class of the match (upset|decisive|clear|narrow).
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).
    """
    with _use_conn(conn, db_path) as conn:
        conn.execute(
            "INSERT INTO matches (run_id, iteration, winner_id, loser_id, "
            "winner_elo_before, winner_elo_after, loser_elo_before, "
            "loser_elo_after, rationale, tier, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                iteration,
                winner_id,
                loser_id,
                winner_before,
                winner_after,
                loser_before,
                loser_after,
                rationale,
                tier,
                _now(),
            ),
        )


def list_matches(
    run_id: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return a run's tournament match rows ordered by creation time."""
    return _list_by_run("matches", run_id, db_path, conn)


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


def add_safety_decision(
    run_id: str,
    stage: str,
    decision: str,
    reason: str,
    matches: list[str],
    db_path: str | None = None,
) -> None:
    """Record a safety-gate decision ('intake' or 'final') for a run."""
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO safety_decisions (run_id, stage, decision, reason, "
            "matches_json, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (run_id, stage, decision, reason, json.dumps(matches), _now()),
        )


def list_safety_decisions(
    run_id: str, db_path: str | None = None
) -> list[dict[str, Any]]:
    """Return a run's safety decisions with the matches list decoded."""
    out = []
    for d in _list_by_run("safety_decisions", run_id, db_path):
        # Expose decoded 'matches' instead of the raw matches_json column.
        d["matches"] = json.loads(d.pop("matches_json") or "[]")
        out.append(d)
    return out
