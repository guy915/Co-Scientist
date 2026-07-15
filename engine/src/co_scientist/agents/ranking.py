"""Ranking agent.

Google role: runs an Elo tournament of pairwise scientific debates to order
hypotheses by merit, concentrating compute on the strongest contenders.

Implemented by the durable graph node ``ranking`` (which owns the tournament,
matchmaking, and Elo update). See ``co_scientist.agents`` for the agent model.
"""

from co_scientist.nodes.ranking import ranking_node

__all__ = ["ranking_node"]
