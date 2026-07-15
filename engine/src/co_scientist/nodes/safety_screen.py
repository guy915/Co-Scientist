"""Back-compat shim: the safety screen node moved to ``co_scientist.agents``.

Re-exports preserve the ``co_scientist.nodes.safety_screen`` import path used by
the workflow graph and the durable task runtime. New code should import from
``co_scientist.agents.safety``.
"""

from co_scientist.agents.safety.safety_screen import safety_screen_node

__all__ = ["safety_screen_node"]
