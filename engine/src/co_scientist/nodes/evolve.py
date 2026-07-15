"""Back-compat shim: the evolve node moved to ``co_scientist.agents``.

Re-exports preserve the ``co_scientist.nodes.evolve`` import path used by the
workflow graph, the durable task runtime, and the prompt registry. New code
should import from ``co_scientist.agents.evolution``.
"""

from co_scientist.agents.evolution.evolve import evolve_node

__all__ = ["evolve_node"]
