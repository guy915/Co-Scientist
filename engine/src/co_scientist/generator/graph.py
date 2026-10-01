"""LangGraph wiring for the hypothesis generator's workflow.

Defines the compiled-workflow type aliases, registers every LangGraph node,
and wires the edges between them from ``co_scientist.workflow_topology``,
which declares the topology once for this streaming path and the durable
path alike. What lives here is only what is specific to compiling it into a
graph: the entry branch, and the path maps LangGraph wants for each
conditional edge.
"""

from collections.abc import Callable, Hashable
from typing import Any, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

# The canonical durable node key -> (agent, callable) registry; see
# _add_workflow_nodes below for how it is wired into the workflow graph.
from co_scientist.agents import NODE_REGISTRY
from co_scientist.state import WorkflowState
from co_scientist.workflow_topology import (
    TASK_ROUTES,
    WORKFLOW_ROUTES,
    LiteratureGated,
    Resolver,
    Route,
    literature_review_nodes,
)

# Compiled LangGraph workflow. The fourth type parameter (StateT) is left
# loose because langgraph's compile() leaks an unbound type variable.
CompiledWorkflow = CompiledStateGraph[Any, Any, Any, Any]

# Workflow graph under construction, pre-compile. Type parameters left loose
# for the same reason as CompiledWorkflow above.
_WorkflowBuilder = StateGraph[Any, Any, Any, Any]


# The node names route_next_task can return, as the identity path map
# langgraph's conditional edge wants (typed with its Hashable key, which is
# invariant). Derived from TASK_ROUTES rather than restated: a task added
# there but missing from a hand-written literal is a route the compiled
# graph rejects at run time, not at review time.
_TASK_ROUTE_NODES: dict[Hashable, str] = {
    node: node for node in sorted(TASK_ROUTES.values())
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


# The nodes route_after_meta_review can return, as langgraph's identity path
# map (see _TASK_ROUTE_NODES for why the type is Hashable-keyed). "meta_review"
# is excluded: the only value routing to it is "meta_review" itself, which
# the resolver sends to the loop point instead, so a self-edge here would be
# permanently unreachable.
_META_REVIEW_ROUTE_NODES: dict[Hashable, str] = {
    node: node
    for node in sorted({*TASK_ROUTES.values(), "evolve", "orchestrator"})
    if node != "meta_review"
}


# The nodes route_after_research_overview can return, derived the same way
# and for the same reason: a stacked overview hands over to the next
# companion or to the primary, so its path map is every task route plus the
# loop point, and END for the terminal firing's None. "research_overview" is
# excluded on the same argument as "meta_review" above -- the only values
# routing to it are SYNTHESIZE, which is never stacked onto itself, and
# TERMINATE, which is never stacked onto at all.
_OVERVIEW_ROUTE_NODES: dict[Hashable, str] = {
    node: node
    for node in sorted({*TASK_ROUTES.values(), "evolve", "orchestrator"})
    if node != "research_overview"
}

# For each node whose successor is a resolver, the nodes that resolver may
# name -- the part of a conditional edge that only a compiled graph needs.
_RESOLVER_PATH_MAPS: dict[str, dict[Hashable, str]] = {
    "orchestrator": _TASK_ROUTE_NODES,
    "meta_review": _META_REVIEW_ROUTE_NODES,
    "research_overview": {**_OVERVIEW_ROUTE_NODES, END: END},
}


def _add_workflow_nodes(
    workflow: _WorkflowBuilder, enable_literature_review_node: bool
) -> None:
    """Registers every workflow node on the graph from NODE_REGISTRY.

    Args:
        workflow: The graph under construction; mutated in place.
        enable_literature_review_node: Whether to include the literature
            review and reflection nodes (requires MCP server).
    """
    gated = literature_review_nodes()
    for key, spec in NODE_REGISTRY.items():
        if key in gated and not enable_literature_review_node:
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


def _ending_at_end(route: Resolver) -> Callable[[WorkflowState], str]:
    """Adapt a resolver to a conditional edge: its None (terminal) is END."""
    return lambda state: route(state) or END


def _add_route_edge(
    workflow: _WorkflowBuilder,
    node: str,
    route: Route,
    enable_literature_review_node: bool,
) -> None:
    """Wires one node's successor as the edge its route kind calls for."""
    if isinstance(route, LiteratureGated):
        # The flow shape is fixed when the graph is compiled, so a gated
        # route is an ordinary edge here (the durable path reads it at
        # commit time instead).
        workflow.add_edge(node, route.pick(enable_literature_review_node))
    elif callable(route):
        workflow.add_conditional_edges(
            node, _ending_at_end(route), _RESOLVER_PATH_MAPS[node]
        )
    else:
        workflow.add_edge(node, route)


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
    absent = (
        frozenset()
        if enable_literature_review_node
        else literature_review_nodes()
    )
    for node, route in WORKFLOW_ROUTES.items():
        if node not in absent:
            _add_route_edge(
                workflow, node, route, enable_literature_review_node
            )
