"""Back-compat shim: comprehensive reflection moved to ``co_scientist.agents``.

Re-exports preserve the ``co_scientist.nodes.comprehensive_reflection`` import
path used by the workflow graph and the durable task runtime. New code should
import from ``co_scientist.agents.reflection``.
"""

from co_scientist.agents.reflection.comprehensive_reflection import (
    comprehensive_reflection_node,
)

__all__ = ["comprehensive_reflection_node"]
