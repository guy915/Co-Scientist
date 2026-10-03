"""Phase 6: research the questions the review's reading left open.

Phases 1-5 search once, from the research goal, and synthesize what came
back. What nothing did before this phase is read that result, notice what
it does not answer, and go looking again -- which is the whole of
``co_scientist.research``.

This module is the assignment of that capability to Generation. It owns
the three decisions the loop deliberately refuses to make for itself: how
much this run may spend (its tier's ceilings), where its first questions
come from (the gaps the per-paper analysis just found), and what happens
to the result (new papers merged into the review's own pool, findings
appended to the synthesis every later agent reads, and the ledger carried
out as plain data for whoever persists it).

Everything here is skipped, quietly and completely, when the run did not
ask for research or has no source to search -- an unresearched review is
the review this node always produced.
"""

import logging
from typing import Any, NamedTuple

from co_scientist.evidence.article_support import records_from_findings
from co_scientist.evidence.search_support import (
    SearchConfig,
)
from co_scientist.mcp_client import MCPToolClient
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
    ResearchRun,
    budget_for_tier,
)
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)

# Fields of a paper analysis that name something the literature did not
# settle. These are what the loop is for, and they are already written by
# Phase 3, so seeding from them costs no extra model call.
_GAP_FIELDS = ("gaps_identified", "unexplored_areas", "methodology_limitations")

# Most findings written into the synthesis section. The findings survive
# whole in the ledger either way; this bounds what every downstream
# generation prompt has to carry.
_MAX_LISTED_FINDINGS = 40


class ResearchOutcome(NamedTuple):
    """What Phase 6 hands back to the node.

    Attributes:
        ledger: The whole research request as plain data, for the state.
        records: Newly found papers, keyed by locator, in the same
            metadata shape Phase 2 produces -- so Phase 5 builds them
            into articles through the path every other paper takes.
        section: Text to append to the synthesis.
    """

    ledger: dict[str, Any]
    records: dict[str, dict[str, Any]]
    section: str


async def run_research_phase(
    state: WorkflowState,
    config: SearchConfig,
    mcp_client: MCPToolClient,
    analyses: list[dict[str, Any]],
) -> ResearchOutcome | None:
    """Research this run's open questions, within its tier's ceilings.

    Args:
        state: Current workflow state.
        config: The review's resolved search configuration.
        mcp_client: Client for this run's MCP servers.
        analyses: Phase 3's per-paper analyses, whose recorded gaps seed
            the first level.

    Returns:
        What the research produced, or None when this run does no
        research -- no tier asked for it, no source is enabled, or the
        loop found nothing at all.
    """
    prepared = _prepare(state, config, mcp_client)
    if prepared is None:
        return None
    retrieval, budget = prepared

    await emit_progress(
        state,
        "literature_research_start",
        f"Researching open questions ({budget.max_threads()} threads max)...",
        0.6,
    )
    result = await conduct_research(
        goal=config.research_goal,
        model=LlmResearchModel(
            config.model_name, run_id=str(state.get("run_id") or "")
        ),
        retrieval=retrieval,
        budget=budget,
        seed_questions=_seed_questions(analyses, budget.breadth),
    )
    logger.info(
        "Deep research: %s threads, %s calls, %s findings (%s)",
        len(result.threads),
        len(result.calls),
        len(result.findings),
        result.stop_reason.value,
    )
    return ResearchOutcome(
        ledger=result_to_dict(result),
        records=records_from_findings(result, retrieval),
        section=_synthesis_section(result),
    )


def _prepare(
    state: WorkflowState, config: SearchConfig, mcp_client: MCPToolClient
) -> tuple[ResearchRetrieval, ResearchBudget] | None:
    """Resolve what this run may search and how much of it it may buy.

    Returns:
        The retrieval port and the budget it runs under, or None when
        this run researches nothing -- no tier asked, the review resolved
        no tool configuration, or no search source is enabled.
    """
    tier = str(state.get("research_tier") or "")
    if not tier or config.workflow is None or config.tool_registry is None:
        return None
    retrieval = ResearchRetrieval(
        McpRetrieval(
            mcp_client,
            config.tool_registry,
            config.workflow,
            ResearchRun(
                run_id=str(state.get("run_id") or ""),
                research_goal=config.research_goal,
            ),
        )
    )
    budget = budget_for_tier(tier, retrieval.sources)
    return None if budget is None else (retrieval, budget)


def _seed_questions(analyses: list[dict[str, Any]], limit: int) -> list[str]:
    """Take the first level's questions from what the papers left open.

    The per-paper analysis already records each paper's stated gaps,
    unexplored areas and method limitations. Those are the questions this
    run has *earned* by reading, so they beat a fresh stance-planning
    call that has read nothing. When the analyses recorded none, an empty
    list is returned and the loop plans its own coverage from the goal.

    Args:
        analyses: Phase 3's per-paper analyses.
        limit: The first level's breadth -- more seeds than this would be
            declined by the budget anyway.

    Returns:
        Distinct gap statements, in the order the papers were analyzed.
    """
    seeds: list[str] = []
    seen: set[str] = set()
    for entry in analyses:
        for gap in _gaps_in(entry.get("analysis")):
            if gap.lower() in seen:
                continue
            seen.add(gap.lower())
            seeds.append(gap)
            if len(seeds) >= limit:
                return seeds
    return seeds


def _gaps_in(analysis: object) -> list[str]:
    """Take one paper analysis's non-empty gap statements, in field order."""
    if not isinstance(analysis, dict):
        return []
    stated = (analysis.get(name) for name in _GAP_FIELDS)
    return [
        value.strip()
        for value in stated
        if isinstance(value, str) and value.strip()
    ]


def _synthesis_section(result: ResearchResult) -> str:
    """Render the research as a section of the review's own synthesis.

    Written into the synthesis rather than returned separately because
    the synthesis is what every later agent reads; a finding that lives
    only in the ledger has been recorded and not used.
    """
    if not result.findings:
        return ""
    lines = [
        "",
        "## Open questions researched",
        "",
        (
            f"Researched {len(result.threads)} question(s) over"
            f" {result.levels_run} level(s), following what each reading"
            f" left open. Stopped: {result.stop_reason.value}."
        ),
        "",
    ]
    for summary in result.summaries():
        lines.extend([summary, ""])
    lines.extend(["### Findings", ""])
    for finding in result.findings[:_MAX_LISTED_FINDINGS]:
        lines.append(f"- {finding.text} [{finding.locator}]")
    declined = result.declined()
    if declined:
        lines.extend(
            [
                "",
                (
                    f"{len(declined)} further question(s) were raised and"
                    " not researched, for budget."
                ),
            ]
        )
    return "\n".join(lines)
