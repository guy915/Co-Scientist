"""LangGraph state definition for hypothesis generation workflow.

The state is passed through all nodes and tracks the complete workflow.
"""

import logging
from typing import Annotated, Any
from collections.abc import Awaitable, Callable

from langgraph.graph import add_messages
from typing_extensions import TypedDict

from co_scientist.models import Article, ExecutionMetrics, Hypothesis

logger = logging.getLogger(__name__)


def deduplicate_hypotheses(existing: list[Hypothesis],
                           new: list[Hypothesis]) -> list[Hypothesis]:
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

    # Check if this is a replacement (same count or updating existing
    # hypotheses) vs. adding new hypotheses
    if len(new) > 0:
        # If first hypothesis in new has same id characteristics as existing,
        # this is a replacement operation, not addition
        existing_texts = {hyp.text.strip().lower() for hyp in existing}
        new_texts = {hyp.text.strip().lower() for hyp in new}

        # If substantial overlap, this is a replacement (e.g., updating
        # metadata)
        overlap = existing_texts & new_texts
        if len(overlap) > len(new) * 0.5:  # More than 50% overlap
            # Replacement operation - use new list as-is but deduplicate within
            # it
            all_hyps = new
        else:
            # Addition operation - merge and deduplicate
            all_hyps = existing + new
    else:
        all_hyps = existing + new

    # Deduplicate
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
            if len(all_hyps) > len(new):
                logger.warning(
                    "Automatic dedup: Removed duplicate hypothesis: %s...",
                    hyp.text[:80])

    return deduplicated


def merge_metrics(existing: ExecutionMetrics,
                  new: ExecutionMetrics) -> ExecutionMetrics:
    """State reducer that merges metrics from multiple nodes.

    When multiple nodes update metrics concurrently, this combines them.

    Args:
        existing: Existing metrics in state
        new: New metrics being added (should contain only deltas)

    Returns:
        Merged metrics (new object, does not mutate inputs)
    """
    # Create a NEW metrics object (don't mutate existing!)
    merged_phase_times = {}

    # Merge phase times from both existing and new
    for phase, time_val in existing.phase_times.items():
        merged_phase_times[phase] = time_val

    for phase, time_val in new.phase_times.items():
        if phase in merged_phase_times:
            merged_phase_times[phase] += time_val
        else:
            merged_phase_times[phase] = time_val

    merged = ExecutionMetrics(
        hypothesis_count=max(existing.hypothesis_count, new.hypothesis_count),
        reviews_count=existing.reviews_count + new.reviews_count,
        tournaments_count=existing.tournaments_count + new.tournaments_count,
        evolutions_count=existing.evolutions_count + new.evolutions_count,
        llm_calls=existing.llm_calls + new.llm_calls,
        total_time=new.total_time
        if new.total_time > 0 else existing.total_time,
        phase_times=merged_phase_times,
    )

    return merged


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

    # Workflow State
    hypotheses: Annotated[list[Hypothesis], deduplicate_hypotheses]
    """Current list of hypotheses being processed (auto-deduplicated)."""

    current_iteration: int
    """Current iteration number (0-indexed)."""

    supervisor_guidance: dict[str, Any]
    """Supervisor's research plan and workflow guidance."""

    meta_review: dict[str, Any]
    """Meta-review insights for guiding evolution."""

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
    messages: Annotated[list[dict[str, Any]], add_messages]
    """Message history for LangSmith observability."""

    # Optional User Preferences and Inputs
    preferences: str | None
    """Optional: Desired approach or focus for hypothesis generation."""

    attributes: list[str] | None
    """Optional: Key qualities to prioritize in hypotheses."""

    constraints: list[str] | None
    """Optional: Requirements or boundaries for hypothesis generation."""

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

    generation_corpus_slug: str | None
    """Shared corpus slug for reuse across draft and validation phases."""

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


class WorkflowConfig(TypedDict):
    """Configuration for the hypothesis generation workflow."""

    model_name: str
    max_iterations: int
    initial_hypotheses_count: int
    evolution_max_count: int
