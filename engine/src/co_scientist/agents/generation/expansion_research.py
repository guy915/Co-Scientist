"""Research expansion, its prompt guidance, and budgeted exploration."""

from __future__ import annotations

import logging
from typing import Any, NamedTuple

from co_scientist.constants import truncate
from co_scientist.evidence.article_support import (
    build_articles_from_metadata,
    records_from_findings,
)
from co_scientist.progress import emit_progress
from co_scientist.research import (
    ResearchBudget,
    ResearchResult,
    conduct_research,
    result_to_dict,
)
from co_scientist.research_adapter import (
    LlmResearchModel,
    McpRetrieval,
    ResearchRetrieval,
    budget_for_tier,
)
from co_scientist.research_adapter.retrieval import ResearchRun
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


# How many of the already-explored hypotheses the expansion prompt names.
# The pool can hold dozens by a late cycle; a bounded sample keeps the
# section prompt-sized while still marking the explored territory.
EXPANSION_POOL_SAMPLE_SIZE = 12


# Per-hypothesis summary length in that coverage list.
EXPANSION_POOL_ITEM_CHARS = 200


# Extra tool-loop round-trips an expansion draft gets on top of the
# count-derived budget: broad retrieval searches more, reads more.
EXPANSION_EXTRA_DRAFT_ITERATIONS = 2


def is_research_expansion(state: WorkflowState) -> bool:
    """Whether a generate cycle is research expansion, not initial draft.

    Args:
        state: The workflow state the generate node was entered with.

    Returns:
        True once the run has completed at least one iteration cycle.
    """
    return int(state.get("current_iteration") or 0) > 0


def explored_hypothesis_summaries(
    state: WorkflowState,
) -> list[str]:
    """Bounded one-line summaries of the hypotheses explored so far.

    Args:
        state: The workflow state carrying the current pool.

    Returns:
        Up to ``EXPANSION_POOL_SAMPLE_SIZE`` truncated hypothesis texts,
        in pool order. Empty before any hypothesis exists.
    """
    hypotheses = state.get("hypotheses") or []
    summaries = [
        truncate(str(h.text).strip(), EXPANSION_POOL_ITEM_CHARS)
        for h in hypotheses[:EXPANSION_POOL_SAMPLE_SIZE]
    ]
    return [s for s in summaries if s]


def _explored_coverage_block(summaries: list[str]) -> str:
    """Renders the explored-territory list, or a none-explored note."""
    if not summaries:
        return ""
    bullets = "".join(f"- {summary}\n" for summary in summaries)
    return (
        "Hypotheses already explored in this run (do NOT re-derive these"
        " directions; expand beyond them):\n"
        f"{bullets}\n"
    )


def _widened_evidence_block(state: WorkflowState) -> str:
    """Renders the exploration's findings, when this cycle bought one.

    On the deep tiers an expansion cycle first runs its own budgeted
    exploration (``expansion_research.research_for_expansion``) and
    leaves the result here. Absent on every other tier, where expansion
    is the prompt and the wider tool-loop budget alone.

    Args:
        state: The workflow state, as the generate node's strategies see
            it after the exploration has been applied.

    Returns:
        The findings block, or an empty string when nothing was
        explored.
    """
    findings = str(state.get("research_expansion_findings") or "").strip()
    return f"\n{findings}\n" if findings else ""


def build_expansion_section(state: WorkflowState) -> str:
    """Renders the research-expansion prompt section for a generate cycle.

    Args:
        state: The workflow state the generate node was entered with.

    Returns:
        The expansion guidance block, or an empty string for the initial
        generation cycle (iteration 0), leaving focused-grounding
        behavior unchanged there.
    """
    if not is_research_expansion(state):
        return ""
    logger.info(
        "Research expansion cycle: switching generation to broad"
        " exploratory retrieval (iteration %s)",
        state.get("current_iteration"),
    )
    coverage = _explored_coverage_block(explored_hypothesis_summaries(state))
    widened = _widened_evidence_block(state)
    return (
        "## Research Expansion Cycle (broad exploratory retrieval)\n\n"
        "This is NOT the initial focused drafting pass. The goal of this"
        " cycle is to widen the evidence base before ideation:\n"
        "1. Run several DIVERSE searches first, before drafting anything:"
        " adjacent subtopics, different model systems or populations,"
        " alternative methodologies, and neighboring research areas"
        " relevant to the goal.\n"
        "2. Prefer sources and angles not already covered by the"
        " literature review context above.\n"
        "3. Only after this broader retrieval, draft hypotheses grounded"
        " in the newly widened evidence, targeting regions this run has"
        " not explored yet.\n\n"
        f"{coverage}"
        f"{widened}"
    )


# Findings named in the expansion prompt. The draft agent reads this
# beside the review synthesis and its own tool results, so the section
# has to widen the evidence base without displacing it.
_MAX_LISTED_FINDINGS = 30


class ExpansionResearch(NamedTuple):
    """What one expansion cycle's exploration produced.

    Attributes:
        section: The widened-evidence block for the expansion prompt.
        articles: The papers the findings were drawn from, in the shape
            the review's own pool uses, so they carry citation keys.
        ledger: The whole request as plain data, for ``research_ledgers``.
    """

    section: str
    articles: list[Any]
    ledger: dict[str, Any]

    def applied_to(self, state: WorkflowState) -> WorkflowState:
        """Return the state the generation strategies should run against.

        The articles are merged before generation rather than after so
        the shared ``[C*]`` citation namespace is built over them too --
        a paper this cycle found and no strategy can cite is a paper the
        exploration did not deliver.

        Args:
            state: The state the generate node was entered with.

        Returns:
            A copy carrying the widened evidence. The original is left
            alone; the node reports its own changes in its result dict.
        """
        merged: dict[str, Any] = {
            **state,
            "articles": [*(state.get("articles") or []), *self.articles],
            "research_expansion_findings": self.section,
        }
        return merged  # type: ignore[return-value]


async def research_for_expansion(
    state: WorkflowState,
) -> ExpansionResearch | None:
    """Explore the regions this run has not covered, within its ceilings.

    Args:
        state: The state the generate node was entered with, for the
            cycle number, the tier, the run's tools and the explored pool.

    Returns:
        What the exploration found, or None when this cycle explores
        nothing -- it is the initial generation cycle, the tier funds no
        research, no source is reachable, or the loop found nothing.
    """
    prepared = await _prepare(state)
    if prepared is None:
        return None
    retrieval, budget = prepared

    await emit_progress(
        state,
        "research_expansion_start",
        f"Exploring beyond the ideas so far ({budget.max_threads()} max)...",
        0.1,
    )
    result = await _explore(state, retrieval, budget)
    logger.info(
        "Research expansion (iteration %s): %s threads, %s calls, %s"
        " findings (%s)",
        state.get("current_iteration"),
        len(result.threads),
        len(result.calls),
        len(result.findings),
        result.stop_reason.value,
    )
    if not result.findings:
        return None
    records = records_from_findings(result, retrieval)
    return ExpansionResearch(
        section=_expansion_section(result),
        articles=build_articles_from_metadata(records, ""),
        ledger=result_to_dict(result),
    )


async def _explore(
    state: WorkflowState,
    retrieval: ResearchRetrieval,
    budget: ResearchBudget,
) -> ResearchResult:
    """Run the loop with no seeds, so it plans its own coverage.

    Args:
        state: The workflow state, for the goal and the run's identity.
        retrieval: The sources this cycle may search.
        budget: The ceilings it runs under.

    Returns:
        Everything the loop did, findings and declined questions alike.
    """
    return await conduct_research(
        goal=_expansion_goal(state),
        model=LlmResearchModel(
            str(state.get("model_name") or ""),
            run_id=str(state.get("run_id") or ""),
        ),
        retrieval=retrieval,
        budget=budget,
        seed_questions=[],
    )


async def _prepare(
    state: WorkflowState,
) -> tuple[ResearchRetrieval, ResearchBudget] | None:
    """Resolve what this cycle may search, and whether it may at all.

    Every gate is checked before a client is opened, so a cycle that
    buys no exploration costs nothing.

    Returns:
        The retrieval port and its budget, or None.
    """
    from co_scientist.evidence.run_config import (
        search_config_for,
    )

    tier = str(state.get("research_tier") or "")
    if not is_research_expansion(state) or not tier:
        return None
    if not state.get("mcp_available"):
        return None
    config = search_config_for(state)
    if config.workflow is None or config.tool_registry is None:
        return None
    retrieval = ResearchRetrieval(await _remote_for(state, config))
    budget = budget_for_tier(tier, retrieval.sources)
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


def _expansion_goal(state: WorkflowState) -> str:
    """State the goal as the ground this run has *not* covered yet.

    The explored pool goes into the goal rather than into seed questions
    because it is not something to research -- it is the boundary the
    planning call has to plan around. Bounded by the same sample the
    expansion prompt uses, so a late cycle's pool cannot grow the goal
    without limit.

    Args:
        state: The workflow state carrying the goal and the pool.

    Returns:
        The research goal, with the explored directions named when the
        run has any.
    """
    goal = str(state.get("research_goal") or "").strip()
    explored = explored_hypothesis_summaries(state)
    if not explored:
        return goal
    listed = "\n".join(f"- {summary}" for summary in explored)
    return (
        f"{goal}\n\nThis run has already explored the directions below."
        " Plan coverage of adjacent subtopics, alternative mechanisms,"
        " different model systems or populations, and neighbouring"
        " research areas that these do NOT cover.\n"
        f"{listed}"
    )


def _expansion_section(result: ResearchResult) -> str:
    """Render the exploration as the prompt's widened-evidence block."""
    lines = [
        "Evidence found by exploring beyond the ideas above"
        f" ({len(result.threads)} question(s) over {result.levels_run}"
        f" level(s); stopped: {result.stop_reason.value}). Ground new"
        " hypotheses in this material:",
        "",
    ]
    lines.extend(
        f"- {finding.text} [{finding.locator}]"
        for finding in result.findings[:_MAX_LISTED_FINDINGS]
    )
    return "\n".join(lines) + "\n"
