"""Proximity agent.

Google role: computes a similarity graph over hypotheses and clusters
near-duplicates so the tournament and report cover distinct ideas.

Implemented by the durable graph node ``proximity`` (whose key string is
preserved). See ``co_scientist.agents`` for the six-agent model.
"""

from co_scientist.agents.proximity.proximity import proximity_node

__all__ = ["proximity_node"]
