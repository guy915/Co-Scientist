"""The six specialized agents of the Co-Scientist system.

Google's AI Co-Scientist is organized as a coalition of six specialized agents
orchestrated by a Supervisor. This package makes that structure explicit: each
module below is one agent and re-exports the node callables that implement it.

    Supervisor   -- plans the run and schedules the next task each cycle.
    Generation   -- proposes novel, literature-grounded hypotheses.
    Reflection   -- reviews, critiques, and verifies hypotheses.
    Ranking      -- runs the Elo tournament to order hypotheses by merit.
    Evolution    -- improves and recombines promising hypotheses.
    Proximity    -- clusters near-duplicate hypotheses.
    Meta-review  -- synthesizes findings into the research overview/roadmap.

A seventh concern, Safety, is cross-cutting rather than one of the six agents
(it screens at intake, per hypothesis, and at final output); ``agents.safety``
exposes the per-hypothesis screen node for completeness.

Why the agents map to more than six graph nodes
------------------------------------------------
Each agent's work is decomposed into one or more durable LangGraph nodes so the
engine can checkpoint and resume at fine granularity (e.g. the Reflection agent
runs as the ``review`` -> ``comprehensive_reflection`` -> ``deep_verification``
sequence, each independently resumable). The node implementations live in these
agent packages; the **key strings** each node registers under are persisted in
the durable task queue and checkpoints, so they are deliberately preserved (this
was a file move, not a key rename). ``NODE_REGISTRY`` below is the single
source of truth for those key strings: the workflow graph registers its nodes
from it, ``task_runtime.TASK_NODES`` derives from it, and ``NODE_TO_AGENT``
projects it down to the node->agent grouping. The rationale lives in
``engine/docs/ARCHITECTURE.md``.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from co_scientist.agents import (
    evolution,
    generation,
    meta_review,
    proximity,
    ranking,
    reflection,
    safety,
    supervisor,
)
from co_scientist.state import WorkflowState

# A durable graph node's implementation: one async state-transform callable.
NodeCallable = Callable[[WorkflowState], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class NodeSpec:
    """One durable graph node: its owning agent and its callable.

    Attributes:
        agent: The agent (package under ``co_scientist.agents``) that owns
            the node.
        node: The async node callable registered under the node's key.
    """

    agent: str
    node: NodeCallable


# The single source of truth for the durable graph-node keys. Each key is the
# exact string registered on the LangGraph workflow and persisted as an
# ``engine.node.<key>`` durable task, so the keys must never change value.
NODE_REGISTRY: dict[str, NodeSpec] = {
    "supervisor": NodeSpec("supervisor", supervisor.supervisor_node),
    "orchestrator": NodeSpec("supervisor", supervisor.orchestrator_node),
    "generate": NodeSpec("generation", generation.generate_node),
    "literature_review": NodeSpec(
        "generation", generation.literature_review_node
    ),
    "review": NodeSpec("reflection", reflection.review_node),
    "reflection": NodeSpec("reflection", reflection.reflection_node),
    "comprehensive_reflection": NodeSpec(
        "reflection", reflection.comprehensive_reflection_node
    ),
    "deep_verification": NodeSpec(
        "reflection", reflection.deep_verification_node
    ),
    "ranking": NodeSpec("ranking", ranking.ranking_node),
    "evolve": NodeSpec("evolution", evolution.evolve_node),
    "proximity": NodeSpec("proximity", proximity.proximity_node),
    "meta_review": NodeSpec("meta_review", meta_review.meta_review_node),
    "research_overview": NodeSpec(
        "meta_review", meta_review.research_overview_node
    ),
    "safety_screen": NodeSpec("safety", safety.safety_screen_node),
}

# The durable graph-node key -> owning agent, projected from NODE_REGISTRY.
NODE_TO_AGENT: dict[str, str] = {
    key: spec.agent for key, spec in NODE_REGISTRY.items()
}

__all__ = [
    "NODE_REGISTRY",
    "NODE_TO_AGENT",
    "NodeCallable",
    "NodeSpec",
    "evolution",
    "generation",
    "meta_review",
    "proximity",
    "ranking",
    "reflection",
    "safety",
    "supervisor",
]
