"""Reflection agent.

Google role: reviews hypotheses for correctness, novelty, and quality, and
verifies their reasoning -- the system's scientific critic.

Implemented by the durable graph nodes ``review`` (initial multi-axis review),
``reflection`` (MCP-gated literature-grounded reflection), ``comprehensive_
reflection`` (observation/simulation/recurrent deep review), and ``deep_
verification`` (probing-question decomposition). See ``co_scientist.agents`` for
why an agent spans more than one node.
"""

from co_scientist.nodes.comprehensive_reflection import (
    comprehensive_reflection_node,
)
from co_scientist.nodes.deep_verification import deep_verification_node
from co_scientist.nodes.reflection import reflection_node
from co_scientist.nodes.review import review_node

__all__ = [
    "comprehensive_reflection_node",
    "deep_verification_node",
    "reflection_node",
    "review_node",
]
