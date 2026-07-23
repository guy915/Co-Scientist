"""Tournament setup and teardown for the Elo ranking node.

Owns the round-invariant scaffolding around the judged matchups: sorting
the pool, resolving the tier-configured round count, gathering the
cross-node context threaded into every matchup, emitting the
start/complete progress events, and building the node's state delta.
Pairing selection, Elo commits, and the graph node stay in ``ranking.py``,
which re-exports these names for compatibility.
"""

import logging
from typing import Any, NamedTuple

from co_scientist.agents.ranking.ranking_results import (
    _build_ranking_delta,
)
from co_scientist.models import Hypothesis
from co_scientist.progress import emit_progress
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


class _TournamentGuidance(NamedTuple):
    """Cross-node context threaded unchanged into every judged matchup.

    A NamedTuple so it still unpacks positionally as the historical
    ``(supervisor_guidance, tool_registry, meta_review, run_setup_guidance,
    run_focus_guidance)`` 5-tuple for callers that iterate it.
    """

    supervisor_guidance: dict[str, Any] | None = None
    tool_registry: Any | None = None
    meta_review: dict[str, Any] | None = None
    run_setup_guidance: str | None = None
    run_focus_guidance: str | None = None


def _gather_tournament_context(state: WorkflowState) -> _TournamentGuidance:
    """Gathers the cross-node context threaded into every judged matchup.

    These are set earlier in the workflow (supervisor planning, a prior
    iteration's meta-review, and the run's setup/focus prompts); threaded
    unchanged into every judged matchup so the judge sees the same context
    for every pairing.

    Args:
        state: Current workflow state.

    Returns:
        The bundled tournament guidance (supervisor guidance, tool registry,
        meta-review, run setup/focus guidance).
    """
    return _TournamentGuidance(
        supervisor_guidance=state.get("supervisor_guidance"),
        tool_registry=state.get("tool_registry"),
        meta_review=state.get("meta_review"),
        run_setup_guidance=state.get("run_setup_guidance"),
        run_focus_guidance=state.get("run_focus_guidance"),
    )


def _sort_hypotheses_for_tournament(hypotheses: list[Hypothesis]) -> None:
    """Sorts the pool by review score in place (text as tiebreaker)."""
    hypotheses.sort(key=lambda h: (h.score, h.text), reverse=True)
    logger.info(
        "Sorted hypotheses by review score (top score: %.2f)",
        hypotheses[0].score,
    )


def _tournament_round_count(
    state: WorkflowState, hypotheses: list[Hypothesis]
) -> int:
    """Resolves the tier-configured tournament round count.

    tournament_pairs is normally set upstream from the run-tier config
    (e.g. 6/12/20/32 pairs for express/default/extended/ultra); the
    "or len(hypotheses)" fallback only applies if it is missing/zero
    (e.g. ad-hoc/test state).
    """
    tournament_rounds = max(
        1, int(state.get("tournament_pairs") or len(hypotheses))
    )
    logger.info("Running %s tournament rounds", tournament_rounds)
    return tournament_rounds


async def _prepare_ranking_round(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
) -> tuple[int, _TournamentGuidance]:
    """Sorts the pool and gathers the cross-node tournament context.

    Also emits the start-of-tournament progress event. The returned
    context is threaded into every judged matchup.

    Args:
        state: Current workflow state.
        hypotheses: Hypothesis pool entering the tournament; sorted in
            place by review score (text as tiebreaker for determinism).

    Returns:
        Tuple of (tournament_rounds, tournament guidance bundle).
    """
    _sort_hypotheses_for_tournament(hypotheses)

    await emit_progress(
        state,
        "tournament_start",
        f"Running tournament with {len(hypotheses)} hypotheses...",
        65,
    )

    tournament_rounds = _tournament_round_count(state, hypotheses)
    return tournament_rounds, _gather_tournament_context(state)


def _sort_hypotheses_by_elo(
    hypotheses: list[Hypothesis],
) -> list[Hypothesis]:
    """Sorts the pool by Elo rating (highest first), unrankable ones last.

    Score then text break ties deterministically when Elo ratings are equal.
    """
    return sorted(
        hypotheses,
        key=lambda item: (
            not item.is_rankable(),
            -item.elo_rating,
            -item.score,
            item.text,
        ),
    )


async def _finalize_ranking_result(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
    matchup_details: list[dict[str, Any]],
    tournament_rounds: int,
    total_llm_calls: int,
) -> dict[str, Any]:
    """Applies matchup results and builds the ranking_node state delta.

    The hypothesis pool is re-ranked by Elo before the delta is built.

    Args:
        state: Current workflow state.
        hypotheses: Hypothesis pool that was paired for this tournament.
        matchup_details: Sequentially committed tournament outcomes.
        tournament_rounds: Number of tournament rounds run.
        total_llm_calls: Total judge LLM calls (summed over debate turns).

    Returns:
        The ranking_node state delta dictionary.
    """
    hypotheses = _sort_hypotheses_by_elo(hypotheses)

    logger.info("Tournament complete. Top Elo: %s", hypotheses[0].elo_rating)
    logger.info("Top hypothesis: %s...", hypotheses[0].text[:100])

    await emit_progress(
        state,
        "tournament_complete",
        f"Tournament complete ({tournament_rounds} rounds)",
        80,
        top_elo=hypotheses[0].elo_rating,
        top_hypothesis=hypotheses[0].text[:200],
    )

    return _build_ranking_delta(
        hypotheses, matchup_details, tournament_rounds, total_llm_calls
    )
