"""Prompt-name lookup for LLM response schemas.

Maps prompt template names to the JSON-schema constants defined in the
sibling stage modules. Called from prompts.load_prompt_with_schema to
pair a markdown prompt template with its response schema.
"""

from typing import Any

from co_scientist.schemas.generation import (
    GENERATION_DRAFT_SCHEMA,
    GENERATION_SCHEMA,
    HYPOTHESIS_NOVELTY_ANALYSIS_SCHEMA,
    HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA,
)
from co_scientist.schemas.literature import LITERATURE_PAPER_ANALYSIS_SCHEMA
from co_scientist.schemas.planning import (
    META_REVIEW_SCHEMA,
    SUPERVISOR_SCHEMA,
)
from co_scientist.schemas.ranking import (
    PROXIMITY_SCHEMA,
    RANKING_SCHEMA,
)
from co_scientist.schemas.review import (
    DEEP_VERIFICATION_SCHEMA,
    REFLECTION_SCHEMA,
    REVIEW_BATCH_SCHEMA,
    REVIEW_SCHEMA,
)
from co_scientist.schemas.synthesis import (
    EVOLUTION_SCHEMA,
    RESEARCH_OVERVIEW_SCHEMA,
)


def get_schema_for_prompt(prompt_name: str) -> dict[str, Any] | None:
    """Get the JSON schema for a given prompt name.

    Args:
        prompt_name: Name of the prompt (e.g., "generation", "review")

    Returns:
        JSON schema dict or None if no schema is defined for this prompt
    """
    # Keys are the prompt template's filename stem (matching prompts/*.md,
    # without the extension), not the schema's own "name" field. Templates
    # with no entry here (e.g. the three query-generation variants, which
    # are conversational/plain-text) legitimately return None so
    # load_prompt_with_schema in prompts.py yields a schema-less call.
    schema_map = {
        "generation_draft_with_tools":
            GENERATION_DRAFT_SCHEMA,
        "generation_debate_and_literature":
            GENERATION_SCHEMA,
        "generation_after_debate":
            GENERATION_SCHEMA,
        "review":
            REVIEW_SCHEMA,
        "review_batch":
            REVIEW_BATCH_SCHEMA,
        "evolution":
            EVOLUTION_SCHEMA,
        "meta_review":
            META_REVIEW_SCHEMA,
        "ranking":
            RANKING_SCHEMA,
        "proximity":
            PROXIMITY_SCHEMA,
        "reflection_observations":
            REFLECTION_SCHEMA,
        "deep_verification":
            DEEP_VERIFICATION_SCHEMA,
        "research_overview":
            RESEARCH_OVERVIEW_SCHEMA,
        "supervisor":
            SUPERVISOR_SCHEMA,
        "literature_review_paper_analysis":
            LITERATURE_PAPER_ANALYSIS_SCHEMA,
        "hypothesis_novelty_analysis":
            HYPOTHESIS_NOVELTY_ANALYSIS_SCHEMA,
        "hypothesis_validation_synthesis":
            HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA,
        "hypothesis_validation_synthesis_with_tools":
            HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA,
    }

    return schema_map.get(prompt_name)
