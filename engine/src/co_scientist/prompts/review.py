"""Prompt builders for the review, deep-verification, and reflection nodes."""
# pylint: disable=inconsistent-quotes

from typing import Any

from co_scientist.prompts._common import (
    _format_meta_review_context,
    _format_run_guidance,
)
from co_scientist.prompts.loading import _build_prompt


# Renders prompts/review.md for the single-hypothesis review path in
# nodes/review.py (used when the batch is too large for comparative review).
def get_review_prompt(
    research_goal: str,
    hypothesis_text: str,
    supervisor_guidance: dict[str, Any] | None = None,
    meta_review: dict[str, Any] | None = None,
    tool_registry: Any | None = None,
    run_setup_guidance: str | None = None,
    run_focus_guidance: str | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get the hypothesis review prompt and schema."""
    return _build_prompt(
        "review",
        {"research_goal": research_goal, "hypothesis_text": hypothesis_text},
        supervisor_guidance=_format_supervisor_guidance_for_review(
            supervisor_guidance
        ),
        meta_review_context=_format_meta_review_context(meta_review),
        run_guidance=_format_run_guidance(
            run_setup_guidance, run_focus_guidance
        ),
        tool_registry=tool_registry,
    )


# Renders prompts/deep_verification.md for nodes/deep_verification.py, run
# once per top-Elo hypothesis. Deliberately takes no guidance/context
# blocks: probing should challenge the hypothesis on its own terms.
def get_deep_verification_prompt(
    research_goal: str,
    hypothesis_text: str,
    tool_registry: Any | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get the deep-verification (probing questions) prompt and schema."""
    return _build_prompt(
        "deep_verification",
        {
            "research_goal": research_goal,
            "hypothesis_text": hypothesis_text,
        },
        tool_registry=tool_registry,
    )


# Renders prompts/review_batch.md for the comparative batch review path in
# nodes/review.py; hypotheses_list is a pre-formatted text block, not a
# Python list.
def get_review_batch_prompt(
    research_goal: str,
    hypotheses_list: str,
    supervisor_guidance: dict[str, Any] | None = None,
    meta_review: dict[str, Any] | None = None,
    tool_registry: Any | None = None,
    run_setup_guidance: str | None = None,
    run_focus_guidance: str | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get the comparative batch hypothesis review prompt and schema."""
    return _build_prompt(
        "review_batch",
        {"research_goal": research_goal, "hypotheses_list": hypotheses_list},
        supervisor_guidance=_format_supervisor_guidance_for_review(
            supervisor_guidance
        ),
        meta_review_context=_format_meta_review_context(meta_review),
        run_guidance=_format_run_guidance(
            run_setup_guidance, run_focus_guidance
        ),
        tool_registry=tool_registry,
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
        criteria = review_phase["critical_criteria"]
        if isinstance(criteria, list):
            criteria = ", ".join(criteria)
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

    return "".join(sections) if sections else ""


# Renders prompts/reflection_observations.md for nodes/reflection.py, run
# per hypothesis against the literature-review synthesis; indra_evidence
# carries optional knowledge-graph enrichment text ("" when unavailable).
def get_reflection_prompt(
    articles_with_reasoning: str,
    hypothesis_text: str,
    meta_review: dict[str, Any] | None = None,
    tool_registry: Any | None = None,
    indra_evidence: str = "",
) -> tuple[str, dict[str, Any] | None]:
    """Get the reflection observations prompt and schema."""
    return _build_prompt(
        "reflection_observations",
        {
            "articles_with_reasoning": articles_with_reasoning,
            "hypothesis": hypothesis_text,
            "indra_evidence": indra_evidence,
        },
        meta_review_context=_format_meta_review_context(meta_review),
        tool_registry=tool_registry,
    )
