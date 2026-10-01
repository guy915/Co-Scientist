"""Tests for the adaptive loop-point routing in the workflow graph topology.

``co_scientist.generator.graph`` wires the LangGraph node/edges from the
topology ``co_scientist.workflow_topology`` declares; the node-set and
terminal-node shape are covered by ``tests/test_generator.py`` via
``HypothesisGenerator._build_graph``. This file exercises the conditional-
edge routing function ``route_next_task`` directly: it maps the orchestrator's
recorded ``next_task`` (a scheduling ``TaskType`` value) to the graph node that
begins that task.
"""

import pytest
from langgraph.graph import StateGraph

from co_scientist.generator.graph import (
    _add_workflow_edges,
    _add_workflow_nodes,
    _resume_router,
)
from co_scientist.scheduling import ALLOWED_LOOP_TASKS, TaskType
from co_scientist.state import WorkflowState
from co_scientist.workflow_topology import TASK_ROUTES, route_next_task
from tests._state import make_state


def _inbound_edges(
    enable_literature_review_node: bool,
) -> dict[str, set[tuple[str, bool]]]:
    """Map each node to its inbound ``(source, conditional)`` edges.

    Compiles the real workflow topology for the given flow shape and reads
    the edge set back, so the assertions below pin the graph as wired rather
    than the routing functions in isolation.
    """
    workflow = StateGraph(WorkflowState)
    _add_workflow_nodes(workflow, enable_literature_review_node)
    _add_workflow_edges(workflow, enable_literature_review_node)
    graph = workflow.compile().get_graph()
    inbound: dict[str, set[tuple[str, bool]]] = {}
    for edge in graph.edges:
        inbound.setdefault(edge.target, set()).add(
            (edge.source, edge.conditional)
        )
    return inbound


def test_task_routes_reconcile_with_allowed_loop_tasks() -> None:
    """The routing table and the scheduler's dispatchable set stay in sync.

    ``scheduling.policy.ALLOWED_LOOP_TASKS`` and
    ``workflow_topology.TASK_ROUTES`` each carry a "keep in sync" comment
    pointing at the other; this pins the invariant programmatically: the
    routing table's keys are exactly the task values the scheduler may
    dispatch at the loop point.
    """
    assert {task.value for task in ALLOWED_LOOP_TASKS} == set(TASK_ROUTES)


def test_routes_each_task_type_to_its_node() -> None:
    """Every task the orchestrator can emit maps to a real entry node."""
    for task in ALLOWED_LOOP_TASKS:
        state = make_state(next_task=task.value)
        assert route_next_task(state) == TASK_ROUTES[task.value]


def test_evolve_routes_through_meta_review() -> None:
    """EVOLVE enters at meta_review so the critique feeds evolve."""
    state = make_state(next_task=TaskType.EVOLVE.value)
    assert route_next_task(state) == "meta_review"


def test_terminate_routes_to_research_overview() -> None:
    """TERMINATE routes to the terminal synthesis node."""
    state = make_state(next_task=TaskType.TERMINATE.value)
    assert route_next_task(state) == "research_overview"


def test_missing_next_task_falls_back_to_synthesis() -> None:
    """A missing decision never dead-ends; it routes to synthesis."""
    state = make_state(next_task=None)
    assert route_next_task(state) == "research_overview"


def test_unknown_next_task_falls_back_to_synthesis() -> None:
    """An unrecognized next_task value routes to synthesis, not a crash."""
    state = make_state(next_task="bogus")
    assert route_next_task(state) == "research_overview"


# --- SUP-SPLIT-001: plan synthesized once at entry, decisions every cycle ---
# The published supervisor listing (corpus MA-4, `01-supervisor.md`) parses the
# goal into a ResearchPlan and SAVEs it exactly once, before the main WHILE
# loop; neither ManageFollowUpTasks nor DecideNextSteps ever revisits it.
# DecideNextSteps is the per-idle-pass decision point (run a tournament batch,
# evolve if stalled, periodic meta-review/overview) against that fixed plan.
# Our topology mirrors that pair: `supervisor` is the entry-only planner and
# `orchestrator` is the loop point. These tests pin that behaviour so the row
# stays honest.


@pytest.mark.parametrize("enable_literature_review_node", [True, False])
def test_supervisor_plan_is_synthesized_once_never_revisited(
    enable_literature_review_node: bool,
) -> None:
    """The supervisor is reachable only at entry, so its plan is built once.

    Its sole inbound edge is the entry conditional from START; no node loops
    back to it, so the plan it synthesizes is never re-synthesized mid-run --
    matching `StartCoScientist`, which parses the plan before the main loop.
    """
    inbound = _inbound_edges(enable_literature_review_node)
    assert inbound["supervisor"] == {("__start__", True)}


@pytest.mark.parametrize("enable_literature_review_node", [True, False])
def test_orchestrator_is_the_per_cycle_loop_point(
    enable_literature_review_node: bool,
) -> None:
    """The orchestrator is re-entered every cycle to decide the next step.

    It is fed by the ranking and proximity nodes each pass (and by START on a
    resumed run), which is the `DecideNextSteps` decision point -- run against
    the fixed plan, never re-planning it.
    """
    inbound_sources = {
        source
        for source, _ in _inbound_edges(enable_literature_review_node)[
            "orchestrator"
        ]
    }
    assert {"__start__", "ranking", "proximity"} <= inbound_sources


def test_fresh_run_enters_supervisor_resume_bypasses_it() -> None:
    """A fresh run plans; a resumed run re-enters at the orchestrator.

    On resume the plan is restored from the checkpoint rather than rebuilt,
    so the entry router routes around the supervisor entirely -- the plan
    survives a checkpoint without a second synthesis.
    """
    assert _resume_router(make_state()) == "supervisor"
    assert _resume_router(make_state(resume=True)) == "orchestrator"
