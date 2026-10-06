from __future__ import annotations

from typing import Any

import pytest

from co_scientist.agents.ranking import (
    ranking_debate,
    remaining_ranking_rounds,
)
from co_scientist.agents.ranking.ranking import (
    ranking_node,
)
from co_scientist.models import ExecutionMetrics, Hypothesis
from tests._llm_fake import stub_call_llm_json
from tests._state import (
    make_hypothesis,
    make_ranking_response,
    make_review,
    make_state,
)


def _record_matchup_prompts(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen_prompts: list[str] = []

    async def fake(*, prompt: str, **_: Any) -> dict[str, Any]:
        seen_prompts.append(prompt)
        return make_ranking_response("a", decision_summary="A wins.")

    monkeypatch.setattr(ranking_debate, "call_llm_json", fake)
    return seen_prompts


async def test_a_rejected_hypothesis_cannot_enter_tournament(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    non_novel = make_hypothesis(
        text="already established mechanism",
        review_disposition="non_novel",
        elo_rating=1700,
    )
    eligible_a = make_hypothesis(text="supported mechanism alpha")
    eligible_b = make_hypothesis(text="supported mechanism beta")
    seen_prompts = _record_matchup_prompts(monkeypatch)
    state = make_state(
        hypotheses=[non_novel, eligible_a, eligible_b],
        tournament_pairs=2,
    )

    result = await ranking_node(state)

    assert all(
        "already established mechanism" not in prompt for prompt in seen_prompts
    )
    assert non_novel.total_matches == 0
    assert result["hypotheses"][-1].id == non_novel.id


def _hyp(text: str = "a hypothesis", **overrides: Any) -> Hypothesis:
    """Tournament entrants require completed review stamps."""
    return make_hypothesis(text=text, reviews=[make_review()], **overrides)


async def test_ranking_node_is_a_no_op_once_the_budget_is_spent() -> None:
    from co_scientist.models import ExecutionMetrics

    hypotheses = [
        _hyp(text=f"h{i}", win_count=1, loss_count=1) for i in range(4)
    ]
    state = make_state(
        hypotheses=hypotheses,
        tournament_pairs=6,
        metrics=ExecutionMetrics(tournaments_count=6),
    )

    result = await ranking_node(state)

    assert result == {"hypotheses": hypotheses}


def test_unrankable_ideas_do_not_hold_the_coverage_floor_open() -> None:
    """Gated ideas can never settle match debt."""
    from co_scientist.agents.ranking.ranking_lifecycle import (
        _tournament_round_count,
    )
    from co_scientist.models import ExecutionMetrics

    hypotheses = [
        _hyp(text="played", win_count=1, loss_count=1),
        _hyp(text="blocked", review_disposition="evidence_blocked"),
        _hyp(text="rejected", review_disposition="non_novel"),
    ]
    spent = make_state(
        hypotheses=hypotheses,
        tournament_pairs=6,
        metrics=ExecutionMetrics(tournaments_count=6),
    )

    assert _tournament_round_count(spent, hypotheses) == 0


async def test_budget_is_charged_for_matches_judged_not_rounds_offered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A distinct-pair ceiling can leave offered rounds unused."""
    from co_scientist.agents.ranking.ranking_lifecycle import (
        _tournament_round_count,
    )
    from co_scientist.models import merge_metrics

    hypotheses = [_hyp(text=f"pool {i} TXT") for i in range(3)]

    stub_call_llm_json(
        monkeypatch,
        ranking_debate,
        make_ranking_response("a"),
        copy_response=True,
    )

    state = make_state(hypotheses=hypotheses, tournament_pairs=20)
    result = await ranking_node(state)

    assert len(result["tournament_matchups"]) == 3
    assert result["metrics"].tournaments_count == 3

    state["metrics"] = merge_metrics(state["metrics"], result["metrics"])
    assert _tournament_round_count(state, hypotheses) == 17


def test_remaining_budget_funds_only_peer_reviewed_coverage() -> None:
    pool = [make_hypothesis(reviews=[make_review()]) for _ in range(3)]
    state = make_state(
        hypotheses=pool, metrics=ExecutionMetrics(tournaments_count=100)
    )
    assert remaining_ranking_rounds(state, pool) == 3
    for hypothesis in pool:
        hypothesis.reviews = []
    assert remaining_ranking_rounds(state, pool) == 0
