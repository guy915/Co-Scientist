"""Storage, dispositions, and prompt projections for mature reviews.

The full, simulation, and recurrent reviews produced by the Reflection
agent's mature cascade (``comprehensive_reflection``) used to be written
to ``hypothesis.enrichments`` and read by nothing (audit E1/I3): a fatal
finding changed no disposition, and neither ranking, evolution,
meta-review, nor the report ever saw them.

This module is their single write path -- ``store_mature_review_result``
persists one result *and* reconciles the review disposition with fatal
findings -- and their shared prompt projection
(``mature_review_summary``), so the ranking judge, the evolution
specialist-feedback ledger, and the meta-review synthesis all read the
same bounded summary.
"""

from typing import Any

from co_scientist.agents.reflection.review_types import ReviewType
from co_scientist.models import Hypothesis

# Enrichment keys holding the three mature review results, in cascade
# order. Recurrent reviews reuse the full-review schema, so full and
# recurrent project identically.
MATURE_REVIEW_KEYS: tuple[str, ...] = ("full", "simulation", "recurrent")

# Reader-facing labels for the three mature review types.
MATURE_REVIEW_LABELS: dict[str, str] = {
    "full": "Full review",
    "simulation": "Simulation review",
    "recurrent": "Recurrent review",
}

# Verdicts that read as "not viable" under the gate's own bands: a full
# or recurrent review that rejects the idea outright, and a simulation
# whose mechanism breaks down at its decisive step. Every other verdict
# (sound, needs_revision, holds, partially_holds) is a revise-or-pass
# signal, never a discard signal -- the same asymmetry as the initial
# review gate.
_FATAL_VERDICTS: dict[ReviewType, frozenset[str]] = {
    ReviewType.FULL: frozenset({"rejected"}),
    ReviewType.RECURRENT: frozenset({"rejected"}),
    ReviewType.SIMULATION: frozenset({"breaks_down"}),
}

# The disposition each non-fatal mature verdict asserts. Only the full and
# recurrent reviews appear: they are the two that re-answer the same
# question the initial screen answered, so their verdict may replace it in
# either direction. A simulation "holds" answers a narrower question -- the
# mechanism's decisive step -- and asserts nothing about correctness, so it
# maps to no disposition and leaves the standing one alone.
_VERDICT_DISPOSITIONS: dict[tuple[ReviewType, str], str] = {
    (ReviewType.FULL, "sound"): "viable",
    (ReviewType.FULL, "needs_revision"): "needs_revision",
    (ReviewType.RECURRENT, "sound"): "viable",
    (ReviewType.RECURRENT, "needs_revision"): "needs_revision",
}

_MAX_JUSTIFICATION_CHARS = 400
_MAX_STEP_CHARS = 200
_MAX_FAILURE_POINT_CHARS = 160
_MAX_FAILURE_POINTS = 3
_MAX_FALSE_ASSUMPTIONS = 3


def _is_fatal_mature_review(
    review_type: ReviewType, result: dict[str, Any]
) -> bool:
    """Return whether one mature review result is a fatal finding."""
    verdict = str(result.get("verdict") or "")
    return verdict in _FATAL_VERDICTS.get(review_type, frozenset())


def mature_disposition(hypothesis: Hypothesis) -> str | None:
    """The disposition the stored mature reviews assert, if any.

    Read off the stored results rather than accumulated as they arrive, so
    the answer is a function of the record and one review call cannot be
    terminal for the rest of the run. ``None`` means the cascade has no
    opinion -- it has not run, or every verdict it recorded speaks to a
    narrower question than the disposition -- and the caller keeps
    whatever the initial screen derived.

    - a fatal verdict (full/recurrent ``rejected``, simulation
      ``breaks_down``) blocks exactly like the initial gate's not-viable
      band. The disposition reuses ``inaccurate`` -- the generic blocking
      member of ``BLOCKING_REVIEW_DISPOSITIONS`` that the tournament and
      the drain read -- while the stored enrichment records which review
      type rejected the idea.
    - a full/recurrent ``needs_revision`` verdict behaves like the
      initial gate's rework band: the idea still ranks and publishes, but
      leaves the deep-review cascade's ``viable`` filter so the budget is
      not re-spent on it.
    - a full/recurrent ``sound`` verdict clears the idea.

    Precedence *within* the cascade is unchanged and deliberately not
    "most recent wins": a fatal finding short-circuits, so a simulation
    whose mechanism holds never undoes a full review that rejected the
    idea's correctness. Between the cascade and the initial screen the
    cascade wins, because it asked the same question in more depth.

    Args:
        hypothesis: The hypothesis whose stored mature results are read.

    Returns:
        The asserted disposition, or None when the cascade is silent.
    """
    disposition: str | None = None
    for key in MATURE_REVIEW_KEYS:
        result = hypothesis.enrichments.get(key)
        if not isinstance(result, dict):
            continue
        review_type = ReviewType(key)
        if _is_fatal_mature_review(review_type, result):
            return "inaccurate"
        verdict = str(result.get("verdict") or "")
        disposition = _VERDICT_DISPOSITIONS.get(
            (review_type, verdict), disposition
        )
    return disposition


def apply_mature_review_disposition(
    hypothesis: Hypothesis, review_type: ReviewType, result: dict[str, Any]
) -> None:
    """Reconcile the review disposition with the stored mature findings.

    Called once per stored result by ``store_mature_review_result``, after
    the result is written, so it re-reads the whole cascade rather than
    ratcheting a single transition onto the standing value.

    ``review_type`` and ``result`` are the finding just stored; they are
    named for the caller's benefit and to keep the write path's signature
    stable -- the decision itself comes from ``mature_disposition``.

    Args:
        hypothesis: The hypothesis the review belongs to.
        review_type: Which mature review produced the result.
        result: The review's structured output.
    """
    del review_type, result
    disposition = mature_disposition(hypothesis)
    if disposition is not None:
        hypothesis.review_disposition = disposition


def reviews_needed(hypothesis: Hypothesis, iteration: int) -> list[ReviewType]:
    """Return the maturity-appropriate reviews due for one hypothesis.

    A hypothesis with no full review yet gets full + simulation; one
    already reviewed gets a recurrent review only if a later iteration
    has not yet been recorded.

    **A review whose result is already stored is not re-issued.** Maturity
    is read from the full review because that is what the phases turn on,
    but the two first-maturity reviews fail independently, and asking for
    both whenever the *full* one is missing re-ran a simulation review
    that had already succeeded -- on every later iteration, for as long
    as the full review kept failing. That was invisible while both were
    one LLM call each. It stopped being invisible when the simulation
    review gained a tool loop it pays for per firing.

    Refreshing a review against newer context is what the recurrent
    review is for; it is not what re-issuing a passed one does, since
    ``store_mature_review_result`` overwrites the earlier result rather
    than accumulating it.

    Args:
        hypothesis: The hypothesis whose reviews are being scheduled.
        iteration: The current workflow iteration.

    Returns:
        The review types due now, in the order they should be issued.
    """
    if ReviewType.FULL.value not in hypothesis.enrichments:
        return [
            review
            for review in (ReviewType.FULL, ReviewType.SIMULATION)
            if review.value not in hypothesis.enrichments
        ]
    recorded = int(hypothesis.enrichments.get("recurrent_review_iteration", -1))
    if iteration > recorded:
        return [ReviewType.RECURRENT]
    return []


def store_mature_review_result(
    hypothesis: Hypothesis,
    review_type: ReviewType,
    result: dict[str, Any],
    iteration: int,
) -> None:
    """Store one mature review result and apply its disposition effects.

    The single write path for full/simulation/recurrent results, shared
    by the in-process node and the durable fan-out aggregate, so both
    apply the same disposition reconciliation (audit E1).

    Args:
        hypothesis: The hypothesis the review belongs to.
        review_type: Which mature review produced the result.
        result: The review's structured output.
        iteration: The workflow iteration, stamped on recurrent reviews.
    """
    hypothesis.enrichments[review_type.value] = result
    if review_type is ReviewType.RECURRENT:
        hypothesis.enrichments["recurrent_review_iteration"] = iteration
    apply_mature_review_disposition(hypothesis, review_type, result)


def _clip_text(value: Any, limit: int) -> str:
    """Normalize whitespace and cap one prose field for prompt context."""
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _project_full_review(review: dict[str, Any]) -> dict[str, Any]:
    """Project one full/recurrent review into a bounded prompt summary."""
    projected: dict[str, Any] = {}
    verdict = str(review.get("verdict") or "")
    if verdict:
        projected["verdict"] = verdict
    justification = _clip_text(
        review.get("justification"), _MAX_JUSTIFICATION_CHARS
    )
    if justification:
        projected["justification"] = justification
    false_assumptions = [
        _clip_text(item.get("assumption"), _MAX_FAILURE_POINT_CHARS)
        for item in review.get("assumptions") or []
        if isinstance(item, dict) and item.get("support") == "likely_false"
    ][:_MAX_FALSE_ASSUMPTIONS]
    if false_assumptions:
        projected["assumptions_likely_false"] = false_assumptions
    return projected


def _project_simulation_review(review: dict[str, Any]) -> dict[str, Any]:
    """Project one simulation review into a bounded prompt summary."""
    projected: dict[str, Any] = {}
    verdict = str(review.get("verdict") or "")
    if verdict:
        projected["verdict"] = verdict
    decisive_step = _clip_text(review.get("decisive_step"), _MAX_STEP_CHARS)
    if decisive_step:
        projected["decisive_step"] = decisive_step
    failure_points = [
        _clip_text(point, _MAX_FAILURE_POINT_CHARS)
        for point in review.get("failure_points") or []
    ][:_MAX_FAILURE_POINTS]
    if failure_points:
        projected["failure_points"] = failure_points
    return projected


def mature_review_summary(
    enrichments: dict[str, Any] | None,
) -> dict[str, dict[str, Any]] | None:
    """Project a hypothesis's mature reviews into a bounded summary.

    Drops the retrieval bookkeeping the stored results carry
    (``retrieved_articles`` and friends are evidence for the review
    itself, not content for a downstream prompt) and caps every prose
    field, because the ranking judge reads this at O(n^2) per cycle.

    Args:
        enrichments: The hypothesis's enrichment dict, if any.

    Returns:
        A dict keyed by mature review type ("full", "simulation",
        "recurrent"), or None when no mature review has run yet -- the
        same omit-rather-than-hollow convention as
        ``Hypothesis.deep_verification_summary``.
    """
    if not enrichments:
        return None
    summary: dict[str, dict[str, Any]] = {}
    for key in MATURE_REVIEW_KEYS:
        review = enrichments.get(key)
        if not isinstance(review, dict):
            continue
        projected = (
            _project_simulation_review(review)
            if key == "simulation"
            else _project_full_review(review)
        )
        if projected:
            summary[key] = projected
    return summary or None
