"""Back-compat shim: deep verification moved to ``co_scientist.agents``.

Re-exports preserve the ``co_scientist.nodes.deep_verification`` import path
used by the workflow graph and the durable task runtime. New code should import
from ``co_scientist.agents.reflection``.
"""

from co_scientist.agents.reflection.deep_verification import (
    deep_verification_node,
)

__all__ = ["deep_verification_node"]
