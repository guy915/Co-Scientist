"""Workflow graph topology for the hypothesis generator.

Defines the compiled-workflow type aliases, registers every LangGraph node,
wires the edges between them, and makes the post-ranking/post-proximity
routing decisions that drive the iteration cycle.
"""

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from co_scientist.nodes.deep_verification import deep_verification_node
from co_scientist.nodes.evolve import evolve_node

# Node callables, one per LangGraph node; see _add_workflow_nodes below for
# how they are wired into the workflow graph.
from co_scientist.nodes.generate import generate_node
from co_scientist.nodes.literature_review import literature_review_node
from co_scientist.nodes.meta_review import meta_review_node
from co_scientist.nodes.orchestrator import orchestrator_node
from co_scientist.nodes.proximity import proximity_node
from co_scientist.nodes.ranking import ranking_node
from co_scientist.nodes.reflection import reflection_node
from co_scientist.nodes.research_overview import research_overview_node
from co_scientist.nodes.review import review_node
from co_scientist.nodes.safety_screen import safety_screen_node
from co_scientist.nodes.supervisor import supervisor_node
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)

# Compiled LangGraph workflow. The fourth type parameter (StateT) is left
# loose because langgraph's compile() leaks an unbound type variable.
CompiledWorkflow = CompiledStateGraph[Any, Any, Any, Any]

# Workflow graph under construction, pre-compile. Type parameters left loose
# for the same reason as CompiledWorkflow above.
_WorkflowBuilder = StateGraph[Any, Any, Any, Any]


# Maps the scheduler's chosen TaskType value (recorded by orchestrator_node in
# state["next_task"]) to the graph node that begins that task. EVOLVE enters at
# meta_review (its critique feeds evolve); TERMINATE enters the terminal
# synthesis. Keep in sync with scheduling.policy.ALLOWED_LOOP_TASKS.
_TASK_ROUTES: dict[str, str] = {
    "generate": "generate",
    "reflect": "review",
    "rank": "safety_screen",
    "evolve": "meta_review",
    "proximity": "proximity",
    "terminate": "research_overview",
}


def _resume_router(state: WorkflowState) -> str:
    """Route the graph entry: resume at the orchestrator, else fresh start.

    A checkpoint-restored state carries ``resume=True`` (Milestone 4), so the
    graph re-enters at the orchestrator loop point — every completed node's
    output is already in the restored pool/ledger, so the orchestrator reads
    state and picks the next task without re-running anything. A fresh run
    starts at the supervisor.
    """
    return "orchestrator" if state.get("resume") else "supervisor"


def _route_next_task(state: WorkflowState) -> str:
    """Route to the node that starts the orchestrator's chosen next task.

    Reads ``next_task`` (set by ``orchestrator_node``) and maps it to a node.
    Falls back to terminal synthesis if the scheduler produced no decision,
    so the graph can never dead-end.
    """
    next_task = state.get("next_task") or "terminate"
    node = _TASK_ROUTES.get(next_task, "research_overview")
    logger.info("Orchestrator routing next_task=%s -> %s", next_task, node)
    return node


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
    workflow.add_node("safety_screen", safety_screen_node)
    workflow.add_node("ranking", ranking_node)
    workflow.add_node("deep_verification", deep_verification_node)
    workflow.add_node("orchestrator", orchestrator_node)
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
    # Entry: a checkpoint-restored run (resume=True) re-enters at the
    # orchestrator loop point; a fresh run starts at the supervisor.
    workflow.add_conditional_edges(
        START,
        _resume_router,
        {"supervisor": "supervisor", "orchestrator": "orchestrator"},
    )

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

    workflow.add_edge("review", "safety_screen")
    workflow.add_edge("safety_screen", "ranking")

    # Evolve branch: meta_review → evolve → review (children re-reviewed).
    workflow.add_edge("meta_review", "evolve")
    workflow.add_edge("evolve", "review")

    # Note: review → safety_screen → ranking already defined above.

    # Every work phase converges on ranking → deep_verification → the
    # orchestrator, which is the single adaptive loop point.
    workflow.add_edge("ranking", "deep_verification")
    workflow.add_edge("deep_verification", "orchestrator")
    # Proximity is a maintenance task; it returns to the orchestrator too.
    workflow.add_edge("proximity", "orchestrator")

    # The orchestrator's recorded decision routes to the node that begins the
    # next task (or to terminal synthesis). This replaces the fixed
    # post-ranking/post-proximity iteration-count edges.
    workflow.add_conditional_edges(
        "orchestrator",
        _route_next_task,
        {
            "generate": "generate",
            "review": "review",
            "safety_screen": "safety_screen",
            "meta_review": "meta_review",
            "proximity": "proximity",
            "research_overview": "research_overview",
        },
    )

    # Terminal synthesis: every completion path flows through the
    # research-overview node before ending.
    workflow.add_edge("research_overview", END)
