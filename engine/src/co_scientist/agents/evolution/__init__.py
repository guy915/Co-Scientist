"""Evolution agent.

Google role: improves top hypotheses -- sharpening, simplifying, and
recombining them into stronger successors that re-enter the tournament.

Implemented by the durable graph node ``evolve`` (whose key string is
preserved), with its context, prompt, and operator helpers. See
``co_scientist.agents`` for the six-agent model.
"""

from co_scientist.agents.evolution.evolve import (
    evolve_node,
    evolve_single_hypothesis_from_outcome,
)
from co_scientist.agents.evolution.operations import (
    EvolutionContext,
    build_evolution_context,
    prepare_outcome_refinement_context,
)

__all__ = [
    "EvolutionContext",
    "build_evolution_context",
    "evolve_node",
    "evolve_single_hypothesis_from_outcome",
    "prepare_outcome_refinement_context",
]
