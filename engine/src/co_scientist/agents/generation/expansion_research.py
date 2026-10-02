"""The exploration program behind a research-expansion cycle.

``research_expansion.py`` gave the technique a distinct prompt and a
larger tool-loop budget, which changes how the draft agent searches but
not *what* the run has read before it drafts. That left the gap
``GEN-TECHNIQUES-001`` names: research expansion was a meta-review
informed generation pass rather than a broad independent exploration of
the regions the run has not staked out.

This module is that exploration, and it is the same capability the
literature review and the deep reviews already run
(``co_scientist.research``) under a third policy. The three differ only
in what they are asked and how often:

* the literature review researches **once per run**, seeded by the gaps
  its own reading recorded;
* a deep review researches **once per hypothesis**, seeded by the
  assumptions that hypothesis failed to confirm;
* this researches **once per expansion cycle**, seeded by nothing --
  deliberately. Every seed the other two use is a doubt about ground the
  run has already covered, and expansion's whole job is the ground it has
  not. So the loop plans its own coverage from a goal that names the
  explored territory as territory to avoid, which is one model call and
  the only shape here that can return something the run has not seen.

**Cost is one more run-level gathering per expansion cycle**, at the same
ceilings the literature review buys: 6 threads on ``extended``, 11 on
``ultra``, times the cycles the scheduler chooses to expand in. Quoted
that way rather than given ceilings of its own, because a third table
holding the same numbers is a knob nobody would turn.
"""

from __future__ import annotations

import logging
from typing import Any, NamedTuple

from co_scientist.agents.generation.research_expansion import (
    explored_hypothesis_summaries,
    is_research_expansion,
)
from co_scientist.evidence.helpers import (
    build_articles_from_metadata,
)
from co_scientist.evidence.research_records import (
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
