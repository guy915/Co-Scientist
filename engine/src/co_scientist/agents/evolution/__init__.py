"""Evolution agent.

Google role: improves top hypotheses -- sharpening, simplifying, and
recombining them into stronger successors that re-enter the tournament.

Implemented by the durable graph node ``evolve`` (whose key string is
preserved), with its context, prompt, and operator helpers. See
``co_scientist.agents`` for the six-agent model.
"""

from co_scientist.agents.evolution.evolve import evolve_node

__all__ = ["evolve_node"]
