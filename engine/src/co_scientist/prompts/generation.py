"""Prompt builders and formatting helpers for the generation nodes.

The builders live in focused submodules grouped by responsibility; this
module re-exports them so callers keep importing from
``co_scientist.prompts.generation``.
"""

from typing import Any

from co_scientist.prompts._common import (
    _format_authors,
    _format_meta_review_context,
    _format_run_guidance,
    _format_year,
)
from co_scientist.prompts.generation_debate import (
    _DEBATE_FINAL_TURN_INSTRUCTIONS,
    _build_debate_literature_variables,
    _build_debate_prompt_variables,
    _format_debate_attributes,
    _format_debate_generation_phase_section,
    _format_debate_key_areas_section,
    _format_supervisor_guidance_for_debate,
    _render_debate_prompt,
    get_debate_generation_prompt,
)
from co_scientist.prompts.generation_draft import (
    _build_draft_prompt_variables,
    _resolve_draft_tool_instructions,
    get_draft_prompt_with_tools,
)
from co_scientist.prompts.generation_formatting import (
    _build_citation_reference_section,
    _format_article_authors,
    _format_article_entry,
    _format_pdf_status,
    _used_articles,
    format_articles_metadata,
    format_attributes,
    format_preferences,
    format_supervisor_guidance_for_generation,
    format_user_hypotheses,
)
from co_scientist.prompts.generation_tools import (
    _format_tool_entry,
    _resolve_tool_registry,
    _tool_entry_sections,
    build_tool_instructions,
)
from co_scientist.prompts.generation_validation import (
    _build_already_validated_context,
    _build_validation_synthesis_prompt_variables,
    _format_hypotheses_with_novelty_analyses,
    _format_novelty_hypothesis_section,
    _format_novelty_paper_analysis,
    _resolve_validation_tool_instructions,
    get_hypothesis_novelty_analysis_prompt,
    get_hypothesis_validation_synthesis_prompt,
    get_validation_synthesis_prompt_with_tools,
)
from co_scientist.prompts.loading import (
    _build_prompt,
    _get_domain_variables,
    load_prompt,
    load_prompt_with_schema,
)

__all__ = [
    "_DEBATE_FINAL_TURN_INSTRUCTIONS",
    "Any",
    "_build_already_validated_context",
    "_build_citation_reference_section",
    "_build_debate_literature_variables",
    "_build_debate_prompt_variables",
    "_build_draft_prompt_variables",
    "_build_prompt",
    "_build_validation_synthesis_prompt_variables",
    "_format_article_authors",
    "_format_article_entry",
    "_format_authors",
    "_format_debate_attributes",
    "_format_debate_generation_phase_section",
    "_format_debate_key_areas_section",
    "_format_hypotheses_with_novelty_analyses",
    "_format_meta_review_context",
    "_format_novelty_hypothesis_section",
    "_format_novelty_paper_analysis",
    "_format_pdf_status",
    "_format_run_guidance",
    "_format_supervisor_guidance_for_debate",
    "_format_tool_entry",
    "_format_year",
    "_get_domain_variables",
    "_render_debate_prompt",
    "_resolve_draft_tool_instructions",
    "_resolve_tool_registry",
    "_resolve_validation_tool_instructions",
    "_tool_entry_sections",
    "_used_articles",
    "build_tool_instructions",
    "format_articles_metadata",
    "format_attributes",
    "format_preferences",
    "format_supervisor_guidance_for_generation",
    "format_user_hypotheses",
    "get_debate_generation_prompt",
    "get_draft_prompt_with_tools",
    "get_hypothesis_novelty_analysis_prompt",
    "get_hypothesis_validation_synthesis_prompt",
    "get_validation_synthesis_prompt_with_tools",
    "load_prompt",
    "load_prompt_with_schema",
]
