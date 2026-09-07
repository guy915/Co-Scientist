"""The review disposition is derived from the record, not written once.

No published listing has the initial-review gate at all (Nature SI Note 8,
``03-reflection.md``), so the mirror direction is that one review call may
not be terminal for the rest of the run. These tests pin the *shape* of
that control flow rather than any threshold: a later, deeper review
governs the disposition, a review carrying none of the gated axes does
not, and re-derivation leaves the dispositions other subsystems own
alone.
"""

from typing import Any

import pytest

from co_scientist.agents.reflection.review import review_node
from co_scientist.agents.reflection.review_gate import (
    derive_review_disposition,
    refresh_review_dispositions,
)
from co_scientist.agents.reflection.review_types import ReviewType
from co_scientist.models import Hypothesis, HypothesisReview
from tests._state import make_hypothesis, make_state


def _gate_review(soundness: int, novelty: int) -> HypothesisReview:
    """Build a review carrying only the two axes the default gate reads."""
    return HypothesisReview(
        review_summary="summary",
        scores={"scientific_soundness": soundness, "novelty": novelty},
        safety_ethical_concerns="none",
        detailed_feedback={},
        constructive_feedback="feedback",
        overall_score=5,
    )


def _scientist_review() -> HypothesisReview:
    """A merged human review: it scores no axis this gate consults."""
    return HypothesisReview(
        review_summary="[scientist-review:7] looks promising",
        scores={"scientist_assessment": 8},
        safety_ethical_concerns="",
        detailed_feedback={"scientist_verdict": "accept"},
        constructive_feedback="promising",
        overall_score=8.0,
    )


def _blocked_hypothesis(**overrides: Any) -> Hypothesis:
    """A hypothesis the initial screen blocked as scientifically unsound."""
    hypothesis = make_hypothesis(
        reviews=[_gate_review(soundness=2, novelty=8)], **overrides
    )
    hypothesis.review_disposition = "inaccurate"
    return hypothesis


def _full_review_result(verdict: str) -> dict[str, Any]:
    """One stored mature full-review result carrying ``verdict``."""
    return {"verdict": verdict, "justification": "because"}


def test_a_deeper_review_clears_the_initial_screen_block() -> None:
    """A later full review that finds the idea sound restores ranking."""
    hypothesis = _blocked_hypothesis()
    hypothesis.enrichments[ReviewType.FULL.value] = _full_review_result("sound")

    assert not hypothesis.is_rankable()
    refresh_review_dispositions([hypothesis])

    assert hypothesis.review_disposition == "viable"
    assert hypothesis.is_rankable()


def test_a_deeper_review_can_still_block() -> None:
    """Revisability runs both ways: a fatal deep verdict blocks a pass."""
    hypothesis = make_hypothesis(reviews=[_gate_review(8, 8)])
    hypothesis.review_disposition = "viable"
    hypothesis.enrichments[ReviewType.FULL.value] = _full_review_result(
        "rejected"
    )

    refresh_review_dispositions([hypothesis])

    assert hypothesis.review_disposition == "inaccurate"
    assert not hypothesis.is_rankable()


def test_a_narrower_later_review_does_not_undo_a_fatal_one() -> None:
    """Simulation answers a narrower question than the full review.

    Deepest-wins is between the initial screen and the mature cascade, not
    within the cascade: a simulation whose mechanism holds says nothing
    about the correctness a full review already rejected.
    """
    hypothesis = make_hypothesis(reviews=[_gate_review(8, 8)])
    hypothesis.enrichments[ReviewType.FULL.value] = _full_review_result(
        "rejected"
    )
    hypothesis.enrichments[ReviewType.SIMULATION.value] = {"verdict": "holds"}

    refresh_review_dispositions([hypothesis])

    assert hypothesis.review_disposition == "inaccurate"


def test_a_correctness_verdict_does_not_clear_a_safety_block() -> None:
    """The cascade is never asked about safety, so it cannot answer it.

    Which quality axes matter is the scientist's call; a review reporting
    a serious safety concern is not (J8). A full review finding the idea
    scientifically sound says nothing about that concern.
    """
    hypothesis = make_hypothesis(reviews=[_gate_review(8, 8)])
    hypothesis.reviews[0].scores["safety"] = 1
    hypothesis.review_disposition = "unsafe"
    hypothesis.enrichments[ReviewType.FULL.value] = _full_review_result("sound")

    refresh_review_dispositions([hypothesis])

    assert hypothesis.review_disposition == "unsafe"
    assert not hypothesis.is_rankable()


def test_a_review_scoring_no_gated_axis_does_not_decide_the_gate() -> None:
    """A merged human review must not silently clear every block.

    It scores ``scientist_assessment`` alone, so reading it through the
    gate's neutral default would mark every blocked idea viable on any run
    a scientist reviewed.
    """
    hypothesis = _blocked_hypothesis()
    hypothesis.reviews.append(_scientist_review())

    refresh_review_dispositions([hypothesis])

    assert hypothesis.review_disposition == "inaccurate"


def test_the_most_recent_gated_review_wins_over_the_first() -> None:
    """Two agent reviews: the later one decides, not the one that landed."""
    hypothesis = _blocked_hypothesis()
    hypothesis.reviews.append(_gate_review(soundness=9, novelty=8))

    assert derive_review_disposition(hypothesis) == "viable"


@pytest.mark.parametrize(
    "foreign", ["evidence_blocked", "review_failed", "duplicate"]
)
def test_dispositions_owned_elsewhere_are_left_alone(foreign: str) -> None:
    """The gate re-derives only the dispositions it writes.

    ``evidence_blocked`` is the app's pre-ranking evidence gate, which
    stores the disposition it displaced and restores that itself;
    ``review_failed`` records a call that produced no review at all; and
    ``duplicate`` is proximity's archive marker.
    """
    hypothesis = make_hypothesis(reviews=[_gate_review(8, 8)])
    hypothesis.review_disposition = foreign

    refresh_review_dispositions([hypothesis])

    assert hypothesis.review_disposition == foreign


def test_an_unreviewed_hypothesis_keeps_its_absent_disposition() -> None:
    """Nothing to derive from is not the same as a clean bill of health."""
    hypothesis = make_hypothesis()

    refresh_review_dispositions([hypothesis])

    assert hypothesis.review_disposition is None


@pytest.mark.asyncio
async def test_review_node_revisits_dispositions_with_nothing_to_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pass that reviews nothing is exactly when a deeper verdict lands.

    ``review_node`` short-circuits when every hypothesis already holds a
    review. That early return is where a mature-cascade verdict recorded
    since the last pass has to be honoured, otherwise the first screen
    stays terminal for the rest of the run.
    """
    hypothesis = _blocked_hypothesis()
    hypothesis.enrichments[ReviewType.FULL.value] = _full_review_result("sound")
    state = make_state(hypotheses=[hypothesis])

    async def _fail(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("review_node must not call the LLM here")

    monkeypatch.setattr(
        "co_scientist.agents.reflection.review.call_llm_json", _fail
    )

    await review_node(state)

    assert hypothesis.is_rankable()


def test_evolution_children_re_enter_review_unreviewed() -> None:
    """An evolved idea is a fresh entrant, so review sees it again.

    Evolution never rewrites a hypothesis in place --
    ``_build_evolution_child`` constructs a new one with ``reviews=[]``
    (SSR §4, §12) -- so the rewritten idea is already selected by the same
    unreviewed filter both execution paths use, at no additional LLM cost
    beyond the review it was always going to get.
    """
    from co_scientist.agents.evolution.evolve_results import (
        _build_evolution_child,
        _RefinedFields,
    )

    parent = _blocked_hypothesis()
    child = _build_evolution_child(
        [parent],
        _RefinedFields(
            refined_text="a rewritten idea",
            explanation="why",
            experiment="how",
            refinement_summary="what changed",
            title="Rewritten",
        ),
        creation_iteration=1,
    )

    assert child.reviews == []
    assert child.review_disposition is None
