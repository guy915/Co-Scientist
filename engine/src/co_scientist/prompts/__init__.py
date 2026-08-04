"""Prompt loading and template substitution utilities.

All prompt templates are stored as markdown files in the templates/
subdirectory. The sibling modules group the prompt builders by the node
that consumes them (loading, review, ranking, planning, literature,
generation), and this package re-exports the public API so callers keep
importing from ``co_scientist.prompts``.
"""

# Convenience functions for common prompts
# One getter per prompt template; each names the template file stem it
# renders (templates/<name>.md) and is called by exactly one node module.
# Private helpers re-exported (the ``as`` alias marks an explicit re-export
# for mypy) for co_scientist.agents.evolution.evolve_prompt, which assembles
# its evolution prompt without a dedicated getter here and imports these from
# the package.
# Not part of the public API.
from co_scientist.prompts._common import (
    PromptRunContext,
)
from co_scientist.prompts._common import (
    _format_bullet_list as _format_bullet_list,
)
from co_scientist.prompts._common import (
    _format_run_guidance as _format_run_guidance,
)
from co_scientist.prompts.generation import (
    DebatePromptRequest,
    DraftPromptRequest,
    ValidationSynthesisRequest,
    build_tool_instructions,
    format_articles_metadata,
    format_attributes,
    format_preferences,
    format_supervisor_guidance_for_generation,
    format_user_hypotheses,
    get_debate_generation_prompt,
    get_draft_prompt_with_tools,
    get_hypothesis_novelty_analysis_prompt,
    get_hypothesis_validation_synthesis_prompt,
    get_validation_synthesis_prompt_with_tools,
)
from co_scientist.prompts.literature import (
    LiteratureQueryInputs,
    get_hypothesis_query_generation_prompt,
    get_literature_review_paper_analysis_prompt,
    get_literature_review_query_generation_prompt,
    get_literature_review_query_generation_pubmed_prompt,
    get_literature_review_synthesis_prompt,
)
from co_scientist.prompts.loading import (
    _get_domain_variables as _get_domain_variables,
)
from co_scientist.prompts.loading import (
    get_prompt_save_path,
    load_prompt,
    load_prompt_with_schema,
    save_prompt_to_disk,
    substitute_variables,
)
from co_scientist.prompts.planning import (
    SupervisorPromptInputs,
    get_meta_review_prompt,
    get_research_overview_prompt,
    get_supervisor_prompt,
)
from co_scientist.prompts.ranking import (
    RankingSide,
    get_proximity_prompt,
    get_ranking_prompt,
)
from co_scientist.prompts.review import (
    get_deep_verification_prompt,
    get_reflection_prompt,
    get_review_batch_prompt,
    get_review_prompt,
)

__all__ = [
    "DebatePromptRequest",
    "DraftPromptRequest",
    "LiteratureQueryInputs",
    "PromptRunContext",
    "RankingSide",
    "SupervisorPromptInputs",
    "ValidationSynthesisRequest",
    "build_tool_instructions",
    "format_articles_metadata",
    "format_attributes",
    "format_preferences",
    "format_supervisor_guidance_for_generation",
    "format_user_hypotheses",
    "get_debate_generation_prompt",
    "get_deep_verification_prompt",
    "get_draft_prompt_with_tools",
    "get_hypothesis_novelty_analysis_prompt",
    "get_hypothesis_query_generation_prompt",
    "get_hypothesis_validation_synthesis_prompt",
    "get_literature_review_paper_analysis_prompt",
    "get_literature_review_query_generation_prompt",
    "get_literature_review_query_generation_pubmed_prompt",
    "get_literature_review_synthesis_prompt",
    "get_meta_review_prompt",
    "get_prompt_save_path",
    "get_proximity_prompt",
    "get_ranking_prompt",
    "get_reflection_prompt",
    "get_research_overview_prompt",
    "get_review_batch_prompt",
    "get_review_prompt",
    "get_supervisor_prompt",
    "get_validation_synthesis_prompt_with_tools",
    "load_prompt",
    "load_prompt_with_schema",
    "save_prompt_to_disk",
    "substitute_variables",
]
