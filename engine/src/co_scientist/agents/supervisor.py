"""Supervisor agent.

Google role: the Supervisor plans the research approach from the goal and, each
cycle, decides which agent runs next until the run terminates.

Implemented by the durable graph nodes ``supervisor`` (initial planning) and
``orchestrator`` (per-cycle next-task decision). See ``co_scientist.agents`` for
why an agent spans more than one node.
"""

from co_scientist.nodes.orchestrator import orchestrator_node
from co_scientist.nodes.supervisor import supervisor_node

__all__ = ["orchestrator_node", "supervisor_node"]
