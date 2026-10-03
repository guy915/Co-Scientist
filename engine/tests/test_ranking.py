from __future__ import annotations

import logging
from typing import Any

import pytest

from co_scientist.agents.ranking import (
    operations,
    ranking,
    ranking_debate,
    ranking_lifecycle,
)
from co_scientist.agents.ranking.ranking import ranking_node
from co_scientist.agents.ranking.ranking_lifecycle import (
    _prepare_ranking_round,
    add_to_tournament,
)
from co_scientist.constants import INITIAL_ELO_RATING
from co_scientist.llm import scoped_telemetry
from co_scientist.models import Hypothesis
from tests._state import make_hypothesis, make_review, make_state


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
        return {
            "winner": winner,
            "decision_summary": "stub decision",
            "confidence_level": "High",
        }

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
    """Tournament entrants require completed review stamps."""
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


async def test_empty_hypotheses_skips_tournament() -> None:
    """Tournament entrants require completed review stamps."""
    state = make_state(hypotheses=[])
    result = await ranking_node(state)
    assert result["hypotheses"] == []
    assert "tournament_matchups" not in result


async def test_evidence_blocked_hypothesis_cannot_enter_tournament(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tournament entrants require completed review stamps."""
    winner = make_hypothesis(text="supported winner TXT alpha")
    loser = make_hypothesis(text="supported loser TXT beta")
    blocked = make_hypothesis(text="ungrounded idea TXT gamma")
    blocked.review_disposition = "evidence_blocked"
    state = make_state(hypotheses=[winner, loser, blocked])
    _stub_winner_by_text(monkeypatch, winner.text)

    result = await ranking_node(state)

    assert blocked.total_matches == 0
    assert all(
        blocked.id not in {match["hypothesis_a_id"], match["hypothesis_b_id"]}
        for match in result["tournament_matchups"]
    )


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


async def test_matchups_carry_hypothesis_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tournament entrants require completed review stamps."""
    winner = make_hypothesis(text="winner pathway TXT alpha")
    loser = make_hypothesis(text="loser pathway TXT beta")
    state = make_state(hypotheses=[winner, loser])
    _stub_winner_by_text(monkeypatch, "winner pathway TXT alpha")

    result = await ranking_node(state)

    matchups = result["tournament_matchups"]
    assert len(matchups) == 1
    valid_ids = {winner.id, loser.id}
    for matchup in matchups:
        assert matchup["hypothesis_a_id"] in valid_ids
        assert matchup["hypothesis_b_id"] in valid_ids
        assert matchup["hypothesis_a_id"] != matchup["hypothesis_b_id"]
        assert matchup["winner_id"] == winner.id
        winner_slot = matchup["winner"]
        slot_id_key = f"hypothesis_{winner_slot}_id"
        assert matchup[slot_id_key] == winner.id


async def test_malformed_judge_response_uses_position_balanced_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    async def fake(**_: Any) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(ranking_debate, "call_llm_json", fake)

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

    async def fake(**_: Any) -> dict[str, Any]:
        return {
            "winner": "a",
            "decision_summary": "stub decision",
            "confidence_level": "High",
        }

    monkeypatch.setattr(ranking_debate, "call_llm_json", fake)

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


async def test_each_round_selects_from_committed_current_elo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hypotheses = [
        make_hypothesis(text="sequential alpha"),
        make_hypothesis(text="sequential beta"),
    ]
    observed_elos: list[tuple[int, int]] = []

    def fake_pairings(
        pool: list[Any], *_: Any, **__: Any
    ) -> list[tuple[Any, Any]]:
        observed_elos.append((pool[0].elo_rating, pool[1].elo_rating))
        return [(pool[0], pool[1])]

    async def fake_judge(*_: Any, **__: Any) -> tuple[str, dict[str, Any]]:
        return "a", {
            "decision_summary": "A wins.",
            "confidence_level": "High",
            "debate_turns": 1,
        }

    monkeypatch.setattr(ranking, "build_tournament_pairings", fake_pairings)
    monkeypatch.setattr(operations, "judge_matchup", fake_judge)
    state = make_state(hypotheses=hypotheses, tournament_pairs=2)

    await ranking._run_tournament_matchups(
        state, hypotheses, 2, ranking._TournamentGuidance()
    )

    assert observed_elos[0] == (1200, 1200)
    assert observed_elos[1] != (1200, 1200)
    assert hypotheses[0].win_count == 2


def _record_matchup_prompts(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen_prompts: list[str] = []

    async def fake(*, prompt: str, **_: Any) -> dict[str, Any]:
        seen_prompts.append(prompt)
        return {
            "winner": "a",
            "decision_summary": "A wins.",
            "confidence_level": "High",
        }

    monkeypatch.setattr(ranking_debate, "call_llm_json", fake)
    return seen_prompts


async def test_a_rejected_hypothesis_cannot_enter_tournament(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tournament entrants require completed review stamps."""
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


def test_budget_scales_with_a_pool_the_tier_number_cannot_cover() -> None:
    """Pool growth can exceed a fixed tier allowance before every child is
    compared."""
    from co_scientist.agents.ranking.ranking_lifecycle import (
        _tournament_round_count,
    )

    hypotheses = [
        _hyp(text=f"h{i}", win_count=1, loss_count=1) for i in range(18)
    ]
    state = make_state(hypotheses=hypotheses, tournament_pairs=12)

    assert _tournament_round_count(state, hypotheses) == 27


def test_budget_is_not_refunded_when_dedup_removes_hypotheses() -> None:
    """Tournament entrants require completed review stamps."""
    from co_scientist.agents.ranking.ranking_lifecycle import (
        consumed_tournament_rounds,
    )
    from co_scientist.models import ExecutionMetrics

    state = make_state(
        hypotheses=[],
        tournament_pairs=12,
        metrics=ExecutionMetrics(tournaments_count=8),
    )

    assert consumed_tournament_rounds(state) == 8


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


def test_spent_budget_still_owes_every_idea_a_win_loss_record() -> None:
    """An unplayed seed rating looks earned; one match can be a coin flip."""
    from co_scientist.agents.ranking.ranking_lifecycle import (
        _tournament_round_count,
    )
    from co_scientist.models import ExecutionMetrics

    played = [_hyp(text=f"old{i}", win_count=1, loss_count=1) for i in range(2)]
    unplayed = [_hyp(text=f"new{i}") for i in range(3)]
    spent = make_state(
        hypotheses=played + unplayed,
        tournament_pairs=6,
        metrics=ExecutionMetrics(tournaments_count=6),
    )

    assert _tournament_round_count(spent, played + unplayed) == 3


def test_one_match_is_not_enough_coverage_to_close_the_floor() -> None:
    from co_scientist.agents.ranking.ranking_lifecycle import _coverage_floor

    once = [_hyp(text=f"h{i}", win_count=1) for i in range(4)]

    assert _coverage_floor(once) == 2


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


def test_floor_counts_a_lone_undercovered_idea_s_own_rounds() -> None:
    from co_scientist.agents.ranking.ranking_lifecycle import _coverage_floor

    lone_fresh = _hyp(text="fresh")
    covered = [_hyp(text=f"c{i}", win_count=1, loss_count=1) for i in range(4)]

    assert _coverage_floor([lone_fresh, *covered]) == 2


def test_floor_is_at_least_the_largest_individual_debt() -> None:
    """A round can settle at most one slot of an individual's match debt."""
    from co_scientist.agents.ranking.ranking_lifecycle import _coverage_floor

    two_fresh = [_hyp(text=f"new{i}") for i in range(2)]
    covered = [_hyp(text=f"c{i}", win_count=1, loss_count=1) for i in range(3)]

    assert _coverage_floor([*two_fresh, *covered]) == 2


async def test_budget_is_charged_for_matches_judged_not_rounds_offered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A distinct-pair ceiling can leave offered rounds unused."""
    from co_scientist.agents.ranking.ranking_lifecycle import (
        _tournament_round_count,
    )
    from co_scientist.models import merge_metrics

    hypotheses = [_hyp(text=f"pool {i} TXT") for i in range(3)]

    async def fake(**_: Any) -> dict[str, Any]:
        return {
            "winner": "a",
            "decision_summary": "stub decision",
            "confidence_level": "High",
        }

    monkeypatch.setattr(ranking_debate, "call_llm_json", fake)

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


def test_entry_sets_the_published_rating() -> None:
    hypothesis = Hypothesis(text="An idea.", elo_rating=0)
    assert add_to_tournament(hypothesis) is True
    assert hypothesis.elo_rating == INITIAL_ELO_RATING


def test_entry_is_idempotent_for_a_rated_hypothesis() -> None:
    """Tournament entrants require completed review stamps."""
    hypothesis = Hypothesis(text="An idea.", elo_rating=1350)
    assert add_to_tournament(hypothesis) is False
    assert hypothesis.elo_rating == 1350


@pytest.mark.asyncio
async def test_tournament_preparation_routes_entry_through_the_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admitted: list[str] = []

    def _spy(hypothesis: Hypothesis) -> bool:
        admitted.append(hypothesis.id)
        return False

    monkeypatch.setattr(ranking_lifecycle, "add_to_tournament", _spy)

    hypotheses = [make_hypothesis(text=f"idea {i}") for i in range(3)]
    # Captured before the call: preparation also sorts the pool in place.
    expected = [h.id for h in hypotheses]
    state = make_state(hypotheses=hypotheses)
    await _prepare_ranking_round(state, hypotheses)

    assert admitted == expected
