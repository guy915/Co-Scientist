"""Review and citation persistence for the final-state drain.

Extracted verbatim from ``app.engine_adapter.drain``: per-hypothesis review
rows (including the deep-verification review) and citation rows, classified
via the shared citation path. ``drain`` re-exports every name here, so the
original module namespace keeps resolving.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from app import store
from app.citations import CitationRecord, classify_citation
from app.report_render import format_deep_verification_critique


@dataclass(frozen=True)
class _CitationSink:
    """The drain's citation lookups, mutated in place as rows are written.

    Attributes:
        ev_id_by_title: Evidence id per source title; a citation may add its
            own source on the fly.
        abstract_by_title: Abstract per retrieved source title, used to
            classify a citation against the paper it cites.
        citation_summary: Running per-state citation counts.
    """

    ev_id_by_title: dict[str, str]
    abstract_by_title: dict[str, str]
    citation_summary: dict[str, int]


@dataclass(frozen=True)
class _CitationTarget:
    """The hypothesis row a citation attaches to, inside one transaction.

    Attributes:
        run_id: Run the citation belongs to.
        hyp_id: Persisted hypothesis row the citation attaches to.
        grounding: Claim text the citation is matched against.
        conn: Open connection of the caller's transaction.
    """

    run_id: str
    hyp_id: str
    grounding: str
    conn: sqlite3.Connection


def _score_or_none(value: Any) -> float | None:
    """Coerce a raw engine score to a float, treating 0/falsy as unset."""
    return float(value or 0) or None


def _persist_engine_review_rows(
    run_id: str, hyp_id: str, h: dict[str, Any], conn: sqlite3.Connection
) -> None:
    """Persist a hypothesis's per-review rows from the engine's reviews list."""
    for rv in h.get("reviews") or []:
        scores = rv.get("scores", {})
        store.add_review(
            store.NewReview(
                run_id=run_id,
                hypothesis_id=hyp_id,
                reviewer_agent="review",
                summary=rv.get("review_summary", ""),
                critique=rv.get("constructive_feedback", ""),
                novelty=_score_or_none(scores.get("novelty", 0)),
                plausibility=_score_or_none(
                    scores.get("scientific_soundness", 0)
                ),
                testability=_score_or_none(scores.get("testability", 0)),
                overall=_score_or_none(rv.get("overall_score", 0)),
            ),
            conn=conn,
        )


def _persist_deep_verification_review(
    run_id: str,
    hyp_id: str,
    h: dict[str, Any],
    conn: sqlite3.Connection,
) -> None:
    """Persist deep-verification probes as a dedicated review row, if any."""
    probes = h.get("deep_verification_probes") or []
    if not probes:
        return
    summary, critique = format_deep_verification_critique(
        probes, h.get("deep_verification_verdict")
    )
    store.add_review(
        store.NewReview(
            run_id=run_id,
            hypothesis_id=hyp_id,
            reviewer_agent="deep_verification",
            summary=summary,
            critique=critique,
        ),
        conn=conn,
    )


def _persist_engine_reviews(
    run_id: str,
    hyp_id: str,
    h: dict[str, Any],
    conn: sqlite3.Connection,
) -> None:
    """Persist a hypothesis's per-review rows plus its deep-verification row."""
    _persist_engine_review_rows(run_id, hyp_id, h, conn)
    _persist_deep_verification_review(run_id, hyp_id, h, conn)


def _ensure_citation_evidence_id(
    run_id: str,
    cite_title: str,
    cite_info: dict[str, Any],
    ev_id_by_title: dict[str, str],
    conn: sqlite3.Connection,
) -> str:
    """Return the evidence id for a cited source, adding it on the fly.

    Mutates `ev_id_by_title` in place when a new evidence row is added.

    Args:
        run_id: Run the cited source belongs to.
        cite_title: Title the source is keyed by.
        cite_info: The engine's raw citation entry.
        ev_id_by_title: Evidence id per source title, updated in place.
        conn: Open connection of the caller's transaction.

    Returns:
        The evidence id for the cited source.
    """
    cite_ev_id = ev_id_by_title.get(cite_title)
    if cite_ev_id is None:
        cite_ev_id = store.add_evidence(
            store.NewEvidence(
                run_id=run_id,
                title=cite_title,
                source=cite_info.get("type", "engine"),
                url=_citation_url(cite_info),
                authors=cite_info.get("authors") or [],
                year=cite_info.get("year"),
                abstract="",
                available=True,
            ),
            conn=conn,
        )
        ev_id_by_title[cite_title] = cite_ev_id
    return cite_ev_id


def _hypothesis_grounding_text(h: dict[str, Any]) -> str:
    """Return the literature-grounding text used as a citation's claim basis.

    Falls back to the hypothesis's own statement text, then to empty, when no
    dedicated grounding text was generated.
    """
    return str(h.get("literature_grounding") or h.get("text") or "")


def _citation_map(h: dict[str, Any]) -> dict[str, Any]:
    """Return a hypothesis's raw engine citation map, defaulting to empty."""
    return h.get("citation_map") or {}


def _citation_url(cite_info: dict[str, Any]) -> str:
    """Return a citation's URL, defaulting to empty (an unavailable source)."""
    return cite_info.get("url") or ""


def _citation_available(cite_info: dict[str, Any], cite_url: str) -> bool:
    """Return whether a cited source counts as available (not retracted)."""
    return (
        bool(cite_url)
        and not bool(cite_info.get("is_retracted"))
        and str(cite_info.get("correction_status") or "").lower() != "retracted"
    )


def _persist_one_citation(
    target: _CitationTarget,
    cite_key: str,
    cite_info: dict[str, Any],
    sink: _CitationSink,
) -> None:
    """Persist one hypothesis citation row, classifying and tallying it.

    Routes the citation through the shared classifier rather than hardcoding
    a state, so the four-state citation UI reflects real runs. The target's
    grounding is the claim the citation supports; it is matched against the
    cited paper's abstract (when the source was retrieved), and a source
    with no resolvable URL (e.g. a knowledge-graph statement) falls out as
    "unavailable".

    Mutates the sink's `ev_id_by_title` (a citation may add evidence for its
    source on the fly) and `citation_summary` (running citation-state
    counts) in place.

    Args:
        target: The hypothesis row, its claim text, and the transaction.
        cite_key: The engine's key for this citation.
        cite_info: The engine's raw citation entry.
        sink: The drain's citation lookups, updated in place.
    """
    cite_title = cite_info.get("title", cite_key)
    cite_url = _citation_url(cite_info)
    cite_ev_id = _ensure_citation_evidence_id(
        target.run_id,
        cite_title,
        cite_info,
        sink.ev_id_by_title,
        target.conn,
    )
    claim = f"[{cite_key}] cited in hypothesis"
    state = classify_citation(
        CitationRecord(
            url=cite_url,
            abstract=sink.abstract_by_title.get(cite_title, ""),
            claim=target.grounding,
            available=_citation_available(cite_info, cite_url),
        )
    )
    sink.citation_summary[state] += 1
    store.add_citation(
        store.NewCitation(
            run_id=target.run_id,
            hypothesis_id=target.hyp_id,
            evidence_id=cite_ev_id,
            claim=claim,
            state=state,
        ),
        conn=target.conn,
    )


def _persist_engine_citations(
    run_id: str,
    hyp_id: str,
    h: dict[str, Any],
    sink: _CitationSink,
    conn: sqlite3.Connection,
) -> None:
    """Persist a hypothesis's citations, classifying each via the shared path.

    Mutates the sink's `ev_id_by_title` (a citation may add evidence for its
    source on the fly) and `citation_summary` (running citation-state
    counts) in place; see `_persist_one_citation` for the per-citation
    classification rules.

    Args:
        run_id: Run the hypothesis belongs to.
        hyp_id: Persisted hypothesis row the citations attach to.
        h: The engine's raw hypothesis payload.
        sink: The drain's citation lookups, updated in place.
        conn: Open connection of the caller's transaction.
    """
    target = _CitationTarget(
        run_id, hyp_id, _hypothesis_grounding_text(h), conn
    )
    for cite_key, cite_info in _citation_map(h).items():
        _persist_one_citation(target, cite_key, cite_info, sink)
