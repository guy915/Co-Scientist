"""Prompt builder for the Phase 1 draft-with-tools generation flow."""

from dataclasses import dataclass, field
from typing import Any

from co_scientist.prompts._common import (
    PromptRunContext,
    PromptSections,
    _format_meta_review_context,
    _run_guidance_section,
    format_lab_constraints_section,
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
class DraftPromptRequest:
    """Inputs for the Phase 1 draft-with-tools prompt.

    Attributes:
        research_goal: The run's research goal.
        hypotheses_count: How many draft hypotheses to produce.
        articles: Literature-review articles for citation metadata.
        articles_with_reasoning: The literature-review synthesis text.
        preferences: Free-text user preferences, if any.
        attributes: Desired hypothesis attributes.
        user_hypotheses: Seed hypotheses supplied by the user.
        instructions: Custom drafting instructions.
        max_iterations: The agent's max tool iterations.
        reference_list: The ``[C*]`` citation reference list.
        research_expansion_section: Rendered research-expansion guidance
            for post-iteration generate cycles (E11b); empty on the
            initial cycle, which keeps focused-grounding behavior.
        falsified_assumptions_section: Rendered avoid-or-rework guidance
            for assumptions verification found incorrect (K9); empty
            until deep verification records one.
        lab_constraints: The scientist's lab constraints elicited by
            the goal interview (K5); empty or absent renders no section.
        skills_section: Rendered science-skills instructions, appended
            to the tool instructions. Empty unless the drafting pass was
            actually given them, which depends on the deployment and on
            whether commands can be confined on this host -- so it is
            passed in by the caller that offered them rather than
            derived here from what is installed.
        context: Run-scoped prompt context (supervisor guidance,
            meta-review, tool registry, run setup/focus guidance).
    """

    research_goal: str
    hypotheses_count: int
    articles: list[Any] | None = None
    articles_with_reasoning: str | None = None
    preferences: str | None = None
    attributes: list[str] | None = None
    user_hypotheses: list[str] | None = None
    instructions: str | None = None
    max_iterations: int = 8
    reference_list: str = ""
    research_expansion_section: str = ""
    falsified_assumptions_section: str = ""
    lab_constraints: list[str] | None = None
    skills_section: str = ""
    context: PromptRunContext = field(default_factory=PromptRunContext)


def _build_draft_prompt_variables(req: DraftPromptRequest) -> dict[str, Any]:
    """Build the template variables for the Phase 1 draft-with-tools prompt."""
    return {
        "goal": req.research_goal,
        "hypotheses_count": req.hypotheses_count,
        "preferences": format_preferences(req.preferences),
        "attributes": format_attributes(req.attributes),
        "user_hypotheses": format_user_hypotheses(req.user_hypotheses),
        "supervisor_guidance": format_supervisor_guidance_for_generation(
            req.context.supervisor_guidance
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
            req.context.tool_registry
        )
        + req.skills_section,
        # Empty outside their conditions, so the initial-cycle prompt
        # renders exactly what it did before these sections existed.
        "research_expansion_section": req.research_expansion_section,
        "falsified_assumptions_section": req.falsified_assumptions_section,
        "lab_constraints_section": format_lab_constraints_section(
            req.lab_constraints
        ),
    }


# Renders prompts/generation_draft_with_tools.md for the Phase 1 draft
# agent in agents/generation/literature_tools/draft.py (schema:
# GENERATION_DRAFT_SCHEMA via the prompt-name lookup). Focuses on reading
# papers and identifying gaps, with the lit review summary included as
# context (not instructions).
def get_draft_prompt_with_tools(
    req: DraftPromptRequest,
) -> tuple[str, dict[str, Any] | None]:
    """Get the Phase 1 draft prompt; params doc'd on DraftPromptRequest.

    Args:
        req: The resolved draft-prompt request.

    Returns:
        Tuple of (rendered prompt string, JSON schema dict or None).
    """
    return _build_prompt(
        "generation_draft_with_tools",
        _build_draft_prompt_variables(req),
        sections=PromptSections(
            meta_review_context=_format_meta_review_context(
                req.context.meta_review
            ),
            run_guidance=_run_guidance_section(req.context),
        ),
        tool_registry=req.context.tool_registry,
    )
