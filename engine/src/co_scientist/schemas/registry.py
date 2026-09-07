"""Prompt-name lookup for LLM response schemas.

Maps prompt template names to the JSON-schema constants defined in the
sibling stage modules. Called from prompts.load_prompt_with_schema to
pair a markdown prompt template with its response schema.
"""

from typing import Any

from co_scientist.schemas.code_evolution import (
    CODE_EVOLUTION_SCHEMA,
)
from co_scientist.schemas.generation import (
    ASSUMPTION_SUB_SCHEMA,
    ASSUMPTION_TREE_SCHEMA,
    GENERATION_DRAFT_SCHEMA,
    GENERATION_SCHEMA,
    HYPOTHESIS_NOVELTY_ANALYSIS_SCHEMA,
    HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA,
)
from co_scientist.schemas.knowledge_base import KNOWLEDGE_BASE_SCHEMA
from co_scientist.schemas.literature import (
    LITERATURE_PAPER_ANALYSIS_SCHEMA,
    LITERATURE_RELEVANCE_BATCH_SCHEMA,
)
from co_scientist.schemas.planning import (
    META_REVIEW_SCHEMA,
    SUPERVISOR_SCHEMA,
)
from co_scientist.schemas.ranking import (
    PROXIMITY_SCHEMA,
    RANKING_SCHEMA,
)
from co_scientist.schemas.research import (
    RESEARCH_COMPRESS_SCHEMA,
    RESEARCH_EXTRACT_SCHEMA,
    RESEARCH_QUERY_SCHEMA,
    RESEARCH_QUESTIONS_SCHEMA,
    RESEARCH_STANCES_SCHEMA,
)
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
    RESEARCH_OVERVIEW_REVIEW_SCHEMA,
    RESEARCH_OVERVIEW_SCHEMA,
)

# Keys are the prompt template's filename stem (matching prompts/*.md,
# without the extension), not the schema's own "name" field. Templates
# with no entry here (e.g. the three query-generation variants, which are
# conversational/plain-text) legitimately have no entry so
# get_schema_for_prompt returns None and load_prompt_with_schema in
# prompts.py yields a schema-less call.
_PROMPT_SCHEMA_MAP: dict[str, dict[str, Any]] = {
    "code_evolution": CODE_EVOLUTION_SCHEMA,
    "research_stances": RESEARCH_STANCES_SCHEMA,
    "research_questions": RESEARCH_QUESTIONS_SCHEMA,
    "research_query": RESEARCH_QUERY_SCHEMA,
    "research_extract": RESEARCH_EXTRACT_SCHEMA,
    "research_compress": RESEARCH_COMPRESS_SCHEMA,
    "generation_draft_with_tools": GENERATION_DRAFT_SCHEMA,
    "generation_assumptions": GENERATION_SCHEMA,
    "generation_assumption_tree": ASSUMPTION_TREE_SCHEMA,
    "generation_assumption_sub": ASSUMPTION_SUB_SCHEMA,
    "generation_debate_and_literature": GENERATION_SCHEMA,
    "generation_after_debate": GENERATION_SCHEMA,
    "review": REVIEW_SCHEMA,
    "review_batch": REVIEW_BATCH_SCHEMA,
    "full_review": FULL_REVIEW_SCHEMA,
    "simulation_review": SIMULATION_REVIEW_SCHEMA,
    "evolution": EVOLUTION_SCHEMA,
    # The two evolution operators that render a published prompt of their
    # own (A.6 feasibility improvement, A.7 out-of-the-box thinking)
    # return the same refined-hypothesis object as evolution.md.
    "evolution_feasibility": EVOLUTION_SCHEMA,
    "evolution_out_of_box": EVOLUTION_SCHEMA,
    "meta_review": META_REVIEW_SCHEMA,
    # The two published ranking prompts (A.4 single-shot, A.5 simulated
    # debate) answer against one judgment schema.
    "ranking_pairwise": RANKING_SCHEMA,
    "ranking_debate": RANKING_SCHEMA,
    "proximity": PROXIMITY_SCHEMA,
    "reflection_observations": REFLECTION_SCHEMA,
    "deep_verification": DEEP_VERIFICATION_SCHEMA,
    "research_overview": RESEARCH_OVERVIEW_SCHEMA,
    # F8: the deep knowledge-base pass is a second call over the same
    # evidence corpus, with its own budget (KNOWLEDGE_BASE_MAX_TOKENS).
    "research_overview_knowledge_base": KNOWLEDGE_BASE_SCHEMA,
    "research_overview_review": RESEARCH_OVERVIEW_REVIEW_SCHEMA,
    # The reviser regenerates the whole overview, so it shares the
    # synthesis schema rather than defining a second copy of the shape.
    "research_overview_revise": RESEARCH_OVERVIEW_SCHEMA,
    "supervisor": SUPERVISOR_SCHEMA,
    "literature_review_paper_analysis": LITERATURE_PAPER_ANALYSIS_SCHEMA,
    "literature_review_relevance_batch": LITERATURE_RELEVANCE_BATCH_SCHEMA,
    "hypothesis_novelty_analysis": HYPOTHESIS_NOVELTY_ANALYSIS_SCHEMA,
    "hypothesis_validation_synthesis": HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA,
    "hypothesis_validation_synthesis_with_tools": (
        HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA
    ),
}


def get_schema_for_prompt(prompt_name: str) -> dict[str, Any] | None:
    """Get the JSON schema for a given prompt name.

    Args:
        prompt_name: Name of the prompt (e.g., "generation", "review")

    Returns:
        JSON schema dict or None if no schema is defined for this prompt
    """
    return _PROMPT_SCHEMA_MAP.get(prompt_name)
