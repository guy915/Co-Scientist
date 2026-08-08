"""What the ranking node publishes when a tournament ends.

Mostly the ordering: ``models.rank_by_elo`` is the canonical one every node
reads, including the ranking node's own published order, and these pin that
there is one comparison rather than two. A second copy of it in
``ranking_lifecycle`` negated Elo and score to sort ascending, which left its
``text`` tiebreak ascending against ``rank_by_elo``'s descending one, so the
two disagreed on every tie -- and ties are the common case at the flat seed
rating, which is exactly where a tiebreak is the whole ordering.

Also the ``tournament_complete`` payload the same function emits, which
carries the winning idea's text to the UI.
"""

from typing import Any

from co_scientist.agents.ranking.ranking_lifecycle import (
    _finalize_ranking_result,
    _sort_hypotheses_by_elo,
)
from co_scientist.constants import INITIAL_ELO_RATING
from co_scientist.models import rank_by_elo
from tests._state import make_hypothesis, make_state


def test_equal_elo_orders_the_same_way_everywhere() -> None:
    """Untouched hypotheses order identically wherever they are ranked.

    Every hypothesis leaves generation at the same seed rating and score, so
    until a tournament separates them the text tiebreak decides the whole
    order. The ranking node publishes one order and the research overview
    re-derives its top-k with ``rank_by_elo``; when the two tiebreaks ran in
    opposite directions those lists were reverses of each other, and the run
    reported a different "strongest idea" depending on which surface asked.
    """
    tied = [make_hypothesis(text=text) for text in ("alpha", "gamma", "beta")]
    assert {h.elo_rating for h in tied} == {INITIAL_ELO_RATING}
    assert {h.score for h in tied} == {0.0}

    node_order = [h.text for h in _sort_hypotheses_by_elo(tied)]

    assert node_order == [h.text for h in rank_by_elo(tied)]
    assert node_order == ["gamma", "beta", "alpha"]


def test_unrankable_ideas_sort_last_without_a_second_comparison() -> None:
    """The tournament's extra rule is a partition over the shared ordering.

    ``zeta`` would lead on the text tiebreak, so a quarantined idea sinking
    to the bottom is the rule doing work rather than the tiebreak happening
    to agree with it -- and the rankable ideas it leaves above keep exactly
    the order ``rank_by_elo`` gave them.
    """
    blocked = make_hypothesis(
        text="zeta", review_disposition="evidence_blocked"
    )
    rankable = [make_hypothesis(text=text) for text in ("alpha", "beta")]

    ordered = _sort_hypotheses_by_elo([blocked, *rankable])

    assert [h.text for h in ordered] == ["beta", "alpha", "zeta"]


def test_an_undermined_idea_sorts_below_every_sound_one() -> None:
    """Deep verification demotes an idea; it no longer removes it.

    An undermined idea ranks and publishes, so nothing else keeps it off
    the top of the list -- and it reached deep verification precisely by
    leading the tournament, which means the Elo it carries would otherwise
    put it first. ``yankee`` here holds the pool's highest rating and still
    lands below both sound ideas, above only the idea a gate refused
    outright.
    """
    undermined = make_hypothesis(
        text="yankee",
        deep_verification_verdict="undermined",
        elo_rating=INITIAL_ELO_RATING + 300,
    )
    blocked = make_hypothesis(
        text="zeta", review_disposition="evidence_blocked"
    )
    rankable = [make_hypothesis(text=text) for text in ("alpha", "beta")]

    ordered = _sort_hypotheses_by_elo([blocked, undermined, *rankable])

    assert [h.text for h in ordered] == ["beta", "alpha", "yankee", "zeta"]


def test_elo_outranks_the_text_tiebreak() -> None:
    """The tiebreak only decides ties, in both orderings.

    A guard on the composition: sorting the shared ordering by rankability
    must be stable, or the Elo ranking it was handed would be re-shuffled.
    """
    pool = [
        make_hypothesis(text="alpha", elo_rating=1400),
        make_hypothesis(text="zeta", elo_rating=1200),
    ]

    assert [h.text for h in _sort_hypotheses_by_elo(pool)] == ["alpha", "zeta"]
    assert [h.text for h in rank_by_elo(pool)] == ["alpha", "zeta"]


async def test_tournament_complete_marks_a_truncated_winner() -> None:
    """A cut idea reaches the UI as cut, not as a complete short one.

    ``top_hypothesis`` is a 200-character window onto the winning idea, and a
    bare slice leaves nothing to tell a long idea's opening 200 characters
    from a short idea stated in full.
    """
    events: list[tuple[str, dict[str, Any]]] = []

    async def callback(event: str, payload: dict[str, Any]) -> None:
        events.append((event, payload))

    long_winner = make_hypothesis(text="w" * 260, elo_rating=1400)
    short_runner_up = make_hypothesis(text="a short idea", elo_rating=1200)
    state = make_state(progress_callback=callback)

    await _finalize_ranking_result(
        state, [long_winner, short_runner_up], [], 1, 1
    )

    event, payload = events[-1]
    assert event == "tournament_complete"
    assert payload["top_hypothesis"] == "w" * 200 + "..."
