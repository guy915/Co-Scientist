"""The agents package is the six-agent view over the durable graph nodes."""

from langgraph.graph import StateGraph

from co_scientist import agents, task_runtime
from co_scientist.agents.generation.generate import generate_node
from co_scientist.agents.reflection.review import review_node
from co_scientist.agents.supervisor.supervisor import supervisor_node
from co_scientist.generator.graph import (
    _add_workflow_edges,
    _add_workflow_nodes,
)
from co_scientist.state import WorkflowState

# The 14 durable node keys, frozen on purpose: they are persisted in the
# durable task queue and checkpoints as ``engine.node.<key>``, so renaming
# one is a data migration, not a refactor. This literal pin is intentional.
FROZEN_DURABLE_NODE_KEYS = {
    "supervisor",
    "generate",
    "review",
    "comprehensive_reflection",
    "safety_screen",
    "ranking",
    "deep_verification",
    "orchestrator",
    "meta_review",
    "evolve",
    "proximity",
    "research_overview",
    "literature_review",
    "reflection",
}


def _compiled_graph_node_keys() -> set[str]:
    """Compile the full workflow graph and return its registered node keys."""
    workflow = StateGraph(WorkflowState)
    _add_workflow_nodes(workflow, enable_literature_review_node=True)
    _add_workflow_edges(workflow, enable_literature_review_node=True)
    compiled = workflow.compile()
    return set(compiled.get_graph().nodes) - {"__start__", "__end__"}


def test_registry_pins_the_frozen_durable_node_keys() -> None:
    """NODE_REGISTRY carries exactly the frozen persisted key strings."""
    assert set(agents.NODE_REGISTRY) == FROZEN_DURABLE_NODE_KEYS


def test_graph_registry_and_task_runtime_agree() -> None:
    """Compiled graph keys == registry keys == durable TASK_NODES keys."""
    registry_keys = set(agents.NODE_REGISTRY)
    assert _compiled_graph_node_keys() == registry_keys
    assert set(task_runtime.TASK_NODES) == registry_keys


def test_node_to_agent_is_projected_from_the_registry() -> None:
    """NODE_TO_AGENT covers every registry key with the spec's agent."""
    assert set(agents.NODE_TO_AGENT) == set(agents.NODE_REGISTRY)
    for key, spec in agents.NODE_REGISTRY.items():
        assert agents.NODE_TO_AGENT[key] == spec.agent


def test_every_agent_owns_at_least_one_node() -> None:
    """The six agents plus supervisor and safety each own a node."""
    owners = set(agents.NODE_TO_AGENT.values())
    assert owners == {
        "supervisor",
        "generation",
        "reflection",
        "ranking",
        "evolution",
        "proximity",
        "meta_review",
        "safety",
    }


def test_registry_holds_the_real_node_callables() -> None:
    """NODE_REGISTRY and TASK_NODES reference the actual node callables."""
    assert agents.NODE_REGISTRY["supervisor"].node is supervisor_node
    assert agents.NODE_REGISTRY["generate"].node is generate_node
    assert agents.NODE_REGISTRY["review"].node is review_node
    assert task_runtime.TASK_NODES["generate"] is generate_node


def test_agent_modules_reexport_the_real_node_callables() -> None:
    """Each agent module re-exports the actual node callable, not a copy."""
    assert agents.supervisor.supervisor_node is supervisor_node
    assert agents.generation.generate_node is generate_node
    assert agents.reflection.review_node is review_node
