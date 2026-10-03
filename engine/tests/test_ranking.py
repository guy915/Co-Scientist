"""Offline contracts for ranking."""

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
    # Deep verification is not named: its verdict demotes rather than
    # withholds, so blaming a thin pool on it would point the reader at a
    # gate that let every one of those ideas through.
    assert "undermined" not in message


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


async def test_a_rejected_hypothesis_cannot_enter_tournament(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A review-rejected idea remains auditable but never pairs."""
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
    """Deep verification demotes a leader instead of deleting it.

    The idea carries the pool's top rating -- it earned that by winning the
    matches that promoted it to verification in the first place -- so
    nothing but the explicit demotion keeps it off the head of the
    published order.
    """
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


# --- match_tier: deterministic decisiveness classification ------------------


def _hyp(text: str = "a hypothesis", **overrides: Any) -> Hypothesis:
    """A peer-reviewed hypothesis, as every idea a tournament sees is.

    The coverage floor is owed only to ideas the run has already reviewed
    (``ranking_lifecycle._coverage_floor``), and the graph routes review
    before ranking, so a fixture with no review is not a pool this node
    ever meets.
    """
    return make_hypothesis(text=text, reviews=[make_review()], **overrides)


def test_tournament_budget_is_spent_across_the_whole_run() -> None:
    """tournament_pairs is a run-level allowance, not a per-invocation one.

    The scheduler asks for ranking once per cycle. Charging each invocation
    the full allowance is how a standard run configured for 12 matches came
    to judge about 22, every one of them real model work on the serial
    spine.

    Every hypothesis here has already played, so the coverage floor is zero
    and the budget arithmetic is what remains. The floor's precedence over
    the budget is pinned separately below.
    """
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
    """The allowance tracks the pool, which the tier constant does not.

    Evolution keeps adding ideas after the first ranking cycle, so a flat
    per-tier ceiling is spent on the ideas that existed first and every idea
    added later gets only the coverage floor's single match. A production run
    ended with twelve of eighteen rankable ideas on exactly one match, which
    from the flat starting rating leaves two reachable ratings -- the report
    showed a dozen ideas tied at 1212 and 1188 and called it a ranking.
    """
    from co_scientist.agents.ranking.ranking_lifecycle import (
        _tournament_round_count,
    )

    hypotheses = [
        _hyp(text=f"h{i}", win_count=1, loss_count=1) for i in range(18)
    ]
    state = make_state(hypotheses=hypotheses, tournament_pairs=12)

    # 18 rankable ideas at three matches each, two ideas per match.
    assert _tournament_round_count(state, hypotheses) == 27


def test_budget_is_not_refunded_when_dedup_removes_hypotheses() -> None:
    """Consumed rounds come from run metrics, not from the surviving pool.

    Proximity dedup removes hypotheses and their match tallies with them.
    Recounting from the pool would hand the run back budget it had already
    spent every time the pool was cleaned.
    """
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
    """A spent budget skips the tournament instead of buying another.

    Every hypothesis has already played, so nothing is owed a first match.
    """
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
    """Coverage outranks the budget: no idea is rated on a coin flip.

    tournament_pairs bounds how far a run refines its ordering. It must not
    decide that a hypothesis is reported at the starting Elo of 1200, which
    in the report is indistinguishable from a rating earned in matches --
    nor on a single match, which from that flat seed has exactly two
    possible outcomes and so reports one of two numbers.
    """
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

    # The two played ideas already have a record; the three unplayed ones owe
    # two matches each, which is six slots and so ceil(6/2) = 3 rounds.
    assert _tournament_round_count(spent, played + unplayed) == 3


def test_one_match_is_not_enough_coverage_to_close_the_floor() -> None:
    """An idea on one match is still owed another.

    This is the shape the bug took in production: the floor funded one match
    per idea while the matchmaker was trying to reach two, so every idea the
    budget could not afford played exactly once. From the flat 1200 seed that
    leaves two reachable ratings, and a run reported six ideas at 1212 and
    seven at 1188 as though that were a ranking.
    """
    from co_scientist.agents.ranking.ranking_lifecycle import _coverage_floor

    once = [_hyp(text=f"h{i}", win_count=1) for i in range(4)]

    assert _coverage_floor(once) == 2


def test_unrankable_ideas_do_not_hold_the_coverage_floor_open() -> None:
    """Quarantined ideas can never be matched, so they cannot owe a match.

    Counting them would keep the floor permanently above zero and loop the
    orchestrator on ranking for the rest of the run.
    """
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
    """A single idea can only settle one of its owed slots per round.

    ``ceil(owed / 2)`` assumes every match pairs two under-covered ideas, so
    each round settles two owed slots. Once the pool is down to ONE idea below
    the minimum, each of its matches settles a single slot of its own, and it
    needs as many rounds as it owes matches. The old ``ceil(owed / 2)`` gave a
    lone idea owing two matches a single round: it played once, stayed one
    match short of the minimum, and the tournament stopped. The floor must be
    at least the largest individual debt.
    """
    from co_scientist.agents.ranking.ranking_lifecycle import _coverage_floor

    lone_fresh = _hyp(text="fresh")
    covered = [_hyp(text=f"c{i}", win_count=1, loss_count=1) for i in range(4)]

    # One idea owes two matches; the rest are covered. ceil(2/2)=1 is too
    # few -- the idea can play only one of those matches per round.
    assert _coverage_floor([lone_fresh, *covered]) == 2


def test_floor_is_at_least_the_largest_individual_debt() -> None:
    """The round count is bounded below by the most-indebted idea.

    Two ideas each owing two matches need two rounds even though their four
    owed slots divide into two pairings: they cannot face each other twice in
    one build, so the second round pairs each with a covered idea instead.
    The two bounds (ceil of the slots, largest single debt) agree here; the
    point is the floor never reports less than either.
    """
    from co_scientist.agents.ranking.ranking_lifecycle import _coverage_floor

    two_fresh = [_hyp(text=f"new{i}") for i in range(2)]
    covered = [_hyp(text=f"c{i}", win_count=1, loss_count=1) for i in range(3)]

    # Four owed slots -> ceil(4/2)=2; largest debt is 2. Floor is 2.
    assert _coverage_floor([*two_fresh, *covered]) == 2


async def test_budget_is_charged_for_matches_judged_not_rounds_offered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The consumption meter counts judged matches, not budgeted rounds.

    ``consumed_tournament_rounds`` reads ``tournaments_count`` and calls it
    "matches this run has already judged", but the delta was built from the
    round count the tournament was *offered*. A pool smaller than the budget
    exhausts its distinct pairs first and stops early, so the difference is
    charged to the run for matches nobody judged.

    Production extended run bc77950f entered its first tournament with four
    rankable ideas against a 20-round budget: six distinct pairs judged, 20
    rounds charged. The 14 phantom rounds spent 70% of the whole-run budget
    before the pool had grown, and every later cycle ran on the coverage
    floor alone -- two matches per newly-added idea, none for the ideas
    already rated.
    """
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

    # Three ideas admit three distinct pairs, so the 20-round budget buys
    # three matches and must be charged for three.
    assert len(result["tournament_matchups"]) == 3
    assert result["metrics"].tournaments_count == 3

    # The next cycle therefore still has the unspent remainder to offer.
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
