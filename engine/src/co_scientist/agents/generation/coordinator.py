"""Generation coordinator: runs the graph path's strategies in parallel.

Planning and finalization live in ``operations`` and are also used by the
app's durable fan-out. The coordinator retains graph-only research expansion
and leaf dispatch; durable execution owns independent leases and failure
isolation, and currently omits citation context for its assumptions batches.
Leaf callables are bound here because this module executes them; tests patch
these bindings rather than an unrelated compatibility facade.
"""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

from co_scientist.agents.generation.assumptions import (
    generate_with_assumptions,
)
from co_scientist.agents.generation.citations import ReferenceIndex
from co_scientist.agents.generation.coordinator_results import (
    GenerationResults,
    _unpack_generation_results,
)
from co_scientist.agents.generation.coordinator_strategy import (
    GenerationCounts,
)
from co_scientist.agents.generation.debate import generate_with_debate
from co_scientist.agents.generation.expansion_research import (
    research_for_expansion,
)
from co_scientist.agents.generation.literature_tools import (
    generate_with_tools,
)
from co_scientist.agents.generation.operations import (
    finalize_generation,
    prepare_generation,
)
from co_scientist.state import WorkflowState

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

    plan = await prepare_generation(state)

    try:
        results = await _execute_generation_tasks(
            state, plan.counts, plan.literature, plan.reference_index
        )
        result = await finalize_generation(state, plan.counts, results)
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
