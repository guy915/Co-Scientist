"""Prompt builders for the ranking/tournament and proximity nodes."""

from dataclasses import dataclass
from typing import Any

from co_scientist.prompts._common import (
    PromptRunContext,
    PromptSections,
    _format_bullet_section,
    _format_meta_review_context,
    _run_guidance_section,
)
from co_scientist.prompts.loading import _build_prompt


@dataclass(frozen=True)
class RankingSide:
    """One side of a pairwise tournament match.

    Bundles every per-hypothesis signal the ranking prompt aggregates, so
    the builder takes two symmetric sides instead of eight interleaved
    ``*_a``/``*_b`` parameters.

    Attributes:
        text: The hypothesis text being compared.
        review: This hypothesis's review scores, if it has been reviewed.
        reflection_notes: This hypothesis's reflection notes, if any.
        deep_verification: This hypothesis's deep-verification result
            (``probes`` and ``verdict``), blank before the first pass.
        mature_reviews: This hypothesis's full/simulation/recurrent review
            summary (``mature_review_summary`` shape), blank before the
            mature Reflection cascade has run.
    """

    text: str
    review: dict[str, Any] | None = None
    reflection_notes: str | None = None
    deep_verification: dict[str, Any] | None = None
    mature_reviews: dict[str, dict[str, Any]] | None = None


def _build_ranking_deep_verification_variables(
    side_a: RankingSide, side_b: RankingSide
) -> dict[str, Any]:
    """Build the deep-verification template variables for ranking prompts.

    Blank before the first deep_verification pass has run on the leaders.

    Args:
        side_a: The "A" side of the match.
        side_b: The "B" side of the match.

    Returns:
        Dict of the two deep-verification template variables.
    """
    dv_a = side_a.deep_verification or {}
    dv_b = side_b.deep_verification or {}
    return {
        "hypothesis_a_deep_verification": _format_deep_verification_context(
            dv_a.get("probes"), dv_a.get("verdict"), "A"
        ),
        "hypothesis_b_deep_verification": _format_deep_verification_context(
            dv_b.get("probes"), dv_b.get("verdict"), "B"
        ),
    }


def _build_ranking_mature_review_variables(
    side_a: RankingSide, side_b: RankingSide
) -> dict[str, Any]:
    """Build the mature-review template variables for ranking prompts.

    Blank before the mature Reflection cascade (full/simulation/recurrent
    reviews) has run on either side.

    Args:
        side_a: The "A" side of the match.
        side_b: The "B" side of the match.

    Returns:
        Dict of the two mature-review template variables.
    """
    return {
        "hypothesis_a_mature_reviews": _format_mature_reviews_context(
            side_a.mature_reviews, "A"
        ),
        "hypothesis_b_mature_reviews": _format_mature_reviews_context(
            side_b.mature_reviews, "B"
        ),
    }


# Governing-criteria section for the judge (finding A2/K4). The review
# stage always scores its fixed eight axes (schemas/review.py) and this
# section does not change them; it tells the judge how the scientist's
# own criteria map onto the verdict when they were supplied:
#
# - Each criterion governs the verdict directly -- the comparison fields
#   of the judgment schema stay the seven standard dimensions (the schema
#   is static), but the judge is told to decide by the scientist's
#   criteria first.
# - Where a criterion overlaps a standard comparison dimension or a review
#   score axis (e.g. a feasibility criterion with feasibility_comparison,
#   a soundness criterion with scientific_soundness), the scientist's
#   framing of that axis weighs heaviest.
# Absent criteria render nothing and the judge keeps the built-in seven.
_CRITERIA_PREAMBLE = (
    "## Scientist Evaluation Criteria (governing)\n"
    "The scientist who commissioned this research specified what matters "
    "most for this goal. Treat these criteria as the governing standard "
    "of your verdict: decide the comparison by them first, and where one "
    "overlaps a standard comparison dimension or review score axis above "
    "(for example a feasibility criterion with feasibility, or a "
    "soundness criterion with scientific soundness), let the scientist's "
    "framing of that axis weigh heaviest:\n"
)


def _format_ranking_evaluation_criteria(
    criteria: list[str] | None,
) -> str:
    """Format the scientist's evaluation criteria for the ranking judge.

    Renders nothing when no criteria were supplied, leaving the judge on
    the template's built-in comparison criteria.
    """
    cleaned = [
        str(item).strip() for item in criteria or [] if str(item).strip()
    ]
    if not cleaned:
        return ""

    sections = [_CRITERIA_PREAMBLE]
    sections.extend(f"- {item}\n" for item in cleaned)
    sections.append("\n")
    return "".join(sections)


def _build_ranking_prompt_variables(
    research_goal: str,
    side_a: RankingSide,
    side_b: RankingSide,
    criteria: list[str] | None,
) -> dict[str, Any]:
    """Build the template variables for the ranking comparison prompt.

    Args:
        research_goal: The run's research goal.
        side_a: The "A" side of the match.
        side_b: The "B" side of the match.
        criteria: The scientist's evaluation criteria, if any (see the
            ``_CRITERIA_PREAMBLE`` mapping comment).

    Returns:
        Dict of template variables for the ranking prompt.
    """
    variables = {
        "research_goal": research_goal,
        "hypothesis_a": side_a.text,
        "hypothesis_b": side_b.text,
        "review_context": _format_review_context(side_a.review, side_b.review),
        "hypothesis_a_reflection_notes": (
            side_a.reflection_notes or "No reflection notes available."
        ),
        "hypothesis_b_reflection_notes": (
            side_b.reflection_notes or "No reflection notes available."
        ),
        # Always produced (empty when absent) so the slot never renders as
        # a {{MISSING:...}} sentinel.
        "evaluation_criteria": _format_ranking_evaluation_criteria(criteria),
    }
    variables.update(_build_ranking_deep_verification_variables(side_a, side_b))
    variables.update(_build_ranking_mature_review_variables(side_a, side_b))
    return variables


# Renders prompts/ranking.md for each pairwise tournament match in
# agents/ranking/ranking.py. Beyond the two hypothesis texts, the
# prompt aggregates
# every per-hypothesis signal available at match time: review scores,
# reflection notes, and (from the second tournament onward) deep-
# verification probes.
def get_ranking_prompt(
    research_goal: str,
    side_a: RankingSide,
    side_b: RankingSide,
    context: PromptRunContext | None = None,
    criteria: list[str] | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Get the ranking (and tournament) comparison prompt and schema.

    Args:
        research_goal: The run's research goal.
        side_a: The "A" side of the match.
        side_b: The "B" side of the match.
        context: Run-scoped prompt context (supervisor guidance,
            meta-review, tool registry, run setup/focus guidance).
        criteria: The scientist's evaluation criteria, if any; when
            present they govern the judge's verdict (finding A2/K4).

    Returns:
        Tuple of (rendered prompt string, JSON schema dict or None).
    """
    ctx = context or PromptRunContext()
    return _build_prompt(
        "ranking",
        _build_ranking_prompt_variables(
            research_goal, side_a, side_b, criteria
        ),
        sections=PromptSections(
            supervisor_guidance=_format_supervisor_guidance_for_ranking(
                ctx.supervisor_guidance
            ),
            meta_review_context=_format_meta_review_context(ctx.meta_review),
            run_guidance=_run_guidance_section(ctx),
        ),
        tool_registry=ctx.tool_registry,
    )


# Renders prompts/proximity.md for
# agents/proximity/proximity.py. The hypothesis texts
# are passed as a JSON array; include_domain=False because similarity
# clustering is domain-neutral by design.
def get_proximity_prompt(
    hypotheses: list[Any], supervisor_guidance: dict[str, Any] | None = None
) -> tuple[str, dict[str, Any] | None]:
    """Get the proximity/similarity analysis prompt and schema."""
    import json

    return _build_prompt(
        "proximity",
        {
            "hypotheses": json.dumps(
                [h["text"] if isinstance(h, dict) else h for h in hypotheses],
                indent=2,
            )
        },
        sections=PromptSections(
            supervisor_guidance=_format_supervisor_guidance_for_proximity(
                supervisor_guidance
            )
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

    bullets = _format_bullet_section(header, key_areas)
    return f"## Supervisor Guidance\n{bullets}{trailer}\n"


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


_MATURE_REVIEW_SECTION_LABELS: dict[str, str] = {
    "full": "Full review",
    "simulation": "Simulation review",
    "recurrent": "Recurrent review",
}


def _format_mature_review_lines(
    section: str, review: dict[str, Any]
) -> list[str]:
    """Format one full/simulation/recurrent review summary as bullets."""
    lines = [f"- {section} verdict: {review.get('verdict', 'unknown')}\n"]
    justification = review.get("justification")
    if justification:
        lines.append(f"  Justification: {justification}\n")
    for assumption in review.get("assumptions_likely_false") or []:
        lines.append(f"  Assumption likely false: {assumption}\n")
    decisive_step = review.get("decisive_step")
    if decisive_step:
        lines.append(f"  Decisive step: {decisive_step}\n")
    for point in review.get("failure_points") or []:
        lines.append(f"  Failure point: {point}\n")
    return lines


def _format_mature_reviews_context(
    mature_reviews: dict[str, dict[str, Any]] | None, label: str
) -> str:
    """Format mature-review findings for one hypothesis in ranking prompts.

    A fatal finding here -- a full or recurrent review that rejected the
    idea, or a simulation whose mechanism broke down -- must be able to
    influence the verdict (audit E1), so the judge reads each mature
    review's verdict and its decisive findings.

    Returns an empty string when no mature review has run, leaving the
    prompt unchanged before the first mature Reflection cascade.

    Args:
        mature_reviews: The ``mature_review_summary`` projection for this
            hypothesis, or None.
        label: The hypothesis label ("A" or "B") for the section header.

    Returns:
        A formatted block with a leading separator, or an empty string.
    """
    if not mature_reviews:
        return ""

    sections = [f"\n\n**Hypothesis {label} Mature Review Findings:**\n"]
    for key, section_label in _MATURE_REVIEW_SECTION_LABELS.items():
        review = mature_reviews.get(key)
        if review:
            sections.extend(_format_mature_review_lines(section_label, review))

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

    return "".join(sections)
