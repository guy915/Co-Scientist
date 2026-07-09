"""Generation node - creates initial hypotheses.

Main entry point for the LangGraph workflow. All generation logic
has been moved to the generation/ package for better organization.
"""
# pylint: disable=inconsistent-quotes

import logging
from typing import Any

from co_scientist.models import create_metrics_update
from co_scientist.nodes.generation import generate_hypotheses
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
    result = await generate_hypotheses(state)

    # Add metrics. The coordinator always returns hypothesis_count (or raises).
    # create_metrics_update wraps it as a metrics delta; hypothesis_count
    # uses max() in the merge_metrics reducer (it's a running total, not
    # additive), so passing the coordinator's total here is correct even
    # across iterations that re-invoke this node.
    metrics = create_metrics_update(hypothesis_count=result["hypothesis_count"])
    result["metrics"] = metrics

    logger.info(
        "Generate node complete: %s",
        result.get("message", "generated hypotheses"),
    )

    return result
