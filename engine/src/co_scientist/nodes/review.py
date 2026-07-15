"""Back-compat shim: the review node moved to ``co_scientist.agents``.

Re-exports preserve the ``co_scientist.nodes.review`` import path used by the
workflow graph and the durable task runtime. New code should import from
``co_scientist.agents.reflection``.
"""

from co_scientist.agents.reflection.review import review_node

__all__ = ["review_node"]
