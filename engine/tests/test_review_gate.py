"""Tests for the initial review gate's scientist-criteria weighting (K4).

The review stage scores eight fixed axes; historically only soundness and
novelty ever gated. When the run carries scientist evaluation criteria,
those criteria select the scored axes the gate consults. Without criteria
the built-in soundness/novelty pair keeps the historical behavior.
"""

import pytest

from co_scientist.agents.reflection.review_gate import (
    _apply_initial_review_gate,
    _gate_axes_for_criteria,
)
from co_scientist.models import HypothesisReview
from tests._state import make_hypothesis


def _review_with_scores(scores: dict[str, int]) -> HypothesisReview:
    """Build a review carrying the given per-axis scores."""
    return HypothesisReview(
        review_summary="summary",
        scores=scores,
        safety_ethical_concerns="none",
        detailed_feedback={},
        constructive_feedback="feedback",
        overall_score=5,
    )


def test_absent_criteria_keep_the_default_soundness_novelty_gate() -> None:
    """Without criteria the gate consults exactly the historical axes."""
    assert _gate_axes_for_criteria(None) == (
        "scientific_soundness",
        "novelty",
    )
    assert _gate_axes_for_criteria([]) == ("scientific_soundness", "novelty")


def test_unmapped_criteria_fall_back_to_the_default_axes() -> None:
    """Criteria matching no scored axis gate like no criteria at all."""
    axes = _gate_axes_for_criteria(["purely aesthetic presentation"])
    assert axes == ("scientific_soundness", "novelty")


def test_criteria_resolve_onto_the_matching_scored_axes() -> None:
    """Each criterion maps onto its axes; duplicates gate once."""
    axes = _gate_axes_for_criteria(
        [
            "Scientific soundness",
            "Novelty over known mechanisms",
            "Discriminating experimental design",
            "Translational feasibility",
        ]
    )
    assert axes == (
        "scientific_soundness",
        "novelty",
        "testability",
        "potential_impact",
    )


def test_the_apps_published_default_criteria_resolve_onto_axes() -> None:
    """R12-4: the app's rendered default criteria still gate soundness.

    ``app.run_modes.DEFAULT_CRITERIA`` renders as "Idea correctness:
    Required" etc. (``criteria_display_strings``) before it ever reaches
    this gate; this is that exact rendering, so a future edit to either
    side that stops mapping "correct" onto scientific_soundness is
    caught here rather than only showing up as a run that stops gating on
    it.
    """
    axes = _gate_axes_for_criteria(
        [
            "Idea correctness: Required",
            "Idea novelty: Required",
            "Maximize impact: Yes",
        ]
    )
    assert axes == ("scientific_soundness", "novelty", "potential_impact")


def test_a_fatal_criterion_axis_blocks_where_the_default_gate_would_not() -> (
    None
):
    """Criteria make their axes gate decisions, not just soundness/novelty.

    Soundness and novelty are both strong here, so the historical gate
    passes the idea; the scientist's testability criterion is fatally
    weak, and with criteria supplied that must block (K4).
    """
    hypothesis = make_hypothesis(text="idea")
    review = _review_with_scores(
        {
            "scientific_soundness": 8,
            "novelty": 8,
            "testability": 1,
        }
    )

    _apply_initial_review_gate(
        [hypothesis], [review], criteria=["Discriminating experimental design"]
    )

    assert hypothesis.review_disposition == "inaccurate"
    assert not hypothesis.is_rankable()


def test_the_same_scores_stay_viable_without_criteria() -> None:
    """The criteria-driven block above is the criteria's doing.

    Identical scores with no criteria supplied keep the historical
    soundness/novelty gate, which passes this idea.
    """
    hypothesis = make_hypothesis(text="idea")
    review = _review_with_scores(
        {
            "scientific_soundness": 8,
            "novelty": 8,
            "testability": 1,
        }
    )

    _apply_initial_review_gate([hypothesis], [review], criteria=None)

    assert hypothesis.review_disposition == "viable"
    assert hypothesis.is_rankable()


@pytest.mark.parametrize(
    ("criteria", "expected"),
    [
        (["Translational feasibility"], "needs_revision"),
        (["Scientific soundness"], "viable"),
    ],
    ids=["rework_band_on_criterion_axis", "strong_on_selected_axis"],
)
def test_criterion_axes_use_the_same_quality_bands(
    criteria: list[str], expected: str
) -> None:
    """Criteria change which axes gate, never the bands that block.

    A 4 on a selected axis is the prompt's rework band (rankable), not
    its not-viable band; a 5 is a pass. Only the not-viable band blocks.
    """
    hypothesis = make_hypothesis(text="idea")
    review = _review_with_scores(
        {
            "scientific_soundness": 8,
            "novelty": 8,
            "testability": 4,
            "potential_impact": 4,
        }
    )

    _apply_initial_review_gate([hypothesis], [review], criteria=criteria)

    assert hypothesis.review_disposition == expected


def test_canonical_axes_keep_their_disposition_names_under_criteria() -> None:
    """Soundness/novelty failures keep their historical dispositions."""
    unsound = make_hypothesis(text="unsound")
    stale = make_hypothesis(text="stale")
    review_unsound = _review_with_scores(
        {"scientific_soundness": 2, "novelty": 8, "testability": 8}
    )
    review_stale = _review_with_scores(
        {"scientific_soundness": 8, "novelty": 1, "testability": 8}
    )

    _apply_initial_review_gate(
        [unsound, stale],
        [review_unsound, review_stale],
        criteria=["Scientific soundness", "Novelty", "Testability"],
    )

    assert unsound.review_disposition == "inaccurate"
    assert stale.review_disposition == "non_novel"


def test_a_serious_safety_score_blocks_without_criteria() -> None:
    """The reviewer's safety verdict rejects, on every run (J8).

    The rubric hands the model "10 = no concern, low = serious concern"
    on the safety axis and reserves 1-2 for "fundamentally flawed, not
    viable". A review saying both is a rejection, and it must not depend
    on the scientist having named safety among the run's criteria.
    """
    hypothesis = make_hypothesis(text="idea")
    review = _review_with_scores(
        {"scientific_soundness": 8, "novelty": 8, "safety": 1}
    )

    _apply_initial_review_gate([hypothesis], [review], criteria=None)

    assert hypothesis.review_disposition == "unsafe"
    assert not hypothesis.is_rankable()


def test_a_missing_safety_score_does_not_block() -> None:
    """An omitted safety score is a review defect, not a safety verdict.

    Production routes structured output through json_object mode, which
    does not enforce the schema, so the key can simply be absent. Reading
    that as the worst score is how the previous gate disqualified whole
    pools.
    """
    hypothesis = make_hypothesis(text="idea")
    review = _review_with_scores({"scientific_soundness": 8, "novelty": 8})

    _apply_initial_review_gate([hypothesis], [review], criteria=None)

    assert hypothesis.review_disposition == "viable"
    assert hypothesis.is_rankable()


def test_a_safety_score_in_the_rework_band_still_ranks() -> None:
    """Only the not-viable band blocks, exactly as for the other axes."""
    hypothesis = make_hypothesis(text="idea")
    review = _review_with_scores(
        {"scientific_soundness": 8, "novelty": 8, "safety": 4}
    )

    _apply_initial_review_gate([hypothesis], [review], criteria=None)

    assert hypothesis.review_disposition == "viable"
    assert hypothesis.is_rankable()


def test_a_safety_rejection_outranks_a_soundness_rejection() -> None:
    """An idea rejected on safety is reported as unsafe, not inaccurate."""
    hypothesis = make_hypothesis(text="idea")
    review = _review_with_scores(
        {"scientific_soundness": 1, "novelty": 1, "safety": 1}
    )

    _apply_initial_review_gate([hypothesis], [review], criteria=None)

    assert hypothesis.review_disposition == "unsafe"
