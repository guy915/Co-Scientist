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

Four pieces, one per thing the loop cannot know for itself:

* :class:`McpRetrieval` -- search and full text over the run's MCP tools.
* :class:`LocalCorpusRetrieval` -- the group's own papers, off local disk.
  The one source that is not a network call, so a run keeps somewhere to
  look when the search server is gone.
* :class:`LlmResearchModel` -- the five judgements, over ``call_llm_json``.
* :func:`budget_for_tier` -- how much research a run tier is buying.

:class:`ResearchRetrieval` joins the two retrieval halves into the single
port the loop expects; either half may be missing, and they go missing
for different reasons.
"""

from co_scientist.research_adapter.budget import (
    budget_for_tier,
    tier_researches,
)
from co_scientist.research_adapter.composite import ResearchRetrieval
from co_scientist.research_adapter.local_corpus import (
    GROUP_CORPUS_SOURCE,
    LocalCorpusRetrieval,
    local_corpus_for,
)
from co_scientist.research_adapter.model import LlmResearchModel
from co_scientist.research_adapter.retrieval import McpRetrieval

__all__ = [
    "GROUP_CORPUS_SOURCE",
    "LlmResearchModel",
    "LocalCorpusRetrieval",
    "McpRetrieval",
    "ResearchRetrieval",
    "budget_for_tier",
    "local_corpus_for",
    "tier_researches",
]
