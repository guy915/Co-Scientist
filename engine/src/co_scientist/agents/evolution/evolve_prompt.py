"""Prompt assembly and meta-review logging for the Evolve node."""

import json
import logging
from typing import Any

from co_scientist.agents.evolution.evolution_operators import (
    EvolutionOperator,
    operator_instruction,
)
from co_scientist.constants import truncate
from co_scientist.models import Hypothesis
from co_scientist.prompts import (
    _format_run_guidance,
    _get_domain_variables,
    load_prompt_with_schema,
)

logger = logging.getLogger(__name__)


def _log_debug_items(
    label: str, items: list[str], *, truncate_items: bool = False
) -> None:
    """Logs a debug header and up to the first 3 items.

    Args:
        label: Human-readable field label (e.g. "common Strengths").
        items: Meta-review items to log.
        truncate_items: Truncate each item to 100 chars when set.
    """
    if not items:
        return
    logger.debug("%s (%s):", label, len(items))
    for item in items[:3]:  # Show first 3
        logger.debug("- %s", truncate(item, 100) if truncate_items else item)


def _log_truncated_items(label: str, items: list[str]) -> None:
    """Logs a debug header and up to 3 items, each truncated to 100 chars."""
    _log_debug_items(label, items, truncate_items=True)


def _log_items(label: str, items: list[str]) -> None:
    """Logs a debug header and up to 3 items verbatim."""
    _log_debug_items(label, items)


def _log_meta_review_debug(meta_review: dict[str, Any]) -> None:
    """Logs meta-review signals used during evolution, for debugging.

    The same fields are also formatted into the prompt itself (see
    _build_meta_review_insights); this only logs them for visibility.

    Args:
        meta_review: Meta-review insights for strategic guidance.
    """
    logger.debug("\n=== evolve single hypothesis ===")
    logger.debug("using meta review for evolution")

    _log_truncated_items(
        "common Strengths", meta_review.get("common_strengths", [])
    )
    _log_truncated_items(
        "common Weaknesses", meta_review.get("common_weaknesses", [])
    )
    _log_items(
        "strategic Recommendations",
        meta_review.get("strategic_recommendations", []),
    )
    _log_items("emerging Themes", meta_review.get("emerging_themes", []))


def _build_review_feedback(hypothesis: Hypothesis) -> str:
    """Formats a hypothesis's latest review as evolution-prompt context.

    Surfaces the most recent review's scores/feedback as context so the
    LLM addresses concrete critique rather than refining blind.

    Args:
        hypothesis: Hypothesis being evolved.

    Returns:
        JSON-formatted review feedback, or an empty string if the
        hypothesis has no reviews yet.
    """
    latest_review = hypothesis.latest_review
    if latest_review is None:
        return ""
    return json.dumps(
        {
            "overall_score": latest_review.overall_score,
            "review_summary": latest_review.review_summary,
            "constructive_feedback": latest_review.constructive_feedback,
            "scores": latest_review.scores,
        },
        indent=2,
    )


def _build_meta_review_insights(meta_review: dict[str, Any]) -> str:
    """Formats meta-review insights for the evolution prompt.

    Args:
        meta_review: Meta-review insights for strategic guidance.

    Returns:
        JSON-formatted meta-review insights.
    """
    return json.dumps(
        {
            "common_strengths": meta_review.get("common_strengths", []),
            "common_weaknesses": meta_review.get("common_weaknesses", []),
            "strategic_recommendations": meta_review.get(
                "strategic_recommendations", []
            ),
            "emerging_themes": meta_review.get("emerging_themes", []),
        },
        indent=2,
    )


def _format_refinement_priorities(
    evolution_phase: dict[str, Any],
) -> str | None:
    """Format the refinement-priorities guidance line, if present."""
    priorities = evolution_phase.get("refinement_priorities")
    if not priorities:
        return None
    if isinstance(priorities, list):
        priorities = ", ".join(priorities)
    return f"**Refinement Priorities:** {priorities}\n"


def _format_iteration_strategy(evolution_phase: dict[str, Any]) -> str | None:
    """Format the iteration-strategy guidance line, if present."""
    strategy = evolution_phase.get("iteration_strategy")
    if not strategy:
        return None
    return f"**Iteration Strategy:** {strategy}\n"


def _format_evolution_guidance_lines(
    evolution_phase: dict[str, Any],
) -> list[str]:
    """Format the non-empty evolution-phase guidance lines."""
    lines = []
    for formatter in (
        _format_refinement_priorities,
        _format_iteration_strategy,
    ):
        section = formatter(evolution_phase)
        if section:
            lines.append(section)
    return lines


def _build_supervisor_guidance_text(
    supervisor_guidance: dict[str, Any] | None,
) -> str:
    """Formats the evolution-phase slice of supervisor guidance.

    Only the evolution_phase slice of the supervisor's workflow_plan is
    relevant here; other phases (e.g. generation) are ignored.

    Args:
        supervisor_guidance: Optional supervisor guidance for evolution phase.

    Returns:
        Formatted supervisor guidance text, or an empty string if there is
        no evolution-phase guidance to surface.
    """
    if not supervisor_guidance or not isinstance(supervisor_guidance, dict):
        return ""
    workflow_plan = supervisor_guidance.get("workflow_plan", {})
    evolution_phase = workflow_plan.get("evolution_phase", {})
    if not evolution_phase:
        return ""

    guidance_sections = ["## Supervisor Guidance for Evolution\n"]
    guidance_sections.extend(_format_evolution_guidance_lines(evolution_phase))
    guidance_sections.append(
        "\nUse this guidance to align your refinement with the research plan.\n"
    )
    return "".join(guidance_sections)


def _format_bullet_list(texts: list[str]) -> str:
    """Format texts as a bullet list, each truncated to 200 chars.

    200 chars is enough for the LLM to recognize overlap without materially
    growing the prompt.
    """
    return "\n".join(f"- {text[:200]}..." for text in texts)


_DIVERSITY_INSTRUCTION_TEMPLATE = """

## CRITICAL: Preserve Diversity

**Other hypotheses being evolved simultaneously:**
{other_hyps}

**Previously removed duplicates (DO NOT recreate these):**
{removed_dups}

**CRITICAL REQUIREMENT:** Your refined hypothesis MUST remain DISTINCT from:
1. All other hypotheses listed above
2. Previously removed duplicates

DO NOT:
- Use the same biomarker/methodology as other hypotheses
- Make only trivial wording changes
- Converge toward similar concepts

DO:
- Maintain the unique aspects of this hypothesis
- Explore different mechanisms or approaches
- Preserve conceptual diversity
"""


def _format_diversity_instruction(
    other_hypotheses_texts: list[str], removed_duplicates: list[str]
) -> str:
    """Builds the anti-convergence directive appended to the evolution prompt.

    Appended after the schema-driven prompt (not merged into its
    variables) as an explicit anti-convergence directive: without this,
    independently evolved hypotheses tend to drift toward the same winning
    idea.

    Args:
        other_hypotheses_texts: Strategically sampled subset of other
            hypotheses (max 15).
        removed_duplicates: Previously removed duplicate texts to avoid.

    Returns:
        Diversity-instruction text to append to the evolution prompt.
    """
    other_hyps_formatted = _format_bullet_list(other_hypotheses_texts)
    # Only the 5 most recently removed duplicates are shown, keeping this
    # section bounded regardless of how many duplicates accumulate over a
    # run.
    removed_dups_formatted = _format_bullet_list(removed_duplicates[-5:])

    return _DIVERSITY_INSTRUCTION_TEMPLATE.format(
        other_hyps=other_hyps_formatted or "None",
        removed_dups=removed_dups_formatted or "None",
    )


def _build_evolution_variables(
    hypothesis: Hypothesis,
    meta_review: dict[str, Any],
    supervisor_guidance: dict[str, Any] | None,
    articles_with_reasoning: str | None,
    tool_registry: Any | None,
    run_setup_guidance: str | None,
    run_focus_guidance: str | None,
    specialist_feedback: str = "",
) -> dict[str, Any]:
    """Builds the template variables for the "evolution" prompt.

    Unlike most nodes, evolve has no dedicated get_evolution_prompt()
    wrapper in prompts.py, so this helper pulls in the normally-internal
    run-guidance/domain helpers itself to build the same variables those
    wrappers assemble. All parameters feed the identically-named "evolution"
    prompt template variables (specialist_feedback and articles_with_reasoning
    fall back to a placeholder / empty string when unset).

    Returns:
        Template variables for the "evolution" prompt.
    """
    variables = _base_evolution_variables(
        hypothesis, meta_review, supervisor_guidance
    )
    variables["run_guidance"] = _format_run_guidance(
        run_setup_guidance, run_focus_guidance
    )
    variables["articles_with_reasoning"] = articles_with_reasoning or ""
    variables["specialist_feedback"] = (
        specialist_feedback or "No prior specialist feedback."
    )
    variables.update(_get_domain_variables(tool_registry))
    return variables


def _base_evolution_variables(
    hypothesis: Hypothesis,
    meta_review: dict[str, Any],
    supervisor_guidance: dict[str, Any] | None,
) -> dict[str, Any]:
    """Builds the hypothesis/meta-review/supervisor-guidance variables."""
    return {
        "original_hypothesis": hypothesis.text,
        "review_feedback": _build_review_feedback(hypothesis),
        "meta_review_insights": _build_meta_review_insights(meta_review),
        "supervisor_guidance": _build_supervisor_guidance_text(
            supervisor_guidance
        ),
    }


def _format_operator_section(operator: EvolutionOperator) -> str:
    """Format the required-evolution-operator section of the prompt."""
    return (
        "\n\n## Required Evolution Operator\n"
        f"**Operator:** {operator.value}\n"
        f"{operator_instruction(operator)}\n"
        "Record how this operator changed the proposal in the refinement "
        "summary.\n"
    )


def _build_evolution_prompt(
    hypothesis: Hypothesis,
    other_hypotheses_texts: list[str],
    meta_review: dict[str, Any],
    removed_duplicates: list[str],
    supervisor_guidance: dict[str, Any] | None,
    articles_with_reasoning: str | None,
    tool_registry: Any | None,
    run_setup_guidance: str | None,
    run_focus_guidance: str | None,
    operator: EvolutionOperator = EvolutionOperator.ENHANCEMENT,
    specialist_feedback: str = "",
) -> tuple[str, dict[str, Any] | None]:
    """Assembles the full evolution prompt (and schema) for one hypothesis.

    Returns:
        Tuple of (full prompt text with diversity instruction appended,
        JSON schema for the expected LLM response).
    """
    variables = _build_evolution_variables(
        hypothesis=hypothesis,
        meta_review=meta_review,
        supervisor_guidance=supervisor_guidance,
        articles_with_reasoning=articles_with_reasoning,
        tool_registry=tool_registry,
        run_setup_guidance=run_setup_guidance,
        run_focus_guidance=run_focus_guidance,
        specialist_feedback=specialist_feedback,
    )
    prompt, schema = load_prompt_with_schema("evolution", variables)

    full_prompt = (
        prompt
        + _format_operator_section(operator)
        + _format_diversity_instruction(
            other_hypotheses_texts, removed_duplicates
        )
    )
    return full_prompt, schema
