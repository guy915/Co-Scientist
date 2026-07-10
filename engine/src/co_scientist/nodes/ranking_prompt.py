"""Matchup prompt assembly and reflection diagnostics for the ranking node."""

import logging
from typing import Any

from co_scientist.models import Hypothesis
from co_scientist.prompts import get_ranking_prompt

logger = logging.getLogger(__name__)


def _review_summary(hypothesis: Hypothesis) -> dict[str, Any] | None:
    """Extracts the latest review scores for a matchup prompt.

    Args:
        hypothesis: Hypothesis to summarize

    Returns:
        Review summary dict, or None if the hypothesis has no reviews
    """
    if not hypothesis.reviews:
        return None
    latest_review = hypothesis.reviews[-1]
    return {
        "scores": latest_review.scores,
        "overall_score": latest_review.overall_score,
    }


def _deep_verification_summary(hypothesis: Hypothesis) -> dict[str, Any] | None:
    """Extracts deep-verification probes for a matchup prompt.

    Args:
        hypothesis: Hypothesis to summarize

    Returns:
        Deep-verification summary dict, or None if no probes are present
    """
    if not hypothesis.deep_verification_probes:
        return None
    return {
        "probes": hypothesis.deep_verification_probes,
        "verdict": hypothesis.deep_verification_verdict,
    }


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


def _build_matchup_prompt(
    hypothesis_a: Hypothesis,
    hypothesis_b: Hypothesis,
    research_goal: str,
    supervisor_guidance: dict[str, Any] | None,
    meta_review: dict[str, Any] | None,
    tool_registry: Any | None,
    run_setup_guidance: str | None,
    run_focus_guidance: str | None,
) -> tuple[str, dict[str, Any] | None, str | None, str | None]:
    """Assembles the ranking-matchup prompt (and schema) for one pairing.

    Args:
        hypothesis_a: First hypothesis.
        hypothesis_b: Second hypothesis.
        research_goal: Research goal for context.
        supervisor_guidance: Optional planning guidance from the supervisor.
        meta_review: Optional cross-iteration meta-review feedback.
        tool_registry: Optional ToolRegistry for dynamic tool instructions.
        run_setup_guidance: Optional run-setup guidance for the prompt.
        run_focus_guidance: Optional run-focus guidance for the prompt.

    Returns:
        Tuple of (prompt, schema, reflection_notes_a, reflection_notes_b);
        the reflection notes are returned alongside the prompt so the
        caller can fold them into the LLM-call metadata without
        re-reading the hypotheses.
    """
    review_a, review_b, deep_verification_a, deep_verification_b = (
        _gather_matchup_summaries(hypothesis_a, hypothesis_b)
    )

    reflection_notes_a = hypothesis_a.reflection_notes
    reflection_notes_b = hypothesis_b.reflection_notes

    logger.debug("\n→ Ranking Tournament Matchup")
    _log_reflection_debug("A", reflection_notes_a)
    _log_reflection_debug("B", reflection_notes_b)

    prompt, schema = get_ranking_prompt(
        research_goal=research_goal,
        hypothesis_a=hypothesis_a.text,
        hypothesis_b=hypothesis_b.text,
        supervisor_guidance=supervisor_guidance,
        review_a=review_a,
        review_b=review_b,
        reflection_notes_a=reflection_notes_a,
        reflection_notes_b=reflection_notes_b,
        deep_verification_a=deep_verification_a,
        deep_verification_b=deep_verification_b,
        meta_review=meta_review,
        tool_registry=tool_registry,
        run_setup_guidance=run_setup_guidance,
        run_focus_guidance=run_focus_guidance,
    )

    _warn_if_reflection_notes_dropped(
        prompt, reflection_notes_a, reflection_notes_b
    )

    return prompt, schema, reflection_notes_a, reflection_notes_b
