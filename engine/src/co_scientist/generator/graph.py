"""Workflow graph topology for the hypothesis generator.

Defines the compiled-workflow type aliases, registers every LangGraph node,
wires the edges between them, and makes the post-ranking/post-proximity
routing decisions that drive the iteration cycle.
"""

import logging
from collections.abc import Hashable
from typing import Any, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

# The canonical durable node key -> (agent, callable) registry; see
# _add_workflow_nodes below for how it is wired into the workflow graph.
from co_scientist.agents import NODE_REGISTRY
from co_scientist.scheduling.models import TaskType, stacked_task_values
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
# meta_review (its critique feeds evolve); META_REVIEW enters the same node and
# returns to the loop point instead (see _route_after_meta_review); TERMINATE
# enters the terminal synthesis. Keep in sync with
# scheduling.policy.ALLOWED_LOOP_TASKS.
_TASK_ROUTES: dict[str, str] = {
    "generate": "generate",
    "reflect": "review",
    "rank": "safety_screen",
    "evolve": "meta_review",
    "meta_review": "meta_review",
    "proximity": "proximity",
    # Both firings of the terminal synthesis node: TERMINATE ends the run
    # there, SYNTHESIZE is the periodic one that returns to the loop point
    # (see _route_after_research_overview).
    "synthesize": "research_overview",
    "terminate": "research_overview",
}

# The node names _route_next_task can return, as the identity path map
# langgraph's conditional edge wants (typed with its Hashable key, which is
# invariant). Derived from _TASK_ROUTES rather than restated: a task added
# there but missing from a hand-written literal is a route the compiled
# graph rejects at run time, not at review time.
_TASK_ROUTE_NODES: dict[Hashable, str] = {
    node: node for node in sorted(_TASK_ROUTES.values())
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


def _stacked_companions(state: WorkflowState) -> tuple[str, ...]:
    """The companion task values this pass queued ahead of its primary.

    One ``DecideNextSteps`` pass may queue several companions alongside
    the task it chose (``scheduling.policy.stack_companions``). They ride
    the decision's own queue actions, and stacking is an *ordering*: the
    companions run first in this order, the primary behind them, so
    ``next_task`` still names the primary for every consumer that reads
    it. Rewritten in full by every orchestrator pass, so a previous
    pass's companions can never leak into this one.
    """
    return stacked_task_values(state.get("supervisor_queue_actions") or [])


def _companion_successor(state: WorkflowState, after: str) -> str | None:
    """The node to run once the companion ``after`` has committed.

    Returns None when ``after`` did not run as a companion on this pass,
    which is the signal for its own router to fall back to whatever that
    node means outside a stacked pass.
    """
    companions = _stacked_companions(state)
    if after not in companions:
        return None
    remaining = companions[companions.index(after) + 1 :]
    value = remaining[0] if remaining else (state.get("next_task") or "")
    return _TASK_ROUTES.get(value, "research_overview")


def _route_next_task(state: WorkflowState) -> str:
    """Route to the node that starts the orchestrator's chosen next task.

    Reads ``next_task`` (set by ``orchestrator_node``) and maps it to a node,
    unless the same pass stacked companions ahead of it -- then the first
    of those. Falls back to terminal synthesis if the scheduler produced no
    decision, so the graph can never dead-end.
    """
    next_task = state.get("next_task") or "terminate"
    companions = _stacked_companions(state)
    node = _TASK_ROUTES.get(
        companions[0] if companions else next_task, "research_overview"
    )
    logger.info("Orchestrator routing next_task=%s -> %s", next_task, node)
    return node


# Where meta-review hands over when it was *not* reached as a stacked
# companion: EVOLVE's own prefix falls through to evolve, and a standalone
# periodic firing returns to the loop point. Every other task value is a
# stacked primary and resolves through _TASK_ROUTES like any other.
_AFTER_META_REVIEW: dict[str, str] = {
    "evolve": "evolve",
    "meta_review": "orchestrator",
}


def _route_after_meta_review(state: WorkflowState) -> str:
    """Route meta-review's successor from the task it was scheduled with.

    Meta-review is three things at once: the prefix node EVOLVE enters at,
    so the critique feeds the evolution prompts; a periodic task of its own
    (listing 01 L60-63); and the stacked companion one pass may queue ahead
    of whatever else it chose. Only the orchestrator's recorded decision
    tells them apart, and it is the same value ``_route_next_task`` already
    routed on.

    ``co_scientist.task_runtime`` routes the durable path through this same
    function, so the two execution paths cannot drift apart on it.
    """
    stacked = _companion_successor(state, TaskType.META_REVIEW.value)
    if stacked is not None:
        return stacked
    next_task = state.get("next_task") or "terminate"
    fixed = _AFTER_META_REVIEW.get(next_task)
    if fixed is not None:
        return fixed
    return _TASK_ROUTES.get(next_task, "research_overview")


def _route_after_research_overview(state: WorkflowState) -> str | None:
    """Route the overview node's successor from the task it was run for.

    The node is three things: the terminal synthesis every completion path
    ends at (listing 01 L65-69's ``RETURN FinalReport``), the periodic
    firing that listing's own "IF enough time has passed" describes, whose
    interim overview the next generate cycle reads (FIX-6), and the
    stacked companion form of that same periodic branch. Only the
    orchestrator's recorded decision tells them apart, exactly as it does
    for meta-review above.

    ``None`` is the terminal answer and is reachable only from the first
    of the three: ``engine.finalize`` is enqueued as this node's successor
    and nowhere else, so a stacked firing that returned it would end the
    run from the middle of a cycle.

    ``co_scientist.task_runtime`` routes the durable path through this
    same function -- returning ``None`` where the graph ends -- so the two
    execution paths cannot drift apart on it.
    """
    stacked = _companion_successor(state, TaskType.SYNTHESIZE.value)
    if stacked is not None:
        return stacked
    if state.get("next_task") == TaskType.SYNTHESIZE.value:
        return "orchestrator"
    return None


# The nodes _route_after_meta_review can return, as langgraph's identity path
# map (see _TASK_ROUTE_NODES for why the type is Hashable-keyed). "meta_review"
# is excluded: the only value routing to it is "meta_review" itself, which
# _AFTER_META_REVIEW sends to the loop point instead, so a self-edge here
# would be permanently unreachable.
_META_REVIEW_ROUTE_NODES: dict[Hashable, str] = {
    node: node
    for node in sorted({*_TASK_ROUTES.values(), "evolve", "orchestrator"})
    if node != "meta_review"
}


# The nodes _route_after_research_overview can return, derived the same way
# and for the same reason: a stacked overview hands over to the next
# companion or to the primary, so its path map is every task route plus the
# loop point, and END for the terminal firing's None. "research_overview" is
# excluded on the same argument as "meta_review" above -- the only values
# routing to it are SYNTHESIZE, which is never stacked onto itself, and
# TERMINATE, which is never stacked onto at all.
_OVERVIEW_ROUTE_NODES: dict[Hashable, str] = {
    node: node
    for node in sorted({*_TASK_ROUTES.values(), "evolve", "orchestrator"})
    if node != "research_overview"
}


# Nodes only registered when the MCP-backed literature-review path is on.
_MCP_GATED_NODES = frozenset({"literature_review", "reflection"})


def _add_workflow_nodes(
    workflow: _WorkflowBuilder, enable_literature_review_node: bool
) -> None:
    """Registers every workflow node on the graph from NODE_REGISTRY.

    Args:
        workflow: The graph under construction; mutated in place.
        enable_literature_review_node: Whether to include the literature
            review and reflection nodes (requires MCP server).
    """
    for key, spec in NODE_REGISTRY.items():
        if key in _MCP_GATED_NODES and not enable_literature_review_node:
            continue
        # cast: langgraph's add_node overloads reject the general async
        # callable alias, though every registered node satisfies them.
        workflow.add_node(key, cast(Any, spec.node))


def _add_entry_edge(workflow: _WorkflowBuilder) -> None:
    """Wires the graph entry: resume at the orchestrator, else supervisor.

    A checkpoint-restored run (resume=True) re-enters at the orchestrator
    loop point; a fresh run starts at the supervisor.
    """
    workflow.add_conditional_edges(
        START,
        _resume_router,
        {"supervisor": "supervisor", "orchestrator": "orchestrator"},
    )


def _add_generation_phase_edges(
    workflow: _WorkflowBuilder, enable_literature_review_node: bool
) -> None:
    """Wires the supervisor through generation into the review phase.

    Args:
        workflow: The graph under construction; mutated in place.
        enable_literature_review_node: Whether the literature review and
            reflection nodes are present, which determines the initial
            flow into "review".
    """
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


def _add_review_and_ranking_edges(workflow: _WorkflowBuilder) -> None:
    """Wires the review phase through the safety screen into ranking."""
    workflow.add_edge("review", "comprehensive_reflection")
    workflow.add_edge("comprehensive_reflection", "safety_screen")
    # Deep verification precedes tournament entry (``03-reflection.md``);
    # the durable twin of this edge is in ``task_runtime``.
    workflow.add_edge("safety_screen", "deep_verification")
    workflow.add_edge("deep_verification", "ranking")


def _add_evolution_edges(workflow: _WorkflowBuilder) -> None:
    """Wires the evolve branch: meta_review → evolve → review (re-reviewed).

    The first edge is conditional because meta-review is also a task in its
    own right (listing 01 L60-63), not only evolve's prefix; a standalone
    firing returns to the loop point instead of falling through to evolve.
    """
    workflow.add_conditional_edges(
        "meta_review", _route_after_meta_review, _META_REVIEW_ROUTE_NODES
    )
    workflow.add_edge("evolve", "review")


def _add_loop_and_terminal_edges(workflow: _WorkflowBuilder) -> None:
    """Wires the orchestrator loop-back edges and terminal synthesis.

    Ranking and proximity are both maintenance tasks that return to the
    adaptive loop point; the orchestrator's recorded decision then routes
    to the node that begins the next task (or to terminal synthesis),
    replacing the fixed post-ranking/post-proximity iteration-count edges.
    Every completion path flows through research-overview before ending.
    """
    workflow.add_edge("ranking", "orchestrator")
    workflow.add_edge("proximity", "orchestrator")
    workflow.add_conditional_edges(
        "orchestrator", _route_next_task, _TASK_ROUTE_NODES
    )
    workflow.add_conditional_edges(
        "research_overview",
        lambda state: _route_after_research_overview(state) or END,
        {**_OVERVIEW_ROUTE_NODES, END: END},
    )


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
    _add_entry_edge(workflow)
    _add_generation_phase_edges(workflow, enable_literature_review_node)
    _add_review_and_ranking_edges(workflow)
    _add_evolution_edges(workflow)
    _add_loop_and_terminal_edges(workflow)
