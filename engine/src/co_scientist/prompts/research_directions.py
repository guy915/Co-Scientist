"""Prompt for developing one drafted research direction.

The research overview draft names its directions and argues each in a
paragraph; this prompt is what turns one of those into the published
exemplar's own depth -- a multi-point "Why research this area?", the
"what is already known" baseline, concrete experiments, and the named
sub-topics beneath.

It is a separate call for the same reason the knowledge base is written
in parts (``prompts/knowledge_base``): six directions at the exemplar's
density is ~13.9k tokens in one stream, which the 600s per-call ceiling
cannot serve at this deployment's measured 27-37 tokens per second.
``schemas.synthesis.RESEARCH_OVERVIEW_TARGET_DIRECTIONS`` records the
arithmetic.
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


@dataclass(frozen=True)
class DirectionWritingMaterial:
    """What one direction's writing call is handed by the draft before it.

    Every direction's title travels with each call, not just this one's:
    the six run concurrently and none sees what the others produced, so
    two neighbouring directions would otherwise argue the same mechanism
    twice. Same reason ``ThemeWritingMaterial`` carries the whole outline.

    Attributes:
        title: The direction this call is responsible for.
        rationale: The importance paragraph the draft argued it with,
            which this call develops rather than contradicts.
        all_directions: Every direction's title, pre-formatted, for the
            overlap the writer must avoid.
    """

    title: str
    rationale: str
    all_directions: str


def get_research_overview_direction_prompt(
    research_goal: str,
    material: DirectionWritingMaterial,
    hypotheses_summary: str,
    evidence_corpus: str = _NO_CORPUS,
    context: PromptRunContext | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get the prompt and schema for developing one drafted direction.

    Args:
        research_goal: The run's research goal.
        material: The direction to develop and the set it sits in.
        hypotheses_summary: Formatted summary of the top-Elo hypotheses.
        evidence_corpus: Analyzed sources, pre-formatted.
        context: Run-scoped prompt context (tool registry, run
            setup/focus guidance).

    Returns:
        Tuple of (rendered prompt string, JSON schema dict or None).
    """
    ctx = context or PromptRunContext()
    return _build_prompt(
        "research_overview_direction",
        {
            "research_goal": research_goal,
            "direction_title": material.title,
            "direction_rationale": material.rationale,
            "all_directions": material.all_directions,
            "hypotheses_summary": hypotheses_summary,
            "evidence_corpus": evidence_corpus,
        },
        sections=PromptSections(run_guidance=_run_guidance_section(ctx)),
        tool_registry=ctx.tool_registry,
    )
