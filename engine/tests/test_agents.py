"""The agents package is the six-agent view over the durable graph nodes."""

from co_scientist import agents
from co_scientist.nodes.generate import generate_node
from co_scientist.nodes.review import review_node
from co_scientist.nodes.supervisor import supervisor_node


def test_node_to_agent_covers_every_registered_graph_node() -> None:
    """Every graph node key maps to exactly one agent, and no phantom keys.

    Mirrors ``generator.graph._add_workflow_nodes`` (all 14 registered node
    keys, including the two MCP-gated ones). Guards against adding a node
    without assigning it to an agent -- the durable node keys are the strings
    persisted in the task queue, so each must have an owning agent.
    """
    registered_node_keys = {
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
    assert set(agents.NODE_TO_AGENT) == registered_node_keys


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


def test_agent_modules_reexport_the_real_node_callables() -> None:
    """Each agent module re-exports the actual node callable, not a copy."""
    assert agents.supervisor.supervisor_node is supervisor_node
    assert agents.generation.generate_node is generate_node
    assert agents.reflection.review_node is review_node
