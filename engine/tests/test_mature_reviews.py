"""Tests for mature-review storage, dispositions, and projections (E1/I3).

Full, simulation, and recurrent reviews used to be written to
``hypothesis.enrichments`` and read by nothing: a fatal finding changed
no disposition and no downstream consumer saw it. These tests pin the
write path's disposition effects and the shared prompt projection.
"""

import pytest

from co_scientist.agents.reflection.mature_reviews import (
    mature_review_summary,
    store_mature_review_result,
)
from co_scientist.agents.reflection.review_types import ReviewType
from co_scientist.models import Hypothesis
from tests._state import make_hypothesis


def _full_review(verdict: str, **overrides: object) -> dict[str, object]:
    """Build a full-review result carrying the given verdict."""
    result: dict[str, object] = {
        "correctness": "checked",
        "assumptions": [],
        "quality_and_novelty": "fine",
        "literature_grounding": "grounded",
        "verdict": verdict,
        "justification": "because",
    }
    result.update(overrides)
    return result


def _simulation_review(verdict: str, **overrides: object) -> dict[str, object]:
    """Build a simulation-review result carrying the given verdict."""
    result: dict[str, object] = {
        "model": "the model",
        "steps": [],
        "failure_points": [],
        "robustness": "robust",
        "verdict": verdict,
        "decisive_step": "step three",
    }
    result.update(overrides)
    return result


def _store(
    hypothesis: Hypothesis,
    review_type: ReviewType,
    result: dict[str, object],
    iteration: int = 1,
) -> None:
    store_mature_review_result(hypothesis, review_type, result, iteration)


def test_a_fatal_full_review_blocks_the_tournament() -> None:
    """A full review that rejects the idea changes the disposition.

    The cascade only reviews ideas the initial gate marked viable; the
    rejected verdict must then bar the idea from the tournament exactly
    like the initial gate's not-viable band (audit E1).
    """
    hypothesis = make_hypothesis(text="idea", review_disposition="viable")

    _store(hypothesis, ReviewType.FULL, _full_review("rejected"))

    assert hypothesis.review_disposition == "inaccurate"
    assert not hypothesis.is_rankable()


def test_a_breaking_simulation_blocks_the_tournament() -> None:
    """A simulation whose mechanism breaks down is a fatal finding."""
    hypothesis = make_hypothesis(text="idea", review_disposition="viable")

    _store(
        hypothesis,
        ReviewType.SIMULATION,
        _simulation_review("breaks_down"),
    )

    assert hypothesis.review_disposition == "inaccurate"
    assert not hypothesis.is_rankable()


def test_a_recurrent_rejection_blocks_like_a_full_review() -> None:
    """Recurrent reviews reuse the full-review schema and its bands."""
    hypothesis = make_hypothesis(text="idea", review_disposition="viable")

    _store(hypothesis, ReviewType.RECURRENT, _full_review("rejected"))

    assert hypothesis.review_disposition == "inaccurate"
    assert hypothesis.enrichments["recurrent_review_iteration"] == 1


@pytest.mark.parametrize(
    ("review_type", "result", "expected"),
    [
        (ReviewType.FULL, _full_review("sound"), "viable"),
        (ReviewType.SIMULATION, _simulation_review("holds"), "viable"),
        (
            ReviewType.SIMULATION,
            _simulation_review("partially_holds"),
            "viable",
        ),
        (
            ReviewType.FULL,
            _full_review("needs_revision"),
            "needs_revision",
        ),
    ],
    ids=[
        "sound_full_review_keeps_viable",
        "holding_simulation_keeps_viable",
        "partial_simulation_still_ranks",
        "needs_revision_publishes_but_leaves_cascade",
    ],
)
def test_only_the_not_viable_band_blocks(
    review_type: ReviewType, result: dict[str, object], expected: str
) -> None:
    """Gate semantics carry over: only fatal findings block.

    ``needs_revision`` stays rankable and publishable -- the same
    asymmetry as the initial review gate -- while partially-held
    simulations are a reservation, not a discard signal.
    """
    hypothesis = make_hypothesis(text="idea", review_disposition="viable")

    _store(hypothesis, review_type, result)

    assert hypothesis.review_disposition == expected
    assert hypothesis.is_rankable()


def test_blocking_dispositions_are_never_downgraded() -> None:
    """A later sound review cannot un-block an already-blocked idea."""
    hypothesis = make_hypothesis(text="idea", review_disposition="inaccurate")

    _store(hypothesis, ReviewType.FULL, _full_review("sound"))

    assert hypothesis.review_disposition == "inaccurate"


def test_a_fatal_simulation_wins_over_a_revising_full_review() -> None:
    """Both reviews land together; the blocking finding dominates."""
    hypothesis = make_hypothesis(text="idea", review_disposition="viable")

    _store(hypothesis, ReviewType.FULL, _full_review("needs_revision"))
    _store(
        hypothesis,
        ReviewType.SIMULATION,
        _simulation_review("breaks_down"),
    )

    assert hypothesis.review_disposition == "inaccurate"


def test_store_keeps_the_result_on_the_enrichments() -> None:
    """The write path stores the result exactly as the node always did."""
    hypothesis = make_hypothesis(text="idea", review_disposition="viable")
    result = _full_review("sound")

    _store(hypothesis, ReviewType.FULL, result)

    assert hypothesis.enrichments["full"] == result


def test_summary_projects_verdicts_and_strips_retrieval_bookkeeping() -> None:
    """Downstream prompts read verdicts and findings, not retrieval state."""
    hypothesis = make_hypothesis(text="idea", review_disposition="viable")
    _store(
        hypothesis,
        ReviewType.FULL,
        _full_review(
            "rejected",
            justification="the mechanism is circular",
            assumptions=[
                {"assumption": "protein X binds Y", "support": "likely_false"},
                {"assumption": "dose is safe", "support": "supported"},
            ],
            retrieval_queries=["query"],
            retrieved_articles=[{"title": "a paper"}],
        ),
    )
    _store(
        hypothesis,
        ReviewType.SIMULATION,
        _simulation_review(
            "breaks_down",
            failure_points=["step two fails", "step four diverges"],
        ),
    )

    summary = mature_review_summary(hypothesis.enrichments)

    assert summary is not None
    assert summary["full"] == {
        "verdict": "rejected",
        "justification": "the mechanism is circular",
        "assumptions_likely_false": ["protein X binds Y"],
    }
    assert summary["simulation"] == {
        "verdict": "breaks_down",
        "decisive_step": "step three",
        "failure_points": ["step two fails", "step four diverges"],
    }
    serialized = repr(summary)
    assert "retrieved_articles" not in serialized
    assert "retrieval_queries" not in serialized


def test_summary_is_none_before_any_mature_review_has_run() -> None:
    """The omit-rather-than-hollow convention of deep verification."""
    assert mature_review_summary(None) is None
    assert mature_review_summary({}) is None
    assert mature_review_summary({"claim_gate": {"decision": "pass"}}) is None


def test_summary_clips_long_prose_fields() -> None:
    """The judge reads this at O(n^2); fields stay bounded."""
    long_text = "x" * 5000
    summary = mature_review_summary(
        {
            "full": _full_review("needs_revision", justification=long_text),
        }
    )

    assert summary is not None
    assert len(summary["full"]["justification"]) <= 400
    assert summary["full"]["justification"].endswith("...")


def test_offline_canned_outputs_leave_dispositions_alone() -> None:
    """The offline backend fills verdict enums with their first value.

    ``sound`` and ``holds`` are both non-fatal, so deterministic offline
    runs keep whatever disposition the initial gate assigned.
    """
    hypothesis = make_hypothesis(text="idea", review_disposition="viable")

    _store(hypothesis, ReviewType.FULL, _full_review("sound"))
    _store(hypothesis, ReviewType.SIMULATION, _simulation_review("holds"))

    assert hypothesis.review_disposition == "viable"
    assert hypothesis.is_rankable()


@pytest.mark.parametrize(
    ("review_type", "verdict"),
    [
        (ReviewType.FULL, "rejected"),
        (ReviewType.SIMULATION, "breaks_down"),
        (ReviewType.RECURRENT, "rejected"),
    ],
)
def test_fatal_verdicts_are_recognized_per_review_type(
    review_type: ReviewType, verdict: str
) -> None:
    """Each review type's fatal verdict blocks from any starting state."""
    hypothesis = make_hypothesis(text="idea", review_disposition="viable")

    result = (
        _simulation_review(verdict)
        if review_type is ReviewType.SIMULATION
        else _full_review(verdict)
    )
    _store(hypothesis, review_type, result)

    assert not hypothesis.is_rankable()
