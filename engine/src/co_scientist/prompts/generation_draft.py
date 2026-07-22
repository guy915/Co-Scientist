"""Prompt builder for the Phase 1 draft-with-tools generation flow."""

from dataclasses import dataclass
from typing import Any

from co_scientist.prompts._common import (
    _format_meta_review_context,
    _format_run_guidance,
)
from co_scientist.prompts.generation_formatting import (
    _build_citation_reference_section,
    format_articles_metadata,
    format_attributes,
    format_preferences,
    format_supervisor_guidance_for_generation,
    format_user_hypotheses,
)
from co_scientist.prompts.generation_tools import build_tool_instructions
from co_scientist.prompts.loading import _build_prompt


def _resolve_draft_tool_instructions(tool_registry: Any | None) -> str:
    """Resolve tool instructions for the draft-generation workflow."""
    tool_ids = []
    if tool_registry:
        tool_ids = tool_registry.get_tools_for_workflow("draft_generation")
    return build_tool_instructions(tool_ids, tool_registry)


@dataclass(frozen=True)
class _DraftPromptRequest:
    """Inputs for the Phase 1 draft-with-tools prompt, one per parameter.

    Mirrors the parameters of get_draft_prompt_with_tools, which forwards
    them here unchanged: the research goal and hypothesis count, the
    supervisor guidance, the literature review outputs (articles, the
    synthesis text, and the ``[C*]`` citation reference list), the user's
    preferences/attributes/starting hypotheses, custom instructions, the
    agent's max tool iterations, the tool registry for dynamic tool
    instructions, cross-iteration meta-review feedback, and the durable
    run setup/focus guidance texts.
    """

    research_goal: str
    hypotheses_count: int
    supervisor_guidance: dict[str, Any] | None
    articles: list[Any] | None
    articles_with_reasoning: str | None
    preferences: str | None
    attributes: list[str] | None
    user_hypotheses: list[str] | None
    instructions: str | None
    max_iterations: int
    tool_registry: Any | None
    reference_list: str
    meta_review: dict[str, Any] | None
    run_setup_guidance: str | None
    run_focus_guidance: str | None


def _build_draft_prompt_variables(req: _DraftPromptRequest) -> dict[str, Any]:
    """Build the template variables for the Phase 1 draft-with-tools prompt."""
    return {
        "goal": req.research_goal,
        "hypotheses_count": req.hypotheses_count,
        "preferences": format_preferences(req.preferences),
        "attributes": format_attributes(req.attributes),
        "user_hypotheses": format_user_hypotheses(req.user_hypotheses),
        "supervisor_guidance": format_supervisor_guidance_for_generation(
            req.supervisor_guidance
        ),
        "articles_with_reasoning": req.articles_with_reasoning
        or "no literature review summary available - examine papers"
        " below directly.",
        "articles_metadata": format_articles_metadata(req.articles or []),
        "citation_reference_section": _build_citation_reference_section(
            req.reference_list or ""
        ),
        "max_iterations": req.max_iterations,
        "instructions": req.instructions
        or "Focus on creative ideation - draft diverse hypotheses"
        " based on literature gaps.",
        "tool_instructions": _resolve_draft_tool_instructions(
            req.tool_registry
        ),
    }


def _load_draft_prompt(
    req: _DraftPromptRequest,
) -> tuple[str, dict[str, Any] | None]:
    """Render the draft prompt and schema for one prompt request."""
    return _build_prompt(
        "generation_draft_with_tools",
        _build_draft_prompt_variables(req),
        meta_review_context=_format_meta_review_context(req.meta_review),
        run_guidance=_format_run_guidance(
            req.run_setup_guidance, req.run_focus_guidance
        ),
        tool_registry=req.tool_registry,
    )


# Renders prompts/generation_draft_with_tools.md for the Phase 1 draft
# agent in nodes/generation/literature_tools/draft.py (schema:
# GENERATION_DRAFT_SCHEMA via the prompt-name lookup). Focuses on reading
# papers and identifying gaps, with the lit review summary included as
# context (not instructions).
def get_draft_prompt_with_tools(
    research_goal: str,
    hypotheses_count: int,
    supervisor_guidance: dict[str, Any] | None = None,
    articles: list[Any] | None = None,
    articles_with_reasoning: str | None = None,
    preferences: str | None = None,
    attributes: list[str] | None = None,
    user_hypotheses: list[str] | None = None,
    instructions: str | None = None,
    max_iterations: int = 8,
    tool_registry: Any | None = None,
    reference_list: str = "",
    meta_review: dict[str, Any] | None = None,
    run_setup_guidance: str | None = None,
    run_focus_guidance: str | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get the Phase 1 draft prompt; params doc'd on _DraftPromptRequest."""
    return _load_draft_prompt(
        _DraftPromptRequest(
            research_goal=research_goal,
            hypotheses_count=hypotheses_count,
            supervisor_guidance=supervisor_guidance,
            articles=articles,
            articles_with_reasoning=articles_with_reasoning,
            preferences=preferences,
            attributes=attributes,
            user_hypotheses=user_hypotheses,
            instructions=instructions,
            max_iterations=max_iterations,
            tool_registry=tool_registry,
            reference_list=reference_list,
            meta_review=meta_review,
            run_setup_guidance=run_setup_guidance,
            run_focus_guidance=run_focus_guidance,
        )
    )
