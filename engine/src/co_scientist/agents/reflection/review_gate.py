"""The peer-review gate and its scientist-criteria weighting.

Classifies reviewed ideas against the review prompt's own quality bands
(finding K4's review half): only the "fundamentally flawed, not viable"
band blocks, and when the scientist supplied evaluation criteria for the
run those criteria select which scored axes the gate consults instead of
the built-in soundness/novelty pair. The reviewer's safety axis is
consulted on every run whatever the criteria (finding J8).

``review_disposition`` is *derived* from the review record a hypothesis
holds, not written once when its first review lands: see
:func:`derive_review_disposition`.
"""

from collections.abc import Iterable, Sequence

from co_scientist.agents.reflection.mature_reviews import mature_disposition
from co_scientist.constants import (
    _NEUTRAL_SCORE,
    NEEDS_REVISION_SCORE,
    NOT_VIABLE_SCORE,
)
from co_scientist.models import (
    SCIENTIST_REVIEWER,
    Hypothesis,
    HypothesisReview,
)

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
# "correct" was added for R12-4: the app's default run-level criteria now
# render as "Idea correctness: Required" (mirroring Google's published run
# plan), which named no existing keyword here and would otherwise have
# silently stopped gating scientific_soundness on every default run.
_CRITERION_AXIS_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("scientific_soundness", ("sound", "rigor", "accura", "correct")),
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


# Every axis the review schema scores, and so every axis this gate can
# read per-axis. A review carrying none of them is not an input to
# :func:`_disposition_for`: reading a review that scores something else
# through ``_gate_score``'s neutral default would mark every blocked idea
# viable. A merged scientist review is exactly that shape (it scores
# ``scientist_assessment`` alone), which is why it is excluded by
# authorship rather than by its axes and read as a whole verdict instead
# (see :func:`_scientist_disposition`).
_SCORED_AXES: frozenset[str] = frozenset(
    axis for axis, _ in _CRITERION_AXIS_KEYWORDS
)

# Dispositions this gate does not own and must never recompute.
# ``evidence_blocked`` belongs to the app's pre-ranking evidence gate,
# which stores the disposition it displaced and restores that itself, so
# overwriting it here would strand the idea; ``review_failed`` records a
# call that produced no review at all; ``duplicate`` is proximity's
# archive marker (the app's
# ``drain.hypotheses.DEDUPLICATED_REVIEW_DISPOSITION``, spelled out here
# because the engine may not import the app), and an archived duplicate
# still holds a gradable review, so re-deriving it would resurrect it.
_FOREIGN_DISPOSITIONS: frozenset[str] = frozenset(
    {"evidence_blocked", "review_failed", "duplicate"}
)

# The one derived disposition a deeper review may not overturn. The mature
# cascade judges correctness, quality and novelty (``FULL_REVIEW_SCHEMA``);
# it is never asked about safety, so its verdict asserts nothing about it.
# Which quality axes matter is the scientist's call, a reported safety
# concern is not (J8) -- so the safety block outranks the cascade in the
# one direction that would clear it, while ``inaccurate``/``non_novel``
# are exactly what a deeper correctness review is entitled to revisit.
_UNSAFE_DISPOSITION = "unsafe"


def _deepest_disposition(hypothesis: Hypothesis, base: str) -> str:
    """Let the mature cascade's verdict supersede a shallower one."""
    if base == _UNSAFE_DISPOSITION:
        return base
    return mature_disposition(hypothesis) or base


def _latest_gradable_review(
    hypothesis: Hypothesis,
) -> HypothesisReview | None:
    """The most recent agent review scoring an axis this gate reads."""
    for review in reversed(hypothesis.reviews):
        if review.reviewer == SCIENTIST_REVIEWER:
            continue
        if _SCORED_AXES.intersection(review.scores):
            return review
    return None


def _latest_scientist_review(
    hypothesis: Hypothesis,
) -> HypothesisReview | None:
    """The most recent scientist verdict, superseding any earlier one."""
    for review in reversed(hypothesis.reviews):
        if review.reviewer == SCIENTIST_REVIEWER:
            return review
    return None


def scientist_disposition(hypothesis: Hypothesis) -> str | None:
    """The disposition the most recent scientist verdict asserts, if any.

    The verdict arrives on the same 1-10 rubric the review prompt hands
    the model (``human_input.VERDICT_REVIEW_SCORES`` maps support/revise/
    oppose onto its bands), so it is read in exactly the bands every other
    review is read in rather than through a second, independently tuned
    policy.

    Returns:
        The scientist's own disposition, or None when no scientist has
        reviewed this hypothesis.
    """
    review = _latest_scientist_review(hypothesis)
    if review is None:
        return None
    if review.overall_score <= NOT_VIABLE_SCORE:
        return "inaccurate"
    if review.overall_score <= NEEDS_REVISION_SCORE:
        return "needs_revision"
    return "viable"


def derive_review_disposition(
    hypothesis: Hypothesis, criteria: list[str] | None = None
) -> str | None:
    """Derive one hypothesis's disposition from the record it holds.

    No published listing has this gate at all (Nature SI Note 8,
    ``03-reflection.md``), which is why it may not be terminal: the
    disposition is a function of every review the hypothesis carries, so
    a later and deeper verdict replaces an earlier one instead of being
    unable to reach it. The two layers, shallowest first:

    1. the most recent review scoring a gated axis -- so a re-review
       supersedes the screen that ran before it, rather than the first
       call deciding the idea's standing for the whole run;
    2. the mature cascade's own verdict (``mature_disposition``), which
       wins when it has one because it asked the same question in more
       depth -- except over ``unsafe``, an axis it was never asked about
       (see ``_UNSAFE_DISPOSITION``);
    3. the most recent scientist verdict, which wins over both for the
       same reason and carries the same safety carve-out (see
       :func:`_scientist_disposition`). This is what makes a
       contributed review reach the tournament, the deep-review cascade
       and the evolution pool instead of only the reviews table.

    Args:
        hypothesis: The hypothesis whose disposition is derived.
        criteria: The run's evaluation criteria, if any.

    Returns:
        The derived disposition, or the standing one when the hypothesis
        holds no review this gate can read.
    """
    review = _latest_gradable_review(hypothesis)
    base = (
        hypothesis.review_disposition
        if review is None
        else _deepest_disposition(
            hypothesis,
            _disposition_for(review, _gate_axes_for_criteria(criteria)),
        )
    )
    # Applied last because a human who has read the idea is the most
    # informed reviewer the run has: an oppose withholds an idea the
    # agents cleared, and a support releases one they called inaccurate or
    # asked to rework. The one verdict it cannot reach is ``unsafe`` --
    # which quality axes matter is the scientist's call, but no
    # endorsement releases an idea a reviewer flagged as a serious safety
    # concern (the carve-out the mature cascade gets, for the same
    # reason). ``evidence_blocked`` and ``duplicate`` are out of reach one
    # layer up: ``refresh_review_dispositions`` never recomputes a foreign
    # disposition.
    scientist = scientist_disposition(hypothesis)
    if scientist is None or base == _UNSAFE_DISPOSITION:
        return base
    return scientist


def refresh_review_dispositions(
    hypotheses: Iterable[Hypothesis], criteria: list[str] | None = None
) -> int:
    """Re-derive every hypothesis's disposition from its review record.

    Costs no LLM calls: it reads reviews the run already paid for. Run it
    wherever the record can have grown since the disposition was last
    written -- a later review pass, a merged scientist review, a mature
    verdict recorded between passes -- so a blocking value set by one
    early call cannot bar an idea from the tournament, the deep-review
    cascade and the evolution pool for the rest of the run.

    Args:
        hypotheses: The pool to re-derive over.
        criteria: The run's evaluation criteria, if any.

    Returns:
        How many dispositions changed.
    """
    revised = 0
    for hypothesis in hypotheses:
        if hypothesis.review_disposition in _FOREIGN_DISPOSITIONS:
            continue
        disposition = derive_review_disposition(hypothesis, criteria)
        if disposition != hypothesis.review_disposition:
            hypothesis.review_disposition = disposition
            revised += 1
    return revised


def apply_initial_review_gate(
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

    That band matters because a blocking value is expensive: a blocked
    idea is barred from the Elo tournament, so it reads as "Disqualified",
    and it is skipped by comprehensive reflection. Worse, the surviving
    pool is what evolution breeds from -- one production run blocked 20 of
    22 ideas, leaving a tournament of two, an Elo ordering built from four
    matches, and an evolution pool that kept re-deriving the same drug.
    The value written here is therefore the *current* derivation, not a
    verdict: ``refresh_review_dispositions`` re-derives it from the whole
    record whenever that record grows, so no single call is terminal.

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
        base = _disposition_for(review, axes)
        hypothesis.review_disposition = _deepest_disposition(hypothesis, base)


# Compatibility for library callers of the former private helper.
_apply_initial_review_gate = apply_initial_review_gate
