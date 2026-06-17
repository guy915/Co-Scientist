"""Generation node - creates initial hypotheses.

Main entry point for the LangGraph workflow. All generation logic
has been moved to the generation/ package for better organization.
"""
# pylint: disable=inconsistent-quotes

import logging
from typing import Any

from co_scientist.models import create_metrics_update
from co_scientist.state import WorkflowState
from co_scientist.nodes.generation import generate_hypotheses

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
    result = await generate_hypotheses(state)

    # Add metrics
    hypothesis_count = result.get("hypothesis_count",
                                  len(result.get("hypotheses", [])))
    metrics = create_metrics_update(hypothesis_count=hypothesis_count)
    result["metrics"] = metrics

    logger.info("Generate node complete: %s",
                result.get('message', 'generated hypotheses'))

    return result
