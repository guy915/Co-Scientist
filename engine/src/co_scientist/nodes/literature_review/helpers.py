"""Back-compat shim: literature-review helpers moved to ``co_scientist.agents``.

Re-exports preserve the ``co_scientist.nodes.literature_review.helpers`` import
path (the reflection agent's deep verification reuses
``build_articles_from_metadata``). New code should import from
``co_scientist.agents.generation.literature_review``.
"""

from co_scientist.agents.generation.literature_review.helpers import (
    build_articles_from_metadata,
)

__all__ = ["build_articles_from_metadata"]
