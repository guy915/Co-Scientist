"""Generation coordinator - orchestrates all generation strategies.

All generation paths output hypotheses with explanation, literature_grounding,
and experiment fields.
When no literature is available, literature_grounding contains an explicit
warning message.

The strategy/count, result-assembly, and enrichment helpers live in sibling
modules (coordinator_strategy.py, coordinator_results.py,
coordinator_enrichment.py); the leaf-strategy dispatch stays here so tests
can monkeypatch generate_with_tools/generate_with_debate on this namespace.
All helper names are re-exported here for compatibility.
"""

import asyncio
import logging
from collections import Counter
from collections.abc import Coroutine
from typing import Any

from co_scientist.agents.generation.assumptions import (
    generate_with_assumptions,
)
from co_scientist.agents.generation.citations import (
    ReferenceIndex,
    build_reference_index,
)
from co_scientist.agents.generation.coordinator_enrichment import (
    _enrich_hypotheses as _enrich_hypotheses,
)
from co_scientist.agents.generation.coordinator_enrichment import (
    _enrich_one_hypothesis as _enrich_one_hypothesis,
)
from co_scientist.agents.generation.coordinator_enrichment import (
    _run_one_enrichment as _run_one_enrichment,
)
from co_scientist.agents.generation.coordinator_results import (
    GenerationResults as GenerationResults,
)
from co_scientist.agents.generation.coordinator_results import (
    _apply_degraded_mode_fallback as _apply_degraded_mode_fallback,
)
from co_scientist.agents.generation.coordinator_results import (
    _build_summary_message_parts as _build_summary_message_parts,
)
from co_scientist.agents.generation.coordinator_results import (
    _emit_complete_progress as _emit_complete_progress,
)
from co_scientist.agents.generation.coordinator_results import (
    _log_bucket_methods as _log_bucket_methods,
)
from co_scientist.agents.generation.coordinator_results import (
    _log_generation_summary as _log_generation_summary,
)
from co_scientist.agents.generation.coordinator_results import (
    _unpack_generation_results as _unpack_generation_results,
)
from co_scientist.agents.generation.coordinator_strategy import (
    GenerationCounts as GenerationCounts,
)
from co_scientist.agents.generation.coordinator_strategy import (
    _check_literature_availability as _check_literature_availability,
)
from co_scientist.agents.generation.coordinator_strategy import (
    _classify_generation_strategy as _classify_generation_strategy,
)
from co_scientist.agents.generation.coordinator_strategy import (
    _determine_generation_counts as _determine_generation_counts,
)
from co_scientist.agents.generation.coordinator_strategy import (
    _emit_start_progress as _emit_start_progress,
)
from co_scientist.agents.generation.coordinator_strategy import (
    _generation_log_case as _generation_log_case,
)
from co_scientist.agents.generation.coordinator_strategy import (
    _log_generation_strategy as _log_generation_strategy,
)
from co_scientist.agents.generation.coordinator_strategy import (
    _split_tools_and_debate_counts as _split_tools_and_debate_counts,
)
from co_scientist.agents.generation.coordinator_strategy import (
    _start_progress_message as _start_progress_message,
)
from co_scientist.agents.generation.debate import (
    generate_with_debate,
)
from co_scientist.agents.generation.expansion_research import (
    research_for_expansion,
)
from co_scientist.agents.generation.literature_tools import (
    generate_with_tools,
)
from co_scientist.agents.meta_review.interim_overview import (
    format_interim_overview,
)
from co_scientist.exceptions import GenerationError
from co_scientist.models import GenerationMethod, Hypothesis
from co_scientist.state import AppendHypotheses, WorkflowState

logger = logging.getLogger(__name__)


def _build_tools_task(
    state: WorkflowState,
    counts: GenerationCounts,
    reference_index: ReferenceIndex,
) -> tuple[str, Coroutine[Any, Any, Any]] | None:
    """Build the tool-based generation task, or None if none is allocated."""
    if counts.tools_count <= 0:
        return None
    logger.info(
        "Running tool-based generation for %s hypotheses", counts.tools_count
    )
    return (
        "tools",
        generate_with_tools(state, counts.tools_count, reference_index),
    )


def _build_debate_lit_task(
    state: WorkflowState,
    counts: GenerationCounts,
    articles_with_reasoning: str | None,
    reference_index: ReferenceIndex,
) -> tuple[str, Coroutine[Any, Any, Any]] | None:
    """Build the debate-with-literature task, or None if none is allocated."""
    if counts.debate_with_lit_count <= 0:
        return None
    logger.info(
        "Running debate-with-literature for %s hypotheses",
        counts.debate_with_lit_count,
    )
    return (
        "debate_lit",
        generate_with_debate(
            state=state,
            count=counts.debate_with_lit_count,
            articles_with_reasoning=articles_with_reasoning,
            reference_index=reference_index,
        ),
    )


def _build_debate_only_task(
    state: WorkflowState,
    counts: GenerationCounts,
) -> tuple[str, Coroutine[Any, Any, Any]] | None:
    """Build the debate-only (degraded-mode) task, or None if unallocated."""
    if counts.debate_only_count <= 0:
        return None
    logger.info(
        "Running debate-only for %s hypotheses", counts.debate_only_count
    )
    return (
        "debate_only",
        generate_with_debate(
            state=state,
            count=counts.debate_only_count,
            # Passed explicitly rather than omitted, so degraded-mode
            # debates never accidentally pick up literature context from a
            # caller-supplied default.
            articles_with_reasoning=None,  # explicitly no literature
            reference_index=ReferenceIndex(text="", sources={}),
        ),
    )


def _build_assumptions_task(
    state: WorkflowState,
    counts: GenerationCounts,
    articles_with_reasoning: str | None,
    reference_index: ReferenceIndex,
) -> tuple[str, Coroutine[Any, Any, Any]] | None:
    """Build the assumptions-technique task, or None if none is allocated."""
    if counts.assumptions_count <= 0:
        return None
    logger.info(
        "Running assumptions generation for %s hypotheses",
        counts.assumptions_count,
    )
    return (
        "assumptions",
        generate_with_assumptions(
            state,
            counts.assumptions_count,
            # Guarded inside the technique: a real (non-empty) reference
            # index grounds the claims; the degraded path supplies an empty
            # index and ignores the prose.
            articles_with_reasoning=articles_with_reasoning,
            reference_index=reference_index,
        ),
    )


def _build_generation_tasks(
    state: WorkflowState,
    counts: GenerationCounts,
    articles_with_reasoning: str | None,
    reference_index: ReferenceIndex,
) -> list[tuple[str, Coroutine[Any, Any, Any]]]:
    """Build the (task_type, coroutine) pairs for each enabled strategy.

    Args:
        state: current workflow state
        counts: per-strategy hypothesis counts from
            _determine_generation_counts.
        articles_with_reasoning: optional literature review context.
        reference_index: citation key → source mapping shared across
            strategies.

    Returns:
        Task list in the order they should be passed to asyncio.gather.
    """
    # Collect tasks to run in parallel. Each entry pairs a tag with its
    # coroutine so results can be routed back to the right bucket after
    # asyncio.gather() returns them in call order (order is not otherwise
    # recoverable once the coroutines are unpacked into gather()).
    task_builders = (
        _build_tools_task(state, counts, reference_index),
        _build_debate_lit_task(
            state, counts, articles_with_reasoning, reference_index
        ),
        _build_debate_only_task(state, counts),
        _build_assumptions_task(
            state, counts, articles_with_reasoning, reference_index
        ),
    )
    return [task for task in task_builders if task is not None]


async def _execute_generation_tasks(
    state: WorkflowState,
    counts: GenerationCounts,
    articles_with_reasoning: str | None,
    reference_index: ReferenceIndex,
) -> GenerationResults:
    """Execute parallel generation tasks and return results."""
    tasks = _build_generation_tasks(
        state, counts, articles_with_reasoning, reference_index
    )

    # Run all tasks in parallel; gather preserves the order tasks were
    # appended in, which is what the index-based unpack in
    # _unpack_generation_results relies on.
    results = await asyncio.gather(*[task for _, task in tasks])

    return _unpack_generation_results(tasks, results)


# Main coordinator function


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


async def _prepare_generation(
    state: WorkflowState,
) -> tuple[GenerationCounts, ReferenceIndex, str | None]:
    """Validate preconditions and resolve strategy, counts, and references.

    Also logs the resolved strategy and emits the generation-start progress
    callback, since both key off the counts computed here.

    Returns:
        Tuple of (counts, reference_index, articles_with_reasoning).

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

    return (
        counts,
        reference_index,
        _with_interim_overview(state, articles_with_reasoning),
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

    Deliberately applied *after* ``_check_literature_availability`` above:
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


async def _finalize_generation(
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


async def generate_hypotheses(state: WorkflowState) -> dict[str, Any]:
    """Coordinate hypothesis generation using appropriate strategies.

    Implements 3-condition strategy:
    - Condition (a): lit review + tools → 50% tool-based + 50% debate-with-lit
    - Condition (b): no lit review → 100% debate-only
    - Condition (c): lit review but no tools → 100% debate-with-lit

    Args:
        state: current workflow state

    Returns:
        dict with hypotheses, debate_transcripts, metrics, and message
    """
    logger.info("Starting hypothesis generation")

    expansion = await research_for_expansion(state)
    if expansion is not None:
        state = expansion.applied_to(state)

    (
        counts,
        reference_index,
        articles_with_reasoning,
    ) = await _prepare_generation(state)

    try:
        results = await _execute_generation_tasks(
            state, counts, articles_with_reasoning, reference_index
        )
        result = await _finalize_generation(state, counts, results)
        if expansion is not None:
            result["articles"] = state.get("articles")
            result["research_ledgers"] = [expansion.ledger]
        return result

    except Exception as e:
        # Log with full context here (this is the top-level entry point),
        # then re-raise so the caller (generate_node) treats generation
        # failure as a hard error rather than a partial/degraded result.
        logger.error("Generation failed: %s", e)
        raise
