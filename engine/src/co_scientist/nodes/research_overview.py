"""Back-compat shim: research-overview node moved to ``co_scientist.agents``.

Re-exports preserve the ``co_scientist.nodes.research_overview`` import path;
new code should import from ``co_scientist.agents.meta_review``.
"""

from co_scientist.agents.meta_review.research_overview import (
    research_overview_node,
)

__all__ = ["research_overview_node"]
