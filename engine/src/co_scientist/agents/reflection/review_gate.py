"""The initial peer-review gate and its scientist-criteria weighting.

Classifies freshly reviewed ideas against the review prompt's own quality
bands (finding K4's review half): only the "fundamentally flawed, not
viable" band blocks, and when the scientist supplied evaluation criteria
for the run those criteria select which scored axes the gate consults
instead of the built-in soundness/novelty pair. The reviewer's safety
axis is consulted on every run whatever the criteria (finding J8).
"""

from collections.abc import Sequence

from co_scientist.constants import (
    _NEUTRAL_SCORE,
    NEEDS_REVISION_SCORE,
    NOT_VIABLE_SCORE,
)
from co_scientist.models import Hypothesis, HypothesisReview

# The axes the gate consults when the scientist supplied no criteria. The
# historical default -- do not change it without also changing the rubric
# the review prompt hands the model.
_DEFAULT_GATE_AXES: tuple[str, ...] = ("scientific_soundness", "novelty")

# The one axis gated on every run, whatever criteria the scientist named
# (finding J8). The reviewer scored safety on all eight axes from the
# start and nothing read the score, so a review saying an idea carries a
# serious safety concern still sent it to the tournament. It is checked
# ahead of the rest so a rejection on safety is reported as such rather
# than as a soundness failure.
#
# The band is the same one every other axis blocks in, and it is the band
# the prompt itself defines: the rubric hands the model "10 = no concern,
# low = serious concern" for this axis and reserves 1-2 for "fundamentally
# flawed, not viable". This is deliberately not a second, independently
# tuned gate -- an idea in the rework band ranks and publishes here as
# everywhere else, and an omitted score reads as neutral (see
# ``_gate_score``), never as the worst one.
_SAFETY_AXIS = "safety"

# Keyword -> scored-axis table resolving a scientist criterion (free text)
# onto the review's eight scored axes (schemas/review.py). A criterion may
# map onto several axes ("translational feasibility" reaches both
# testability and impact); an axis is gated at most once whatever the
# criteria say. Matching is substring-on-lowercase, deliberately coarse:
# the gate only needs to know which axes the scientist cares about, and a
# criterion that matches nothing simply adds no axis.
_CRITERION_AXIS_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("scientific_soundness", ("sound", "rigor", "accura")),
    ("plausibility", ("plausib",)),
    ("novelty", ("novel", "origin", "innov")),
    ("relevance", ("relevan", "align")),
    ("testability", ("testab", "falsif", "experiment", "feasib", "verif")),
    ("safety", ("safe", "ethic", "risk")),
    ("clarity", ("clear", "clarit", "precis")),
    ("potential_impact", ("impact", "significan", "translat")),
)


def _gate_score(review: HypothesisReview, criterion: str) -> int:
    """One review score, defaulting to neutral rather than to the floor.

    A missing key used to read as 0 and disqualify the idea outright.
    Nothing guarantees the key is there: the schema marks every criterion
    required, but production routes structured output through a provider in
    json_object mode, which does not enforce a schema. An absent score is a
    review defect, and the idea should not pay for it.
    """
    value = review.scores.get(criterion)
    return _NEUTRAL_SCORE if value is None else int(value)


def _gate_axes_for_criteria(criteria: list[str] | None) -> tuple[str, ...]:
    """Resolve the scientist's criteria onto the review's scored axes.

    Args:
        criteria: The run's evaluation criteria, if any.

    Returns:
        The scored axes the gate consults, in first-match order. Absent or
        unmapped criteria fall back to the built-in soundness/novelty pair,
        so a run without criteria gates exactly as it always did (K4).
    """
    axes: list[str] = []
    for criterion in criteria or []:
        text = str(criterion).lower()
        for axis, keywords in _CRITERION_AXIS_KEYWORDS:
            if axis not in axes and any(word in text for word in keywords):
                axes.append(axis)
    return tuple(axes) or _DEFAULT_GATE_AXES


def _fatal_disposition(fatal_axes: Sequence[str]) -> str:
    """Map the not-viable axes onto the blocking disposition names.

    The two canonical axes keep their historical names; a fatal failure on
    any other scientist-selected axis also reads as not viable, so it
    reuses ``inaccurate`` -- a member of ``BLOCKING_REVIEW_DISPOSITIONS``,
    which is what the tournament and the drain actually read.
    """
    soundness_fatal = "scientific_soundness" in fatal_axes
    novelty_fatal = "novelty" in fatal_axes
    if soundness_fatal and novelty_fatal:
        return "inaccurate_and_non_novel"
    if soundness_fatal:
        return "inaccurate"
    if novelty_fatal:
        return "non_novel"
    return "inaccurate"


def _disposition_for(review: HypothesisReview, axes: Sequence[str]) -> str:
    """Map one review's gate scores onto a disposition.

    Args:
        review: The review whose scores are gated.
        axes: The scored axes the gate consults for this run.

    Returns:
        ``unsafe`` when the reviewer scored safety in the "not viable"
        band, the blocking disposition when any consulted axis falls in
        that band, ``needs_revision`` when the weakest consulted axis
        falls in the rework band, and ``viable`` otherwise.
    """
    if _gate_score(review, _SAFETY_AXIS) <= NOT_VIABLE_SCORE:
        return "unsafe"
    scores = {axis: _gate_score(review, axis) for axis in axes}
    fatal = [axis for axis in axes if scores[axis] <= NOT_VIABLE_SCORE]
    if fatal:
        return _fatal_disposition(fatal)
    if min(scores.values()) <= NEEDS_REVISION_SCORE:
        return "needs_revision"
    return "viable"


def _apply_initial_review_gate(
    hypotheses: list[Hypothesis],
    reviews: list[HypothesisReview],
    criteria: list[str] | None = None,
) -> None:
    """Classify ideas against the review prompt's own quality bands.

    The thresholds are the rubric the prompt hands the model, not a
    separate policy: only its "fundamentally flawed, not viable" band
    blocks. The gate previously blocked at <= 3, which caught the whole
    "major deficiencies, needs substantial rework" band as well -- a revise
    signal read as a discard signal.

    That is expensive twice over, because the disposition is never
    revisited. A blocked idea is barred from the Elo tournament, so it
    reads as "Disqualified" for the rest of the run, and it is skipped by
    comprehensive reflection. Worse, the surviving pool is what evolution
    breeds from: one production run blocked 20 of 22 ideas, leaving a
    tournament of two, an Elo ordering built from four matches, and an
    evolution pool that kept re-deriving the same drug.

    Ideas in the rework band are marked ``needs_revision``: rankable and
    publishable, so the tournament decides their fate on the evidence, but
    still excluded from the deep-review cascade so the run does not spend
    its budget on its weakest ideas.

    The reviewer's safety score is read on every run (J8) and blocks in
    that same not-viable band, as ``unsafe``. It is the only axis gated
    unconditionally: which quality axes matter is the scientist's call,
    while a review reporting a serious safety concern is not.

    When the run carries scientist evaluation criteria (K4), the criteria
    select which scored axes are gated -- a feasibility-focused goal gates
    testability as well as the built-in pair -- rather than only
    soundness and novelty ever deciding. Without criteria the default axes
    keep the historical behavior.

    Args:
        hypotheses: Hypotheses to classify, aligned with ``reviews``.
        reviews: One review per hypothesis, in the same order.
        criteria: The run's evaluation criteria, if any.
    """
    axes = _gate_axes_for_criteria(criteria)
    for hypothesis, review in zip(hypotheses, reviews, strict=True):
        hypothesis.review_disposition = _disposition_for(review, axes)
