"""Generation agent.

Google role: generates novel, diverse, and testable hypotheses for the research
goal, grounding them in the literature.

Implemented by the durable graph nodes ``generate`` (hypothesis generation with
its debate/assumption/technique strategies) and ``literature_review`` (MCP-gated
retrieval that grounds generation); their key strings are preserved. See
``co_scientist.agents`` for the six-agent model.
"""

from co_scientist.agents.generation.generate import generate_node
from co_scientist.agents.generation.literature_review import (
    literature_review_node,
)

__all__ = ["generate_node", "literature_review_node"]
