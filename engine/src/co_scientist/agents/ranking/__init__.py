"""Ranking agent.

Google role: runs an Elo tournament of pairwise scientific debates to order
hypotheses by merit, concentrating compute on the strongest contenders.

Implemented by the durable graph node ``ranking`` (whose key string is
preserved), with its tournament, matchmaking, and Elo helpers. See
``co_scientist.agents`` for the six-agent model.
"""

from co_scientist.agents.ranking.ranking import ranking_node

__all__ = ["ranking_node"]
