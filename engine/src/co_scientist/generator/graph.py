"""Workflow graph topology for the hypothesis generator.

Defines the compiled-workflow type aliases, registers every LangGraph node,
wires the edges between them, and makes the post-ranking/post-proximity
routing decisions that drive the iteration cycle.
"""

import logging
from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from co_scientist.nodes.deep_verification import deep_verification_node
from co_scientist.nodes.evolve import evolve_node

# Node callables, one per LangGraph node; see _add_workflow_nodes below for
# how they are wired into the workflow graph.
from co_scientist.nodes.generate import generate_node
from co_scientist.nodes.literature_review import literature_review_node
from co_scientist.nodes.meta_review import meta_review_node
from co_scientist.nodes.proximity import proximity_node
from co_scientist.nodes.ranking import ranking_node
from co_scientist.nodes.reflection import reflection_node
from co_scientist.nodes.research_overview import research_overview_node
from co_scientist.nodes.review import review_node
from co_scientist.nodes.supervisor import supervisor_node
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)

# Compiled LangGraph workflow. The fourth type parameter (StateT) is left
# loose because langgraph's compile() leaks an unbound type variable.
CompiledWorkflow = CompiledStateGraph[Any, Any, Any, Any]

# Workflow graph under construction, pre-compile. Type parameters left loose
# for the same reason as CompiledWorkflow above.
_WorkflowBuilder = StateGraph[Any, Any, Any, Any]


def _after_ranking(state: WorkflowState) -> str:
    """Decide what to do after ranking based on workflow state."""
    current_iteration = state.get("current_iteration", 0)
    max_iterations = state.get("max_iterations", 0)
    # Check if we've already run meta_review (indicates we're in
    # iteration cycle)
    has_meta_review = bool(state.get("meta_review", {}))

    if not has_meta_review:
        # First ranking - check if we should start iterating
        if current_iteration < max_iterations:
            logger.info(
                "Starting iteration %s/%s",
                current_iteration + 1,
                max_iterations,
            )
            return "iterate"
        else:
            logger.info("No iterations needed, ending workflow")
            return "end"
    else:
        # We're in an iteration cycle - go through proximity for
        # deduplication
        logger.info("Going through proximity check")
        return "proximity"


def _after_proximity(state: WorkflowState) -> str:
    """Check if should continue after proximity deduplication."""
    # Note: proximity node increments current_iteration
    current_iteration = state.get("current_iteration", 0)
    max_iterations = state.get("max_iterations", 0)

    if current_iteration < max_iterations:
        logger.info(
            "Continuing to iteration %s/%s",
            current_iteration + 1,
            max_iterations,
        )
        return "iterate"
    else:
        logger.info("All iterations complete after deduplication")
        return "end"


def _add_workflow_nodes(
    workflow: _WorkflowBuilder, enable_literature_review_node: bool
) -> None:
    """Registers every workflow node on the graph.

    Args:
        workflow: The graph under construction; mutated in place.
        enable_literature_review_node: Whether to include the literature
            review and reflection nodes (requires MCP server).
    """
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("generate", generate_node)
    workflow.add_node("review", review_node)
    workflow.add_node("ranking", ranking_node)
    workflow.add_node("deep_verification", deep_verification_node)
    workflow.add_node("meta_review", meta_review_node)
    workflow.add_node("evolve", evolve_node)
    workflow.add_node("proximity", proximity_node)
    workflow.add_node("research_overview", research_overview_node)

    if enable_literature_review_node:
        workflow.add_node("literature_review", literature_review_node)
        workflow.add_node("reflection", reflection_node)


def _add_workflow_edges(
    workflow: _WorkflowBuilder, enable_literature_review_node: bool
) -> None:
    """Wires every workflow edge, including the entry point and routing.

    Args:
        workflow: The graph under construction, with all nodes already
            registered; mutated in place.
        enable_literature_review_node: Whether the literature review and
            reflection nodes are present, which determines the initial
            flow into "review".
    """
    # Initial flow - conditional based on literature review availability
    workflow.set_entry_point("supervisor")

    if enable_literature_review_node:
        # Full flow: supervisor → literature_review → generate → reflection
        # → review → ranking
        workflow.add_edge("supervisor", "literature_review")
        workflow.add_edge("literature_review", "generate")
        workflow.add_edge("generate", "reflection")
        workflow.add_edge("reflection", "review")
    else:
        # Simplified flow: supervisor → generate → review → ranking
        workflow.add_edge("supervisor", "generate")
        workflow.add_edge("generate", "review")

    workflow.add_edge("review", "ranking")

    # Iteration cycle: meta_review → evolve → review → ranking → proximity
    workflow.add_edge("meta_review", "evolve")
    workflow.add_edge("evolve", "review")  # Re-review evolved hypotheses

    # Note: review → ranking already defined above

    # Deep-verification runs on the top-ranked hypotheses after ranking,
    # then the same post-ranking routing decision (_after_ranking) is
    # made one node later.
    workflow.add_edge("ranking", "deep_verification")
    workflow.add_conditional_edges(
        "deep_verification",
        _after_ranking,
        {
            "iterate": "meta_review",
            "proximity": "proximity",
            "end": "research_overview",
        },
    )

    # After proximity, check if we should continue iterating
    workflow.add_conditional_edges(
        "proximity",
        _after_proximity,
        {"iterate": "meta_review", "end": "research_overview"},
    )

    # Terminal synthesis: every completion path flows through the
    # research-overview node before ending.
    workflow.add_edge("research_overview", END)
