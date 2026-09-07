"""Pins tournament entry as a named step (listing 04's ``AddToTournament``).

Google's Ranking listing opens with a function that fetches a hypothesis,
exits early when it already has a rating, and otherwise sets the entry
rating. Our entry has always been correct by construction -- the dataclass
seeds every hypothesis at the published rating -- but nothing *named* the
step, so nothing said where the listing's guard lives. These tests assert the
control flow: the function exists, both of its branches behave as printed,
and the tournament boundary actually routes through it rather than relying on
the default.
"""

from __future__ import annotations

import pytest

from co_scientist.agents.ranking import ranking_lifecycle
from co_scientist.agents.ranking.ranking_lifecycle import (
    _prepare_ranking_round,
    add_to_tournament,
)
from co_scientist.constants import INITIAL_ELO_RATING
from co_scientist.models import Hypothesis
from tests._state import make_hypothesis, make_state


def test_entry_sets_the_published_rating() -> None:
    """A hypothesis with no rating enters at the listing's rating."""
    hypothesis = Hypothesis(text="An idea.", elo_rating=0)
    assert add_to_tournament(hypothesis) is True
    assert hypothesis.elo_rating == INITIAL_ELO_RATING


def test_entry_is_idempotent_for_a_rated_hypothesis() -> None:
    """A hypothesis already in the tournament is left untouched.

    The listing's guard: ``IF HypothesisToAdd.EloRating IS NOT empty THEN
    ... EXIT function``. A hypothesis that has played must keep the rating
    it earned.
    """
    hypothesis = Hypothesis(text="An idea.", elo_rating=1350)
    assert add_to_tournament(hypothesis) is False
    assert hypothesis.elo_rating == 1350


@pytest.mark.asyncio
async def test_tournament_preparation_routes_entry_through_the_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every hypothesis entering a round is admitted by the named step.

    This is the shape assertion: entry-by-dataclass-default would pass a
    rating check while calling nothing, so what is pinned is that the
    boundary calls ``add_to_tournament`` once per hypothesis.
    """
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
