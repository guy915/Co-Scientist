"""Matchup prompt assembly and reflection diagnostics for the ranking node."""

import dataclasses
import logging
from typing import Any

from co_scientist.models import Hypothesis
from co_scientist.prompts import (
    PromptRunContext,
    RankingSide,
    get_ranking_prompt,
)

logger = logging.getLogger(__name__)


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


@dataclasses.dataclass(frozen=True)
class _MatchupSummaries:
    """Per-side review, deep-verification, and reflection-note context."""

    review_a: dict[str, Any] | None
    review_b: dict[str, Any] | None
    deep_verification_a: dict[str, Any] | None
    deep_verification_b: dict[str, Any] | None
    reflection_notes_a: str | None
    reflection_notes_b: str | None


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


def _deep_verification_summary(hypothesis: Hypothesis) -> dict[str, Any] | None:
    """Extracts deep-verification probes for a matchup prompt.

    Thin delegate to Hypothesis.deep_verification_summary(): kept as a
    local name because ranking.py re-exports every ranking_prompt name for
    compatibility (see its import block), so removing the name here would
    break that re-export surface even though the projection itself now
    lives on the model.

    Args:
        hypothesis: Hypothesis to summarize

    Returns:
        Deep-verification summary dict, or None if no probes are present
    """
    return hypothesis.deep_verification_summary()


def _log_reflection_coverage(hypotheses: list[Hypothesis]) -> None:
    """Logs how many hypotheses arrived with reflection notes attached.

    Diagnostic-only bookkeeping: does not affect tournament behavior, only
    the debug logging (helps spot upstream nodes that failed to populate
    reflection_notes before ranking runs).

    Args:
        hypotheses: All hypotheses entering the ranking tournament.
    """
    hypotheses_with_reflection = sum(
        1 for h in hypotheses if h.reflection_notes
    )
    logger.debug("\n=== ranking tournament debug ===")
    logger.debug("total hypotheses: %s", len(hypotheses))
    logger.debug(
        "hypotheses with reflection notes: %s/%s",
        hypotheses_with_reflection,
        len(hypotheses),
    )

    if hypotheses_with_reflection == 0:
        logger.debug("warning: No hypotheses have reflection notes!")
    elif hypotheses_with_reflection < len(hypotheses):
        logger.debug("warning: Some hypotheses missing reflection notes")
    else:
        logger.debug("all hypotheses have reflection notes")


def _log_reflection_debug(label: str, reflection_notes: str | None) -> None:
    """Logs reflection-note availability for one side of a matchup.

    Args:
        label: Display label for the hypothesis ("A" or "B")
        reflection_notes: Reflection notes for that hypothesis, if any
    """
    if not reflection_notes:
        logger.debug("hypothesis %s: missing reflection notes", label)
        return
    # Extract classification from notes
    classification = "unknown"
    if "Classification:" in reflection_notes:
        classification = (
            reflection_notes.split("Classification:")[-1].strip().split("\n")[0]
        )
    logger.debug(
        "hypothesis %s: has reflection (%s chars, classification: %s)",
        label,
        len(reflection_notes),
        classification,
    )
    logger.debug(
        "hypothesis %s reflection: %s...", label, reflection_notes[:200]
    )


def _gather_matchup_summaries(
    hypothesis_a: Hypothesis, hypothesis_b: Hypothesis
) -> tuple[
    dict[str, Any] | None,
    dict[str, Any] | None,
    dict[str, Any] | None,
    dict[str, Any] | None,
]:
    """Extracts review and deep-verification summaries for both sides.

    Deep-verification probes are only populated after the first tournament,
    once the deep_verification node has run on the leaders.

    Args:
        hypothesis_a: First hypothesis.
        hypothesis_b: Second hypothesis.

    Returns:
        Tuple of (review_a, review_b, deep_verification_a,
        deep_verification_b).
    """
    return (
        _review_summary(hypothesis_a),
        _review_summary(hypothesis_b),
        _deep_verification_summary(hypothesis_a),
        _deep_verification_summary(hypothesis_b),
    )


def _warn_if_reflection_notes_dropped(
    prompt: str, reflection_notes_a: str | None, reflection_notes_b: str | None
) -> None:
    """Confirms reflection notes made it into the rendered prompt text.

    Catches silent template regressions where a variable stops being
    interpolated.

    Args:
        prompt: Rendered ranking-matchup prompt.
        reflection_notes_a: Reflection notes for hypothesis A, if any.
        reflection_notes_b: Reflection notes for hypothesis B, if any.
    """
    if not (reflection_notes_a or reflection_notes_b):
        return
    if "Reflection Notes" in prompt:
        logger.debug("prompt includes 'Reflection Notes' section")
    else:
        logger.debug(
            "warning: Reflection notes provided but not found in prompt"
        )


def _log_matchup_reflection_notes(
    hypothesis_a: Hypothesis, hypothesis_b: Hypothesis
) -> tuple[str | None, str | None]:
    """Extracts reflection notes for both sides and logs their availability."""
    reflection_notes_a = hypothesis_a.reflection_notes
    reflection_notes_b = hypothesis_b.reflection_notes
    logger.debug("\n→ Ranking Tournament Matchup")
    _log_reflection_debug("A", reflection_notes_a)
    _log_reflection_debug("B", reflection_notes_b)
    return reflection_notes_a, reflection_notes_b


def _render_matchup_prompt(
    hypothesis_a: Hypothesis,
    hypothesis_b: Hypothesis,
    context: _MatchupPromptContext,
    summaries: _MatchupSummaries,
) -> tuple[str, dict[str, Any] | None]:
    """Renders the ranking-matchup prompt template with gathered context."""
    return get_ranking_prompt(
        research_goal=context.research_goal,
        side_a=RankingSide(
            text=hypothesis_a.text,
            review=summaries.review_a,
            reflection_notes=summaries.reflection_notes_a,
            deep_verification=summaries.deep_verification_a,
        ),
        side_b=RankingSide(
            text=hypothesis_b.text,
            review=summaries.review_b,
            reflection_notes=summaries.reflection_notes_b,
            deep_verification=summaries.deep_verification_b,
        ),
        context=PromptRunContext(
            supervisor_guidance=context.supervisor_guidance,
            meta_review=context.meta_review,
            tool_registry=context.tool_registry,
            run_setup_guidance=context.run_setup_guidance,
            run_focus_guidance=context.run_focus_guidance,
        ),
    )


def _gather_matchup_side_summaries(
    hypothesis_a: Hypothesis, hypothesis_b: Hypothesis
) -> _MatchupSummaries:
    """Bundles review, deep-verification, and reflection-note context."""
    review_a, review_b, deep_verification_a, deep_verification_b = (
        _gather_matchup_summaries(hypothesis_a, hypothesis_b)
    )
    reflection_notes_a, reflection_notes_b = _log_matchup_reflection_notes(
        hypothesis_a, hypothesis_b
    )
    return _MatchupSummaries(
        review_a=review_a,
        review_b=review_b,
        deep_verification_a=deep_verification_a,
        deep_verification_b=deep_verification_b,
        reflection_notes_a=reflection_notes_a,
        reflection_notes_b=reflection_notes_b,
    )


def _assemble_matchup_prompt(
    hypothesis_a: Hypothesis,
    hypothesis_b: Hypothesis,
    context: _MatchupPromptContext,
) -> tuple[str, dict[str, Any] | None, str | None, str | None]:
    """Gathers summaries and reflection notes, then renders the prompt."""
    summaries = _gather_matchup_side_summaries(hypothesis_a, hypothesis_b)

    prompt, schema = _render_matchup_prompt(
        hypothesis_a, hypothesis_b, context, summaries
    )
    _warn_if_reflection_notes_dropped(
        prompt, summaries.reflection_notes_a, summaries.reflection_notes_b
    )
    return (
        prompt,
        schema,
        summaries.reflection_notes_a,
        summaries.reflection_notes_b,
    )


def _build_matchup_prompt(
    hypothesis_a: Hypothesis,
    hypothesis_b: Hypothesis,
    context: _MatchupPromptContext,
) -> tuple[str, dict[str, Any] | None, str | None, str | None]:
    """Assembles the ranking-matchup prompt (and schema) for one pairing.

    Args:
        hypothesis_a: First hypothesis.
        hypothesis_b: Second hypothesis.
        context: Run-level context threaded into the prompt (research goal,
            guidance, meta-review, tool registry).

    Returns:
        Tuple of (prompt, schema, reflection_notes_a, reflection_notes_b).
    """
    return _assemble_matchup_prompt(hypothesis_a, hypothesis_b, context)
