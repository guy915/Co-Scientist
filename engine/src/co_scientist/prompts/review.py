"""Prompt builders for the review, deep-verification, and reflection nodes."""

from typing import Any

from co_scientist.prompts._common import (
    PromptRunContext,
    PromptSections,
    _csv_value,
    _format_meta_review_context,
    _run_guidance_section,
)
from co_scientist.prompts.loading import _build_prompt


def _review_sections(context: PromptRunContext) -> PromptSections:
    """Build the shared context blocks for the two review prompts."""
    return PromptSections(
        supervisor_guidance=_format_supervisor_guidance_for_review(
            context.supervisor_guidance
        ),
        meta_review_context=_format_meta_review_context(context.meta_review),
        run_guidance=_run_guidance_section(context),
    )


# Renders prompts/review.md for the single-hypothesis review path in
# agents/reflection/review.py (used when the batch is too large for
# comparative review).
def get_review_prompt(
    research_goal: str,
    hypothesis_text: str,
    context: PromptRunContext | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get the hypothesis review prompt and schema.

    Args:
        research_goal: The run's research goal.
        hypothesis_text: The hypothesis under review.
        context: Run-scoped prompt context (supervisor guidance,
            meta-review, tool registry, run setup/focus guidance).

    Returns:
        Tuple of (rendered prompt string, JSON schema dict or None).
    """
    ctx = context or PromptRunContext()
    return _build_prompt(
        "review",
        {"research_goal": research_goal, "hypothesis_text": hypothesis_text},
        sections=_review_sections(ctx),
        tool_registry=ctx.tool_registry,
    )


# Renders prompts/deep_verification.md for
# agents/reflection/deep_verification.py, run
# once per top-Elo hypothesis. Deliberately takes no guidance/context
# blocks: probing should challenge the hypothesis on its own terms.
def get_deep_verification_prompt(
    research_goal: str,
    hypothesis_text: str,
    tool_registry: Any | None = None,
    evidence_context: str = "No retrieved evidence available.",
) -> tuple[str, dict[str, Any] | None]:
    """Get the deep-verification (probing questions) prompt and schema.

    Takes ``tool_registry`` directly rather than a ``PromptRunContext``:
    it uses no other field of that bundle, by design (see above).
    """
    return _build_prompt(
        "deep_verification",
        {
            "research_goal": research_goal,
            "hypothesis_text": hypothesis_text,
            "evidence_context": evidence_context,
        },
        tool_registry=tool_registry,
    )


# Renders prompts/review_batch.md for the comparative batch review path in
# agents/reflection/review.py; hypotheses_list is a pre-formatted
# text block, not a
# Python list.
def get_review_batch_prompt(
    research_goal: str,
    hypotheses_list: str,
    context: PromptRunContext | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get the comparative batch hypothesis review prompt and schema.

    Args:
        research_goal: The run's research goal.
        hypotheses_list: Pre-formatted block listing the batch's hypotheses.
        context: Run-scoped prompt context (supervisor guidance,
            meta-review, tool registry, run setup/focus guidance).

    Returns:
        Tuple of (rendered prompt string, JSON schema dict or None).
    """
    ctx = context or PromptRunContext()
    return _build_prompt(
        "review_batch",
        {"research_goal": research_goal, "hypotheses_list": hypotheses_list},
        sections=_review_sections(ctx),
        tool_registry=ctx.tool_registry,
    )


# Helper functions to format supervisor guidance for different contexts
# Each helper extracts only the slice of the supervisor's output relevant
# to its node and renders it as a markdown section; all of them return ""
# when the needed keys are absent, so guidance is strictly additive.
def _format_review_phase_guidance(review_phase: dict[str, Any]) -> list[str]:
    """Format the workflow_plan.review_phase slice of supervisor guidance.

    Args:
        review_phase: The `workflow_plan.review_phase` dict from supervisor
            guidance (may be empty).

    Returns:
        Section lines, headed by the shared "Supervisor Guidance for
        Review" title whenever review_phase is non-empty (even if neither
        of its known fields is present); an empty list otherwise.
    """
    if not review_phase:
        return []

    sections = ["## Supervisor Guidance for Review\n"]
    if review_phase.get("critical_criteria"):
        criteria = _csv_value(review_phase["critical_criteria"])
        sections.append(f"**Critical Criteria to Emphasize:** {criteria}\n")
    if review_phase.get("review_depth"):
        sections.append(
            f"**Review Depth Required:** {review_phase['review_depth']}\n"
        )
    return sections


def _format_config_preferences_guidance(
    preferences: list[Any] | None,
) -> list[str]:
    """Format the config_synthesis preferences slice of supervisor guidance."""
    if not preferences:
        return []
    sections = ["**Preferences (a good idea should satisfy):**\n"]
    sections.extend(f"- {p}\n" for p in preferences)
    return sections


def _format_config_review_instructions_guidance(
    review_instructions: list[Any] | None,
) -> list[str]:
    """Format the config_synthesis review-instructions guidance slice."""
    if not review_instructions:
        return []
    sections = [
        "\n**Review instructions (validate, do not restate the"
        " preferences):**\n"
    ]
    sections.extend(f"- {r}\n" for r in review_instructions)
    return sections


def _format_config_attributes_guidance(
    attributes: list[Any] | None,
) -> list[str]:
    """Format the config_synthesis stratification-attributes slice."""
    if not attributes:
        return []
    sections = ["\n**Stratification attributes (score each 1-5):**\n"]
    for attr in attributes:
        if isinstance(attr, dict) and attr.get("name"):
            sections.append(f"- {attr['name']}: {attr.get('rubric', '')}\n")
    return sections


def _format_config_synthesis_guidance(
    config: Any, *, needs_header: bool
) -> list[str]:
    """Format the config_synthesis slice of supervisor guidance.

    Synthesized config: preferences constrain what a good idea is (shared
    with generation); review_instructions are reviewer-only comparative
    guidance.

    Args:
        config: The `config_synthesis` value from supervisor guidance.
        needs_header: Whether the shared "Supervisor Guidance for Review"
            title still needs to be emitted, i.e. no earlier section already
            added it.

    Returns:
        Section lines, headed by the shared title only when needs_header is
        true and this slice has content; an empty list when config is not a
        dict or carries none of the three known fields.
    """
    if not isinstance(config, dict):
        return []

    preferences = config.get("preferences")
    review_instructions = config.get("review_instructions")
    attributes = config.get("attributes")

    sections = []
    if needs_header and any((preferences, review_instructions, attributes)):
        sections.append("## Supervisor Guidance for Review\n")
    sections.extend(_format_config_preferences_guidance(preferences))
    sections.extend(
        _format_config_review_instructions_guidance(review_instructions)
    )
    sections.extend(_format_config_attributes_guidance(attributes))
    return sections


def _format_supervisor_guidance_for_review(
    supervisor_guidance: dict[str, Any] | None,
) -> str:
    """Format supervisor guidance for review prompts."""
    if not supervisor_guidance or not isinstance(supervisor_guidance, dict):
        return ""

    workflow_plan = supervisor_guidance.get("workflow_plan", {})
    sections = _format_review_phase_guidance(
        workflow_plan.get("review_phase", {})
    )

    config = supervisor_guidance.get("config_synthesis", {})
    sections.extend(
        _format_config_synthesis_guidance(config, needs_header=not sections)
    )

    return "".join(sections)


# Renders prompts/reflection_observations.md for
# agents/reflection/reflection.py, run
# per hypothesis against the literature-review synthesis; indra_evidence
# carries optional knowledge-graph enrichment text ("" when unavailable).
def get_reflection_prompt(
    articles_with_reasoning: str,
    hypothesis_text: str,
    indra_evidence: str = "",
    context: PromptRunContext | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get the reflection observations prompt and schema.

    Args:
        articles_with_reasoning: The literature-review synthesis text.
        hypothesis_text: The hypothesis being reflected on.
        indra_evidence: Optional knowledge-graph enrichment text.
        context: Run-scoped prompt context; only the meta-review and tool
            registry reach this prompt.

    Returns:
        Tuple of (rendered prompt string, JSON schema dict or None).
    """
    ctx = context or PromptRunContext()
    return _build_prompt(
        "reflection_observations",
        {
            "articles_with_reasoning": articles_with_reasoning,
            "hypothesis": hypothesis_text,
            "indra_evidence": indra_evidence,
        },
        sections=PromptSections(
            meta_review_context=_format_meta_review_context(ctx.meta_review)
        ),
        tool_registry=ctx.tool_registry,
    )
