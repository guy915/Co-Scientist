"""Back-compat shim: the meta-review node moved to ``co_scientist.agents``.

Re-exports preserve the ``co_scientist.nodes.meta_review`` import path. New code
should import from ``co_scientist.agents.meta_review``.
"""

from co_scientist.agents.meta_review.meta_review import meta_review_node

__all__ = ["meta_review_node"]
