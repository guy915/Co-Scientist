from __future__ import annotations

import pytest

from co_scientist.agents.ranking import (
    remaining_ranking_rounds,
)
from co_scientist.agents.ranking.ranking_debate import (
    _build_matchup_prompt,
    _MatchupPromptContext,
    _parse_verdict_line,
)
from co_scientist.models import ExecutionMetrics
from tests._state import make_hypothesis, make_review, make_state


def test_remaining_budget_funds_only_peer_reviewed_coverage() -> None:
    pool = [make_hypothesis(reviews=[make_review()]) for _ in range(3)]
    state = make_state(
        hypotheses=pool, metrics=ExecutionMetrics(tournaments_count=100)
    )
    assert remaining_ranking_rounds(state, pool) == 3
    for hypothesis in pool:
        hypothesis.reviews = []
    assert remaining_ranking_rounds(state, pool) == 0


def _matchup_context() -> _MatchupPromptContext:
    return _MatchupPromptContext(research_goal="test goal")


def test_matchup_prompt_surfaces_fatal_mature_review_findings() -> None:
    """Paid-for mature findings must reach the judge rather than remain
    write-only."""
    hypothesis_a = make_hypothesis(text="idea A")
    hypothesis_a.enrichments["full"] = {
        "verdict": "rejected",
        "justification": "the proposed pathway is circular",
        "retrieved_articles": [{"title": "never shown to a judge"}],
    }
    hypothesis_a.enrichments["simulation"] = {
        "verdict": "breaks_down",
        "decisive_step": "ligand binding never occurs",
        "failure_points": ["step two"],
    }
    hypothesis_b = make_hypothesis(text="idea B")

    prompt, _, _, _ = _build_matchup_prompt(
        hypothesis_a, hypothesis_b, _matchup_context()
    )

    assert "Hypothesis 1 Mature Review Findings" in prompt
    assert "Full review verdict: rejected" in prompt
    assert "the proposed pathway is circular" in prompt
    assert "Simulation review verdict: breaks_down" in prompt
    assert "ligand binding never occurs" in prompt
    assert "Hypothesis 2 Mature Review Findings" not in prompt
    assert "never shown to a judge" not in prompt


@pytest.mark.parametrize(
    ("text", "side"),
    [
        ("... better idea: 1", "a"),
        ("BETTER IDEA:2", "b"),
        ("better hypothesis: 2", "b"),
        ("better idea: A", "a"),
        ("End with better idea: 1 or 2. Prevails.\n\nbetter idea: 2", "b"),
        ("conclude with better idea: 1 or 2", None),
        ("better idea: 3", None),
        ("", None),
    ],
)
def test_verdict_line_is_the_concluding_better_idea_statement(
    text: str, side: str | None
) -> None:
    assert _parse_verdict_line(text) == side
