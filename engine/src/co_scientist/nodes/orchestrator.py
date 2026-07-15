"""Back-compat shim: the orchestrator node moved to ``co_scientist.agents``.

Re-exports preserve the ``co_scientist.nodes.orchestrator`` import path used by
the workflow graph and the durable task runtime. New code should import from
``co_scientist.agents.supervisor``.
"""

from co_scientist.agents.supervisor.orchestrator import orchestrator_node

__all__ = ["orchestrator_node"]
