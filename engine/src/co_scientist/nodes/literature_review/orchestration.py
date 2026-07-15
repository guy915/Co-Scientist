"""Back-compat shim: literature-review orchestration moved to agents.

Re-exports preserve the ``co_scientist.nodes.literature_review.orchestration``
import path (the reflection agent's deep verification reuses
``_phase2_collect_papers``). New code should import from
``co_scientist.agents.generation.literature_review``.
"""

from co_scientist.agents.generation.literature_review.orchestration import (
    _phase2_collect_papers,
)

__all__ = ["_phase2_collect_papers"]
