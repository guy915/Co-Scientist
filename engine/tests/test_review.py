"""Tests for review_node: adaptive peer-review strategy and score parsing.

The node selects between two strategies by hypothesis count, gated by
``COMPARATIVE_BATCH_THRESHOLD`` (== 5):

- ``num_hypotheses <= 5`` -> comparative batch (one LLM call returning a
  ``reviews`` list, one entry per hypothesis).
- ``num_hypotheses > 5`` -> parallel individual (one LLM call per hypothesis,
  each returning a flat review dict).

Both call ``call_llm_json``; these tests stub that out and assert on the real
review-attachment and score-parsing logic. ``overall_score`` is computed as the
mean of the per-criterion ``scores`` dict (not taken from the LLM response),
and the node sets ``hypothesis.score`` to that value.

Reviews are incremental: only hypotheses without an existing review are sent
to the LLM, so re-invoking the node on a grown pool costs LLM calls only for
the new hypotheses.
"""

from typing import Any

import pytest

from co_scientist.constants import COMPARATIVE_BATCH_THRESHOLD
from co_scientist.models import HypothesisReview
from co_scientist.nodes import review
from co_scientist.nodes.review import review_node
from tests._state import make_hypothesis, make_state


def test_initial_review_gate_classifies_accuracy_and_novelty_failures() -> None:
    """Low soundness/novelty scores become explicit tournament exclusions."""
    hypotheses = [make_hypothesis(text=f"idea {index}") for index in range(4)]
    scores = [(2, 8), (8, 2), (2, 2), (8, 8)]
    reviews = [
        HypothesisReview(
            review_summary="summary",
            scores={"scientific_soundness": soundness, "novelty": novelty},
            safety_ethical_concerns="none",
            detailed_feedback={},
            constructive_feedback="feedback",
            overall_score=5,
        )
        for soundness, novelty in scores
    ]

    review._apply_initial_review_gate(hypotheses, reviews)

    assert [hypothesis.review_disposition for hypothesis in hypotheses] == [
        "inaccurate",
        "non_novel",
        "inaccurate_and_non_novel",
        "viable",
    ]


def _stub_llm(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, Any]
) -> None:
    """Patch review's call_llm_json to return a fixed response for every call.

    The same response is returned regardless of arguments, so in the parallel
    path every hypothesis receives an identical review.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        response: The canned JSON response to return.
    """

    async def fake(**_: Any) -> dict[str, Any]:
        return response

    monkeypatch.setattr(review, "call_llm_json", fake)


def _batch_entry(scores: dict[str, int]) -> dict[str, Any]:
    """Build one comparative-batch review entry with the given scores.

    Args:
        scores: Per-criterion integer scores for this hypothesis.

    Returns:
        A single review-entry dict in the batch ``reviews`` shape.
    """
    return {
        "review_summary": "batch summary",
        "scores": scores,
        "safety_ethical_concerns": "none noted",
        "detailed_feedback": {"novelty": "ok"},
        "constructive_feedback": "tighten the experiment",
    }


async def test_comparative_batch_attaches_reviews(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A small batch (<= threshold) is reviewed via one comparative call.

    Three hypotheses sit below ``COMPARATIVE_BATCH_THRESHOLD`` (5), so the
    comparative-batch path runs. The stub returns one entry per hypothesis;
    each hypothesis gets that entry's review with overall_score == mean(scores).
    """
    hyps = [
        make_hypothesis(text="h0"),
        make_hypothesis(text="h1"),
        make_hypothesis(text="h2"),
    ]
    assert len(hyps) <= COMPARATIVE_BATCH_THRESHOLD
    _stub_llm(
        monkeypatch,
        {
            "reviews": [
                _batch_entry({"soundness": 8, "novelty": 6}),  # mean 7.0
                _batch_entry({"soundness": 4, "novelty": 6}),  # mean 5.0
                _batch_entry({"soundness": 9, "novelty": 9}),  # mean 9.0
            ]
        },
    )

    result = await review_node(state=make_state(hypotheses=hyps))

    returned = result["hypotheses"]
    assert len(returned) == 3
    # The comparative-batch strategy ran (and exactly one LLM call was made).
    assert result["messages"][0]["metadata"]["strategy"] == "comparative batch"
    assert result["metrics"].llm_calls == 1
    assert result["metrics"].reviews_count == 3
    # Each hypothesis received exactly one review with parsed fields.
    expected_overalls = [7.0, 5.0, 9.0]
    expected_scores = [
        {"soundness": 8, "novelty": 6},
        {"soundness": 4, "novelty": 6},
        {"soundness": 9, "novelty": 9},
    ]
    for hyp, expected, scores in zip(
        returned, expected_overalls, expected_scores, strict=True
    ):
        assert len(hyp.reviews) == 1
        rev = hyp.reviews[0]
        assert rev.overall_score == pytest.approx(expected)
        assert rev.review_summary == "batch summary"
        # scores flow through verbatim, keyed to the matching batch entry.
        assert rev.scores == scores
        assert rev.safety_ethical_concerns == "none noted"
        assert rev.constructive_feedback == "tighten the experiment"
        # Node mirrors the review's overall_score onto the hypothesis score.
        assert hyp.score == pytest.approx(expected)


async def test_parallel_individual_attaches_reviews(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A large batch (> threshold) is reviewed via parallel individual calls.

    Six hypotheses exceed ``COMPARATIVE_BATCH_THRESHOLD`` (5), so the
    parallel-individual path runs (one call per hypothesis). The stub returns
    the same flat review dict for every call; overall_score == mean(scores).
    """
    count = COMPARATIVE_BATCH_THRESHOLD + 1  # 6 -> exceeds the threshold
    hyps = [make_hypothesis(text=f"h{i}") for i in range(count)]
    _stub_llm(
        monkeypatch,
        {
            "review_summary": "individual summary",
            "scores": {"soundness": 7, "novelty": 5},  # mean 6.0
            "safety_ethical_concerns": "no concerns",
            "detailed_feedback": {"relevance": "strong"},
            "constructive_feedback": "add controls",
        },
    )

    result = await review_node(state=make_state(hypotheses=hyps))

    returned = result["hypotheses"]
    assert len(returned) == count
    # The parallel strategy ran with one LLM call per hypothesis.
    assert result["messages"][0]["metadata"]["strategy"] == "parallel"
    assert result["metrics"].llm_calls == count
    assert result["metrics"].reviews_count == count
    for hyp in returned:
        assert len(hyp.reviews) == 1
        rev = hyp.reviews[0]
        assert rev.overall_score == pytest.approx(6.0)
        assert rev.review_summary == "individual summary"
        assert rev.scores == {"soundness": 7, "novelty": 5}
        assert rev.safety_ethical_concerns == "no concerns"
        assert rev.constructive_feedback == "add controls"
        assert hyp.score == pytest.approx(6.0)


async def test_individual_missing_scores_defaults_to_overall_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The individual path falls back to ``overall_score`` when scores empty.

    With an empty ``scores`` dict, ``review_single_hypothesis`` does not compute
    a mean; it uses ``response.get("overall_score", 0.0)`` instead. Six
    hypotheses route through this individual path.
    """
    count = COMPARATIVE_BATCH_THRESHOLD + 1  # 6 -> parallel individual path
    hyps = [make_hypothesis(text=f"h{i}") for i in range(count)]
    _stub_llm(
        monkeypatch,
        {
            "review_summary": "no criteria scores",
            "scores": {},
            "overall_score": 42.0,
            "safety_ethical_concerns": "",
            "detailed_feedback": {},
            "constructive_feedback": "",
        },
    )

    result = await review_node(state=make_state(hypotheses=hyps))

    returned = result["hypotheses"]
    assert len(returned) == count
    assert result["messages"][0]["metadata"]["strategy"] == "parallel"
    for hyp in returned:
        assert len(hyp.reviews) == 1
        assert hyp.reviews[0].overall_score == pytest.approx(42.0)
        assert hyp.score == pytest.approx(42.0)


async def test_empty_hypotheses_returns_empty_without_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zero hypotheses skip review entirely (nothing is unreviewed).

    With no unreviewed hypotheses there is no LLM work to do; the node
    returns an empty hypothesis list without calling the LLM or raising.
    """

    async def fail(**_: Any) -> dict[str, Any]:
        raise AssertionError("no LLM call expected for an empty pool")

    monkeypatch.setattr(review, "call_llm_json", fail)

    result = await review_node(state=make_state(hypotheses=[]))

    assert result["hypotheses"] == []
    assert result["messages"][0]["metadata"]["strategy"] == "skipped"


async def test_second_invocation_reviews_only_new_hypotheses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-invoking review on a grown pool only calls the LLM for new items.

    Evolution appends immutable children without shrinking the pool, so the
    node must review incrementally: a second invocation with one new
    unreviewed hypothesis issues exactly one review call (not one per pool
    member), and the previously reviewed hypotheses keep their single review.
    """
    calls: list[dict[str, Any]] = []

    async def counting_stub(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        count = kwargs["prompt_metadata"]["hypotheses_count"]
        return {
            "reviews": [_batch_entry({"soundness": 6}) for _ in range(count)]
        }

    monkeypatch.setattr(review, "call_llm_json", counting_stub)

    hyps = [make_hypothesis(text=f"h{i}") for i in range(3)]
    first = await review_node(state=make_state(hypotheses=hyps))
    assert len(calls) == 1
    assert first["metrics"].reviews_count == 3

    # The pool grows by one unreviewed hypothesis (e.g. an evolved child).
    hyps.append(make_hypothesis(text="child"))
    second = await review_node(state=make_state(hypotheses=hyps))

    # One comparative-batch call covering only the single new hypothesis.
    assert len(calls) == 2
    assert calls[1]["prompt_metadata"]["hypotheses_count"] == 1
    assert second["metrics"].reviews_count == 1
    # Previously reviewed hypotheses were not re-reviewed; the new one was.
    assert [len(h.reviews) for h in second["hypotheses"]] == [1, 1, 1, 1]
