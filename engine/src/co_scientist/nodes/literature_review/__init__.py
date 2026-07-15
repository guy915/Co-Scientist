"""Back-compat shim: literature-review node moved to ``co_scientist.agents``.

Re-exports preserve the ``co_scientist.nodes.literature_review`` import path
used by the workflow graph and the durable task runtime. New code should import
from ``co_scientist.agents.generation.literature_review``. Individual submodules
still imported through this path (e.g. by the reflection agent's deep
verification) keep their own thin shims alongside this file.
"""

from co_scientist.agents.generation.literature_review import (
    literature_review_node,
)

__all__ = ["literature_review_node"]
