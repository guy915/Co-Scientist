"""Tests for meta_review_node: review aggregation and response mapping.

The node walks every hypothesis' latest review and, when at least one exists,
makes a single ``call_llm_json`` call to synthesize a meta-review; these tests
stub that call and assert on the deterministic short-circuit (no reviews) and
the response-to-``meta_review`` field mapping, including the flattening of
``recurring_themes`` objects to ``emerging_themes`` strings.
"""

from typing import Any

import pytest

from co_scientist.models import HypothesisReview
from co_scientist.nodes import meta_review
from co_scientist.nodes.meta_review import (
    _collect_feedback_records,
    _collect_review_summaries,
    meta_review_node,
)
from tests._state import make_hypothesis, make_state


def _make_review(**overrides: Any) -> HypothesisReview:
    """Build a HypothesisReview with all required fields populated.

    Args:
        **overrides: HypothesisReview fields to override.

    Returns:
        A HypothesisReview instance.
    """
    fields: dict[str, Any] = {
        "review_summary": "a solid review",
        "scores": {"novelty": 8, "relevance": 7},
        "safety_ethical_concerns": "none",
        "detailed_feedback": {"novelty": "novel angle"},
        "constructive_feedback": "tighten the experiment",
        "overall_score": 7.5,
    }
    fields.update(overrides)
    return HypothesisReview(**fields)


def _stub_llm(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, Any]
) -> list[dict[str, Any]]:
    """Patch meta_review's call_llm_json and record each invocation.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        response: The dict the stub returns for every call.

    Returns:
        A list that the stub appends to on each call, for spy assertions.
    """
    calls: list[dict[str, Any]] = []

    async def fake(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return response

    monkeypatch.setattr(meta_review, "call_llm_json", fake)
    return calls


async def test_no_reviews_returns_default_without_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hypotheses with empty reviews short-circuit to the default meta_review.

    The LLM must not be called, and the returned dict carries only the
    ``meta_review`` key with the four default subfields.
    """
    calls = _stub_llm(monkeypatch, {"meta_review_summary": "should not appear"})
    state = make_state(
        hypotheses=[make_hypothesis(text="aaa"), make_hypothesis(text="bbb")]
    )

    result = await meta_review_node(state)

    assert calls == []  # The LLM was never invoked.
    assert result == {
        "meta_review": {
            "summary": "No reviews available",
            "common_strengths": [],
            "common_weaknesses": [],
            "strategic_recommendations": [],
        }
    }
    # The short-circuit branch omits emerging_themes/metrics/messages.
    assert "emerging_themes" not in result["meta_review"]
    assert "metrics" not in result
    assert "messages" not in result


async def test_with_reviews_maps_response_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A populated review triggers the LLM and maps its response fields.

    summary/strengths/weaknesses/strategic_recommendations are copied through
    to their meta_review keys, and the LLM is called exactly once.
    """
    calls = _stub_llm(
        monkeypatch,
        {
            "meta_review_summary": "overall the set is promising",
            "strengths": ["clear mechanism", "testable"],
            "weaknesses": ["narrow scope"],
            "strategic_recommendations": ["broaden the cohort"],
            "recurring_themes": [],
        },
    )
    state = make_state(
        hypotheses=[
            make_hypothesis(text="reviewed hyp", reviews=[_make_review()])
        ]
    )

    result = await meta_review_node(state)

    assert len(calls) == 1  # Exactly one LLM call for the synthesis.
    mr = result["meta_review"]
    assert mr["summary"] == "overall the set is promising"
    assert mr["common_strengths"] == ["clear mechanism", "testable"]
    assert mr["common_weaknesses"] == ["narrow scope"]
    assert mr["strategic_recommendations"] == ["broaden the cohort"]
    # The with-reviews branch carries metrics and a message.
    assert "metrics" in result
    assert result["messages"][0]["metadata"]["phase"] == "meta_review"


async def test_recurring_themes_flattened_to_emerging_themes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """recurring_themes objects and plain strings flatten to theme strings.

    A dict entry contributes its ``theme`` value; a plain-string entry is
    stringified, exercising both branches of the flattening logic.
    """
    _stub_llm(
        monkeypatch,
        {
            "meta_review_summary": "summary",
            "recurring_themes": [
                {
                    "theme": "mitochondrial dysfunction",
                    "description": "x",
                    "frequency": 3,
                },
                "oxidative stress",
            ],
        },
    )
    state = make_state(
        hypotheses=[
            make_hypothesis(text="reviewed hyp", reviews=[_make_review()])
        ]
    )

    result = await meta_review_node(state)

    assert result["meta_review"]["emerging_themes"] == [
        "mitochondrial dysfunction",
        "oxidative stress",
    ]


def test_review_collection_keeps_complete_history() -> None:
    """An older critique remains visible after a later review is added."""
    hypothesis = make_hypothesis(
        text="reviewed hyp",
        reviews=[
            _make_review(review_summary="first failure pattern"),
            _make_review(review_summary="later reassessment"),
        ],
    )
    [record] = _collect_review_summaries([hypothesis])
    assert [review["review_summary"] for review in record["reviews"]] == [
        "first failure pattern",
        "later reassessment",
    ]


def test_feedback_collection_keeps_full_debate_transcript() -> None:
    """Every ranking debate turn reaches Meta-review unchanged."""
    transcript = [
        {"turn": 1, "reasoning": "A has stronger causal evidence."},
        {"turn": 2, "reasoning": "B has a cleaner falsification test."},
    ]
    records = _collect_feedback_records(
        [make_hypothesis(text="reviewed", reviews=[_make_review()])],
        [
            {
                "hypothesis_a_id": "a",
                "hypothesis_b_id": "b",
                "winner_id": "b",
                "debate_turns": 2,
                "debate_transcript": transcript,
            }
        ],
    )
    debate = next(r for r in records if r["record_type"] == "ranking_debate")
    assert debate["debate_transcript"] == transcript
