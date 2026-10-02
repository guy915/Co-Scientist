"""Generation agent.

Google role: generates novel, diverse, and testable hypotheses for the research
goal, grounding them in the literature.

Implemented by the durable graph nodes ``generate`` (hypothesis generation with
its debate/assumption/technique strategies) and ``literature_review`` (MCP-gated
retrieval that grounds generation); their key strings are preserved. See
``co_scientist.agents`` for the six-agent model.

``prepare_generation`` returns the shared ``GenerationPlan`` allocation and
citation inputs. ``finalize_generation`` consumes ``GenerationResults`` and
returns an append update with lineage and degraded grounding applied. Callers
own strategy execution, failure policy, metrics, and state commits.
"""

from co_scientist.agents.generation.coordinator_strategy import (
    GenerationCounts,
)
from co_scientist.agents.generation.generate import generate_node
from co_scientist.agents.generation.literature_review import (
    literature_review_node,
)
from co_scientist.agents.generation.operations import (
    GenerationPlan,
    GenerationResults,
    finalize_generation,
    prepare_generation,
)

__all__ = [
    "GenerationCounts",
    "GenerationPlan",
    "GenerationResults",
    "finalize_generation",
    "generate_node",
    "literature_review_node",
    "prepare_generation",
]
