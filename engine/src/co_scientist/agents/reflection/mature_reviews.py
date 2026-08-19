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
from co_scientist.models import BLOCKING_REVIEW_DISPOSITIONS, Hypothesis

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


def apply_mature_review_disposition(
    hypothesis: Hypothesis, review_type: ReviewType, result: dict[str, Any]
) -> None:
    """Reconcile the review disposition with one mature review finding.

    The mature cascade only reviews ideas the initial gate marked
    ``viable``, so the transitions start there:

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
    - every other verdict leaves the disposition alone.

    The update is monotonic: an existing blocking disposition is never
    downgraded, and ``needs_revision`` never overwrites ``viable`` only
    to be overwritten back.

    Args:
        hypothesis: The hypothesis the review belongs to.
        review_type: Which mature review produced the result.
        result: The review's structured output.
    """
    if hypothesis.review_disposition in BLOCKING_REVIEW_DISPOSITIONS:
        return
    if _is_fatal_mature_review(review_type, result):
        hypothesis.review_disposition = "inaccurate"
        return
    verdict = str(result.get("verdict") or "")
    if (
        verdict == "needs_revision"
        and review_type in (ReviewType.FULL, ReviewType.RECURRENT)
        and hypothesis.review_disposition == "viable"
    ):
        hypothesis.review_disposition = "needs_revision"


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
