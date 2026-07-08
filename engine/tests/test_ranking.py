"""Tests for ranking_node: the Elo pairwise tournament orchestration.

The node's external dependency is ``call_llm_json``, invoked once per matchup
via ``judge_matchup``. These tests stub that call so the judged winner is
deterministic, then assert on the real Elo-update and win/loss bookkeeping the
node performs, plus the recorded ``tournament_matchups`` it returns. The pure
Elo math itself is covered separately in ``tests/test_elo.py``.
"""

from typing import Any

import pytest

from co_scientist.constants import INITIAL_ELO_RATING
from co_scientist.nodes import ranking
from co_scientist.nodes.ranking import ranking_node
from tests._state import make_hypothesis, make_state


def _stub_winner_by_text(monkeypatch: pytest.MonkeyPatch,
                         winner_text: str) -> None:
    """Patch ranking's call_llm_json to always elect ``winner_text``.

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
        winner = "a" if winner_pos < _other_text_pos(prompt,
                                                     winner_text) else "b"
        return {
            "winner": winner,
            "decision_summary": "stub decision",
            "confidence_level": "High",
        }

    monkeypatch.setattr(ranking, "call_llm_json", fake)


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
    after = prompt[winner_pos + len(winner_text):]
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


async def test_empty_hypotheses_skips_tournament() -> None:
    """An empty hypothesis list also short-circuits without matchups."""
    state = make_state(hypotheses=[])
    result = await ranking_node(state)
    assert result["hypotheses"] == []
    assert "tournament_matchups" not in result


async def test_deterministic_winner_updates_elo_and_counts(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The elected winner gains Elo and wins every round; the loser drops."""
    winner = make_hypothesis(text="winner pathway TXT alpha")
    loser = make_hypothesis(text="loser pathway TXT beta")
    state = make_state(hypotheses=[winner, loser])
    _stub_winner_by_text(monkeypatch, "winner pathway TXT alpha")

    result = await ranking_node(state)

    # With two hypotheses the node runs len(hypotheses) == 2 rounds, and the
    # same hypothesis wins both, so counts accumulate to 2.
    assert winner.elo_rating > INITIAL_ELO_RATING
    assert winner.win_count == 2
    assert winner.loss_count == 0
    assert loser.elo_rating < INITIAL_ELO_RATING
    assert loser.loss_count == 2
    assert loser.win_count == 0

    # The winner sorts first by Elo in the returned state.
    assert result["hypotheses"][0] is winner

    matchups = result["tournament_matchups"]
    assert len(matchups) == 2
    for matchup in matchups:
        # The recorded winner's after-Elo exceeds its before-Elo every round.
        assert matchup["winner_elo_after"] > matchup["winner_elo_before"]
        assert matchup["loser_elo_after"] < matchup["loser_elo_before"]
        assert matchup["reasoning"] == "stub decision"
        assert matchup["confidence"] == "High"
        # Every matchup carries a decisiveness tier from the confidence + gap.
        assert matchup["tier"] in {"upset", "decisive", "clear", "narrow"}


async def test_matchups_carry_hypothesis_ids(
        monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert len(matchups) == 2
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


async def test_malformed_judge_response_defaults_to_slot_a(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty judge response defaults winner to slot 'a' with fallbacks."""

    async def fake(**_: Any) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(ranking, "call_llm_json", fake)

    state = make_state(hypotheses=[
        make_hypothesis(text="first hypothesis TXT"),
        make_hypothesis(text="second hypothesis TXT"),
    ])
    result = await ranking_node(state)

    matchups = result["tournament_matchups"]
    assert len(matchups) == 2
    for matchup in matchups:
        # judge_matchup defaults an absent/invalid winner to slot "a".
        assert matchup["winner"] == "a"
        # ranking_node fills missing reasoning/confidence with placeholders.
        assert matchup["reasoning"] == "No reasoning provided"
        assert matchup["confidence"] == "Unknown"


async def test_ranking_honors_tournament_pairs(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-run tournament depth controls the number of pairwise matches."""
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

    monkeypatch.setattr(ranking, "call_llm_json", fake)

    state = make_state(hypotheses=hypotheses, tournament_pairs=5)
    result = await ranking_node(state)

    assert len(result["tournament_matchups"]) == 5


# --- match_tier: deterministic decisiveness classification ------------------


def test_match_tier_upset_when_loser_outrated_winner() -> None:
    """A win by a hypothesis rated >= ELO_UPSET_MARGIN below the loser is an
    upset, regardless of confidence."""
    from co_scientist.constants import ELO_UPSET_MARGIN
    assert ranking.match_tier(1200, 1200 + ELO_UPSET_MARGIN, "High") == "upset"
    assert ranking.match_tier(1200, 1200 + ELO_UPSET_MARGIN, "Low") == "upset"


def test_match_tier_maps_confidence_when_not_an_upset() -> None:
    """Absent an upset, tier follows the judge's confidence level."""
    assert ranking.match_tier(1300, 1200, "High") == "decisive"
    assert ranking.match_tier(1300, 1200, "Medium") == "clear"
    assert ranking.match_tier(1300, 1200, "Low") == "narrow"


def test_match_tier_confidence_is_case_insensitive_with_narrow_fallback(
) -> None:
    """Casing is ignored and an unknown confidence falls back to 'narrow'."""
    assert ranking.match_tier(1300, 1200, "high") == "decisive"
    assert ranking.match_tier(1300, 1200, "") == "narrow"
    assert ranking.match_tier(1300, 1200, "Unknown") == "narrow"
