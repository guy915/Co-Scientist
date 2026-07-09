"""Prompt builders for the ranking/tournament and proximity nodes."""
# pylint: disable=inconsistent-quotes

from typing import Any

from co_scientist.prompts._common import (
    _format_meta_review_context,
    _format_run_guidance,
)
from co_scientist.prompts.loading import _build_prompt


def _build_ranking_prompt_variables(
    research_goal: str,
    hypothesis_a: str,
    hypothesis_b: str,
    review_a: dict[str, Any] | None,
    review_b: dict[str, Any] | None,
    reflection_notes_a: str | None,
    reflection_notes_b: str | None,
    deep_verification_a: dict[str, Any] | None,
    deep_verification_b: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the template variables for the ranking comparison prompt.

    Args:
        research_goal: The research goal
        hypothesis_a: Text of the first hypothesis
        hypothesis_b: Text of the second hypothesis
        review_a: Optional review dict for hypothesis A
        review_b: Optional review dict for hypothesis B
        reflection_notes_a: Optional reflection notes for hypothesis A
        reflection_notes_b: Optional reflection notes for hypothesis B
        deep_verification_a: Optional deep-verification dict for hypothesis A
        deep_verification_b: Optional deep-verification dict for hypothesis B

    Returns:
        Dict of template variables for the ranking prompt.
    """
    variables = {
        "research_goal": research_goal,
        "hypothesis_a": hypothesis_a,
        "hypothesis_b": hypothesis_b,
        "review_context": _format_review_context(review_a, review_b),
        "hypothesis_a_reflection_notes": (
            reflection_notes_a or "No reflection notes available."
        ),
        "hypothesis_b_reflection_notes": (
            reflection_notes_b or "No reflection notes available."
        ),
    }

    # Add deep-verification probes if available (blank before the first
    # deep_verification pass has run on the leaders).
    dv_a = deep_verification_a or {}
    dv_b = deep_verification_b or {}
    variables["hypothesis_a_deep_verification"] = (
        _format_deep_verification_context(
            dv_a.get("probes"), dv_a.get("verdict"), "A"
        )
    )
    variables["hypothesis_b_deep_verification"] = (
        _format_deep_verification_context(
            dv_b.get("probes"), dv_b.get("verdict"), "B"
        )
    )

    return variables


# Renders prompts/ranking.md for each pairwise tournament match in
# nodes/ranking.py. Beyond the two hypothesis texts, the prompt aggregates
# every per-hypothesis signal available at match time: review scores,
# reflection notes, and (from the second tournament onward) deep-
# verification probes.
def get_ranking_prompt(
    research_goal: str,
    hypothesis_a: str,
    hypothesis_b: str,
    supervisor_guidance: dict[str, Any] | None = None,
    review_a: dict[str, Any] | None = None,
    review_b: dict[str, Any] | None = None,
    reflection_notes_a: str | None = None,
    reflection_notes_b: str | None = None,
    deep_verification_a: dict[str, Any] | None = None,
    deep_verification_b: dict[str, Any] | None = None,
    meta_review: dict[str, Any] | None = None,
    tool_registry: Any | None = None,
    run_setup_guidance: str | None = None,
    run_focus_guidance: str | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get the ranking (and tournament) comparison prompt and schema."""
    variables = _build_ranking_prompt_variables(
        research_goal=research_goal,
        hypothesis_a=hypothesis_a,
        hypothesis_b=hypothesis_b,
        review_a=review_a,
        review_b=review_b,
        reflection_notes_a=reflection_notes_a,
        reflection_notes_b=reflection_notes_b,
        deep_verification_a=deep_verification_a,
        deep_verification_b=deep_verification_b,
    )

    return _build_prompt(
        "ranking",
        variables,
        supervisor_guidance=_format_supervisor_guidance_for_ranking(
            supervisor_guidance
        ),
        meta_review_context=_format_meta_review_context(meta_review),
        run_guidance=_format_run_guidance(
            run_setup_guidance, run_focus_guidance
        ),
        tool_registry=tool_registry,
    )


# Renders prompts/proximity.md for nodes/proximity.py. The hypothesis texts
# are passed as a JSON array; include_domain=False because similarity
# clustering is domain-neutral by design.
def get_proximity_prompt(
    hypotheses: list[Any], supervisor_guidance: dict[str, Any] | None = None
) -> tuple[str, dict[str, Any] | None]:
    """Get the proximity/similarity analysis prompt and schema."""
    import json  # pylint: disable=import-outside-toplevel

    return _build_prompt(
        "proximity",
        {
            "hypotheses": json.dumps(
                [h["text"] if isinstance(h, dict) else h for h in hypotheses],
                indent=2,
            )
        },
        supervisor_guidance=_format_supervisor_guidance_for_proximity(
            supervisor_guidance
        ),
        include_domain=False,
    )


def _format_key_areas_guidance(
    supervisor_guidance: dict[str, Any] | None, header: str, trailer: str
) -> str:
    """Format the supervisor's key research areas as a guidance section.

    Args:
        supervisor_guidance: Supervisor guidance dict from workflow state.
        header: Bolded sub-header introducing the key-areas list.
        trailer: Sentence telling the node how to apply the key areas.

    Returns:
        A markdown guidance section, or an empty string without key areas.
    """
    if not supervisor_guidance or not isinstance(supervisor_guidance, dict):
        return ""

    goal_analysis = supervisor_guidance.get("research_goal_analysis", {})
    key_areas = goal_analysis.get("key_areas", [])
    if not key_areas:
        return ""

    sections = ["## Supervisor Guidance\n", f"**{header}:**\n"]
    for area in key_areas:
        sections.append(f"- {area}\n")
    sections.append(f"\n{trailer}\n")
    return "".join(sections)


def _format_supervisor_guidance_for_ranking(
    supervisor_guidance: dict[str, Any] | None,
) -> str:
    """Format supervisor guidance for ranking prompts."""
    return _format_key_areas_guidance(
        supervisor_guidance,
        "Key Research Areas to Consider",
        "When comparing hypotheses, prioritize those that better"
        " address these key areas.",
    )


def _format_supervisor_guidance_for_proximity(
    supervisor_guidance: dict[str, Any] | None,
) -> str:
    """Format supervisor guidance for proximity prompts."""
    return _format_key_areas_guidance(
        supervisor_guidance,
        "Key Research Areas",
        "When assessing similarity, consider whether hypotheses"
        " explore different aspects of these key areas. Hypotheses"
        " that address the same area with similar approaches should"
        " be flagged as duplicates.",
    )


def _format_probe_lines(probe: dict[str, Any]) -> list[str]:
    """Format one deep-verification probe's question/answer lines."""
    question = probe.get("question", "")
    answer = probe.get("answer", "")
    fundamental = (
        " (fundamental assumption)"
        if probe.get("assumption_is_fundamental")
        else ""
    )
    lines = [f"- Q{fundamental}: {question}\n"]
    if answer:
        lines.append(f"  A: {answer}\n")
    return lines


def _format_deep_verification_context(
    probes: list[dict[str, Any]] | None, verdict: str | None, label: str
) -> str:
    """Format deep-verification probes for one hypothesis in ranking prompts.

    Returns an empty string when no probes are available so the ranking prompt
    is unchanged on the first tournament (before any deep verification has run).

    Args:
        probes: Probing-question entries from the deep-verification node, or
            None.
        verdict: The deep-verification verdict ("holds", "weakened", or
            "undermined"), or None.
        label: The hypothesis label ("A" or "B") for the section header.

    Returns:
        A formatted block with a leading separator, or an empty string.
    """
    if not probes:
        return ""

    verdict_text = verdict or "unknown"
    sections = [
        f"\n\n**Hypothesis {label} Deep Verification"
        f" (verdict: {verdict_text}):**\n"
    ]
    for probe in probes:
        sections.extend(_format_probe_lines(probe))

    return "".join(sections)


def _format_single_review_scores(
    label: str, review: dict[str, Any] | None
) -> list[str]:
    """Format one hypothesis's review scores as a guidance section.

    Args:
        label: The hypothesis label ("A" or "B") for the section header.
        review: The review dict for this hypothesis, or None.

    Returns:
        Section lines, or an empty list when review is absent.
    """
    if not review:
        return []

    sections = [f"**Hypothesis {label} Review Scores:**\n"]
    if isinstance(review, dict):
        for criterion, score in review.get("scores", {}).items():
            sections.append(f"- {criterion}: {score}\n")
        if "overall_score" in review:
            sections.append(f"- Overall Score: {review['overall_score']}\n")
    sections.append("\n")
    return sections


def _format_review_context(
    review_a: dict[str, Any] | None, review_b: dict[str, Any] | None
) -> str:
    """Format review scores for ranking prompts."""
    if not review_a and not review_b:
        return ""

    sections = [
        "## Review Scores Context\n",
        "The following review scores are available to inform your"
        " comparison:\n\n",
    ]
    sections.extend(_format_single_review_scores("A", review_a))
    sections.extend(_format_single_review_scores("B", review_b))
    sections.append(
        "Consider these scores, but make your judgment based on"
        " comprehensive comparison, not just scores.\n"
    )

    return "".join(sections) if sections else ""
