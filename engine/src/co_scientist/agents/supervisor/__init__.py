"""Supervisor agent.

Google role: the Supervisor plans the research approach from the goal and, each
cycle, decides which agent runs next until the run terminates.

Implemented by the durable graph nodes ``supervisor`` (initial planning) and
``orchestrator`` (per-cycle next-task decision), with the decision helper;
their key strings are preserved. See ``co_scientist.agents`` for the model.
"""

from co_scientist.agents.supervisor.orchestrator import orchestrator_node
from co_scientist.agents.supervisor.supervisor import supervisor_node

__all__ = ["orchestrator_node", "supervisor_node"]
