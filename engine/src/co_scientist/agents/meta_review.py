"""Meta-review agent.

Google role: synthesizes recurring patterns across all reviews and debates into
a research overview -- the roadmap, specific aims, and suggested directions.

Implemented by the durable graph nodes ``meta_review`` (cross-hypothesis
synthesis) and ``research_overview`` (terminal roadmap/NIH-aims generation). See
``co_scientist.agents`` for why an agent spans more than one node.
"""

from co_scientist.nodes.meta_review import meta_review_node
from co_scientist.nodes.research_overview import research_overview_node

__all__ = ["meta_review_node", "research_overview_node"]
