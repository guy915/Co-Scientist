"""Literature review node package.

Splits the multi-phase literature review pipeline across modules by phase:
query generation, paper collection, PDF/content retrieval, context
enrichment, per-paper analysis, and cross-paper synthesis. The public entry
point is ``literature_review_node``.
"""

from co_scientist.agents.generation.literature_review.node import (
    literature_review_node,
)

__all__ = ["literature_review_node"]
