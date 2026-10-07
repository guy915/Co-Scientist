"""Operations mutate caller-owned ideas without store writes; guidance and
median Elo are snapshots at the caller's tournament/wave boundary."""

from dataclasses import dataclass
from typing import Any

from co_scientist.domains.research_state.models import Hypothesis
from co_scientist.domains.research_state.state import WorkflowState
from co_scientist.science.ranking.ranking_debate import (
    _DebateContext,
    _matchup_debate_turns,
    _median_elo,
    build_matchup,
    judge_matchup,
)
from co_scientist.science.ranking.ranking_lifecycle import (
    TournamentGuidance,
    _gather_tournament_context,
)


@dataclass(frozen=True)
class RankingPromptContext:
    research_goal: str
    model_name: str
    guidance: TournamentGuidance
    run_id: str | None = None
    criteria: list[str] | None = None
    preferences: str | None = None


@dataclass(frozen=True)
class RankingJudgingContext:
    prompt: RankingPromptContext
    median_elo: float


@dataclass(frozen=True)
class RankingJudgement:
    winner: str
    response: dict[str, Any]
    budgeted_turns: int


@dataclass(frozen=True)
class RankingMatchResult:
    detail: dict[str, Any]
    llm_calls: int


def prepare_ranking_prompt_context(
    state: WorkflowState, *, preferences: str | None = None
) -> RankingPromptContext:
    """Node tournaments supply scientist preferences; durable waves omit
    them."""
    return RankingPromptContext(
        research_goal=state["research_goal"],
        model_name=state["model_name"],
        guidance=_gather_tournament_context(state),
        run_id=state.get("run_id"),
        criteria=state.get("criteria"),
        preferences=preferences,
    )


def prepare_ranking_judging_context(
    prompt: RankingPromptContext, hypotheses: list[Hypothesis]
) -> RankingJudgingContext:
    return RankingJudgingContext(prompt, _median_elo(hypotheses))


async def judge_ranking_matchup(
    pair: tuple[Hypothesis, Hypothesis],
    context: RankingJudgingContext,
    matchup_index: int,
) -> RankingJudgement:
    prompt = context.prompt
    guidance = prompt.guidance
    depth = _matchup_debate_turns(pair[0], pair[1], context.median_elo)
    debate = _DebateContext(
        pair[0],
        pair[1],
        prompt.research_goal,
        prompt.model_name,
        supervisor_guidance=guidance.supervisor_guidance,
        meta_review=guidance.meta_review,
        tool_registry=guidance.tool_registry,
        run_setup_guidance=guidance.run_setup_guidance,
        run_focus_guidance=guidance.run_focus_guidance,
        run_id=prompt.run_id,
        matchup_index=matchup_index,
        criteria=prompt.criteria,
        preferences=prompt.preferences,
    )
    winner, response = await judge_matchup(debate, debate_turns=depth)
    return RankingJudgement(winner, response, depth)


def apply_ranking_matchup(
    pair: tuple[Hypothesis, Hypothesis],
    judgement: RankingJudgement,
    *,
    k_factor: int,
    current_iteration: int,
) -> RankingMatchResult:
    detail = build_matchup(
        pair,
        judgement.winner,
        judgement.response,
        k_factor=k_factor,
        iteration=current_iteration,
    ).to_dict()
    calls = int(
        judgement.response.get(
            "physical_calls", judgement.response.get("debate_turns", judgement.budgeted_turns)
        )
    )
    return RankingMatchResult(detail, calls)
