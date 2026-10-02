"""Ranking agent.

Google role: runs an Elo tournament of pairwise scientific debates to order
hypotheses by merit, concentrating compute on the strongest contenders.

Implemented by the durable graph node ``ranking`` (whose key string is
preserved), with its tournament, matchmaking, and Elo helpers. See
``co_scientist.agents`` for the six-agent model.
"""

from co_scientist.agents.ranking.operations import (
    RankingJudgement,
    RankingJudgingContext,
    RankingMatchResult,
    RankingPromptContext,
    apply_ranking_matchup,
    judge_ranking_matchup,
    prepare_ranking_judging_context,
    prepare_ranking_prompt_context,
)
from co_scientist.agents.ranking.ranking import ranking_node
from co_scientist.agents.ranking.ranking_lifecycle import (
    TournamentGuidance,
    finalize_ranking,
    prepare_ranking_round,
    remaining_ranking_rounds,
)
from co_scientist.agents.ranking.ranking_pairings import (
    build_tournament_pairings,
)

__all__ = [
    "RankingJudgement",
    "RankingJudgingContext",
    "RankingMatchResult",
    "RankingPromptContext",
    "TournamentGuidance",
    "apply_ranking_matchup",
    "build_tournament_pairings",
    "finalize_ranking",
    "judge_ranking_matchup",
    "prepare_ranking_judging_context",
    "prepare_ranking_prompt_context",
    "prepare_ranking_round",
    "ranking_node",
    "remaining_ranking_rounds",
]
