"""Match-level ranking tests: tiers, event loops, coverage floors.

Split out of ``test_ranking.py`` to keep that module within the size cap.
"""

from typing import Any

import pytest

from co_scientist.agents.ranking import ranking, ranking_debate
from co_scientist.agents.ranking.ranking import ranking_node
from co_scientist.constants import MAX_CONCURRENT_LLM_CALLS
from tests._state import make_hypothesis, make_state


def test_match_tier_upset_when_loser_outrated_winner() -> None:
    """A deep-underdog win is an upset regardless of confidence.

    Specifically, a win by a hypothesis rated >= ELO_UPSET_MARGIN below
    the loser.
    """
    from co_scientist.constants import ELO_UPSET_MARGIN

    assert ranking.match_tier(1200, 1200 + ELO_UPSET_MARGIN, "High") == "upset"
    assert ranking.match_tier(1200, 1200 + ELO_UPSET_MARGIN, "Low") == "upset"


def test_match_tier_maps_confidence_when_not_an_upset() -> None:
    """Absent an upset, tier follows the judge's confidence level."""
    assert ranking.match_tier(1300, 1200, "High") == "decisive"
    assert ranking.match_tier(1300, 1200, "Medium") == "clear"
    assert ranking.match_tier(1300, 1200, "Low") == "narrow"


def test_match_tier_confidence_is_case_insensitive_with_narrow_fallback() -> (
    None
):
    """Casing is ignored and an unknown confidence falls back to 'narrow'."""
    assert ranking.match_tier(1300, 1200, "high") == "decisive"
    assert ranking.match_tier(1300, 1200, "") == "narrow"
    assert ranking.match_tier(1300, 1200, "Unknown") == "narrow"


def test_matchup_judging_survives_more_than_one_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The judge's concurrency bound must not be shared across event loops.

    The durable worker runs each scientific task on its own thread with its
    own event loop, so an ``asyncio.Semaphore`` created once at import time
    binds to whichever loop first waits on it and then raises
    "is bound to a different event loop" from every other. It only stayed
    hidden while the tournament judged fewer matchups than the semaphore had
    permits and therefore never actually waited; once a wave filled, a real
    ranking task died on it in production.
    """
    import asyncio

    async def fake_call_llm_json(**_: Any) -> dict[str, Any]:
        await asyncio.sleep(0)
        return {"winner": "A", "reasoning": "because"}

    monkeypatch.setattr(ranking_debate, "call_llm_json", fake_call_llm_json)

    hyp_a = make_hypothesis(text="a")
    hyp_b = make_hypothesis(text="b")

    async def judge_a_full_wave() -> None:
        """Force real contention so the semaphore has to wait."""
        mp = ranking_debate._MatchupPrompt("prompt", None, None, None)
        await asyncio.gather(
            *(
                ranking._call_matchup_judge(
                    mp,
                    ranking_debate._DebateContext(
                        hyp_a, hyp_b, "goal", "model", matchup_index=index
                    ),
                )
                # More waiters than permits, so acquisition must block.
                for index in range(MAX_CONCURRENT_LLM_CALLS * 2)
            )
        )

    asyncio.run(judge_a_full_wave())
    # A second task, on a second loop, is the case that broke.
    asyncio.run(judge_a_full_wave())


# --- coverage guarantee: no rankable idea leaves the tournament short ------


async def test_every_rankable_idea_reaches_the_minimum_match_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scheduling honors the coverage minimum instead of stopping early.

    Reproduced the audit shape: a pool where one idea has never played and the
    rest already carry a win-loss record. The coverage floor used to fund that
    idea a single round (``ceil(2/2)``), it played once, and the tournament
    stopped with it one match short of the minimum -- a rating indistinguish-
    able from a coin flip. The floor now counts the idea's own two rounds, so
    the tournament keeps going until every rankable idea has a record.
    """
    from co_scientist.constants import TOURNAMENT_MIN_MATCHES_PER_HYPOTHESIS
    from co_scientist.models import ExecutionMetrics

    fresh = make_hypothesis(text="fresh mechanism")
    covered = [
        make_hypothesis(
            text=f"covered mechanism {i}", win_count=1, loss_count=1
        )
        for i in range(4)
    ]
    hypotheses = [fresh, *covered]

    async def fake_judge(*_: Any, **__: Any) -> tuple[str, dict[str, Any]]:
        return "a", {
            "decision_summary": "A wins.",
            "confidence_level": "High",
            "debate_turns": 1,
        }

    monkeypatch.setattr(ranking, "judge_matchup", fake_judge)
    # Budget already spent by earlier cycles: only the coverage floor can
    # grant rounds now, which isolates the floor's sizing of the pass.
    state = make_state(
        hypotheses=hypotheses,
        tournament_pairs=6,
        metrics=ExecutionMetrics(tournaments_count=99),
    )

    result = await ranking_node(state)

    for hypothesis in result["hypotheses"]:
        if hypothesis.is_rankable():
            assert hypothesis.total_matches >= (
                TOURNAMENT_MIN_MATCHES_PER_HYPOTHESIS
            ), f"{hypothesis.text} left short of the minimum"
