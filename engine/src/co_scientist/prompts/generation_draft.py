"""Prompt builder for the Phase 1 draft-with-tools generation flow."""

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


def _build_draft_prompt_variables(
    research_goal: str,
    hypotheses_count: int,
    supervisor_guidance: dict[str, Any] | None,
    articles: list[Any] | None,
    articles_with_reasoning: str | None,
    preferences: str | None,
    attributes: list[str] | None,
    user_hypotheses: list[str] | None,
    instructions: str | None,
    reference_list: str,
    max_iterations: int,
    tool_instructions: str,
) -> dict[str, Any]:
    """Build the template variables for the Phase 1 draft-with-tools prompt."""
    return {
        "goal": research_goal,
        "hypotheses_count": hypotheses_count,
        "preferences": format_preferences(preferences),
        "attributes": format_attributes(attributes),
        "user_hypotheses": format_user_hypotheses(user_hypotheses),
        "supervisor_guidance": format_supervisor_guidance_for_generation(
            supervisor_guidance
        ),
        "articles_with_reasoning": articles_with_reasoning
        or "no literature review summary available - examine papers"
        " below directly.",
        "articles_metadata": format_articles_metadata(articles or []),
        "citation_reference_section": _build_citation_reference_section(
            reference_list or ""
        ),
        "max_iterations": max_iterations,
        "instructions": instructions
        or "Focus on creative ideation - draft diverse hypotheses"
        " based on literature gaps.",
        "tool_instructions": tool_instructions,
    }


# Renders prompts/generation_draft_with_tools.md for the Phase 1 draft
# agent in nodes/generation/literature_tools/draft.py (schema:
# GENERATION_DRAFT_SCHEMA via the prompt-name lookup).
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
    """Get prompt for Phase 1: drafting hypotheses with tools.

    Uses generation_draft_with_tools.md template.
    Focuses on reading papers and identifying gaps.
    Includes lit review summary as context (not instructions).

    Args:
        research_goal: The research goal
        hypotheses_count: Number of hypotheses to draft
        supervisor_guidance: Optional guidance from supervisor
        articles: List of Article objects from literature review
        articles_with_reasoning: Literature review synthesis
        preferences: Criteria for strong hypotheses
        attributes: Key attributes to prioritize
        user_hypotheses: User-provided starting hypotheses
        instructions: Custom instructions
        max_iterations: Max tool iterations for the agent
        tool_registry: Optional ToolRegistry for dynamic tool instructions
        reference_list: Optional citation reference list of `[C*]` keys
        meta_review: Optional cross-iteration meta-review feedback
        run_setup_guidance: Optional durable run setup guidance text
        run_focus_guidance: Optional durable run focus guidance text
    """
    tool_instructions = _resolve_draft_tool_instructions(tool_registry)

    variables = _build_draft_prompt_variables(
        research_goal=research_goal,
        hypotheses_count=hypotheses_count,
        supervisor_guidance=supervisor_guidance,
        articles=articles,
        articles_with_reasoning=articles_with_reasoning,
        preferences=preferences,
        attributes=attributes,
        user_hypotheses=user_hypotheses,
        instructions=instructions,
        reference_list=reference_list,
        max_iterations=max_iterations,
        tool_instructions=tool_instructions,
    )

    return _build_prompt(
        "generation_draft_with_tools",
        variables,
        meta_review_context=_format_meta_review_context(meta_review),
        run_guidance=_format_run_guidance(
            run_setup_guidance, run_focus_guidance
        ),
        tool_registry=tool_registry,
    )
