"""Back-compat shim: the proximity node moved to ``co_scientist.agents``.

Re-exports preserve the ``co_scientist.nodes.proximity`` import path used by
the workflow graph, the durable task runtime, and the app viewer. New code and
monkeypatch seams should target ``co_scientist.agents.proximity`` directly.
"""

from co_scientist.agents.proximity.proximity import proximity_node

__all__ = ["proximity_node"]
