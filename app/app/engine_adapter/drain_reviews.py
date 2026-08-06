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


# Reviewer label for a scientist-authored review, matching the row
# `runs_contrib.add_human_review` writes. Kept apart from the engine's
# "review" agent so a human review never reaches a reader as an anonymous
# agent one.
_SCIENTIST_REVIEWER = "scientist"


def _scientist_review_row_survives(
    source_id: str, conn: sqlite3.Connection
) -> bool:
    """Return whether the review's own stored row is still there.

    An unparseable id cannot name a row, so it reads as gone and the review
    is restored -- losing a human review is the worse of the two failures.
    """
    if not source_id.isdigit():
        return False
    return store.review_exists(int(source_id), conn=conn)


def _persist_scientist_review(
    run_id: str, hyp_id: str, rv: dict[str, Any], conn: sqlite3.Connection
) -> bool:
    """Restore a merged scientist review, or report that it needs no row.

    A scientist review reaches the drain because the merge carried it into
    engine state (``engine_tasks_inputs._scientist_hypothesis_review``),
    which is also where its author and verdict ride. Its own row usually
    survived the run's resets untouched -- scientist rows are deliberately
    retained -- so the drain must not write a second, differently-attributed
    copy of it. The one case that does need a row back is a review of an
    *agent* hypothesis: deleting that hypothesis for the replay cascades the
    human review away with it, and only engine state still holds it.

    Returns:
        Whether this review was handled here, so the generic per-review
        insert must skip it.
    """
    feedback = rv.get("detailed_feedback") or {}
    source_id = str(feedback.get("scientist_review_id") or "")
    if not source_id:
        return False
    if _scientist_review_row_survives(source_id, conn):
        return True
    store.add_review(
        store.NewReview(
            run_id=run_id,
            hypothesis_id=hyp_id,
            reviewer_agent=_SCIENTIST_REVIEWER,
            summary=rv.get("review_summary", ""),
            critique=str(feedback.get("scientist_critique") or ""),
            overall=_score_or_none(rv.get("overall_score", 0)),
            author=str(feedback.get("scientist_author") or ""),
            verdict=str(feedback.get("scientist_verdict") or "") or None,
        ),
        conn=conn,
    )
    return True


def _persist_engine_review_rows(
    run_id: str, hyp_id: str, h: dict[str, Any], conn: sqlite3.Connection
) -> None:
    """Persist a hypothesis's per-review rows from the engine's reviews list."""
    for rv in h.get("reviews") or []:
        if _persist_scientist_review(run_id, hyp_id, rv, conn):
            continue
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


# Enrichment key -> persisted reviewer_agent for the mature Reflection
# cascade's reviews (audit E1). Distinct agents keep the results apart in
# the UI instead of collapsing them under a single "Full review" row.
_MATURE_REVIEW_AGENTS: tuple[tuple[str, str, str], ...] = (
    ("full", "full_review", "Full review verdict"),
    ("simulation", "simulation_review", "Simulation review verdict"),
    ("recurrent", "recurrent_review", "Recurrent review verdict"),
)


def _format_mature_critique(key: str, review: dict[str, Any]) -> str:
    """Render one mature review result as the persisted critique text.

    Reads only the schema's content fields, so the retrieval bookkeeping
    the engine stores alongside each result never reaches the row.
    """
    lines: list[str] = []
    if key == "simulation":
        _append_simulation_critique(lines, review)
    else:
        _append_full_critique(lines, review)
    return "\n".join(lines).strip()


def _labeled_lines(pairs: tuple[tuple[str, Any], ...]) -> list[str]:
    """Render the non-empty members of (label, value) pairs as lines."""
    lines = []
    for label, value in pairs:
        text = str(value or "").strip()
        if text:
            lines.append(f"{label}: {text}")
    return lines


def _assumption_line(item: dict[str, Any]) -> str | None:
    """Render one full-review assumption entry, or None when empty."""
    assumption = str(item.get("assumption") or "").strip()
    if not assumption:
        return None
    support = str(item.get("support") or "").strip()
    return f"Assumption ({support or 'unrated'}): {assumption}"


def _append_full_critique(lines: list[str], review: dict[str, Any]) -> None:
    """Render the full/recurrent review's content fields."""
    lines += _labeled_lines(
        (
            ("Correctness", review.get("correctness")),
            ("Quality and novelty", review.get("quality_and_novelty")),
            ("Literature grounding", review.get("literature_grounding")),
            ("Justification", review.get("justification")),
        )
    )
    for item in review.get("assumptions") or []:
        if isinstance(item, dict) and (line := _assumption_line(item)):
            lines.append(line)


def _simulation_step_line(index: int, item: dict[str, Any]) -> str | None:
    """Render one simulation step entry, or None when empty."""
    step = str(item.get("step") or "").strip()
    if not step:
        return None
    plausible = "plausible" if item.get("plausible") else "implausible"
    return f"Step {index} ({plausible}): {step}"


def _simulation_step_lines(review: dict[str, Any]) -> list[str]:
    """Render the simulation review's numbered steps."""
    lines = []
    for index, item in enumerate(review.get("steps") or [], start=1):
        if isinstance(item, dict) and (
            line := _simulation_step_line(index, item)
        ):
            lines.append(line)
    return lines


def _failure_point_lines(review: dict[str, Any]) -> list[str]:
    """Render the simulation review's failure points."""
    lines = []
    for point in review.get("failure_points") or []:
        text = str(point).strip()
        if text:
            lines.append(f"Failure point: {text}")
    return lines


def _append_simulation_critique(
    lines: list[str], review: dict[str, Any]
) -> None:
    """Render the simulation review's content fields."""
    model = str(review.get("model") or "").strip()
    if model:
        lines.append(f"Simulated model: {model}")
    lines += _simulation_step_lines(review)
    lines += _failure_point_lines(review)
    lines += _labeled_lines(
        (
            ("Robustness", review.get("robustness")),
            ("Decisive step", review.get("decisive_step")),
        )
    )


def _persist_mature_review_rows(
    run_id: str,
    hyp_id: str,
    h: dict[str, Any],
    conn: sqlite3.Connection,
) -> None:
    """Persist the mature cascade's reviews as distinctly-labeled rows.

    The full, simulation, and recurrent reviews used to stop at the
    engine's enrichments (audit E1): the report reader never saw them.
    Each result present at drain time becomes its own review row under a
    distinct reviewer_agent, with the verdict as the row's summary.
    """
    enrichments = h.get("enrichments") or {}
    for key, reviewer_agent, verdict_label in _MATURE_REVIEW_AGENTS:
        review = enrichments.get(key)
        if not isinstance(review, dict):
            continue
        verdict = str(review.get("verdict") or "unspecified")
        store.add_review(
            store.NewReview(
                run_id=run_id,
                hypothesis_id=hyp_id,
                reviewer_agent=reviewer_agent,
                summary=f"{verdict_label}: {verdict}",
                critique=_format_mature_critique(key, review),
            ),
            conn=conn,
        )


def _persist_engine_reviews(
    run_id: str,
    hyp_id: str,
    h: dict[str, Any],
    conn: sqlite3.Connection,
) -> None:
    """Persist every review row one drained hypothesis carries."""
    _persist_engine_review_rows(run_id, hyp_id, h, conn)
    _persist_deep_verification_review(run_id, hyp_id, h, conn)
    _persist_mature_review_rows(run_id, hyp_id, h, conn)


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
