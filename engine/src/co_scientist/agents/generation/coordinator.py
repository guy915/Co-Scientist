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
    GenerationResults,
    _unpack_generation_results,
    finalize_generation,
    prepare_generation,
)
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


def _build_generation_tasks(
    state: WorkflowState,
    counts: GenerationCounts,
    literature: str | None,
    reference_index: ReferenceIndex,
) -> list[tuple[str, Coroutine[Any, Any, Any]]]:
    """Build only allocated strategies, in hypothesis and transcript order."""
    tasks = []
    task: Coroutine[Any, Any, Any]
    for kind, count in counts.strategy_counts.items():
        if count <= 0:
            continue
        if kind == "tools":
            task = generate_with_tools(state, count, reference_index)
        elif kind == "assumptions":
            task = generate_with_assumptions(
                state,
                count,
                articles_with_reasoning=literature,
                reference_index=reference_index,
            )
        else:
            # Degraded debates must never pick up caller-supplied literature.
            has_lit = kind == "debate_lit"
            task = generate_with_debate(
                state=state,
                count=count,
                articles_with_reasoning=literature if has_lit else None,
                reference_index=(
                    reference_index
                    if has_lit
                    else ReferenceIndex(text="", sources={})
                ),
            )
        tasks.append((kind, task))
    return tasks


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
