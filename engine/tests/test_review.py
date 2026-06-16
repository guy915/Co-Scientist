# Copyright 2026 The Co-Scientist Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
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
"""

from typing import Any

import pytest

from co_scientist.constants import COMPARATIVE_BATCH_THRESHOLD
from co_scientist.nodes import review
from co_scientist.nodes.review import review_node
from tests._state import make_hypothesis, make_state


def _stub_llm(monkeypatch: pytest.MonkeyPatch,
              response: dict[str, Any]) -> None:
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
        monkeypatch: pytest.MonkeyPatch) -> None:
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
    for hyp, expected in zip(returned, expected_overalls):
        assert len(hyp.reviews) == 1
        rev = hyp.reviews[0]
        assert rev.overall_score == pytest.approx(expected)
        assert rev.review_summary == "batch summary"
        assert rev.scores == hyp.reviews[0].scores
        assert rev.safety_ethical_concerns == "none noted"
        assert rev.constructive_feedback == "tighten the experiment"
        # Node mirrors the review's overall_score onto the hypothesis score.
        assert hyp.score == pytest.approx(expected)


async def test_parallel_individual_attaches_reviews(
        monkeypatch: pytest.MonkeyPatch) -> None:
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
        monkeypatch: pytest.MonkeyPatch) -> None:
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
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero hypotheses route through the comparative branch and attach nothing.

    The empty count still satisfies ``<= threshold``, so a single batch call is
    made (stubbed to return no reviews). The node returns an empty hypothesis
    list without raising.
    """
    _stub_llm(monkeypatch, {"reviews": []})

    result = await review_node(state=make_state(hypotheses=[]))

    assert result["hypotheses"] == []
    assert result["messages"][0]["metadata"]["strategy"] == "comparative batch"
    assert result["metrics"].reviews_count == 0
