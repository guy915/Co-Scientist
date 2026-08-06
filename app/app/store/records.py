"""Per-run supporting records: evidence, citations, reviews, matches, safety.

Groups the simple insert/list helpers for the tables that hang off a run:
literature evidence and the claim-to-evidence citation links, reviewer
critiques, pairwise tournament matches, and safety-gate decisions. The
tournament matches live in ``app.store.records_matches``, the safety-gate
decisions in ``app.store.records_safety``, the proximity edges in
``app.store.records_proximity``, and the shared per-run listing query in
``app.store.records_support``; all are re-exported here so the module
namespace is unchanged.

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
from app.store.records_matches import NewMatch as NewMatch
from app.store.records_matches import _insert_match_row as _insert_match_row
from app.store.records_matches import add_match as add_match
from app.store.records_matches import count_matches as count_matches
from app.store.records_matches import list_matches as list_matches
from app.store.records_proximity import (
    NewProximityEdge as NewProximityEdge,
)
from app.store.records_proximity import (
    add_proximity_edge as add_proximity_edge,
)
from app.store.records_proximity import (
    list_proximity_edges as list_proximity_edges,
)
from app.store.records_safety import (
    NewSafetyDecision as NewSafetyDecision,
)
from app.store.records_safety import (
    add_safety_decision as add_safety_decision,
)
from app.store.records_safety import (
    list_safety_decisions as list_safety_decisions,
)
from app.store.records_safety import (
    resolve_safety_decision as resolve_safety_decision,
)
from app.store.records_safety import (
    safety_stage_is_approved as safety_stage_is_approved,
)
from app.store.records_support import _list_by_run as _list_by_run

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
    produced both.
    """

    run_id: str
    title: str
    source: str = "mock"
    url: str = ""
    authors: Iterable[str] | None = None
    year: int | None = None
    abstract: str = ""
    available: bool = True
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


def _evidence_passage_text(f: NewEvidence) -> str:
    """Materialize the exact passage a claim-evidence span indexes.

    Mirrors ``app.claim_grounding.evidence_passages``' text formula so the
    stored column and the text a span was located in never drift apart.
    """
    return " ".join(str(part or "") for part in (f.title, f.abstract)).strip()


def _insert_evidence_row(
    conn: sqlite3.Connection, ev_id: str, f: NewEvidence
) -> None:
    """Insert an evidence row for a run on an open connection."""
    conn.execute(
        "INSERT INTO evidence (id, run_id, title, source, url, "
        "authors_json, year, abstract, available, mime_type, sha256, "
        "byte_size, document_version, extraction_tool, doi, pmid, "
        "passage_text, retrieved_at, retrieval_score, retrieval_rationale, "
        "retriever_version, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            ev_id,
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
            f.doi,
            f.pmid,
            _evidence_passage_text(f),
            f.retrieved_at,
            f.retrieval_score,
            f.retrieval_rationale,
            f.retriever_version,
            _now(),
        ),
    )


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
        _insert_evidence_row(conn, ev_id, evidence)
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
        A list of evidence dicts with decoded authors and available fields.
    """
    out = []
    for d in _list_by_run("evidence", run_id, db_path, conn):
        d["authors"] = json.loads(d.pop("authors_json") or "[]")
        d["available"] = bool(d["available"])
        out.append(d)
    return out


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

    ``label`` is the entailment verdict ('supports' | 'contradicts' |
    'insufficient') and ``claim_role`` marks a categorical finding versus
    a visibly speculative proposal. ``supporting``/``contradicting`` are
    the spans for/against the claim -- JSON-serializable provenance
    objects (``{evidence_id, quote, start, end, source, url}``; legacy
    rows stored bare passage strings). ``assessor`` is the provenance id
    of the entailment assessor.
    """

    run_id: str
    hypothesis_id: str
    claim: str
    label: str
    supporting: Iterable[Any]
    contradicting: Iterable[Any]
    assessor: str
    claim_role: str = "categorical"


def _insert_claim_evidence_row(
    conn: sqlite3.Connection, edge: NewClaimEvidence
) -> None:
    """Insert one claim-level entailment edge on an open connection."""
    conn.execute(
        "INSERT INTO claim_evidence (run_id, hypothesis_id, claim, label, "
        "claim_role, supporting_json, contradicting_json, assessor, "
        "created_at) VALUES (?,?,?,?,?,?,?,?,?)",
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
        ),
    )


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
        _insert_claim_evidence_row(conn, edge)


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


@dataclass(frozen=True)
class NewReview:
    """One reviewer's assessment of a hypothesis, mirroring the row.

    ``reviewer_agent`` names the agent that produced the review (e.g.
    'reflection'); the four reviewer-assigned scores are optional.
    ``author`` and ``verdict`` carry a scientist reviewer's identity and
    categorical judgement as their own columns, so neither has to be
    recovered by reading the summary prose; both stay empty for an agent
    review.
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


def _insert_review_row(conn: sqlite3.Connection, review: NewReview) -> None:
    """Insert a reviewer's assessment of a hypothesis on an open connection."""
    conn.execute(
        "INSERT INTO reviews (run_id, hypothesis_id, "
        "reviewer_agent, summary, critique, "
        "novelty, plausibility, testability, overall, author, verdict, "
        "created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
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
            _now(),
        ),
    )


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
        _insert_review_row(conn, review)


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
