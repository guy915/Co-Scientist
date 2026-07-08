"""Prompt builders for the review, deep-verification, and reflection nodes."""
# pylint: disable=inconsistent-quotes

from typing import Any

from co_scientist.prompts._common import _format_meta_review_context
from co_scientist.prompts._common import _format_run_guidance
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
        {
            "research_goal": research_goal,
            "hypothesis_text": hypothesis_text
        },
        supervisor_guidance=_format_supervisor_guidance_for_review(
            supervisor_guidance),
        meta_review_context=_format_meta_review_context(meta_review),
        run_guidance=_format_run_guidance(run_setup_guidance,
                                          run_focus_guidance),
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
        {
            "research_goal": research_goal,
            "hypotheses_list": hypotheses_list
        },
        supervisor_guidance=_format_supervisor_guidance_for_review(
            supervisor_guidance),
        meta_review_context=_format_meta_review_context(meta_review),
        run_guidance=_format_run_guidance(run_setup_guidance,
                                          run_focus_guidance),
        tool_registry=tool_registry,
    )


# Helper functions to format supervisor guidance for different contexts
# Each helper extracts only the slice of the supervisor's output relevant
# to its node and renders it as a markdown section; all of them return ""
# when the needed keys are absent, so guidance is strictly additive.
def _format_supervisor_guidance_for_review(
        supervisor_guidance: dict[str, Any] | None) -> str:
    """Format supervisor guidance for review prompts."""
    if not supervisor_guidance or not isinstance(supervisor_guidance, dict):
        return ""

    sections = []
    workflow_plan = supervisor_guidance.get("workflow_plan", {})
    review_phase = workflow_plan.get("review_phase", {})

    if review_phase:
        sections.append("## Supervisor Guidance for Review\n")
        if review_phase.get("critical_criteria"):
            criteria = review_phase["critical_criteria"]
            if isinstance(criteria, list):
                criteria = ", ".join(criteria)
            sections.append(f"**Critical Criteria to Emphasize:** {criteria}\n")
        if review_phase.get("review_depth"):
            sections.append(
                f"**Review Depth Required:** {review_phase['review_depth']}\n")

    # Synthesized config: preferences constrain what a good idea is (shared with
    # generation); review_instructions are reviewer-only comparative guidance.
    config = supervisor_guidance.get("config_synthesis", {})
    if isinstance(config, dict):
        preferences = config.get("preferences") or []
        review_instructions = config.get("review_instructions") or []
        attributes = config.get("attributes") or []
        if not sections and (preferences or review_instructions or attributes):
            sections.append("## Supervisor Guidance for Review\n")
        if preferences:
            sections.append("**Preferences (a good idea should satisfy):**\n")
            sections.extend(f"- {p}\n" for p in preferences)
        if review_instructions:
            sections.append(
                "\n**Review instructions (validate, do not restate the"
                " preferences):**\n")
            sections.extend(f"- {r}\n" for r in review_instructions)
        if attributes:
            sections.append("\n**Stratification attributes (score each 1-5):**"
                            "\n")
            for attr in attributes:
                if isinstance(attr, dict) and attr.get("name"):
                    sections.append(
                        f"- {attr['name']}: {attr.get('rubric', '')}\n")

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
