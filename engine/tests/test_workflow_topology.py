"""The workflow topology is declared once; each divergence is deliberate.

``co_scientist.workflow_topology`` declares every node's successor. The
compiled graph is wired from it and ``task_runtime.next_task_type`` resolves
through it, so these tests check two things: that the wiring really follows
the declaration, and -- one test per entry in that module's list -- that the
places the two paths differ are exactly the declared ones.
``test_task_runtime.test_next_task_type_mirrors_graph_topology`` is the
cross-check of the two answers everywhere they agree.
"""

import pytest
from langgraph.graph import END, START

from co_scientist.agents import NODE_REGISTRY
from co_scientist.scheduling import TaskType
from co_scientist.state import WorkflowState
from co_scientist.task_runtime import next_task_type
from co_scientist.workflow_topology import (
    TASK_ROUTES,
    WORKFLOW_ROUTES,
    LiteratureGated,
    literature_review_nodes,
)
from tests._state import make_state
from tests._topology import (
    ABSENT,
    build_graph,
    decision_states,
    graph_successor,
)


def _declared_edges(literature_review: bool) -> set[tuple[str, str]]:
    """The fixed edges the declaration calls for in one flow shape."""
    absent = set() if literature_review else literature_review_nodes()
    edges: set[tuple[str, str]] = set()
    for node, route in WORKFLOW_ROUTES.items():
        if node in absent:
            continue
        if isinstance(route, LiteratureGated):
            edges.add((node, route.pick(literature_review)))
        elif isinstance(route, str):
            edges.add((node, route))
    return edges


def test_every_registered_node_declares_a_successor_and_only_those() -> None:
    """The declaration covers the registry exactly, and names real nodes."""
    assert set(WORKFLOW_ROUTES) == set(NODE_REGISTRY)
    named = set(TASK_ROUTES.values()) | literature_review_nodes()
    for route in WORKFLOW_ROUTES.values():
        if isinstance(route, str):
            named.add(route)
        elif isinstance(route, LiteratureGated):
            named.add(route.off)
    assert named <= set(NODE_REGISTRY)


@pytest.mark.parametrize("literature_review", [True, False])
def test_the_graph_is_wired_from_the_declaration(
    literature_review: bool,
) -> None:
    """The compiled edges are the declared ones: no extra, none missing."""
    graph = build_graph(literature_review)
    assert set(graph.edges) == _declared_edges(literature_review)
    resolver_nodes = {
        node for node, route in WORKFLOW_ROUTES.items() if callable(route)
    }
    assert set(graph.branches) == resolver_nodes | {START}


def test_the_review_phase_runs_in_the_published_order() -> None:
    """Supervisor to loop point, in the order the listings give.

    Deep verification sits between the safety screen and ranking
    (``03-reflection.md``: verified, *then* AddToTournament), so no idea is
    ranked before its core assumptions have been probed.
    """
    state = make_state(mcp_available=True)
    chain = ["supervisor"]
    while chain[-1] != "orchestrator":
        successor = next_task_type(chain[-1], state)
        assert successor is not None
        chain.append(successor)
    assert chain == [
        "supervisor",
        "literature_review",
        "generate",
        "reflection",
        "review",
        "comprehensive_reflection",
        "safety_screen",
        "deep_verification",
        "ranking",
        "orchestrator",
    ]


# --- Declared divergences, in the order workflow_topology lists them -------


def _gated(node: str) -> LiteratureGated:
    route = WORKFLOW_ROUTES[node]
    assert isinstance(route, LiteratureGated)
    return route


@pytest.mark.parametrize("node", ["supervisor", "generate"])
def test_the_graph_takes_its_flow_shape_from_how_it_was_built(
    node: str,
) -> None:
    """Divergence 1, graph half: ``mcp_available`` in the state is not read.

    The shape is fixed when the graph is compiled (the nodes it skips are not
    registered at all), so the state a run carries cannot re-route it.
    """
    for literature_review in (True, False):
        graph = build_graph(literature_review)
        for mcp_available in (True, False):
            state = make_state(mcp_available=mcp_available)
            assert graph_successor(graph, node, state) == _gated(node).pick(
                literature_review
            )


@pytest.mark.parametrize("node", ["supervisor", "generate"])
def test_the_durable_path_takes_its_flow_shape_from_committed_state(
    node: str,
) -> None:
    """Divergence 1, durable half: ``mcp_available`` is read at commit time."""
    for mcp_available in (True, False):
        state = make_state(mcp_available=mcp_available)
        assert next_task_type(node, state) == _gated(node).pick(mcp_available)


def test_the_gated_routes_skip_the_literature_nodes_when_the_flow_is_off() -> (
    None
):
    """Divergence 1, concretely: which edges the shape changes."""
    assert _declared_edges(True) - _declared_edges(False) == {
        ("supervisor", "literature_review"),
        ("literature_review", "generate"),
        ("generate", "reflection"),
        ("reflection", "review"),
    }
    assert _declared_edges(False) - _declared_edges(True) == {
        ("supervisor", "generate"),
        ("generate", "review"),
    }
    assert literature_review_nodes() == {"literature_review", "reflection"}


def test_a_missing_mcp_flag_is_the_simplified_flow_on_the_durable_path() -> (
    None
):
    """Divergence 1: the durable selector treats an absent key as off."""
    state = make_state()
    del state["mcp_available"]  # type: ignore[misc]
    assert next_task_type("supervisor", state) == "generate"
    assert next_task_type("generate", state) == "review"


@pytest.mark.parametrize("node", ["literature_review", "reflection"])
def test_the_durable_path_still_routes_the_nodes_the_simplified_graph_lacks(
    node: str,
) -> None:
    """Divergence 1: with the flow off the graph has no such node at all."""
    state = make_state(mcp_available=False)
    assert graph_successor(build_graph(False), node, state) == ABSENT
    assert next_task_type(node, state) == WORKFLOW_ROUTES[node]


@pytest.mark.parametrize("node", sorted(WORKFLOW_ROUTES))
def test_a_safety_halt_ends_the_durable_path_from_every_node(
    node: str,
) -> None:
    """Divergence 2: ``safety_blocked`` stops the run; the graph ignores it."""
    graph = build_graph(True)
    for state in decision_states():
        halted = make_state(**{**state, "safety_blocked": True})
        assert next_task_type(node, halted) is None
        assert graph_successor(graph, node, halted) == graph_successor(
            graph, node, state
        )


def test_the_entry_edge_exists_only_on_the_graph() -> None:
    """Divergence 3: the graph enters through START; the durable path does not.

    A resumed run re-enters at the orchestrator on the graph; the durable
    path has no entry node to resolve, so asking for one is an error.
    """
    graph = build_graph(True)
    assert START not in WORKFLOW_ROUTES
    assert graph_successor(graph, START, make_state()) == "supervisor"
    assert graph_successor(graph, START, make_state(resume=True)) == (
        "orchestrator"
    )
    with pytest.raises(ValueError, match="unsupported completed task node"):
        next_task_type(START, make_state())


def test_the_end_of_the_run_is_none_durable_and_end_on_the_graph() -> None:
    """Divergence 4: one terminal state, two encodings of it."""
    state = make_state(next_task=TaskType.TERMINATE.value)
    graph = build_graph(True)
    branch = next(iter(graph.branches["research_overview"].values()))
    assert next_task_type("research_overview", state) is None
    assert branch.path.invoke(state) == END
    assert graph_successor(graph, "research_overview", state) is None


def _evolve_with_meta_review_stacked_ahead() -> WorkflowState:
    """A decision the scheduler never produces: EVOLVE already runs it."""
    return make_state(
        next_task=TaskType.EVOLVE.value,
        supervisor_queue_actions=[
            {
                "action": "enqueue",
                "task_type": TaskType.META_REVIEW.value,
                "reason": "stacked",
            }
        ],
    )


def test_the_graph_path_map_rejects_what_the_durable_path_returns() -> None:
    """Divergence 5: only a state the scheduler never produces tells them apart.

    ``stack_companions`` never stacks meta-review ahead of EVOLVE, which
    already runs it; were it to, the resolver would name ``meta_review``
    itself. The graph's path map for that node excludes the self-edge, so
    LangGraph would refuse the value, while the durable path returns it
    unchecked.
    """
    state = _evolve_with_meta_review_stacked_ahead()
    graph = build_graph(True)
    branch = next(iter(graph.branches["meta_review"].values()))
    chosen = branch.path.invoke(state)
    assert chosen == "meta_review"
    assert branch.ends is not None
    assert chosen not in branch.ends
    assert next_task_type("meta_review", state) == "meta_review"
