"""Generation planning and finalization shared by graph and durable callers.

These operations validate and allocate a cycle, then turn its successful
strategy results into an append update. They do not schedule or execute
strategies, commit state, or decide failure isolation. Preparation buys no
research: graph-only expansion remains in the coordinator, so calling this
boundary from a durable planner does not change its retrieval or spend.
Finalization can run configured enrichment tools and must precede any store
transaction.
"""

import logging
from collections import Counter
from dataclasses import dataclass
from typing import Any

from co_scientist.agents.generation.citations import (
    ReferenceIndex,
    build_reference_index,
)
from co_scientist.agents.generation.coordinator_enrichment import (
    _enrich_hypotheses,
)
from co_scientist.agents.generation.coordinator_results import (
    GenerationResults,
    _apply_degraded_mode_fallback,
    _emit_complete_progress,
    _log_generation_summary,
)
from co_scientist.agents.generation.coordinator_strategy import (
    GenerationCounts,
    _check_literature_availability,
    _determine_generation_counts,
    _emit_start_progress,
    _log_generation_strategy,
)
from co_scientist.agents.meta_review.interim_overview import (
    format_interim_overview,
)
from co_scientist.exceptions import GenerationError
from co_scientist.models import GenerationMethod, Hypothesis
from co_scientist.state import AppendHypotheses, WorkflowState

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GenerationPlan:
    """Resolved allocation and shared inputs for one generation cycle.

    Attributes:
        counts: Hypothesis allocation per method, including mode flags.
        reference_index: Shared citation keys across the enabled strategies.
        literature: Literature context, with any interim overview prepended.
            Debate-only callers must explicitly omit this context.
    """

    counts: GenerationCounts
    reference_index: ReferenceIndex
    literature: str | None


def _log_reference_index_summary(reference_index: ReferenceIndex) -> None:
    """Log a paper/KG-source breakdown of a non-empty reference index."""
    if reference_index.is_empty():
        return
    # Keys are uniformly "C<n>"; the paper/KG split lives in each source's
    # "type" field (see build_reference_index).
    counts = Counter(s.get("type") for s in reference_index.sources.values())
    logger.info(
        "Built reference index: %s paper(s), %s KG source(s)",
        counts["paper"],
        counts["knowledge_graph"],
    )


def _extract_generation_inputs(
    state: WorkflowState,
) -> tuple[str | None, bool, bool, int]:
    """Extract generation preconditions from state, validating as it goes.

    Args:
        state: current workflow state

    Returns:
        Tuple of (articles_with_reasoning, mcp_available, enable_tool_calling,
        total_count).

    Raises:
        GenerationError: if supervisor_guidance is missing from state.
    """
    # supervisor_guidance drives prompt assembly in every downstream
    # generation path, so its absence is treated as a hard precondition
    # failure rather than something to silently work around.
    if not state.get("supervisor_guidance"):
        raise GenerationError(
            "No supervisor_guidance in state for node=generation"
        )
    articles_with_reasoning = state.get("articles_with_reasoning")
    mcp_available = bool(state.get("mcp_available", False))
    enable_tool_calling = bool(
        state.get("enable_tool_calling_generation", False)
    )
    total_count = state["initial_hypotheses_count"]
    return (
        articles_with_reasoning,
        mcp_available,
        enable_tool_calling,
        total_count,
    )


async def prepare_generation(
    state: WorkflowState,
) -> GenerationPlan:
    """Validate preconditions and resolve strategy, counts, and references.

    Also logs the resolved strategy and emits the generation-start progress
    callback, since both key off the counts computed here.

    Returns:
        The allocation, shared citation namespace, and strategy context.

    Raises:
        GenerationError: if supervisor_guidance is missing from state.
    """
    (
        articles_with_reasoning,
        mcp_available,
        enable_tool_calling,
        total_count,
    ) = _extract_generation_inputs(state)

    has_literature = _check_literature_availability(
        articles_with_reasoning, mcp_available
    )
    counts = _determine_generation_counts(
        state, total_count, has_literature, enable_tool_calling
    )

    # Shared [C*] citation-key namespace for every strategy below.
    reference_index = build_reference_index(
        articles=state.get("articles"),
        context_enrichment_sources=state.get("context_enrichment_sources"),
    )
    _log_reference_index_summary(reference_index)

    _log_generation_strategy(counts, total_count)
    await _emit_start_progress(state, counts, total_count)

    return GenerationPlan(
        counts=counts,
        reference_index=reference_index,
        literature=_with_interim_overview(state, articles_with_reasoning),
    )


def _with_interim_overview(
    state: WorkflowState, articles_with_reasoning: str | None
) -> str | None:
    """Prepend this run's own interim overview to the generation context.

    The feedback edge of FIX-6: a periodic ``research_overview`` firing
    leaves the directions and open questions it synthesized on the state,
    and this is where the next cycle reads them. Spliced onto the context
    the strategies are already handed rather than into a new prompt slot
    -- it describes what this run has established so far, which is what
    that context is.

    Deliberately applied after the literature-availability check in planning:
    the run's own synthesis is not literature, and a degraded-mode run
    must not read as having retrieved something. For the same reason the
    debate-only strategy, which passes ``articles_with_reasoning=None``
    explicitly, never sees it.

    Args:
        state: The workflow state the generate node was entered with.
        articles_with_reasoning: The literature-review context, or None
            when this run has none.

    Returns:
        The context with the interim block above it, or the context
        unchanged when this run has had no periodic firing yet.
    """
    block = format_interim_overview(state)
    if not block:
        return articles_with_reasoning
    if not articles_with_reasoning:
        return block
    return f"{block}\n\n{articles_with_reasoning}"


def _stamp_generation_lineage(
    hypotheses: list[Hypothesis], creation_iteration: int
) -> None:
    """Stamp generation-0 lineage and research-expansion provenance in place.

    origin/generation keep their construction defaults (GENERATION, 0); the
    Generation agent produces roots, so parent_id stays None. Later
    research-expansion cycles reuse this node with a higher iteration, in
    which case the underlying generation method is preserved as provenance
    before the observable technique is stamped over it.

    Args:
        hypotheses: hypotheses to stamp, mutated in place.
        creation_iteration: workflow iteration that produced these
            hypotheses.
    """
    for hyp in hypotheses:
        hyp.creation_iteration = creation_iteration
        if creation_iteration > 0:
            if hyp.generation_method is not None:
                hyp.enrichments["base_generation_method"] = (
                    hyp.generation_method.value
                )
            hyp.generation_method = GenerationMethod.RESEARCH_EXPANSION


async def finalize_generation(
    state: WorkflowState,
    counts: GenerationCounts,
    results: GenerationResults,
) -> dict[str, Any]:
    """Apply the degraded-mode fallback, enrich, and build the result dict.

    Args:
        state: current workflow state
        counts: per-strategy counts from _determine_generation_counts
        results: gathered generation results from _execute_generation_tasks

    Returns:
        dict with hypotheses, debate_transcripts, hypothesis_count,
        llm_call_count, message.
    """
    # Only debate_only_hypotheses need the fallback message: tools_ and
    # debate_with_lit_hypotheses are only populated when has_literature was
    # true, so is_degraded_mode and those lists are mutually exclusive by
    # construction. Assumptions generation runs in the same no-literature
    # path, so its hypotheses need the same fallback grounding.
    if counts.is_degraded_mode:
        _apply_degraded_mode_fallback(results.debate_only_hypotheses)
        _apply_degraded_mode_fallback(results.assumptions_hypotheses)

    _log_generation_summary(results)
    message_content = await _emit_complete_progress(state, results, counts)

    all_hypotheses = results.all_hypotheses
    _stamp_generation_lineage(all_hypotheses, state.get("current_iteration", 0))

    # Run post-generation enrichments (e.g., NVD CVE lookup)
    await _enrich_hypotheses(all_hypotheses, state)

    # Append (not replace): a later generation cycle adds to the pool.
    return {
        "hypotheses": AppendHypotheses(all_hypotheses),
        "debate_transcripts": results.debate_transcripts,
        "hypothesis_count": len(all_hypotheses),
        "llm_call_count": results.llm_call_count,
        "message": message_content,
    }
