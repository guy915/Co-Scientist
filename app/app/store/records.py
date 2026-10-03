"""Evidence, citations, reviews, tournament matches and safety records.

Each helper accepts a database override and, where applicable, a caller's
transaction connection. Hypothesis lineage and evidence provenance remain
separate from the mutable tournament state.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.citations import CitationState
from app.claims.gate import DEFAULT_CLAIM_ROLE
from app.store.db import _list_by_run, _now, _use_conn, connect

# ---------------------------------------------------------------------------
# Evidence / citations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NewEvidence:
    """One evidence row to insert, mirroring the evidence table.

    ``source`` names where the evidence came from (e.g. 'pubmed', 'arxiv',
    or 'mock') and ``available`` records whether its full text is
    available. The next five fields are upload/extraction provenance for
    attached documents: the original media type, content digest (immutable
    document identity), upload size in bytes, version label for
    extraction/cache provenance, and the extractor (with version) that
    produced the text. ``doi``/``pmid`` are canonical identifiers, when the
    source has them, and ``retrieved_at`` is when the article was retrieved
    -- distinct from the row's ``created_at`` insert stamp. ``passage_text``
    is not a constructor field: it is always materialized from ``title`` +
    ``abstract`` at insert time, so it is exactly the text a claim-evidence
    span's offsets index, never a value a caller could pass out of sync
    with the row it describes. ``retrieval_score``/``retrieval_rationale``/
    ``retriever_version`` are the persisted hybrid-retrieval provenance
    (see ``search_support.py``'s scorer): the combined lexical+semantic
    score, the semantic pass's stated reason, and the method/version that
    produced both. ``retrieval_call_id`` names the search that found this
    row (``retrieval_calls.id``); None is a real state rather than a gap
    -- an uploaded document and a directly fetched corpus paper have no
    query behind them. ``retracted`` is reported alongside ``available``
    rather than folded into it -- a retracted source still persists as
    unavailable, unchanged, but a reader is told which one it was (see
    ``engine_adapter.drain.evidence_resolution.ResolvedArticle``).
    ``source_type`` is what kind of source it is (peer-reviewed, preprint,
    database record, web page, attached document), classified from the
    metadata at drain time; it is reported to a reader and gates nothing.
    """

    run_id: str
    title: str
    source: str = "mock"
    url: str = ""
    authors: Iterable[str] | None = None
    year: int | None = None
    abstract: str = ""
    available: bool = True
    retracted: bool = False
    source_type: str = ""
    mime_type: str | None = None
    sha256: str | None = None
    byte_size: int | None = None
    document_version: str | None = None
    extraction_tool: str | None = None
    doi: str | None = None
    pmid: str | None = None
    retrieved_at: float | None = None
    retrieval_score: float | None = None
    retrieval_rationale: str | None = None
    retriever_version: str | None = None
    retrieval_call_id: str | None = None


def _evidence_passage_text(f: NewEvidence) -> str:
    """Materialize the exact passage a claim-evidence span indexes.

    Mirrors ``app.claims.grounding.evidence_passages``' text formula so the
    stored column and the text a span was located in never drift apart.
    """
    return " ".join(str(part or "") for part in (f.title, f.abstract)).strip()


def add_evidence(
    evidence: NewEvidence,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> str:
    """Insert an evidence row and return its generated id.

    Args:
        evidence: The evidence row to insert (see :class:`NewEvidence`).
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).

    Returns:
        The identifier assigned to the new evidence row.
    """
    ev_id = str(uuid.uuid4())
    with _use_conn(conn, db_path) as conn:
        conn.execute(
            "INSERT INTO evidence (id, run_id, title, source, url, "
            "authors_json, year, abstract, available, retracted, source_type, "
            "mime_type, sha256, byte_size, document_version, extraction_tool, "
            "doi, pmid, passage_text, retrieved_at, retrieval_score, "
            "retrieval_rationale, retriever_version, retrieval_call_id, "
            "created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                ev_id,
                evidence.run_id,
                evidence.title,
                evidence.source,
                evidence.url,
                json.dumps(list(evidence.authors or [])),
                evidence.year,
                evidence.abstract,
                1 if evidence.available else 0,
                1 if evidence.retracted else 0,
                evidence.source_type or None,
                evidence.mime_type,
                evidence.sha256,
                evidence.byte_size,
                evidence.document_version,
                evidence.extraction_tool,
                evidence.doi,
                evidence.pmid,
                _evidence_passage_text(evidence),
                evidence.retrieved_at,
                evidence.retrieval_score,
                evidence.retrieval_rationale,
                evidence.retriever_version,
                evidence.retrieval_call_id,
                _now(),
            ),
        )
    return ev_id


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
        A list of evidence dicts with decoded authors and available/
        retracted fields. ``retracted`` reads back False for a row
        persisted before that column existed (NULL), the same as a row
        that was never flagged -- an old run has no way to know, so it
        renders exactly as it did before this column existed.
    """
    rows = _list_by_run(
        "evidence", run_id, db_path, conn, json_fields=("authors",)
    )
    for row in rows:
        row["available"] = bool(row["available"])
        row["retracted"] = bool(row.get("retracted"))
    return rows


@dataclass(frozen=True)
class NewCitation:
    """One classified claim-to-evidence citation link to insert.

    ``state`` is the classification of how the cited evidence relates to
    the claim it was attached to.
    """

    run_id: str
    hypothesis_id: str
    evidence_id: str
    claim: str
    state: CitationState


def add_citation(
    citation: NewCitation,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Insert a classified claim-to-evidence citation link.

    Args:
        citation: The citation link to insert (see :class:`NewCitation`).
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).
    """
    with _use_conn(conn, db_path) as conn:
        conn.execute(
            "INSERT INTO citations (run_id, hypothesis_id, evidence_id, "
            "claim, state, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                citation.run_id,
                citation.hypothesis_id,
                citation.evidence_id,
                citation.claim,
                citation.state.value,
                _now(),
            ),
        )


def list_citations(
    run_id: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return a run's citation rows ordered by creation time."""
    return _list_by_run("citations", run_id, db_path, conn)


@dataclass(frozen=True)
class NewClaimEvidence:
    """One claim-level entailment edge of the claim-evidence graph.

    ``label`` is the entailment verdict (an ``EntailmentLabel`` value) and
    ``claim_role`` marks a categorical finding versus a visibly speculative
    proposal (a ``ClaimRole`` value); ``app.claims.gate`` says what each
    means to a reader. ``supporting``/``contradicting`` are
    the spans for/against the claim -- JSON-serializable provenance
    objects (``{evidence_id, quote, start, end, source, url}``; legacy
    rows stored bare passage strings). ``assessor`` is the provenance id
    of the entailment assessor. ``verification_method`` records the decision
    path without upgrading its scientific authority; old rows remain unknown.
    """

    run_id: str
    hypothesis_id: str
    claim: str
    label: str
    supporting: Iterable[Any]
    contradicting: Iterable[Any]
    assessor: str
    claim_role: str = DEFAULT_CLAIM_ROLE
    verification_method: str = "legacy_unknown"


def add_claim_evidence(
    edge: NewClaimEvidence,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Insert one claim-level entailment edge for the claim-evidence graph.

    Args:
        edge: The entailment edge to insert (see
            :class:`NewClaimEvidence`).
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).
    """
    with _use_conn(conn, db_path) as conn:
        conn.execute(
            "INSERT INTO claim_evidence (run_id, hypothesis_id, claim, label, "
            "claim_role, supporting_json, contradicting_json, assessor, "
            "created_at, verification_method) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                edge.run_id,
                edge.hypothesis_id,
                edge.claim,
                edge.label,
                edge.claim_role,
                json.dumps(list(edge.supporting)),
                json.dumps(list(edge.contradicting)),
                edge.assessor,
                _now(),
                edge.verification_method,
            ),
        )


def list_claim_evidence(
    run_id: str,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return a run's claim-evidence edges with passage lists decoded."""
    return _list_by_run(
        "claim_evidence",
        run_id,
        db_path,
        conn,
        json_fields=("supporting", "contradicting"),
    )


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NewReview:
    """One reviewer's assessment of a hypothesis, mirroring the row.

    ``reviewer_agent`` names the agent that produced the review (e.g.
    'reflection'); the four reviewer-assigned scores are optional.
    ``author`` and ``verdict`` carry a scientist reviewer's identity and
    categorical judgement as their own columns, so neither has to be
    recovered by reading the summary prose; both stay empty for an agent
    review. ``detail_json`` carries one review type's own structured
    fields beyond summary/critique (e.g. the simulation review's failure
    points), display-only -- see ``drain.reviews._review_detail_json``.
    """

    run_id: str
    hypothesis_id: str
    reviewer_agent: str
    summary: str
    critique: str
    novelty: float | None = None
    plausibility: float | None = None
    testability: float | None = None
    overall: float | None = None
    author: str = ""
    verdict: str | None = None
    detail_json: str | None = None


def add_review(
    review: NewReview,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Insert a reviewer's assessment of a hypothesis.

    Args:
        review: The review row to insert (see :class:`NewReview`).
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).
    """
    with _use_conn(conn, db_path) as conn:
        conn.execute(
            "INSERT INTO reviews (run_id, hypothesis_id, "
            "reviewer_agent, summary, critique, "
            "novelty, plausibility, testability, overall, author, verdict, "
            "detail_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                review.run_id,
                review.hypothesis_id,
                review.reviewer_agent,
                review.summary,
                review.critique,
                review.novelty,
                review.plausibility,
                review.testability,
                review.overall,
                review.author,
                review.verdict,
                review.detail_json,
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


def review_exists(
    review_id: int,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> bool:
    """Return whether a review row is still stored under this id.

    Review ids are AUTOINCREMENT, so a deleted row's id is never handed to a
    later review; a scientist review carried in engine state can therefore
    ask by id whether its own row survived the run's resets.
    """
    with _use_conn(conn, db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM reviews WHERE id=?", (review_id,)
        ).fetchone()
        return row is not None


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
        conn.execute(
            "INSERT INTO matches (run_id, iteration, winner_id, loser_id, "
            "winner_elo_before, winner_elo_after, loser_elo_before, "
            "loser_elo_after, rationale, tier, debate_turns, "
            "debate_transcript, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                match.run_id,
                match.iteration,
                match.winner_id,
                match.loser_id,
                match.winner_before,
                match.winner_after,
                match.loser_before,
                match.loser_after,
                match.rationale,
                match.tier,
                match.debate_turns,
                match.debate_transcript,
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


@dataclass(frozen=True)
class NewSafetyDecision:
    """One safety-gate decision to record, mirroring the row.

    ``stage`` is the gate that ran ('intake', 'hypothesis', or 'final'),
    ``decision`` its verdict, and ``matches`` the policy patterns that
    fired. ``requires_review`` marks a decision a human must adjudicate,
    and ``assessor`` is the provenance id of whatever produced it.
    """

    run_id: str
    stage: str
    decision: str
    reason: str
    matches: list[str]
    category: str | None = None
    policy_version: str | None = None
    risk_domains: list[str] | None = None
    requires_review: bool = False
    assessor: str | None = None


def add_safety_decision(
    decision: NewSafetyDecision,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Record a safety-gate decision.

    Args:
        decision: The decision to record (see
            :class:`NewSafetyDecision`).
        db_path: Optional override for the SQLite database path.
        conn: Optional open connection to reuse (e.g. from ``transaction``).
    """
    with _use_conn(conn, db_path) as conn:
        conn.execute(
            "INSERT INTO safety_decisions (run_id, stage, decision, reason, "
            "matches_json, category, policy_version, risk_domains_json, "
            "requires_review, assessor, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                decision.run_id,
                decision.stage,
                decision.decision,
                decision.reason,
                json.dumps(decision.matches),
                decision.category,
                decision.policy_version,
                json.dumps(decision.risk_domains or []),
                1 if decision.requires_review else 0,
                decision.assessor,
                _now(),
            ),
        )


def list_safety_decisions(
    run_id: str, db_path: str | None = None
) -> list[dict[str, Any]]:
    """Return a run's safety decisions with the matches list decoded."""
    rows = _list_by_run(
        "safety_decisions",
        run_id,
        db_path,
        json_fields=("matches", "risk_domains"),
    )
    for row in rows:
        row["requires_review"] = bool(row.get("requires_review"))
    return rows


def count_unresolved_review_decisions(
    run_id: str,
    *,
    db_path: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Count a run's safety decisions still awaiting human review.

    Seeks the run's rows via ``idx_safety_run(run_id, created_at)`` and
    counts in SQL rather than decoding every row's JSON columns the way
    ``list_safety_decisions`` does -- this runs on the ``GET /runs/{id}``
    hot path, so it stays a single indexed COUNT rather than a full listing.
    """
    with _use_conn(conn, db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM safety_decisions WHERE run_id=? AND "
            "requires_review=1 AND resolution IS NULL",
            (run_id,),
        ).fetchone()
        return int(row[0]) if row else 0


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
    with connect(db_path) as conn:
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
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT resolution FROM safety_decisions WHERE run_id=? AND "
            "stage=? AND policy_version=? ORDER BY id DESC LIMIT 1",
            (run_id, stage, policy_version),
        ).fetchone()
    return bool(row and row["resolution"] == "approved")
