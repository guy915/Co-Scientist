"""Back-compat shim: the supervisor node moved to ``co_scientist.agents``.

Re-exports preserve the ``co_scientist.nodes.supervisor`` import path used by
the workflow graph and the durable task runtime. New code should import from
``co_scientist.agents.supervisor``.
"""

from co_scientist.agents.supervisor.supervisor import supervisor_node

__all__ = ["supervisor_node"]
