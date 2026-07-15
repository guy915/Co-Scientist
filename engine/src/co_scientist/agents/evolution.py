"""Evolution agent.

Google role: improves top hypotheses -- sharpening, simplifying, and
recombining them into stronger successors that re-enter the tournament.

Implemented by the durable graph node ``evolve``. See ``co_scientist.agents``
for the agent model.
"""

from co_scientist.nodes.evolve import evolve_node

__all__ = ["evolve_node"]
