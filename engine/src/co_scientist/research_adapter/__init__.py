"""Deep research, wired to this engine.

``co_scientist.research`` is a standalone capability: it sequences a
budgeted, breadth-decaying literature search and imports nothing from
the rest of this repository. It states what it needs as two protocols --
a way to search and a way to call a model -- and this package is the
implementation of those protocols for *this* engine.

That split is the point. The loop can be handed to any agent, or lifted
into another codebase, without carrying the MCP client, the prompt
library or the tier vocabulary with it; and this package can be replaced
wholesale to run the same loop against a different provider.

Three pieces, one per thing the loop cannot know for itself:

* :class:`McpRetrieval` -- search and full text over the run's MCP tools.
* :class:`LlmResearchModel` -- the five judgements, over ``call_llm_json``.
* :func:`budget_for_tier` -- how much research a run tier is buying.

:class:`ResearchRetrieval` wraps the MCP port as the single port the loop
expects.
"""

from co_scientist.research_adapter.budget import (
    budget_for_tier,
    tier_researches,
)
from co_scientist.research_adapter.model import LlmResearchModel
from co_scientist.research_adapter.retrieval import (
    McpRetrieval,
    ResearchRetrieval,
)

__all__ = [
    "LlmResearchModel",
    "McpRetrieval",
    "ResearchRetrieval",
    "budget_for_tier",
    "tier_researches",
]
