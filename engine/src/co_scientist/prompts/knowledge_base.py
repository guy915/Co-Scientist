"""Prompts for the deep knowledge-base synthesis pass (F8).

Two prompts, not one, and in their own module rather than beside the
research-overview prompts in ``planning.py``: that module is at its
file-length ceiling, and these two are read together -- the outline
prompt decides a structure the theme prompt is then handed back.

Why the pass is split at all is recorded on
``constants.tokens.KNOWLEDGE_BASE_OUTLINE_MAX_TOKENS``: one call asking
for the whole ~20,000-token span cannot be served inside the 600s
per-call ceiling, whatever budget it carries.
"""

from dataclasses import dataclass
from typing import Any

from co_scientist.prompts._common import (
    PromptRunContext,
    PromptSections,
    _run_guidance_section,
)
from co_scientist.prompts.loading import _build_prompt

_NO_CORPUS = "No verified evidence corpus available."


def get_knowledge_base_outline_prompt(
    research_goal: str,
    hypotheses_summary: str,
    evidence_corpus: str = _NO_CORPUS,
    context: PromptRunContext | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get the knowledge-base outline prompt and schema.

    Args:
        research_goal: The run's research goal.
        hypotheses_summary: Formatted summary of the top-Elo hypotheses,
            for orientation only -- the section states what is known, not
            what the run proposed.
        evidence_corpus: Analyzed sources, pre-formatted.
        context: Run-scoped prompt context (tool registry, run
            setup/focus guidance).

    Returns:
        Tuple of (rendered prompt string, JSON schema dict or None).
    """
    ctx = context or PromptRunContext()
    return _build_prompt(
        "research_overview_knowledge_base_outline",
        {
            "research_goal": research_goal,
            "hypotheses_summary": hypotheses_summary,
            "evidence_corpus": evidence_corpus,
        },
        sections=PromptSections(run_guidance=_run_guidance_section(ctx)),
        tool_registry=ctx.tool_registry,
    )


@dataclass(frozen=True)
class ThemeWritingMaterial:
    """What one theme's writing call is handed by the outline before it.

    The whole outline travels with every theme, not just the theme's own
    slice: each writing call runs without sight of what the others
    produced, so two themes whose headings overlap would otherwise become
    two passages saying the same thing.

    Attributes:
        title: The theme this call is responsible for.
        sections: That theme's outlined headings and the evidence ids each
            was assigned, pre-formatted.
        outline: The full outline -- every theme and its headings --
            pre-formatted, for the overlap the writer must avoid.
    """

    title: str
    sections: str
    outline: str


def get_knowledge_base_theme_prompt(
    research_goal: str,
    material: ThemeWritingMaterial,
    evidence_corpus: str = _NO_CORPUS,
    context: PromptRunContext | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get the prompt and schema for writing one outlined theme.

    Args:
        research_goal: The run's research goal.
        material: The theme to write and the outline it sits in.
        evidence_corpus: Analyzed sources, pre-formatted.
        context: Run-scoped prompt context (tool registry, run
            setup/focus guidance).

    Returns:
        Tuple of (rendered prompt string, JSON schema dict or None).
    """
    ctx = context or PromptRunContext()
    return _build_prompt(
        "research_overview_knowledge_base_theme",
        {
            "research_goal": research_goal,
            "theme_title": material.title,
            "theme_sections": material.sections,
            "outline": material.outline,
            "evidence_corpus": evidence_corpus,
        },
        sections=PromptSections(run_guidance=_run_guidance_section(ctx)),
        tool_registry=ctx.tool_registry,
    )
