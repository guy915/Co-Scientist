"""LangGraph state definition for hypothesis generation workflow.

The state is passed through all nodes and tracks the complete workflow.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from langgraph.graph import add_messages
from typing_extensions import TypedDict

from co_scientist.models import (
    Article,
    ExecutionMetrics,
    Hypothesis,
    merge_metrics,
)

logger = logging.getLogger(__name__)


def _hypothesis_ids(hypotheses: list[Hypothesis]) -> set[str]:
    """Return the set of ids for hypotheses."""
    return {hyp.id for hyp in hypotheses}


def _normalized_texts(hypotheses: list[Hypothesis]) -> set[str]:
    """Return the set of stripped, lowercased texts for hypotheses."""
    return {hyp.text.strip().lower() for hyp in hypotheses}


def _resolve_hypothesis_pool(
    existing: list[Hypothesis], new: list[Hypothesis]
) -> list[Hypothesis]:
    """Decide whether `new` replaces or extends the existing hypothesis pool.

    Nodes use the reducer for two different purposes:
     - Updating nodes (ranking.py, proximity.py, evolve.py) return
       already-known hypotheses -- possibly re-scored, pruned to a subset,
       or rewritten by evolution -- and mean "this is the pool now".
     - Producing nodes (generate.py) return genuinely new hypotheses that
       should be appended to the existing pool.
    The primary discriminator is identity: if every incoming hypothesis id
    already exists in state, the update targets known hypotheses and is a
    replacement. Text overlap is kept as a secondary signal for callers
    (and tests) that rebuild equivalent hypotheses as fresh objects.
    Without the id check, evolve.py's rewritten texts would fail the
    overlap test and be merged as additions, resurrecting the lower-ranked
    hypotheses evolution had intentionally discarded.

    Args:
        existing: Existing hypotheses in state.
        new: New hypotheses being added or replacing existing.

    Returns:
        `new` alone for a replacement, or `existing + new` for an addition
        (neither deduplicated yet).
    """
    existing_ids = _hypothesis_ids(existing)
    new_ids = _hypothesis_ids(new)
    overlap = _normalized_texts(existing) & _normalized_texts(new)

    if new_ids <= existing_ids or len(overlap) > len(new) * 0.5:
        # Replacement operation - use new list as-is but deduplicate within it
        return new
    # Addition operation - merge and deduplicate
    return existing + new


def _dedupe_by_text(
    all_hyps: list[Hypothesis], new_count: int
) -> list[Hypothesis]:
    """Drop hypotheses whose normalized text already appeared earlier.

    Identity here is by normalized text, not id: within `all_hyps`, the first
    hypothesis with a given text wins. For a replacement, that is always the
    incoming (re-scored) version, since `all_hyps` is exactly the new list;
    for an addition, it is whichever of existing/new was appended first, so
    a genuinely duplicate new hypothesis is dropped in favor of the one
    already in state.

    Args:
        all_hyps: The candidate pool to deduplicate (existing+new, or just
            new for a replacement).
        new_count: Length of the reducer's original `new` argument, used
            only to decide whether a dropped duplicate is worth a warning
            (see the comment below).

    Returns:
        `all_hyps` with later duplicates by normalized text removed.
    """
    seen = set()
    deduplicated = []

    for hyp in all_hyps:
        # Use text hash for exact duplicate detection
        text_key = hyp.text.strip().lower()
        if text_key not in seen:
            seen.add(text_key)
            deduplicated.append(hyp)
        else:
            # Only log if this is truly a duplicate (not from replacement)
            # For a pure replacement, all_hyps is new itself, so this is
            # always false there; it only fires for real existing+new
            # duplicates found during an addition.
            if len(all_hyps) > new_count:
                logger.warning(
                    "Automatic dedup: Removed duplicate hypothesis: %s...",
                    hyp.text[:80],
                )

    return deduplicated


# This is the LangGraph reducer wired to WorkflowState.hypotheses (see
# `Annotated[list[Hypothesis], deduplicate_hypotheses]` below): every node
# that returns a "hypotheses" key in its state update triggers this
# function, with `existing` the current cumulative pool and `new` the value
# just returned by that node.
def deduplicate_hypotheses(
    existing: list[Hypothesis], new: list[Hypothesis]
) -> list[Hypothesis]:
    """State reducer that automatically deduplicates hypotheses on state update.

    This is a LangGraph anti-duplicate strategy: duplicates are automatically
    removed every time the state is updated, preventing them from propagating.

    Args:
        existing: Existing hypotheses in state
        new: New hypotheses being added or replacing existing

    Returns:
        Deduplicated list of hypotheses
    """
    # If new list is provided, use it (this is a replacement operation)
    # Only merge if new contains different hypotheses
    if not new:
        return existing

    all_hyps = _resolve_hypothesis_pool(existing, new)
    return _dedupe_by_text(all_hyps, len(new))


# Fields wrapped in Annotated[T, reducer] use `reducer` to combine a node's
# returned value with the prior state instead of the TypedDict default of
# last-write-wins; unannotated fields (e.g. current_iteration) are always
# overwritten outright by whichever node returns them.
class WorkflowState(TypedDict):
    """Complete state for the hypothesis generation workflow.

    This state is passed through all nodes in the LangGraph workflow.
    Each node reads from and writes to this state.
    """

    # Input
    research_goal: str
    """The research question to generate hypotheses for."""

    # Configuration
    model_name: str
    """LLM model to use (litellm format) for worker nodes."""

    supervisor_model_name: str
    """LLM model to use for supervisor and meta-review nodes (falls back to
    model_name if not set).
    """

    max_iterations: int
    """Number of refinement iterations to run."""

    initial_hypotheses_count: int
    """Number of initial hypotheses to generate."""

    evolution_max_count: int
    """Number of top hypotheses to evolve each iteration."""

    tournament_pairs: int
    """Number of pairwise Elo comparisons to run in each ranking pass."""

    literature_review_papers_count: int
    """Number of papers to read/analyze during literature review."""

    # Workflow State
    hypotheses: Annotated[list[Hypothesis], deduplicate_hypotheses]
    """Current list of hypotheses being processed (auto-deduplicated)."""

    current_iteration: int
    """Current iteration number (0-indexed)."""

    supervisor_guidance: dict[str, Any]
    """Supervisor's research plan and workflow guidance."""

    meta_review: dict[str, Any]
    """Meta-review insights for guiding evolution."""

    research_overview: dict[str, Any] | None
    """Terminal research overview plus NIH Specific Aims synthesis."""

    removed_duplicates: list[dict[str, Any]]
    """Tracking removed duplicate hypotheses."""

    tournament_matchups: list[dict[str, Any]]
    """List of tournament matchups with reasoning."""

    evolution_details: list[dict[str, Any]]
    """List of evolution transformations with reasoning."""

    # Metrics
    metrics: Annotated[ExecutionMetrics, merge_metrics]
    """Execution metrics for the workflow (auto-merged from concurrent updates).
    """

    start_time: float
    """Workflow start timestamp."""

    run_id: str
    """Unique identifier for this run (used for logging)."""

    # Progress Callback
    progress_callback: None | (Callable[[str, dict[str, Any]], Awaitable[None]])
    """Optional async callback for progress updates."""

    # Messages (for LangSmith tracing)
    # add_messages is LangGraph's own builtin reducer (id-based append/
    # merge), unlike the two custom reducers above.
    messages: Annotated[list[dict[str, Any]], add_messages]
    """Message history for LangSmith observability."""

    # Optional User Preferences and Inputs
    preferences: str | None
    """Optional: Desired approach or focus for hypothesis generation."""

    attributes: list[str] | None
    """Optional: Key qualities to prioritize in hypotheses."""

    constraints: list[str] | None
    """Optional: Requirements or boundaries for hypothesis generation."""

    criteria: list[str] | None
    """Optional: Explicit success criteria for judging hypotheses."""

    run_focus_guidance: str | None
    """Prompt-ready guidance for the selected run focus."""

    run_setup_guidance: str | None
    """Prompt-ready summary of the durable run setup fields."""

    starting_hypotheses: list[str] | None
    """Optional: User-provided starting hypotheses to build upon."""

    literature: list[str] | None
    """Optional: User-provided literature references to incorporate."""

    articles_with_reasoning: str | None
    """Literature review results with analytical reasoning (formatted for
    prompts).
    """

    literature_review_queries: list[str] | None
    """Generated search queries for literature review."""

    articles: list[Article] | None
    """Individual articles extracted from literature review (for hypothesis
    comparison).
    """

    debate_transcripts: list[dict[str, Any]] | None
    """Internal debate transcripts from parallel debates. Each entry:
    {debate_id, transcript, hypothesis_text}
    """

    mcp_available: bool | None
    """Whether MCP server (for literature review tools) is available."""

    pubmed_available: bool | None
    """Whether PubMed API (Entrez) is available."""

    enable_tool_calling_generation: bool | None
    """Enable tool-calling generation where generate node queries literature
    tools directly (requires enable_literature_review_node=True + MCP server,
    default False).
    """

    dev_test_lit_tools_isolation: bool | None
    """Development mode: force cache on lit review, allocate all hypotheses to
    lit tools (no debate).
    """

    tool_registry: Any | None
    """Optional ToolRegistry for config-driven tool selection."""

    context_enrichment_sources: list[dict[str, Any]] | None
    """Structured sources returned by context enrichment tools during
    literature review (e.g., INDRA mechanistic statements). Used to build
    [KG1]-style citation keys for hypothesis generation. Domain-agnostic:
    any enrichment tool can populate this.
    """
