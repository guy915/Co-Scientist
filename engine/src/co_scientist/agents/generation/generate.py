"""Generation node - creates initial hypotheses.

Main entry point for the LangGraph workflow. All generation logic
has been moved to the generation/ package for better organization.
"""

import logging
from typing import Any

from co_scientist.agents.generation.coordinator import generate_hypotheses
from co_scientist.models import MetricDeltas, create_metrics_update
from co_scientist.skills import scoped_skill_usage
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


async def generate_node(state: WorkflowState) -> dict[str, Any]:
    """LangGraph node for hypothesis generation.

    Delegates to generation coordinator which orchestrates all strategies:
    - Literature usage (standard or tool-based)
    - Debate generation (with or without literature review, depending on
      configuration and availability)

    Args:
        state: current workflow state

    Returns:
        dict with hypotheses, debate_transcripts, metrics, and message
    """
    logger.info("Starting generate node")

    # Delegate to coordinator
    # This does all the real work: choosing a generation strategy (tool-
    # based / debate-with-literature / debate-only) based on literature and
    # tool-calling availability, running it, and returning a dict with
    # hypotheses, debate_transcripts, hypothesis_count, and message. Any
    # failure inside the coordinator propagates as an exception rather than
    # a partial result.
    # The science skills the drafting pass invokes are counted here
    # rather than returned through the coordinator: the invocation
    # happens inside a workspace tool handler and the number is wanted at
    # this node boundary, which is what the scope exists for. The durable
    # path scopes its own (engine_tasks_fanout_generation.py), since it
    # runs each strategy as a separate task and never enters this node.
    with scoped_skill_usage() as skills:
        result = await generate_hypotheses(state)

    # Add metrics. The coordinator always returns hypothesis_count (or
    # raises). create_metrics_update wraps it as a metrics delta;
    # hypothesis_count uses max() in the merge_metrics reducer (it's a
    # running total, not additive), so passing the coordinator's total here
    # is correct even across iterations that re-invoke this node.
    # llm_call_count is the real completions every strategy this cycle
    # spent (debate turns, assumption-tree calls, tool-loop iterations);
    # llm_calls is additive in the reducer, unlike hypothesis_count (finding
    # L3 -- generation previously reported no llm_calls at all, so
    # max_llm_calls never saw this node's real spend).
    metrics = create_metrics_update(
        hypothesis_count=result["hypothesis_count"],
        deltas=MetricDeltas(
            llm_calls=result.get("llm_call_count", 0),
            skills_used=skills.snapshot(),
        ),
    )
    result["metrics"] = metrics

    logger.info(
        "Generate node complete: %s",
        result.get("message", "generated hypotheses"),
    )

    return result
