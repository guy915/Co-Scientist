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
from app.store.db import _now, _use_conn

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
    mime_type: str | None = None,
    sha256: str | None = None,
    byte_size: int | None = None,
    document_version: str | None = None,
    extraction_tool: str | None = None,
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
        mime_type: Original document media type when uploaded.
        sha256: Content digest for immutable document identity.
        byte_size: Original upload size in bytes.
        document_version: Version label for extraction/cache provenance.
        extraction_tool: Extractor and version used to produce text.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).

    Returns:
        The identifier of the newly inserted evidence row.
    """
    ev_id = str(uuid.uuid4())
    with _use_conn(conn, db_path) as conn:
        conn.execute(
            "INSERT INTO evidence (id, run_id, title, source, url, "
            "authors_json, year, abstract, available, mime_type, sha256, "
            "byte_size, document_version, extraction_tool, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                mime_type,
                sha256,
                byte_size,
                document_version,
                extraction_tool,
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


def add_claim_evidence(
    run_id: str,
    hypothesis_id: str,
    claim: str,
    label: str,
    supporting: Iterable[Any],
    contradicting: Iterable[Any],
    assessor: str,
    claim_role: str = "categorical",
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Insert one claim-level entailment edge for the claim-evidence graph.

    Args:
        run_id: Identifier of the run the claim belongs to.
        hypothesis_id: Identifier of the hypothesis the claim was extracted
            from.
        claim: The atomic claim text.
        label: Entailment verdict ('supports' | 'contradicts' | 'insufficient').
        supporting: Support spans that support the claim — JSON-serializable
            provenance objects (``{evidence_id, quote, start, end, source,
            url}``); legacy rows stored bare passage strings.
        contradicting: Support spans that contradict the claim (same shape).
        assessor: Provenance id of the entailment assessor.
        claim_role: Categorical finding or visibly speculative proposal.
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).
    """
    with _use_conn(conn, db_path) as conn:
        conn.execute(
            "INSERT INTO claim_evidence (run_id, hypothesis_id, claim, label, "
            "claim_role, supporting_json, contradicting_json, assessor, "
            "created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                hypothesis_id,
                claim,
                label,
                claim_role,
                json.dumps(list(supporting)),
                json.dumps(list(contradicting)),
                assessor,
                _now(),
            ),
        )


def list_claim_evidence(
    run_id: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return a run's claim-evidence edges with passage lists decoded."""
    out = []
    for d in _list_by_run("claim_evidence", run_id, db_path, conn):
        d["supporting"] = json.loads(d.pop("supporting_json") or "[]")
        d["contradicting"] = json.loads(d.pop("contradicting_json") or "[]")
        out.append(d)
    return out


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
    debate_turns: int = 1,
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
        debate_turns: Debate depth (1 = single-turn comparison, >1 = multi-
            turn scientific debate).
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).
    """
    with _use_conn(conn, db_path) as conn:
        conn.execute(
            "INSERT INTO matches (run_id, iteration, winner_id, loser_id, "
            "winner_elo_before, winner_elo_after, loser_elo_before, "
            "loser_elo_after, rationale, tier, debate_turns, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
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
                debate_turns,
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
    category: str | None = None,
    policy_version: str | None = None,
    risk_domains: list[str] | None = None,
    requires_review: bool = False,
    assessor: str | None = None,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Record a safety-gate decision ('intake', 'hypothesis', or 'final')."""
    with _use_conn(conn, db_path) as conn:
        conn.execute(
            "INSERT INTO safety_decisions (run_id, stage, decision, reason, "
            "matches_json, category, policy_version, risk_domains_json, "
            "requires_review, assessor, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                stage,
                decision,
                reason,
                json.dumps(matches),
                category,
                policy_version,
                json.dumps(risk_domains or []),
                1 if requires_review else 0,
                assessor,
                _now(),
            ),
        )


def list_safety_decisions(
    run_id: str, db_path: str | None = None
) -> list[dict[str, Any]]:
    """Return a run's safety decisions with the matches list decoded."""
    out = []
    for d in _list_by_run("safety_decisions", run_id, db_path):
        # Expose decoded 'matches' instead of the raw matches_json column.
        d["matches"] = json.loads(d.pop("matches_json") or "[]")
        d["risk_domains"] = json.loads(d.pop("risk_domains_json", None) or "[]")
        d["requires_review"] = bool(d.get("requires_review"))
        out.append(d)
    return out


def add_proximity_edge(
    run_id: str,
    source_hypothesis_id: str,
    target_hypothesis_id: str,
    similarity: float,
    *,
    degree: str | None = None,
    cluster_id: str | None = None,
    method: str | None = None,
    version: str | None = None,
    model: str | None = None,
    updated_at: float | None = None,
    conn: sqlite3.Connection | None = None,
    db_path: str | None = None,
) -> None:
    """Persist one explainable proximity edge between stored hypotheses."""
    with _use_conn(conn, db_path) as active:
        active.execute(
            "INSERT INTO proximity_edges (run_id, source_hypothesis_id, "
            "target_hypothesis_id, similarity, degree, cluster_id, method, "
            "version, model, updated_at, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                source_hypothesis_id,
                target_hypothesis_id,
                similarity,
                degree,
                cluster_id,
                method,
                version,
                model,
                updated_at,
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


def resolve_safety_decision(
    run_id: str,
    decision_id: int,
    resolution: str,
    resolved_by: str,
    db_path: str | None = None,
) -> bool:
    """Resolve one held/redacted safety decision exactly once."""
    if resolution not in {"approved", "rejected"}:
        raise ValueError("resolution must be approved or rejected")
    with _use_conn(None, db_path) as conn:
        cursor = conn.execute(
            "UPDATE safety_decisions SET resolution=?, resolved_by=?, "
            "resolved_at=? WHERE id=? AND run_id=? AND requires_review=1 "
            "AND resolution IS NULL",
            (resolution, resolved_by, _now(), decision_id, run_id),
        )
        return cursor.rowcount == 1


def safety_stage_is_approved(
    run_id: str,
    stage: str,
    policy_version: str,
    db_path: str | None = None,
) -> bool:
    """Return whether a reviewer approved the latest matching policy stage."""
    with _use_conn(None, db_path) as conn:
        row = conn.execute(
            "SELECT resolution FROM safety_decisions WHERE run_id=? AND "
            "stage=? AND policy_version=? ORDER BY id DESC LIMIT 1",
            (run_id, stage, policy_version),
        ).fetchone()
    return bool(row and row["resolution"] == "approved")
