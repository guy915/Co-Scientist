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
was a file move, not a key rename). ``co_scientist.nodes`` keeps thin re-export
shims at the old import paths. The full node->agent mapping is ``NODE_TO_AGENT``
below, and the rationale lives in ``engine/docs/ARCHITECTURE.md``.
"""

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

# The durable graph-node key -> owning agent. The keys are the exact strings
# registered in generator.graph and persisted as ``engine.node.<key>`` durable
# tasks; this dict is the single source of truth for the node->agent grouping.
NODE_TO_AGENT: dict[str, str] = {
    "supervisor": "supervisor",
    "orchestrator": "supervisor",
    "generate": "generation",
    "literature_review": "generation",
    "review": "reflection",
    "reflection": "reflection",
    "comprehensive_reflection": "reflection",
    "deep_verification": "reflection",
    "ranking": "ranking",
    "evolve": "evolution",
    "proximity": "proximity",
    "meta_review": "meta_review",
    "research_overview": "meta_review",
    "safety_screen": "safety",
}

__all__ = [
    "NODE_TO_AGENT",
    "evolution",
    "generation",
    "meta_review",
    "proximity",
    "ranking",
    "reflection",
    "safety",
    "supervisor",
]
