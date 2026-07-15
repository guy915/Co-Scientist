"""Back-compat shim: the reflection node moved to ``co_scientist.agents``.

Re-exports preserve the ``co_scientist.nodes.reflection`` import path used by
the workflow graph and the durable task runtime. New code should import from
``co_scientist.agents.reflection``.
"""

from co_scientist.agents.reflection.reflection import reflection_node

__all__ = ["reflection_node"]
