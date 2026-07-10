"""Tests for the adaptive loop-point routing in the workflow graph topology.

``co_scientist.generator.graph`` wires up the LangGraph node/edge topology;
the node-set and terminal-node shape are covered by ``tests/test_generator.py``
via ``HypothesisGenerator._build_graph``. This file exercises the conditional-
edge routing function ``_route_next_task`` directly: it maps the orchestrator's
recorded ``next_task`` (a scheduling ``TaskType`` value) to the graph node that
begins that task.
"""

from co_scientist.generator.graph import _TASK_ROUTES, _route_next_task
from co_scientist.scheduling import ALLOWED_LOOP_TASKS, TaskType
from tests._state import make_state


def test_routes_each_task_type_to_its_node() -> None:
    """Every task the orchestrator can emit maps to a real entry node."""
    for task in ALLOWED_LOOP_TASKS:
        state = make_state(next_task=task.value)
        assert _route_next_task(state) == _TASK_ROUTES[task.value]


def test_evolve_routes_through_meta_review() -> None:
    """EVOLVE enters at meta_review so the critique feeds evolve."""
    state = make_state(next_task=TaskType.EVOLVE.value)
    assert _route_next_task(state) == "meta_review"


def test_terminate_routes_to_research_overview() -> None:
    """TERMINATE routes to the terminal synthesis node."""
    state = make_state(next_task=TaskType.TERMINATE.value)
    assert _route_next_task(state) == "research_overview"


def test_missing_next_task_falls_back_to_synthesis() -> None:
    """A missing decision never dead-ends; it routes to synthesis."""
    state = make_state(next_task=None)
    assert _route_next_task(state) == "research_overview"


def test_unknown_next_task_falls_back_to_synthesis() -> None:
    """An unrecognized next_task value routes to synthesis, not a crash."""
    state = make_state(next_task="bogus")
    assert _route_next_task(state) == "research_overview"
