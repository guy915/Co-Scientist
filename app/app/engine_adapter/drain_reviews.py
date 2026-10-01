"""Review persistence for the final-state drain.

Extracted verbatim from ``app.engine_adapter.drain``: per-hypothesis review
rows, covering the scientist-authored review, the engine's own review list,
the deep-verification review, and the mature Reflection cascade. ``drain``
re-exports the names its callers and tests use, so the original module
namespace keeps resolving for them.

The citation half of the original module now lives in ``drain_citations``
(split out when this file outgrew the 500-line ceiling), and the structured
``detail_json`` builders in ``drain_review_detail`` (split out when
persisting the report's review block took it past the ceiling a second
time); the names importers use are re-exported below, so importers written
against ``drain_reviews`` -- ``drain`` and ``drain_hypotheses`` among them
-- keep resolving unchanged.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app import store
from app.engine_adapter.drain_citations import (
    _CitationSink as _CitationSink,
)
from app.engine_adapter.drain_citations import (
    _persist_engine_citations as _persist_engine_citations,
)
from app.engine_adapter.drain_review_detail import (
    _ASSUMPTION_SUPPORT_LABELS as _ASSUMPTION_SUPPORT_LABELS,
)
from app.engine_adapter.drain_review_detail import (
    _deep_verification_detail as _deep_verification_detail,
)
from app.engine_adapter.drain_review_detail import (
    _detail_json as _detail_json,
)
from app.engine_adapter.drain_review_detail import (
    _initial_review_detail as _initial_review_detail,
)
from app.engine_adapter.drain_review_detail import (
    _mature_review_detail as _mature_review_detail,
)
from app.engine_adapter.drain_review_detail import (
    _review_detail_json as _review_detail_json,
)
from app.engine_adapter.drain_review_detail import (
    _simulation_detail as _simulation_detail,
)
from app.engine_adapter.drain_review_detail import (
    _verdict_detail as _verdict_detail,
)
from app.report_render import format_deep_verification_critique


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


def _novelty_review_lines(rv: dict[str, Any]) -> list[str]:
    """Render the published novelty review's two named lists (MO-3).

    Google's exemplar (docs/CORPUS-EXTRACTION.md,
    reviews/als-reflection-reviews.md -- 106 lines, sha256 2f486c549886,
    Figure A.11) prints a novelty review as "Aspects already explored:" and
    "Novel Aspects:", each a bulleted list. Empty when the review named
    nothing in either list.
    """
    already = [str(x).strip() for x in rv.get("already_explored") or []]
    already = [x for x in already if x]
    novel = [str(x).strip() for x in rv.get("novel_aspects") or []]
    novel = [x for x in novel if x]
    lines: list[str] = []
    if already:
        lines += ["Aspects already explored:"]
        lines += [f"- {item}" for item in already]
    if novel:
        if lines:
            lines.append("")
        lines += ["Novel Aspects:"]
        lines += [f"- {item}" for item in novel]
    return lines


def _persist_engine_review_rows(
    run_id: str, hyp_id: str, h: dict[str, Any], conn: sqlite3.Connection
) -> None:
    """Persist a hypothesis's per-review rows from the engine's reviews list."""
    for rv in h.get("reviews") or []:
        if _persist_scientist_review(run_id, hyp_id, rv, conn):
            continue
        scores = rv.get("scores", {})
        critique_lines = [str(rv.get("constructive_feedback") or "")]
        novelty_lines = _novelty_review_lines(rv)
        if novelty_lines:
            critique_lines += ["", *novelty_lines]
        store.add_review(
            store.NewReview(
                run_id=run_id,
                hypothesis_id=hyp_id,
                reviewer_agent="review",
                summary=rv.get("review_summary", ""),
                critique="\n".join(critique_lines).strip(),
                novelty=_score_or_none(scores.get("novelty", 0)),
                plausibility=_score_or_none(
                    scores.get("scientific_soundness", 0)
                ),
                testability=_score_or_none(scores.get("testability", 0)),
                overall=_score_or_none(rv.get("overall_score", 0)),
                detail_json=_detail_json(_initial_review_detail(rv)),
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
            detail_json=_detail_json(
                _deep_verification_detail(
                    probes, h.get("deep_verification_verdict")
                )
            ),
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
    """Render one full-review assumption entry, or None when empty.

    ``reasoning`` (MO-9) is the published free-text paragraph explaining the
    support verdict; appended when present so a hypothesis reviewed through
    full review alone still carries it, the way deep verification's
    ``sub_assumptions[].verification`` always has.

    This line is baked into the review's persisted ``critique`` text at
    drain time (``_format_mature_critique``, below), not recomputed on
    read -- so a run drained before this label mapping existed keeps
    reading "Assumption (supported): ..." forever; only a newly drained
    run picks up the published wording. Deep verification's own
    ``sub_assumptions[].status`` is a separate field this function never
    sees -- it is not rendered to a reader anywhere in this codebase (only
    its sibling ``probes``/``verdict`` are, via
    ``format_deep_verification_critique``), so this change does not touch
    it.
    """
    assumption = str(item.get("assumption") or "").strip()
    if not assumption:
        return None
    support = str(item.get("support") or "").strip()
    label = _ASSUMPTION_SUPPORT_LABELS.get(support, support or "unrated")
    line = f"Assumption ({label}): {assumption}"
    reasoning = str(item.get("reasoning") or "").strip()
    if reasoning:
        line += f" — {reasoning}"
    return line


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
                detail_json=_review_detail_json(key, review),
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
