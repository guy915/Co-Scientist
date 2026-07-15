"""Back-compat shim: proximity graph helpers moved to ``co_scientist.agents``.

Re-exports preserve the ``co_scientist.nodes.proximity_graph`` import path. New
code should import from ``co_scientist.agents.proximity.proximity_graph``.
"""

from co_scientist.agents.proximity.proximity_graph import (
    build_proximity_graph,
    member_match_key,
)

__all__ = ["build_proximity_graph", "member_match_key"]
