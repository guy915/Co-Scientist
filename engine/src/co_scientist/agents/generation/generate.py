"""Generation node - creates initial hypotheses.

Main entry point for the LangGraph workflow. All generation logic
has been moved to the generation/ package for better organization.

The node itself is delegation plus one metrics delta, and both halves
have a history worth keeping next to them.

The coordinator does the real work -- choosing a strategy (tool-based /
debate-with-literature / debate-only) from literature and tool-calling
availability, running it, and returning hypotheses, transcripts,
``hypothesis_count`` and a message. A failure inside it propagates as an
exception rather than as a partial result.

The delta carries three fields with three different merge policies.
``hypothesis_count`` is a running total and merges with ``max()``, so
passing the coordinator's total is correct even across iterations that
re-invoke this node. ``llm_calls`` is additive and is the real
completions every strategy spent this cycle -- debate turns,
assumption-tree calls, tool-loop iterations (finding L3: generation
reported none at all, so ``max_llm_calls`` never saw its spend).
``skills_used`` is additive too, and is scoped here rather than returned
through the coordinator because the invocation happens inside a
workspace tool handler while the count is wanted at this node boundary.
The durable path scopes its own in ``engine_tasks.fanout_generation``,
since it runs each strategy as a separate task and never enters here.
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

    Args:
        state: current workflow state

    Returns:
        dict with hypotheses, debate_transcripts, metrics, and message
    """
    logger.info("Starting generate node")
    with scoped_skill_usage() as skills:
        result = await generate_hypotheses(state)
    result["metrics"] = create_metrics_update(
        hypothesis_count=result["hypothesis_count"],
        deltas=MetricDeltas(
            llm_calls=result.get("llm_call_count", 0),
            skills_used=skills.snapshot(),
        ),
    )
    logger.info(
        "Generate node complete: %s",
        result.get("message", "generated hypotheses"),
    )
    return result
