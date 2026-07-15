"""Reflection agent.

Google role: reviews hypotheses for correctness, novelty, and quality, and
verifies their reasoning -- the system's scientific critic.

Implemented by the durable graph nodes ``review`` (initial review),
``reflection`` (literature-grounded reflection), ``comprehensive_reflection``
(observation/simulation/recurrent deep review), and ``deep_verification``
(probing-question decomposition); their key strings are preserved. See
``co_scientist.agents`` for the six-agent model.
"""

from co_scientist.agents.reflection.comprehensive_reflection import (
    comprehensive_reflection_node,
)
from co_scientist.agents.reflection.deep_verification import (
    deep_verification_node,
)
from co_scientist.agents.reflection.reflection import reflection_node
from co_scientist.agents.reflection.review import review_node

__all__ = [
    "comprehensive_reflection_node",
    "deep_verification_node",
    "reflection_node",
    "review_node",
]
