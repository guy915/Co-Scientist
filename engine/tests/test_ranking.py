from __future__ import annotations

import logging
from typing import Any

import pytest

from co_scientist.agents.ranking import (
    ranking_debate,
)
from co_scientist.agents.ranking.ranking import ranking_node
from co_scientist.agents.ranking.ranking_lifecycle import (
    add_to_tournament,
)
from co_scientist.constants import INITIAL_ELO_RATING
from co_scientist.llm import scoped_telemetry
from co_scientist.models import Hypothesis
from tests._llm_fake import stub_call_llm_json
from tests._state import (
    make_hypothesis,
    make_ranking_response,
    make_review,
    make_state,
)


def _stub_winner_by_text(
    monkeypatch: pytest.MonkeyPatch, winner_text: str
) -> None:
    """Presentation slots alternate; the stub must elect the same actual
    idea."""

    async def fake(**kwargs: Any) -> dict[str, Any]:
        prompt = kwargs["prompt"]
        winner_pos = prompt.find(winner_text)
        winner = (
            "a" if winner_pos < _other_text_pos(prompt, winner_text) else "b"
        )
        return make_ranking_response(winner)

    monkeypatch.setattr(ranking_debate, "call_llm_json", fake)


def _other_text_pos(prompt: str, winner_text: str) -> int:
    winner_pos = prompt.find(winner_text)
    before = prompt[:winner_pos]
    after = prompt[winner_pos + len(winner_text) :]
    marker = "TXT"
    pos_after = after.find(marker)
    if pos_after != -1:
        return winner_pos + len(winner_text) + pos_after
    return before.rfind(marker)


async def test_fewer_than_two_hypotheses_skips_tournament() -> None:
    only = make_hypothesis(text="lone hypothesis TXT")
    state = make_state(hypotheses=[only])
    result = await ranking_node(state)
    assert result["hypotheses"] == [only]
    assert "tournament_matchups" not in result
    assert only.win_count == 0
    assert only.loss_count == 0
    assert only.elo_rating == INITIAL_ELO_RATING


async def test_skipped_tournament_names_the_pool_and_the_gates(
    caplog: pytest.LogCaptureFixture,
) -> None:
    kept = make_hypothesis(text="the one survivor TXT alpha")
    rejected = make_hypothesis(text="rejected idea TXT gamma")
    rejected.review_disposition = "inaccurate"
    also_rejected = make_hypothesis(text="rejected idea TXT delta")
    also_rejected.review_disposition = "evidence_blocked"
    state = make_state(hypotheses=[kept, rejected, also_rejected])

    with caplog.at_level(logging.WARNING):
        result = await ranking_node(state)

    assert "tournament_matchups" not in result
    message = caplog.text
    assert "1 of 3 hypotheses are rankable" in message
    assert "2 rejected in review" in message
    # Verification demotes rather than excludes; it cannot explain a thin pool.
    assert "undermined" not in message


async def test_deterministic_winner_updates_elo_and_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    winner = make_hypothesis(text="winner pathway TXT alpha")
    loser = make_hypothesis(text="loser pathway TXT beta")
    state = make_state(hypotheses=[winner, loser])
    _stub_winner_by_text(monkeypatch, "winner pathway TXT alpha")

    result = await ranking_node(state)

    # Repeated judgments of one pair ratchet ratings without a new opponent.
    assert winner.elo_rating > INITIAL_ELO_RATING
    assert winner.win_count == 1
    assert winner.loss_count == 0
    assert loser.elo_rating < INITIAL_ELO_RATING
    assert loser.loss_count == 1
    assert loser.win_count == 0

    assert result["hypotheses"][0] is winner

    matchups = result["tournament_matchups"]
    assert len(matchups) == 1
    for matchup in matchups:
        assert matchup["winner_elo_after"] > matchup["winner_elo_before"]
        assert matchup["loser_elo_after"] < matchup["loser_elo_before"]
        assert matchup["reasoning"] == "stub decision"
        assert matchup["confidence"] == "High"
        assert matchup["tier"] in {"upset", "decisive", "clear", "narrow"}


async def test_malformed_judge_response_uses_position_balanced_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    stub_call_llm_json(monkeypatch, ranking_debate, {}, copy_response=True)

    # Fixed ids split hashed fallback slots; random ids make this a coin flip.
    # Several distinct comparisons are needed to observe slot balance.
    ids = [
        "fallback-hyp-alpha",
        "fallback-hyp-epsilon",
        "fallback-hyp-beta",
        "fallback-hyp-delta",
    ]
    state = make_state(
        hypotheses=[
            make_hypothesis(text=f"hypothesis {i} TXT", id=ids[i])
            for i in range(4)
        ],
        tournament_pairs=4,
    )
    result = await ranking_node(state)

    matchups = result["tournament_matchups"]
    assert len(matchups) > 1
    assert not all(
        matchup["winner_id"] == matchup["hypothesis_a_id"]
        for matchup in matchups
    )
    for matchup in matchups:
        assert matchup["invalid_output_fallback"] is True
        assert matchup["reasoning"] == "No reasoning provided"
        assert matchup["confidence"] == "Unknown"


async def test_ranking_honors_tournament_pairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hypotheses = [
        make_hypothesis(text="first tournament TXT"),
        make_hypothesis(text="second tournament TXT"),
        make_hypothesis(text="third tournament TXT"),
    ]

    stub_call_llm_json(
        monkeypatch,
        ranking_debate,
        make_ranking_response("a"),
        copy_response=True,
    )

    state = make_state(hypotheses=hypotheses, tournament_pairs=5)
    result = await ranking_node(state)

    assert len(result["tournament_matchups"]) == 3
    assert (
        len(
            {
                frozenset({m["hypothesis_a_id"], m["hypothesis_b_id"]})
                for m in result["tournament_matchups"]
            }
        )
        == 3
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


async def test_an_undermined_hypothesis_competes_but_publishes_last(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verification can land after the flawed leader has earned high Elo."""
    undermined = make_hypothesis(
        text="invalidated mechanism",
        deep_verification_verdict="undermined",
        elo_rating=1800,
    )
    eligible_a = make_hypothesis(text="supported mechanism alpha")
    eligible_b = make_hypothesis(text="supported mechanism beta")
    seen_prompts = _record_matchup_prompts(monkeypatch)
    state = make_state(
        hypotheses=[undermined, eligible_a, eligible_b],
        tournament_pairs=2,
    )

    result = await ranking_node(state)

    assert any("invalidated mechanism" in prompt for prompt in seen_prompts)
    assert undermined.total_matches
    assert result["hypotheses"][-1].id == undermined.id


def _hyp(text: str = "a hypothesis", **overrides: Any) -> Hypothesis:
    """Tournament entrants require completed review stamps."""
    return make_hypothesis(text=text, reviews=[make_review()], **overrides)


def test_tournament_budget_is_spent_across_the_whole_run() -> None:
    """Invoking ranking in a later cycle must not recharge its allowance."""
    from co_scientist.agents.ranking.ranking_lifecycle import (
        _tournament_round_count,
    )
    from co_scientist.models import ExecutionMetrics

    hypotheses = [
        _hyp(text=f"h{i}", win_count=1, loss_count=1) for i in range(4)
    ]

    fresh = make_state(hypotheses=hypotheses, tournament_pairs=12)
    assert _tournament_round_count(fresh, hypotheses) == 12

    partway = make_state(
        hypotheses=hypotheses,
        tournament_pairs=12,
        metrics=ExecutionMetrics(tournaments_count=9),
    )
    assert _tournament_round_count(partway, hypotheses) == 3

    spent = make_state(
        hypotheses=hypotheses,
        tournament_pairs=12,
        metrics=ExecutionMetrics(tournaments_count=12),
    )
    assert _tournament_round_count(spent, hypotheses) == 0


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


@pytest.mark.parametrize(
    ("answer", "turns", "expected"),
    [
        ({"winner": "invalid"}, 1, {"ranking_invalid_turn": 1}),
        ({"winner": "a"}, 2, {"ranking_tied_votes": 1}),
        ({"winner": "a"}, 1, {}),
    ],
)
async def test_judge_discloses_invalid_and_tied_decisions(
    monkeypatch: pytest.MonkeyPatch,
    answer: dict[str, Any],
    turns: int,
    expected: dict[str, int],
) -> None:
    async def completion(**kwargs: Any) -> dict[str, Any]:
        return dict(answer)

    monkeypatch.setattr(ranking_debate, "call_llm_json", completion)
    ctx = ranking_debate._DebateContext(
        Hypothesis(text="Candidate one"),
        Hypothesis(text="Candidate two"),
        "Public research goal",
        "test-model",
    )
    with scoped_telemetry("ranking") as telemetry:
        winner, response = await ranking_debate.judge_matchup(ctx, turns)
    assert winner in {"a", "b"}
    assert response["debate_turns"] == turns
    events = telemetry.snapshot().get("ranking::test-model", {})
    assert events.get("deterministic_fallbacks", {}) == expected
    assert events.get("calls", 0) == 0


@pytest.mark.parametrize(
    ("rating", "admitted", "after"),
    [(0, True, INITIAL_ELO_RATING), (1350, False, 1350)],
)
def test_entry_rates_an_unrated_hypothesis_once(
    rating: int, admitted: bool, after: int
) -> None:
    hypothesis = Hypothesis(text="An idea.", elo_rating=rating)
    assert add_to_tournament(hypothesis) is admitted
    assert hypothesis.elo_rating == after
