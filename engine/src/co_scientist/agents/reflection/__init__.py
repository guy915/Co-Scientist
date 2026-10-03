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
    ReviewRun,
    comprehensive_reflection_node,
    review_hypothesis,
)
from co_scientist.agents.reflection.deep_verification import (
    deep_verification_node,
)
from co_scientist.agents.reflection.reflection import (
    observe_hypothesis,
    reflection_node,
)
from co_scientist.agents.reflection.review import review_node
from co_scientist.agents.reflection.review_gate import apply_initial_review_gate
from co_scientist.agents.reflection.review_types import ReviewType
from co_scientist.agents.reflection.verification import (
    has_valid_verification,
    select_hypotheses_to_verify,
    verify_hypothesis,
)

__all__ = [
    "ReviewRun",
    "ReviewType",
    "apply_initial_review_gate",
    "comprehensive_reflection_node",
    "deep_verification_node",
    "has_valid_verification",
    "observe_hypothesis",
    "reflection_node",
    "review_hypothesis",
    "review_node",
    "select_hypotheses_to_verify",
    "verify_hypothesis",
]
