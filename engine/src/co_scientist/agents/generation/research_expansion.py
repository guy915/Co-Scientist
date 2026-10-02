"""Research expansion as a distinct generation technique (audit E11b).

When the adaptive scheduler re-enters the generate node after the first
cycle, the run is expanding its search region, not repeating initial
generation. Previously that was only a relabel: the hypotheses were
stamped ``GenerationMethod.RESEARCH_EXPANSION`` while running the exact
same prompts as the first cycle. This module gives the technique its own
behavior for the generation paths this package owns:

- a distinct prompt section switching the draft agent from focused
  grounding (support the gaps already identified) to broad exploratory
  retrieval -- several diverse queries across adjacent subtopics,
  methods, and populations, widening the evidence base BEFORE ideation;
- bounded coverage of the already-explored pool, so expansion targets
  regions the run has not staked out yet;
- a larger tool-loop budget for the draft agent, since broad retrieval
  legitimately needs more search/read round-trips than focused drafting;
- on the deep tiers, a budgeted exploration of the regions the run has
  not staked out, run before any drafting and rendered into the section
  below (``expansion_research``). That is what makes this an exploration
  program rather than a differently-worded generation pass, which is the
  gap ``GEN-TECHNIQUES-001`` recorded.

Detection keys off ``current_iteration``: generation in iteration 0 is
initial generation; every later generate cycle is research expansion
(the same signal ``operations._stamp_generation_lineage`` uses when it
stamps the method).
"""

import logging

from co_scientist.constants import truncate
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
