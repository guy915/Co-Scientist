"""Research one hypothesis's own claim, for the reviews that ground.

The full and simulation reviews already retrieve: they formulate keyword
queries from the hypothesis, read what comes back, and stop. That single
round is the gap ``REFLECT-TYPES-001`` names -- a review that reads a
result set has no way to notice what the set does not answer and go back
for it.

This module is the assignment of ``co_scientist.research`` to Reflection.
It is the same capability the literature review runs, under a different
policy, because the two spend on opposite shapes: the review researches
once per run, a reflection researches once per *hypothesis*. So the
ceiling here bounds two factors rather than one -- how much one
hypothesis may buy (``review_budget_for_tier``) and how many hypotheses
buy anything at all (``reviewed_hypothesis_limit``, best-ranked first).
The product is quotable before a run starts, which is the only reason a
per-hypothesis loop is safe to add at all.

Seeds come from what this run has already learned about *this*
hypothesis: the assumptions a previous cycle's full review marked
uncertain or likely false, and the failure points its simulation named.
Those are doubts the run has earned. With none of them on record the
loop plans its own coverage from the hypothesis text, one model call.
"""

from __future__ import annotations

import logging
from typing import Any, NamedTuple

from co_scientist.agents.generation.literature_review.helpers import (
    build_articles_from_metadata,
)
from co_scientist.agents.generation.literature_review.research_phase import (
    records_from_findings,
)
from co_scientist.models import Article, Hypothesis, rank_by_elo
from co_scientist.research import (
    ResearchBudget,
    conduct_research,
    result_to_dict,
)
from co_scientist.research_adapter import (
    LlmResearchModel,
    McpRetrieval,
    ResearchRetrieval,
)
from co_scientist.research_adapter.budget import (
    review_budget_for_tier,
    reviewed_hypothesis_limit,
)
from co_scientist.research_adapter.retrieval import ResearchRun
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)

# Prior-review fields naming a doubt worth researching, and the support
# values that make an assumption one. A "supported" assumption is not a
# question; researching it would spend a thread confirming what the last
# review already concluded.
_UNSETTLED_SUPPORT = ("uncertain", "likely_false")

# Longest hypothesis text carried into the research goal. The loop sends
# the goal with every question it formulates, so an unbounded hypothesis
# would ride along in each of them.
_MAX_GOAL_CHARS = 1200


class ReviewResearch(NamedTuple):
    """What research found for one hypothesis under review.

    Attributes:
        articles: Papers something was actually drawn from, each
            stamped with the id of the search that surfaced it.
        ledger: The whole research request as plain data, for the state
            to accumulate and the drain to persist.
    """

    articles: list[Article]
    ledger: dict[str, Any]


async def research_for_review(
    state: WorkflowState, hypothesis: Hypothesis
) -> ReviewResearch | None:
    """Research what this hypothesis's own reviews have left open.

    Args:
        state: Current workflow state, for the tier, the run's tools and
            the ranked pool this hypothesis is selected from.
        hypothesis: The hypothesis whose reviews this evidence grounds.

    Returns:
        What the research found, or None when this hypothesis buys no
        research -- the tier does not fund reviews, no source is
        enabled, or the hypothesis is outside the tier's ranked cap.
    """
    prepared = await _prepare(state, hypothesis)
    if prepared is None:
        return None
    retrieval, budget = prepared

    result = await conduct_research(
        goal=_research_goal(state, hypothesis),
        model=LlmResearchModel(
            str(state.get("model_name") or ""),
            run_id=str(state.get("run_id") or ""),
        ),
        retrieval=retrieval,
        budget=budget,
        seed_questions=_seed_questions(hypothesis, budget.breadth),
    )
    logger.info(
        "Review research for %s: %s threads, %s calls, %s findings (%s)",
        hypothesis.id,
        len(result.threads),
        len(result.calls),
        len(result.findings),
        result.stop_reason.value,
    )
    records = records_from_findings(result, retrieval)
    return ReviewResearch(
        articles=build_articles_from_metadata(records, ""),
        ledger=result_to_dict(result),
    )


async def _prepare(
    state: WorkflowState, hypothesis: Hypothesis
) -> tuple[ResearchRetrieval, ResearchBudget] | None:
    """Resolve what this hypothesis may search, and whether it may at all.

    Returns:
        The retrieval port and its budget, or None when this hypothesis
        researches nothing. Every gate is checked before any client is
        opened, so an unfunded review costs nothing.
    """
    from co_scientist.agents.reflection.deep_verification_evidence import (
        _probe_search_config,
    )

    tier = str(state.get("research_tier") or "")
    if not tier or not state.get("mcp_available"):
        return None
    if hypothesis.id not in _researched_hypothesis_ids(state, tier):
        return None
    config = _probe_search_config(state)
    if config.workflow is None or config.tool_registry is None:
        return None
    retrieval = ResearchRetrieval(await _remote_for(state, config))
    budget = review_budget_for_tier(tier, retrieval.sources)
    return None if budget is None else (retrieval, budget)


async def _remote_for(state: WorkflowState, config: Any) -> McpRetrieval:
    """Open the MCP half of retrieval.

    Only called once the caller has confirmed ``mcp_available``.
    """
    from co_scientist.mcp_client import get_mcp_client

    client = await get_mcp_client(tool_registry=config.tool_registry)
    return McpRetrieval(
        client,
        config.tool_registry,
        config.workflow,
        ResearchRun(
            run_id=str(state.get("run_id") or ""),
            research_goal=config.research_goal,
        ),
    )


def _researched_hypothesis_ids(state: WorkflowState, tier: str) -> set[str]:
    """Select the hypotheses this tier researches, best-ranked first.

    Ordering is the canonical one (``rank_by_elo``), and both halves of
    its key matter here. This node runs *before* ranking -- the graph
    goes review, comprehensive reflection, safety screen, ranking -- so
    on the first cycle every Elo is still the default and the tie breaks
    on the initial review's own score, which the node immediately
    upstream has just written. Later cycles have a tournament behind
    them and the Elo decides. Restating that comparison locally is how a
    second copy comes to disagree with it, so it is borrowed whole.

    Selection is computed from the whole pool rather than passed in, so
    the in-process node and a durable per-hypothesis task -- which sees
    one hypothesis and the restored state, never the batch -- select
    identically.

    Args:
        state: Current workflow state.
        tier: Normalized run tier.

    Returns:
        Ids of the hypotheses funded for research, empty when the tier
        funds none.
    """
    limit = reviewed_hypothesis_limit(tier)
    if limit < 1:
        return set()
    viable = [
        hypothesis
        for hypothesis in state.get("hypotheses") or []
        if hypothesis.review_disposition == "viable"
    ]
    return {hypothesis.id for hypothesis in rank_by_elo(viable)[:limit]}


def _research_goal(state: WorkflowState, hypothesis: Hypothesis) -> str:
    """State what this research is for: the claim, inside the run's goal.

    The loop formulates every question against this text, so it carries
    both -- the hypothesis alone loses the domain the run is working in,
    and the goal alone is what the literature review already researched.
    """
    claim = " ".join((hypothesis.text or "").split())[:_MAX_GOAL_CHARS]
    return (
        f"{state.get('research_goal') or ''}\n\n"
        f"Specifically, the claim under review: {claim}"
    ).strip()


def _seed_questions(hypothesis: Hypothesis, limit: int) -> list[str]:
    """Take the first level's questions from this hypothesis's own record.

    Args:
        hypothesis: The hypothesis under review.
        limit: The first level's breadth -- more seeds than this would be
            declined by the budget anyway.

    Returns:
        Distinct doubts already raised about this hypothesis, most
        recently reviewed first, or an empty list when none are on
        record, which leaves the loop to plan its own coverage.
    """
    seeds: list[str] = []
    seen: set[str] = set()
    for doubt in _unsettled(hypothesis):
        if doubt.lower() in seen:
            continue
        seen.add(doubt.lower())
        seeds.append(doubt)
        if len(seeds) >= limit:
            break
    return seeds


def _unsettled(hypothesis: Hypothesis) -> list[str]:
    """Collect the doubts a previous cycle's mature reviews recorded."""
    full = hypothesis.enrichments.get("full")
    simulation = hypothesis.enrichments.get("simulation")
    doubts = _unsettled_assumptions(full)
    if isinstance(simulation, dict):
        doubts.extend(
            " ".join(str(point).split())
            for point in simulation.get("failure_points") or []
            if str(point).strip()
        )
    return doubts


def _unsettled_assumptions(review: object) -> list[str]:
    """Assumptions a full review could not confirm, in the order stated."""
    if not isinstance(review, dict):
        return []
    return [
        " ".join(str(item.get("assumption")).split())
        for item in review.get("assumptions") or []
        if isinstance(item, dict)
        and item.get("support") in _UNSETTLED_SUPPORT
        and str(item.get("assumption") or "").strip()
    ]
