"""Tests for meta_review_node: review aggregation and response mapping.

The node walks every hypothesis' latest review and, when at least one exists,
makes a single ``call_llm_json`` call to synthesize a meta-review; these tests
stub that call and assert on the deterministic short-circuit (no reviews) and
the response-to-``meta_review`` field mapping, including the flattening of
``recurring_themes`` objects to ``emerging_themes`` strings.
"""

import pytest

from co_scientist.agents.meta_review import meta_review
from co_scientist.agents.meta_review.meta_review import (
    _collect_feedback_records,
    _collect_review_summaries,
    meta_review_node,
)
from tests._llm_fake import stub_call_llm_json
from tests._state import make_hypothesis, make_review, make_state


async def test_no_reviews_returns_default_without_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hypotheses with empty reviews short-circuit to the default meta_review.

    The LLM must not be called, and the returned dict carries only the
    ``meta_review`` key with the four default subfields.
    """
    calls = stub_call_llm_json(
        monkeypatch, meta_review, {"meta_review_summary": "should not appear"}
    )
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

    summary/strengths/weaknesses/strategic_recommendations/
    potential_connections are copied through to their meta_review keys,
    and the LLM is called exactly once.
    """
    calls = stub_call_llm_json(
        monkeypatch,
        meta_review,
        {
            "meta_review_summary": "overall the set is promising",
            "strengths": ["clear mechanism", "testable"],
            "weaknesses": ["narrow scope"],
            "strategic_recommendations": ["broaden the cohort"],
            "recurring_themes": [],
            "potential_connections": [
                {
                    "related_hypotheses": ["Hypothesis 1", "Hypothesis 2"],
                    "connection_type": "complementary_mechanism",
                    "synthesis_opportunity": "combine both interventions",
                }
            ],
        },
    )
    state = make_state(
        hypotheses=[
            make_hypothesis(text="reviewed hyp", reviews=[make_review()])
        ]
    )

    result = await meta_review_node(state)

    assert len(calls) == 1  # Exactly one LLM call for the synthesis.
    mr = result["meta_review"]
    assert mr["summary"] == "overall the set is promising"
    assert mr["common_strengths"] == ["clear mechanism", "testable"]
    assert mr["common_weaknesses"] == ["narrow scope"]
    assert mr["strategic_recommendations"] == ["broaden the cohort"]
    # I2: potential_connections (the field closest to "which directions
    # remain open") is threaded into state, not discarded.
    assert mr["potential_connections"][0]["synthesis_opportunity"] == (
        "combine both interventions"
    )
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
    stub_call_llm_json(
        monkeypatch,
        meta_review,
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
            make_hypothesis(text="reviewed hyp", reviews=[make_review()])
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
            make_review(review_summary="first failure pattern"),
            make_review(review_summary="later reassessment"),
        ],
    )
    [record] = _collect_review_summaries([hypothesis])
    assert [review["review_summary"] for review in record["reviews"]] == [
        "first failure pattern",
        "later reassessment",
    ]


def test_review_collection_numbers_hypotheses_from_one() -> None:
    """The index the model quotes back to a scientist starts at 1.

    Meta-review's recommendations name ideas by this number ("Fluspirilene
    (Hypothesis 1)"), so it is user-facing prose rather than an offset, and
    a 0-based one published an off-by-one in the report.
    """
    hypotheses = [
        make_hypothesis(text=f"hyp {i}", reviews=[make_review()])
        for i in range(3)
    ]

    records = _collect_review_summaries(hypotheses)

    assert [record["hypothesis_index"] for record in records] == [1, 2, 3]


def test_review_collection_includes_mature_review_findings() -> None:
    """Full/simulation/recurrent outputs join the synthesis (audit E1).

    They were computed at LLM + retrieval cost but read by nothing before
    this; the meta-review must see their verdicts like any other review.
    """
    hypothesis = make_hypothesis(text="reviewed hyp", reviews=[make_review()])
    hypothesis.enrichments["full"] = {
        "verdict": "rejected",
        "justification": "circular pathway",
        "retrieved_articles": [{"title": "not for the synthesis"}],
    }
    hypothesis.enrichments["simulation"] = {
        "verdict": "breaks_down",
        "decisive_step": "binding fails",
    }

    [record] = _collect_review_summaries([hypothesis])

    assert record["mature_reviews"]["full"]["verdict"] == "rejected"
    assert record["mature_reviews"]["full"]["justification"] == (
        "circular pathway"
    )
    assert record["mature_reviews"]["simulation"]["verdict"] == "breaks_down"
    assert "retrieved_articles" not in str(record["mature_reviews"])


def test_review_collection_omits_mature_reviews_before_the_cascade() -> None:
    """No mature review has run -> no hollow mature_reviews block."""
    hypothesis = make_hypothesis(text="reviewed hyp", reviews=[make_review()])

    [record] = _collect_review_summaries([hypothesis])

    assert "mature_reviews" not in record


def test_feedback_collection_keeps_full_debate_transcript() -> None:
    """Every ranking debate turn reaches Meta-review unchanged."""
    transcript = [
        {"turn": 1, "reasoning": "A has stronger causal evidence."},
        {"turn": 2, "reasoning": "B has a cleaner falsification test."},
    ]
    records = _collect_feedback_records(
        [make_hypothesis(text="reviewed", reviews=[make_review()])],
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
