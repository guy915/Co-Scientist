"""Tests for the full Reflection review cascade."""

from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.reflection import comprehensive_reflection as cr
from co_scientist.agents.reflection.review_types import ReviewType
from co_scientist.models import Article
from tests._state import make_hypothesis, make_state


async def test_full_and_simulation_run_for_every_viable_hypothesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every idea passing initial review receives both mature review modes."""
    fake = AsyncMock(return_value={"verdict": "sound"})
    monkeypatch.setattr(cr, "call_llm_json", fake)
    viable = [make_hypothesis(text="a"), make_hypothesis(text="b")]
    for hypothesis in viable:
        hypothesis.review_disposition = "viable"
    rejected = make_hypothesis(text="rejected")
    rejected.review_disposition = "non_novel"

    result = await cr.comprehensive_reflection_node(
        make_state(hypotheses=[*viable, rejected], current_iteration=0)
    )

    assert fake.await_count == 4
    assert all("full" in h.enrichments for h in viable)
    assert all("simulation" in h.enrichments for h in viable)
    assert rejected.enrichments == {}
    assert result["metrics"].llm_calls == 4


async def test_later_cycle_runs_recurrent_review_with_tournament_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mature hypotheses are re-reviewed once per later tournament cycle."""
    fake = AsyncMock(return_value={"verdict": "needs_revision"})
    monkeypatch.setattr(cr, "call_llm_json", fake)
    hypothesis = make_hypothesis(text="mature", elo_rating=1337)
    hypothesis.review_disposition = "viable"
    hypothesis.enrichments.update({"full": {}, "simulation": {}})
    state = make_state(
        hypotheses=[hypothesis],
        current_iteration=2,
        meta_review={"common_weaknesses": ["missing control"]},
    )

    await cr.comprehensive_reflection_node(state)
    await cr.comprehensive_reflection_node(state)

    assert fake.await_count == 1
    call = fake.await_args
    assert call is not None
    prompt = call.kwargs["prompt"]
    assert "recurrent/tournament review" in prompt
    assert "1337" in prompt
    assert hypothesis.enrichments["recurrent_review_iteration"] == 2


async def test_evolved_hypothesis_receives_missing_observation_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The post-evolution cascade restores the observation-review invariant."""
    hypothesis = make_hypothesis(text="evolved child")
    hypothesis.review_disposition = "viable"
    hypothesis.enrichments.update({"full": {}, "simulation": {}})
    observation = AsyncMock(
        return_value={
            "classification": "missing_piece",
            "reasoning": "explains x",
        }
    )
    monkeypatch.setattr(cr, "analyze_single_hypothesis", observation)
    monkeypatch.setattr(cr, "call_llm_json", AsyncMock(return_value={}))

    await cr.comprehensive_reflection_node(
        make_state(
            hypotheses=[hypothesis],
            current_iteration=0,
            articles_with_reasoning="retrieved observations",
        )
    )

    observation.assert_awaited_once()
    assert (
        hypothesis.enrichments["observation"]["classification"]
        == "missing_piece"
    )
    assert "explains x" in (hypothesis.reflection_notes or "")


@pytest.mark.asyncio
async def test_full_review_executes_targeted_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A full review searches and evaluates evidence specific to the idea.

    The search runs on keywords formulated from the hypothesis, not on the
    hypothesis text itself: the literature back end ANDs every term, so prose
    would retrieve nothing and leave the review ungrounded.
    """
    # First call formulates the queries, second is the review itself.
    call = AsyncMock(
        side_effect=[
            {"queries": ["mechanism X response Y"]},
            {"verdict": "sound"},
        ]
    )
    retrieve = AsyncMock(
        return_value=(
            [
                Article(
                    title="Targeted validation",
                    source_id="validation-1",
                    abstract="The proposed mechanism survived direct testing.",
                    used_in_analysis=True,
                )
            ],
            [],
        )
    )
    monkeypatch.setattr(cr, "call_llm_json", call)
    monkeypatch.setattr(cr, "_retrieve_probe_evidence", retrieve)
    hypothesis = make_hypothesis(text="Mechanism X controls response Y")
    state = make_state(
        hypotheses=[hypothesis],
        research_goal="Understand response Y",
        mcp_available=True,
    )

    _, result = await cr._run_review(state, hypothesis, ReviewType.FULL)

    retrieve.assert_awaited_once_with(state, ["mechanism X response Y"])
    assert result is not None
    assert result["retrieval_queries"] == ["mechanism X response Y"]
    assert result["retrieved_articles"][0]["source_id"] == "validation-1"
    # The retrieved evidence reaches the review prompt (the last call).
    prompt = call.await_args_list[-1].kwargs["prompt"]
    assert "Targeted validation" in prompt
    assert "survived direct testing" in prompt


@pytest.mark.asyncio
async def test_query_generation_is_skipped_without_a_search_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No MCP means no search, so the review must not pay to write queries."""
    call = AsyncMock(return_value={"verdict": "sound"})
    monkeypatch.setattr(cr, "call_llm_json", call)
    hypothesis = make_hypothesis(text="Mechanism X controls response Y")
    state = make_state(
        hypotheses=[hypothesis],
        research_goal="Understand response Y",
        mcp_available=False,
    )

    _, result = await cr._run_review(state, hypothesis, ReviewType.FULL)

    assert result is not None
    assert result["retrieval_queries"] == []
    # The review call only -- no query-generation call was spent.
    assert call.await_count == 1
