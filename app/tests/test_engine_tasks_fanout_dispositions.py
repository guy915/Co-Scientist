"""The durable review aggregate re-derives dispositions, pool-wide.

The durable path is the canonical mirror of the published per-hypothesis
review chaining (FIX-9), so it is also where the review disposition must
stop being a one-shot write (FIX-4): the aggregate re-derives every
hypothesis in the pool from the review record it holds, not only the ones
this batch reviewed.
"""

from typing import Any

from co_scientist.models import Hypothesis, HypothesisReview

from app.engine_tasks.fanout_aggregates import _apply_review_items


def _blocking_review() -> HypothesisReview:
    """An initial screen that lands in the not-viable band."""
    return HypothesisReview(
        review_summary="unsound",
        scores={"scientific_soundness": 2, "novelty": 8},
        safety_ethical_concerns="none",
        detailed_feedback={},
        constructive_feedback="rework",
        overall_score=3.0,
    )


def _blocked_hypothesis() -> Hypothesis:
    """A hypothesis the initial screen barred from the tournament."""
    hypothesis = Hypothesis(text="alpha", reviews=[_blocking_review()])
    hypothesis.review_disposition = "inaccurate"
    return hypothesis


def test_aggregate_reopens_an_idea_a_deeper_review_cleared() -> None:
    """A full review recorded since the last pass restores ranking."""
    hypothesis = _blocked_hypothesis()
    hypothesis.enrichments["full"] = {"verdict": "sound"}

    successful, failed, _ = _apply_review_items(
        {hypothesis.id: hypothesis}, [], None
    )

    assert (successful, failed) == (0, 0)
    assert hypothesis.is_rankable()


def test_aggregate_leaves_the_evidence_gate_s_disposition_alone() -> None:
    """``evidence_blocked`` belongs to the pre-ranking gate, which restores it.

    Re-deriving it here would strand the idea: the gate stores the
    disposition it displaced and puts that back itself.
    """
    hypothesis = _blocked_hypothesis()
    hypothesis.review_disposition = "evidence_blocked"
    hypothesis.enrichments["full"] = {"verdict": "sound"}

    _apply_review_items({hypothesis.id: hypothesis}, [], None)

    assert hypothesis.review_disposition == "evidence_blocked"


def test_aggregate_keeps_a_hypothesis_no_review_can_grade_untouched() -> None:
    """Nothing gradable held means nothing derived, not a clean bill."""
    hypothesis = Hypothesis(text="beta")

    _apply_review_items({hypothesis.id: hypothesis}, [], None)

    assert hypothesis.review_disposition is None


def test_aggregate_reads_the_run_s_criteria_when_re_deriving() -> None:
    """Scientist criteria select the axes, on the refresh path as well."""
    hypothesis = Hypothesis(
        text="gamma",
        reviews=[
            HypothesisReview(
                review_summary="weak experiment",
                scores={"scientific_soundness": 8, "testability": 1},
                safety_ethical_concerns="none",
                detailed_feedback={},
                constructive_feedback="design a test",
                overall_score=5.0,
            )
        ],
    )
    criteria: list[Any] = ["Discriminating experimental design"]

    _apply_review_items({hypothesis.id: hypothesis}, [], None, criteria)

    assert not hypothesis.is_rankable()
