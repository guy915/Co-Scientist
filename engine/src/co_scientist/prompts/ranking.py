"""Prompt builders for the ranking/tournament and proximity nodes.

The tournament judge has two published prompts, and they are two
templates here. ``ranking_pairwise.md`` is Figure A.4 -- a single expert
evaluator comparing two hypotheses in one shot, used for lower-ranked
matchups. ``ranking_debate.md`` is Figure A.5 -- a panel of domain
experts running the published multi-turn debate procedure, used for
top-ranked matchups. They shared one template until the prompt-fidelity
audit, which put A.5's panel framing in front of every single-shot A.4
comparison and left A.5's own debate procedure with nowhere to render.
"""

from typing import Any

from co_scientist.prompts._common import (
    PromptRunContext,
    PromptSections,
    _format_bullet_section,
    _format_meta_review_context,
    _run_guidance_section,
)
from co_scientist.prompts.generation_draft import format_preferences
from co_scientist.prompts.loading import _build_prompt, _get_domain_variables
from co_scientist.prompts.ranking_sides import (
    RankingSide as RankingSide,
)
from co_scientist.prompts.ranking_sides import (
    format_side_review,
)

# Governing-criteria section for the judge (finding A2/K4). The review
# stage always scores its fixed eight axes (schemas/review.py) and this
# section does not change them; it sits under the published
# "Evaluation criteria:" / "Criteria for hypothesis superiority:" label,
# beside the {preferences} slot, and tells the judge how the scientist's
# own criteria map onto the verdict when they were supplied:
#
# - Each criterion governs the verdict directly -- the comparison fields
#   of the judgment schema stay the published five evaluation aspects
#   (the schema is static), but the judge is told to decide by the
#   scientist's criteria first.
# - Where a criterion overlaps one of those aspects or a review score
#   axis (e.g. a resource criterion with desirability for implementation,
#   a specificity criterion with sufficiency of detail), the scientist's
#   framing of that axis weighs heaviest.
# Absent criteria render nothing and the judge keeps the published five.
_CRITERIA_PREAMBLE = (
    "**Scientist Evaluation Criteria (governing)**\n"
    "The scientist who commissioned this research specified what matters "
    "most for this goal. Treat these criteria as the governing standard "
    "of your verdict: decide the comparison by them first, and where one "
    "overlaps an evaluation aspect or review score axis (for example a "
    "resource criterion with desirability for implementation, or a "
    "specificity criterion with sufficiency of detail), let the "
    "scientist's framing of that axis weigh heaviest:\n"
)

# The published "Considerations:" (A.4) / "Additional notes:" (A.5) slot.
# Everything we thread into the judge that is neither the goal, the
# criteria, the two hypotheses nor their reviews is run context: the
# deployment's domain block, the supervisor's plan, the previous
# iteration's meta-review critique, and the run's setup/focus guidance.
# They render under this one published label instead of four invented
# headings of their own.
_NO_NOTES = "No additional considerations for this comparison.\n"


def _format_ranking_evaluation_criteria(
    criteria: list[str] | None,
) -> str:
    """Format the scientist's evaluation criteria for the ranking judge.

    Renders nothing when no criteria were supplied, leaving the judge on
    the published evaluation aspects alone.
    """
    cleaned = [
        str(item).strip() for item in criteria or [] if str(item).strip()
    ]
    if not cleaned:
        return ""

    sections = ["\n", _CRITERIA_PREAMBLE]
    sections.extend(f"- {item}\n" for item in cleaned)
    return "".join(sections)


# Published ranking-04/ranking-05 both hand the judge a {preferences}
# slot. This is the same published slot evolution resolved onto our
# ``preferences: str`` field (MP-3); ranking reads the same field so the
# two agents cannot diverge on what "preferences" means. It renders bare
# under the published label rather than under a heading of our own, and
# format_preferences emits a default sentence when none was supplied --
# so unlike the criteria section this one always renders.
def _format_ranking_preferences(preferences: str | None) -> str:
    """Format the scientist's stated preferences for the ranking judge."""
    return f"{format_preferences(preferences)}\n"


def _format_ranking_notes(context: PromptRunContext) -> str:
    """Fill the published considerations/notes slot with the run context.

    Each block is stripped and rejoined on one blank line so an absent
    one leaves no spacing behind, and the slot is never empty -- the
    published label always has something under it.
    """
    domain = _get_domain_variables(context.tool_registry)
    blocks = (
        domain["domain_context"],
        domain["domain_review_guidance"],
        _format_supervisor_guidance_for_ranking(context.supervisor_guidance),
        _format_meta_review_context(context.meta_review),
        _run_guidance_section(context),
    )
    present = [block.strip() for block in blocks if block and block.strip()]
    if not present:
        return _NO_NOTES
    return "\n\n".join(present) + "\n"


def _build_ranking_prompt_variables(
    research_goal: str,
    side_a: RankingSide,
    side_b: RankingSide,
    context: PromptRunContext,
) -> dict[str, Any]:
    """Build the template variables for the ranking comparison prompt.

    Args:
        research_goal: The run's research goal.
        side_a: The "A" side of the match, presented as hypothesis 1.
        side_b: The "B" side of the match, presented as hypothesis 2.
        context: Run-scoped prompt context; supplies the preferences and
            criteria slots and everything under the published notes slot.

    Returns:
        Dict of template variables for the ranking prompt.
    """
    return {
        "research_goal": research_goal,
        "hypothesis_a": side_a.text,
        "hypothesis_b": side_b.text,
        # The published per-hypothesis review slot: this side's own
        # scores, reflection analysis, deep-verification probes and
        # mature-review verdicts, composed in prompts/ranking_sides.py.
        "review_1": format_side_review(side_a, "1"),
        "review_2": format_side_review(side_b, "2"),
        # Always produced (empty when absent) so the slot never renders as
        # a {{MISSING:...}} sentinel.
        "evaluation_criteria": _format_ranking_evaluation_criteria(
            context.criteria
        ),
        "preferences": _format_ranking_preferences(context.preferences),
        "notes": _format_ranking_notes(context),
    }


# Renders prompts/ranking_pairwise.md (published A.4) or, for a
# top-ranked multi-turn matchup, prompts/ranking_debate.md (published
# A.5) for each pairwise tournament match in agents/ranking/ranking.py.
def get_ranking_prompt(
    research_goal: str,
    side_a: RankingSide,
    side_b: RankingSide,
    context: PromptRunContext | None = None,
    *,
    debate: bool = False,
) -> tuple[str, dict[str, Any] | None]:
    """Get the ranking (and tournament) comparison prompt and schema.

    Args:
        research_goal: The run's research goal.
        side_a: The "A" side of the match, presented as hypothesis 1.
        side_b: The "B" side of the match, presented as hypothesis 2.
        context: Run-scoped prompt context (supervisor guidance,
            meta-review, tool registry, run setup/focus guidance, and the
            scientist's preferences and evaluation criteria -- the latter
            govern the judge's verdict when present, finding A2/K4).
        debate: True for a top-ranked multi-turn matchup, which renders
            published ranking-05's simulated-debate prompt; False for a
            lower-ranked single-shot comparison, which renders published
            ranking-04's.

    Returns:
        Tuple of (rendered prompt string, JSON schema dict or None).

    Note:
        The scientist's preferences and criteria ride ``context`` rather
        than parameters of their own: published ranking-04/05 surface a
        ``{preferences}`` slot to the judge (MP-6), and both describe the
        run rather than this match.
    """
    ctx = context or PromptRunContext()
    return _build_prompt(
        "ranking_debate" if debate else "ranking_pairwise",
        _build_ranking_prompt_variables(research_goal, side_a, side_b, ctx),
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
