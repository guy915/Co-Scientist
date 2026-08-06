"""Tests for ranking_node: the Elo pairwise tournament orchestration.

The node's external dependency is ``call_llm_json`` (consumed in
``ranking_debate``), invoked once per matchup
via ``judge_matchup``. These tests stub that call so the judged winner is
deterministic, then assert on the real Elo-update and win/loss bookkeeping the
node performs, plus the recorded ``tournament_matchups`` it returns. The pure
Elo math itself is covered separately in ``tests/test_elo.py``.
"""

import logging
from typing import Any

import pytest

from co_scientist.agents.ranking import ranking, ranking_debate
from co_scientist.agents.ranking.ranking import ranking_node
from co_scientist.constants import (
    INITIAL_ELO_RATING,
)
from tests._state import make_hypothesis, make_state


def _stub_winner_by_text(
    monkeypatch: pytest.MonkeyPatch, winner_text: str
) -> None:
    """Patch the debate judge's call_llm_json to always elect ``winner_text``.

    ``judge_matchup`` builds a prompt that embeds both hypotheses' texts in
    slot order (hypothesis "a" first, then "b") and reads ``response["winner"]``
    as either "a" or "b". The stub inspects the prompt to find where the
    designated winner's text sits relative to the other and returns the slot
    letter accordingly, so the same hypothesis wins regardless of which slot the
    node's randomized pairing places it in.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        winner_text: The hypothesis text that should win every matchup.
    """

    async def fake(**kwargs: Any) -> dict[str, Any]:
        prompt = kwargs["prompt"]
        winner_pos = prompt.find(winner_text)
        # The winner is in slot "a" when its text precedes the opponent's; the
        # opponent occupies whichever slot the winner does not.
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
    """Return the position of the non-winner hypothesis text in the prompt.

    Both hypothesis texts appear exactly once in the matchup prompt. Removing
    the winner's occurrence leaves the opponent's; this finds the opponent's
    position by scanning for the first text block index that is not
    the winner's.

    Args:
        prompt: The matchup prompt containing both hypothesis texts.
        winner_text: The designated winner's text.

    Returns:
        The character index of the opponent's text within the prompt.
    """
    winner_pos = prompt.find(winner_text)
    # Search for the other text by looking on each side of the winner's text.
    before = prompt[:winner_pos]
    after = prompt[winner_pos + len(winner_text) :]
    # The opponent text marker is a stable unique token shared by test inputs.
    marker = "TXT"
    pos_after = after.find(marker)
    if pos_after != -1:
        return winner_pos + len(winner_text) + pos_after
    return before.rfind(marker)


async def test_fewer_than_two_hypotheses_skips_tournament() -> None:
    """A single hypothesis returns unchanged with no tournament run."""
    only = make_hypothesis(text="lone hypothesis TXT")
    state = make_state(hypotheses=[only])
    result = await ranking_node(state)
    assert result["hypotheses"] == [only]
    # The early return carries only the hypotheses; no tournament side effects.
    assert "tournament_matchups" not in result
    assert only.win_count == 0
    assert only.loss_count == 0
    assert only.elo_rating == INITIAL_ELO_RATING


async def test_skipped_tournament_names_the_pool_and_the_gates(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The skip reports the pool it could not rank, and why it could not.

    "Need at least 2 hypotheses" beside a run holding eight ideas read as a
    miscount rather than as the gates having emptied the pool, which is the
    one fact that makes it actionable.
    """
    kept = make_hypothesis(text="the one survivor TXT alpha")
    undermined = make_hypothesis(text="undermined idea TXT beta")
    undermined.deep_verification_verdict = "undermined"
    rejected = make_hypothesis(text="rejected idea TXT gamma")
    rejected.review_disposition = "inaccurate"
    state = make_state(hypotheses=[kept, undermined, rejected])

    with caplog.at_level(logging.WARNING):
        result = await ranking_node(state)

    assert "tournament_matchups" not in result
    message = caplog.text
    assert "1 of 3 hypotheses are rankable" in message
    assert "1 undermined by deep verification" in message
    assert "1 rejected in review" in message


async def test_empty_hypotheses_skips_tournament() -> None:
    """An empty hypothesis list also short-circuits without matchups."""
    state = make_state(hypotheses=[])
    result = await ranking_node(state)
    assert result["hypotheses"] == []
    assert "tournament_matchups" not in result


async def test_evidence_blocked_hypothesis_cannot_enter_tournament(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pre-ranking evidence disposition excludes an ungrounded idea."""
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
    """The elected winner gains Elo and wins its match; the loser drops."""
    winner = make_hypothesis(text="winner pathway TXT alpha")
    loser = make_hypothesis(text="loser pathway TXT beta")
    state = make_state(hypotheses=[winner, loser])
    _stub_winner_by_text(monkeypatch, "winner pathway TXT alpha")

    result = await ranking_node(state)

    # Two hypotheses admit exactly one comparison, so the tournament stops
    # after it however many rounds were allowed. Judging it repeatedly would
    # ratchet the winner's rating without ever testing it against anything
    # new -- which is what production was doing.
    assert winner.elo_rating > INITIAL_ELO_RATING
    assert winner.win_count == 1
    assert winner.loss_count == 0
    assert loser.elo_rating < INITIAL_ELO_RATING
    assert loser.loss_count == 1
    assert loser.win_count == 0

    # The winner sorts first by Elo in the returned state.
    assert result["hypotheses"][0] is winner

    matchups = result["tournament_matchups"]
    assert len(matchups) == 1
    for matchup in matchups:
        # The recorded winner's after-Elo exceeds its before-Elo every round.
        assert matchup["winner_elo_after"] > matchup["winner_elo_before"]
        assert matchup["loser_elo_after"] < matchup["loser_elo_before"]
        assert matchup["reasoning"] == "stub decision"
        assert matchup["confidence"] == "High"
        # Every matchup carries a decisiveness tier from the confidence + gap.
        assert matchup["tier"] in {"upset", "decisive", "clear", "narrow"}


async def test_matchups_carry_hypothesis_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each matchup records the two hypotheses' stable ids and the winner's id.

    The id fields sit alongside the truncated-text fields and must resolve to
    the actual hypotheses in the pairing (and the winner id must equal the id
    of whichever slot won).
    """
    winner = make_hypothesis(text="winner pathway TXT alpha")
    loser = make_hypothesis(text="loser pathway TXT beta")
    state = make_state(hypotheses=[winner, loser])
    _stub_winner_by_text(monkeypatch, "winner pathway TXT alpha")

    result = await ranking_node(state)

    matchups = result["tournament_matchups"]
    # Two hypotheses admit exactly one comparison.
    assert len(matchups) == 1
    valid_ids = {winner.id, loser.id}
    for matchup in matchups:
        assert matchup["hypothesis_a_id"] in valid_ids
        assert matchup["hypothesis_b_id"] in valid_ids
        assert matchup["hypothesis_a_id"] != matchup["hypothesis_b_id"]
        # The stubbed winner wins every round, so the recorded winner_id is its
        # id and it matches whichever slot the pairing placed it in.
        assert matchup["winner_id"] == winner.id
        winner_slot = matchup["winner"]
        slot_id_key = f"hypothesis_{winner_slot}_id"
        assert matchup[slot_id_key] == winner.id


async def test_malformed_judge_response_uses_position_balanced_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid judgments cannot award every matchup to presentation slot A."""

    async def fake(**_: Any) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(ranking_debate, "call_llm_json", fake)

    # Four hypotheses so the tournament has several distinct comparisons to
    # make: the balance is only observable across more than one matchup, and
    # a two-hypothesis pool admits exactly one.
    #
    # Ids are fixed rather than left at make_hypothesis's default random
    # uuid4: _balanced_invalid_fallback (ranking_debate_turns.py) hashes the
    # sorted pair of ids to pick the fallback slot, so random ids make "did
    # every matchup land in slot A" a per-run coin flip -- the rare failure
    # this test exists to catch. These four were verified (not guessed) to
    # split the resulting matchups across both slots; a naive sequential
    # choice like "hyp-1".."hyp-4" instead sends every fallback to slot A
    # and would make the assertion below vacuously true.
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
    # Not every fallback verdict may go to the hypothesis in slot A.
    assert not all(
        matchup["winner_id"] == matchup["hypothesis_a_id"]
        for matchup in matchups
    )
    for matchup in matchups:
        assert matchup["invalid_output_fallback"] is True
        # ranking_node fills missing reasoning/confidence with placeholders.
        assert matchup["reasoning"] == "No reasoning provided"
        assert matchup["confidence"] == "Unknown"


async def test_ranking_honors_tournament_pairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-run tournament depth controls the number of pairwise matches.

    Bounded by the comparisons the pool actually admits: three hypotheses
    have three distinct pairs, so a request for five stops at three rather
    than re-judging two of them.
    """
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
    # Every one of them a different comparison.
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
    """Later matchmaking observes Elo committed by the previous result."""
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

    monkeypatch.setattr(ranking, "_build_tournament_pairings", fake_pairings)
    monkeypatch.setattr(ranking, "judge_matchup", fake_judge)
    state = make_state(hypotheses=hypotheses, tournament_pairs=2)

    await ranking._run_tournament_matchups(
        state, hypotheses, 2, ranking._TournamentGuidance()
    )

    assert observed_elos[0] == (1200, 1200)
    assert observed_elos[1] != (1200, 1200)
    assert hypotheses[0].win_count == 2


def _record_matchup_prompts(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Stub the debate judge to always elect slot "a" and record its prompts.

    Args:
        monkeypatch: The pytest monkeypatch fixture.

    Returns:
        The list every matchup prompt is appended to.
    """
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


async def test_undermined_hypothesis_cannot_enter_tournament(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed fundamental verification remains auditable but never pairs."""
    undermined = make_hypothesis(
        text="invalidated mechanism",
        deep_verification_verdict="undermined",
        elo_rating=1800,
    )
    non_novel = make_hypothesis(
        text="already established mechanism",
        review_disposition="non_novel",
        elo_rating=1700,
    )
    eligible_a = make_hypothesis(text="supported mechanism alpha")
    eligible_b = make_hypothesis(text="supported mechanism beta")
    seen_prompts = _record_matchup_prompts(monkeypatch)
    state = make_state(
        hypotheses=[undermined, non_novel, eligible_a, eligible_b],
        tournament_pairs=2,
    )

    result = await ranking_node(state)

    assert all("invalidated mechanism" not in prompt for prompt in seen_prompts)
    assert all(
        "already established mechanism" not in prompt for prompt in seen_prompts
    )
    assert undermined.total_matches == 0
    assert non_novel.total_matches == 0
    assert {hypothesis.id for hypothesis in result["hypotheses"][-2:]} == {
        undermined.id,
        non_novel.id,
    }


# --- match_tier: deterministic decisiveness classification ------------------
