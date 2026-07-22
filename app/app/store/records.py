"""Per-run supporting records: evidence, citations, reviews, matches, safety.

Groups the simple insert/list helpers for the tables that hang off a run:
literature evidence and the claim-to-evidence citation links, reviewer
critiques, pairwise tournament matches, and safety-gate decisions.

Every helper accepts ``db_path`` (override for the SQLite database path)
and ``conn`` (an open connection to reuse, e.g. from ``transaction``).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.citations import CitationState
from app.store.db import _now, _use_conn

# ---------------------------------------------------------------------------
# Evidence / citations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _NewEvidenceFields:
    """Fields needed to insert an evidence row.

    ``source`` names where the evidence came from (e.g. 'pubmed', 'arxiv',
    or 'mock') and ``available`` records whether its full text is
    available. The last five fields are upload/extraction provenance for
    attached documents: the original media type, content digest (immutable
    document identity), upload size in bytes, version label for
    extraction/cache provenance, and the extractor (with version) that
    produced the text.
    """

    ev_id: str
    run_id: str
    title: str
    source: str
    url: str
    authors: Iterable[str] | None
    year: int | None
    abstract: str
    available: bool
    mime_type: str | None
    sha256: str | None
    byte_size: int | None
    document_version: str | None
    extraction_tool: str | None


def _insert_evidence_row(
    conn: sqlite3.Connection, f: _NewEvidenceFields
) -> None:
    """Insert an evidence row for a run on an open connection."""
    conn.execute(
        "INSERT INTO evidence (id, run_id, title, source, url, "
        "authors_json, year, abstract, available, mime_type, sha256, "
        "byte_size, document_version, extraction_tool, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            f.ev_id,
            f.run_id,
            f.title,
            f.source,
            f.url,
            json.dumps(list(f.authors or [])),
            f.year,
            f.abstract,
            1 if f.available else 0,
            f.mime_type,
            f.sha256,
            f.byte_size,
            f.document_version,
            f.extraction_tool,
            _now(),
        ),
    )


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
    """Insert an evidence row; returns its id (see _NewEvidenceFields)."""
    fields = _NewEvidenceFields(
        ev_id=str(uuid.uuid4()),
        run_id=run_id,
        title=title,
        source=source,
        url=url,
        authors=authors,
        year=year,
        abstract=abstract,
        available=available,
        mime_type=mime_type,
        sha256=sha256,
        byte_size=byte_size,
        document_version=document_version,
        extraction_tool=extraction_tool,
    )
    with _use_conn(conn, db_path) as conn:
        _insert_evidence_row(conn, fields)
    return fields.ev_id


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


def _insert_claim_evidence_row(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    hypothesis_id: str,
    claim: str,
    label: str,
    claim_role: str,
    supporting: Iterable[Any],
    contradicting: Iterable[Any],
    assessor: str,
) -> None:
    """Insert one claim-level entailment edge on an open connection."""
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

    ``label`` is the entailment verdict ('supports' | 'contradicts' |
    'insufficient') and ``claim_role`` marks a categorical finding versus
    a visibly speculative proposal. ``supporting``/``contradicting`` are
    the spans for/against the claim -- JSON-serializable provenance
    objects (``{evidence_id, quote, start, end, source, url}``; legacy
    rows stored bare passage strings). ``assessor`` is the provenance id
    of the entailment assessor.
    """
    with _use_conn(conn, db_path) as conn:
        _insert_claim_evidence_row(
            conn,
            run_id=run_id,
            hypothesis_id=hypothesis_id,
            claim=claim,
            label=label,
            claim_role=claim_role,
            supporting=supporting,
            contradicting=contradicting,
            assessor=assessor,
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


def _insert_review_row(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    hypothesis_id: str,
    reviewer_agent: str,
    summary: str,
    critique: str,
    novelty: float | None,
    plausibility: float | None,
    testability: float | None,
    overall: float | None,
) -> None:
    """Insert a reviewer's assessment of a hypothesis on an open connection."""
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

    ``reviewer_agent`` names the agent that produced the review (e.g.
    'reflection'); the four reviewer-assigned scores are optional.
    """
    with _use_conn(conn, db_path) as conn:
        _insert_review_row(
            conn,
            run_id=run_id,
            hypothesis_id=hypothesis_id,
            reviewer_agent=reviewer_agent,
            summary=summary,
            critique=critique,
            novelty=novelty,
            plausibility=plausibility,
            testability=testability,
            overall=overall,
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


@dataclass(frozen=True)
class _MatchFields:
    """Fields needed to insert one pairwise tournament match row.

    Carries the winner's and loser's Elo before/after the match, the
    judge's rationale for why the winner prevailed, the decisiveness
    ``tier`` (upset|decisive|clear|narrow), and the debate depth in turns
    (1 = single-turn comparison, >1 = multi-turn scientific debate).
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
    tier: str | None
    debate_turns: int


def _insert_match_row(conn: sqlite3.Connection, f: _MatchFields) -> None:
    """Insert the outcome row for a pairwise tournament match."""
    conn.execute(
        "INSERT INTO matches (run_id, iteration, winner_id, loser_id, "
        "winner_elo_before, winner_elo_after, loser_elo_before, "
        "loser_elo_after, rationale, tier, debate_turns, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
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
            _now(),
        ),
    )


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

    Field semantics are documented on ``_MatchFields``.
    """
    fields = _MatchFields(
        run_id=run_id,
        iteration=iteration,
        winner_id=winner_id,
        loser_id=loser_id,
        winner_before=winner_before,
        winner_after=winner_after,
        loser_before=loser_before,
        loser_after=loser_after,
        rationale=rationale,
        tier=tier,
        debate_turns=debate_turns,
    )
    with _use_conn(conn, db_path) as conn:
        _insert_match_row(conn, fields)


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
