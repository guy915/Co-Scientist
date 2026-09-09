"""A scientist's review is a verdict the gate reads, not a peer review.

Two separate obligations meet on the same record (PARITY
``HITL-MANUAL-REVIEW-001``). A scientist-contributed review must *reach*
the disposition every later stage reads -- the tournament, the deep-review
cascade, the evolution pool -- rather than being stored and ignored. And
it must not *stand in for* the agent peer review the run owes every
hypothesis: a review holding only a human verdict left the idea marked
reviewed, so the review node, the durable review fan-out and the
scheduler's unreviewed backlog all skipped it and it competed ungated.
"""

from co_scientist.agents.reflection.review_gate import (
    derive_review_disposition,
    refresh_review_dispositions,
)
from co_scientist.agents.supervisor.orchestrator_stats import (
    _compute_stats,
    _default_budget,
)
from co_scientist.constants import NEEDS_REVISION_SCORE, NOT_VIABLE_SCORE
from co_scientist.models import (
    SCIENTIST_REVIEWER,
    Hypothesis,
    HypothesisReview,
    has_peer_review,
)
from co_scientist.scheduling.models import TaskType
from co_scientist.scheduling.policy import required_transition
from co_scientist.state import WorkflowState
from tests._state import make_hypothesis, make_state


def _agent_review(**scores: int) -> HypothesisReview:
    """Build an agent review carrying the given per-axis scores."""
    return HypothesisReview(
        review_summary="agent summary",
        scores={"scientific_soundness": 8, "novelty": 8, "safety": 9, **scores},
        safety_ethical_concerns="none",
        detailed_feedback={},
        constructive_feedback="feedback",
        overall_score=8,
    )


def _scientist_review(score: int) -> HypothesisReview:
    """Build a merged scientist review as the app's merge shapes one."""
    return HypothesisReview(
        review_summary="[scientist-review:7] Scientist verdict",
        scores={"scientist_assessment": score},
        safety_ethical_concerns="",
        detailed_feedback={"scientist_verdict": "oppose"},
        constructive_feedback="the control cannot distinguish the mechanism",
        overall_score=float(score),
        reviewer=SCIENTIST_REVIEWER,
    )


def _hypothesis_with(*reviews: HypothesisReview) -> Hypothesis:
    """Build a hypothesis holding the given reviews, in order."""
    hypothesis = make_hypothesis("A proposed mechanism for kinase X")
    hypothesis.reviews.extend(reviews)
    return hypothesis


def test_a_scientist_review_alone_is_not_a_peer_review() -> None:
    """The run still owes an agent review to a human-reviewed idea."""
    assert not has_peer_review(_hypothesis_with(_scientist_review(2)))
    assert has_peer_review(_hypothesis_with(_agent_review()))
    assert has_peer_review(
        _hypothesis_with(_scientist_review(2), _agent_review())
    )


def test_the_scheduler_still_counts_a_human_reviewed_idea_unreviewed() -> None:
    """Policy step 5 forces a review pass before ranking or evolving."""
    state = make_state()
    state["hypotheses"] = [_hypothesis_with(_scientist_review(8))]

    stats = _compute_stats(state, {})

    assert stats.reviewed_count == 0
    assert stats.unreviewed_count == 1


def test_an_opposing_scientist_verdict_withholds_the_idea() -> None:
    """An expert's oppose reaches the disposition the tournament reads."""
    hypothesis = _hypothesis_with(
        _agent_review(), _scientist_review(NOT_VIABLE_SCORE)
    )

    assert refresh_review_dispositions([hypothesis]) == 1
    assert hypothesis.review_disposition == "inaccurate"
    assert not hypothesis.is_rankable()


def test_a_revise_verdict_demotes_without_withholding() -> None:
    """The rework band ranks and publishes, as it does for an agent review."""
    hypothesis = _hypothesis_with(
        _agent_review(), _scientist_review(NEEDS_REVISION_SCORE)
    )

    assert derive_review_disposition(hypothesis) == "needs_revision"
    assert hypothesis.is_rankable()


def test_a_supporting_verdict_clears_a_quality_block() -> None:
    """The scientist outranks the model on the axes the model judged."""
    hypothesis = _hypothesis_with(
        _agent_review(scientific_soundness=1), _scientist_review(8)
    )

    assert derive_review_disposition(hypothesis) == "viable"


def test_a_supporting_verdict_cannot_clear_a_safety_block() -> None:
    """No human endorsement releases an idea the reviewer flagged unsafe."""
    hypothesis = _hypothesis_with(_agent_review(safety=1), _scientist_review(8))

    assert refresh_review_dispositions([hypothesis]) == 1
    assert hypothesis.review_disposition == "unsafe"
    assert not hypothesis.is_rankable()


def test_the_latest_scientist_verdict_wins() -> None:
    """A second review supersedes the first, as it does for agent reviews."""
    hypothesis = _hypothesis_with(
        _agent_review(),
        _scientist_review(NOT_VIABLE_SCORE),
        _scientist_review(8),
    )

    assert derive_review_disposition(hypothesis) == "viable"


def test_a_scientist_verdict_cannot_reopen_a_foreign_disposition() -> None:
    """Evidence and proximity own their own exclusions (see the gate)."""
    hypothesis = _hypothesis_with(_agent_review(), _scientist_review(8))
    hypothesis.review_disposition = "evidence_blocked"

    assert refresh_review_dispositions([hypothesis]) == 0
    assert hypothesis.review_disposition == "evidence_blocked"


def test_the_reviewer_attribution_survives_serialization() -> None:
    """Authorship rides the checkpoint, not just the live object."""
    hypothesis = _hypothesis_with(_agent_review(), _scientist_review(2))

    restored = Hypothesis.from_dict(hypothesis.to_dict())

    assert [review.reviewer for review in restored.reviews] == [
        "agent",
        SCIENTIST_REVIEWER,
    ]
    assert not has_peer_review(_hypothesis_with(restored.reviews[1]))


def _scheduler_pool() -> WorkflowState:
    """A settled pool plus one just-admitted, unreviewed contribution."""
    settled = _hypothesis_with(_agent_review())
    settled.win_count, settled.loss_count = 1, 1
    admitted = _hypothesis_with(_scientist_review(8))
    return make_state(
        hypotheses=[settled, admitted],
        current_iteration=1,
        max_iterations=5,
    )


def test_an_admitted_idea_does_not_pull_the_run_into_ranking() -> None:
    """Coverage is owed to reviewed ideas, so review still comes first.

    The tournament's coverage floor is checked (step 3) above the
    unreviewed backlog (step 6), so an idea that is rankable with no
    matches is itself a reason to rank -- which would put a contributed
    hypothesis into the tournament ungated, through the front door,
    whether or not its steering message survived to this decision.
    """
    state = _scheduler_pool()

    decision = required_transition(
        _compute_stats(state, {}), _default_budget(state)
    )

    assert decision is not None
    assert decision.next_task is TaskType.REFLECT


def test_steering_still_schedules_generation_when_it_arrives() -> None:
    """A steer that reaches this decision outranks the review backlog."""
    state = _scheduler_pool()
    state["pending_steering"] = True

    decision = required_transition(
        _compute_stats(state, {}), _default_budget(state)
    )

    assert decision is not None
    assert decision.next_task is TaskType.GENERATE
