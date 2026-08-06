"""Public API for LLM response schemas.

These schemas are used with response_format of type json_schema to
constrain LLM outputs to specific formats. The schema constants are
defined in stage-grouped submodules (generation, review, ranking,
planning, synthesis, literature) and are all re-exported here, together
with get_schema_for_prompt from the registry module, so callers can
keep importing everything from co_scientist.schemas. Most schemas share
a name with a markdown prompt template in prompts/ and are wired to it
through get_schema_for_prompt in registry.py (called from
prompts.load_prompt_with_schema); a few (literature query generation,
paper analysis, novelty analysis) are instead imported directly by the
node modules that call the LLM, bypassing the name-based lookup.
"""

from co_scientist.schemas.generation import (
    ASSUMPTION_SUB_SCHEMA,
    ASSUMPTION_TREE_SCHEMA,
    GENERATION_DRAFT_SCHEMA,
    GENERATION_SCHEMA,
    HYPOTHESIS_NOVELTY_ANALYSIS_SCHEMA,
    HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA,
)
from co_scientist.schemas.literature import (
    LITERATURE_PAPER_ANALYSIS_SCHEMA,
    LITERATURE_QUERY_SCHEMA,
)
from co_scientist.schemas.planning import (
    META_REVIEW_SCHEMA,
    SUPERVISOR_SCHEMA,
)
from co_scientist.schemas.ranking import (
    PROXIMITY_SCHEMA,
    RANKING_SCHEMA,
)
from co_scientist.schemas.registry import get_schema_for_prompt
from co_scientist.schemas.review import (
    DEEP_VERIFICATION_SCHEMA,
    FULL_REVIEW_SCHEMA,
    REFLECTION_SCHEMA,
    REVIEW_BATCH_SCHEMA,
    REVIEW_SCHEMA,
    SIMULATION_REVIEW_SCHEMA,
)
from co_scientist.schemas.synthesis import (
    EVOLUTION_SCHEMA,
    RESEARCH_OVERVIEW_SCHEMA,
)

__all__ = [
    "ASSUMPTION_SUB_SCHEMA",
    "ASSUMPTION_TREE_SCHEMA",
    "DEEP_VERIFICATION_SCHEMA",
    "EVOLUTION_SCHEMA",
    "FULL_REVIEW_SCHEMA",
    "GENERATION_DRAFT_SCHEMA",
    "GENERATION_SCHEMA",
    "HYPOTHESIS_NOVELTY_ANALYSIS_SCHEMA",
    "HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA",
    "LITERATURE_PAPER_ANALYSIS_SCHEMA",
    "LITERATURE_QUERY_SCHEMA",
    "META_REVIEW_SCHEMA",
    "PROXIMITY_SCHEMA",
    "RANKING_SCHEMA",
    "REFLECTION_SCHEMA",
    "RESEARCH_OVERVIEW_SCHEMA",
    "REVIEW_BATCH_SCHEMA",
    "REVIEW_SCHEMA",
    "SIMULATION_REVIEW_SCHEMA",
    "SUPERVISOR_SCHEMA",
    "get_schema_for_prompt",
]
