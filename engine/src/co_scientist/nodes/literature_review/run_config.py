"""Back-compat shim: literature-review run config moved to agents.

Re-exports preserve the ``co_scientist.nodes.literature_review.run_config``
import path (the reflection agent's deep verification reuses
``_get_search_config``). New code should import from
``co_scientist.agents.generation.literature_review``.
"""

from co_scientist.agents.generation.literature_review.run_config import (
    _get_search_config,
)

__all__ = ["_get_search_config"]
