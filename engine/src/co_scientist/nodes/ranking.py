"""Back-compat shim: the ranking node moved to ``co_scientist.agents``.

Re-exports preserve the ``co_scientist.nodes.ranking`` import path used by the
workflow graph and the durable task runtime. New code should import from
``co_scientist.agents.ranking``.
"""

from co_scientist.agents.ranking.ranking import ranking_node

__all__ = ["ranking_node"]
