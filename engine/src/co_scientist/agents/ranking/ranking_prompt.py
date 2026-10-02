"""Matchup prompt assembly for the ranking node."""

import dataclasses
from typing import Any

from co_scientist.agents.reflection.mature_reviews import (
    mature_review_summary,
)
from co_scientist.models import Hypothesis
from co_scientist.prompts import (
    PromptRunContext,
    RankingSide,
    get_ranking_prompt,
)


@dataclasses.dataclass(frozen=True)
class _MatchupPromptContext:
    """Run-level context shared by every ranking-matchup prompt.

    These are set earlier in the workflow and threaded unchanged into each
    pairing, independent of which two hypotheses are being compared.
    """

    research_goal: str
    supervisor_guidance: dict[str, Any] | None = None
    meta_review: dict[str, Any] | None = None
    tool_registry: Any | None = None
    run_setup_guidance: str | None = None
    run_focus_guidance: str | None = None
    criteria: list[str] | None = None
    preferences: str | None = None
    # Which published prompt this matchup renders: ranking-05's
    # simulated scientific debate for a top-ranked multi-turn matchup,
    # ranking-04's single-shot comparison otherwise.
    debate: bool = False


def _review_summary(hypothesis: Hypothesis) -> dict[str, Any] | None:
    """Extracts the latest review's scores for a matchup prompt.

    Narrower than Hypothesis.review_summary(): the judge only needs the
    numeric scores, and this is the run's highest-volume call (O(n^2) per
    cycle), so the narrative fields are dropped to keep each prompt terse.

    Args:
        hypothesis: Hypothesis to summarize

    Returns:
        Review summary dict, or None if the hypothesis has no reviews
    """
    summary = hypothesis.review_summary()
    if summary is None:
        return None
    return {
        "scores": summary["scores"],
        "overall_score": summary["overall_score"],
    }


def _ranking_side(hypothesis: Hypothesis) -> RankingSide:
    """Project one idea's review and evidence into the judge's input."""
    return RankingSide(
        text=hypothesis.text,
        review=_review_summary(hypothesis),
        reflection_notes=hypothesis.reflection_notes,
        deep_verification=hypothesis.deep_verification_summary(),
        mature_reviews=mature_review_summary(hypothesis.enrichments),
    )


def _build_matchup_prompt(
    hypothesis_a: Hypothesis,
    hypothesis_b: Hypothesis,
    context: _MatchupPromptContext,
) -> tuple[str, dict[str, Any] | None, str | None, str | None]:
    """Render the comparison prompt with each idea's actual review evidence."""
    prompt, schema = get_ranking_prompt(
        research_goal=context.research_goal,
        side_a=_ranking_side(hypothesis_a),
        side_b=_ranking_side(hypothesis_b),
        context=PromptRunContext(
            supervisor_guidance=context.supervisor_guidance,
            meta_review=context.meta_review,
            tool_registry=context.tool_registry,
            run_setup_guidance=context.run_setup_guidance,
            run_focus_guidance=context.run_focus_guidance,
            preferences=context.preferences,
            criteria=context.criteria,
        ),
        debate=context.debate,
    )
    return (
        prompt,
        schema,
        hypothesis_a.reflection_notes,
        hypothesis_b.reflection_notes,
    )
