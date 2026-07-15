"""Back-compat shim: the generate node moved to ``co_scientist.agents``.

Re-exports preserve the ``co_scientist.nodes.generate`` import path used by the
workflow graph and the durable task runtime. New code should import from
``co_scientist.agents.generation``.
"""

from co_scientist.agents.generation.generate import generate_node

__all__ = ["generate_node"]
