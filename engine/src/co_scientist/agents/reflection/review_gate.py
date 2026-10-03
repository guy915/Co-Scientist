"""Review types, mature evidence, derived dispositions and bounded rechecks."""

from __future__ import annotations

import enum
from collections.abc import Iterable, Sequence
from typing import Any

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
from co_scientist.schemas import get_schema_for_prompt


class ReviewType(str, enum.Enum):
    """The six review types the Reflection agent can apply (SSR §4)."""

    INITIAL = "initial"
    FULL = "full"
    DEEP_VERIFICATION = "deep_verification"
    OBSERVATION = "observation"
    SIMULATION = "simulation"
    RECURRENT = "recurrent"


# Prompt-template stem backing each review type (get_schema_for_prompt resolves
# each stem to its structured-output schema).
_PROMPT_BY_TYPE: dict[ReviewType, str] = {
    ReviewType.INITIAL: "review",
    ReviewType.FULL: "full_review",
    ReviewType.DEEP_VERIFICATION: "deep_verification",
    ReviewType.OBSERVATION: "reflection_observations",
    ReviewType.SIMULATION: "simulation_review",
    ReviewType.RECURRENT: "full_review",
}


def prompt_name_for(review_type: ReviewType) -> str:
    """Return the prompt-template stem implementing a review type."""
    return _PROMPT_BY_TYPE[review_type]


def schema_for(review_type: ReviewType) -> dict[str, Any] | None:
    """Return the structured-output schema for a review type, if any."""
    return get_schema_for_prompt(_PROMPT_BY_TYPE[review_type])


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


# The review issued as a recheck. Not a free choice: it has to be one the
# cascade's own disposition table already reads (``mature_reviews``).
RECHECK_REVIEW_TYPE = ReviewType.RECURRENT

# Enrichment key recording that this hypothesis has had its one recheck.
# It rides in ``enrichments``, which is checkpointed with the hypothesis,
# so a run that resumes from SQLite does not re-fire the whole wave --
# a marker held only in memory turns a bounded cost into an unbounded one
# on every restart.
RECHECK_MARKER = "review_recheck_issued"

# The run-wide ceiling, over and above the per-hypothesis rule. Sized to
# cover the 22-idea incident run whole while bounding the largest pool
# this system has actually produced (46 ideas) to roughly 2% of the
# express tier's call budget.
MAX_RECHECKS_PER_RUN = 24

# The blocks this recheck owns: the review gate's own not-viable band
# (``review_gate._fatal_disposition``). Every other blocking value is
# decided elsewhere and must not be re-opened here -- ``unsafe`` is the
# reviewer's safety axis, which a correctness review is never asked
# about; ``evidence_blocked`` belongs to the app's pre-ranking evidence
# gate, which restores the disposition it displaced itself;
# ``review_failed`` records a call that produced no review to revisit;
# ``duplicate`` is proximity's archive marker. Stated as an allow-list so
# a new disposition elsewhere cannot silently become recheckable.
_RECHECKABLE_DISPOSITIONS: frozenset[str] = frozenset(
    {"inaccurate", "non_novel", "inaccurate_and_non_novel"}
)


def recheck_issued(hypothesis: Hypothesis) -> bool:
    """Return whether this hypothesis has already had its one recheck."""
    return bool(hypothesis.enrichments.get(RECHECK_MARKER))


def mark_recheck_issued(hypothesis: Hypothesis) -> None:
    """Record the recheck attempt, before its answer is known.

    Marked on issue rather than on success: a failed call has still spent
    the attempt, and re-firing on failure is how a bounded wave becomes a
    per-cycle one for exactly the ideas the reviewer keeps failing on.
    """
    hypothesis.enrichments[RECHECK_MARKER] = True


def _is_recheckable(hypothesis: Hypothesis) -> bool:
    """Return whether one blocked idea is this recheck's to re-open.

    The cascade having no opinion yet (``mature_disposition`` is None) is
    part of the test, not a shortcut: a hypothesis the cascade itself
    rejected carries the same ``inaccurate`` disposition, and its fatal
    verdict short-circuits, so a recurrent ``sound`` could never clear it.
    """
    if hypothesis.review_disposition not in _RECHECKABLE_DISPOSITIONS:
        return False
    # A block a scientist asked for is not the gate misfiring, so there is
    # nothing here to re-open: the derivation restores the verdict
    # whatever a recurrent review answers, and the call is spent for
    # nothing (see ``review_gate.derive_review_disposition``).
    if scientist_disposition(hypothesis) == "inaccurate":
        return False
    return mature_disposition(hypothesis) is None


def recheck_targets(hypotheses: Iterable[Hypothesis]) -> list[Hypothesis]:
    """Return the blocked ideas due one recurrent review, within budget.

    Both bounds are read off the pool rather than tracked in a counter, so
    they hold across a checkpoint round trip and a run resume without a
    state channel of their own.

    Args:
        hypotheses: The run's whole hypothesis pool.

    Returns:
        The hypotheses to recheck now, capped so the run's issued
        rechecks never exceed ``MAX_RECHECKS_PER_RUN``.
    """
    issued = 0
    pending: list[Hypothesis] = []
    for hypothesis in hypotheses:
        if recheck_issued(hypothesis):
            issued += 1
        elif _is_recheckable(hypothesis):
            pending.append(hypothesis)
    return pending[: max(MAX_RECHECKS_PER_RUN - issued, 0)]
