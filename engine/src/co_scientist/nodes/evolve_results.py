"""Applying evolution LLM responses and building the evolve state delta."""

import logging
from typing import Any

from co_scientist.constants import DUPLICATE_SIMILARITY_THRESHOLD
from co_scientist.models import (
    Hypothesis,
    create_metrics_update,
    phase_message,
)
from co_scientist.nodes.evolve_context import _find_most_similar

logger = logging.getLogger(__name__)


def _extract_evolution_fields(
    hypothesis: Hypothesis, response: dict[str, Any]
) -> tuple[str, str | None, str | None, str]:
    """Extracts the refined fields from an evolution LLM response.

    Args:
        hypothesis: Hypothesis being evolved; supplies fallback values for
            fields the response omits.
        response: Parsed JSON response from the evolution LLM call.

    Returns:
        Tuple of (refined_text, explanation, experiment,
        refinement_summary).
    """
    # Prefer the canonical "hypothesis" key; fall back to the legacy
    # "refined_hypothesis_text" name, and finally to the pre-evolution text
    # if the LLM response omits both (defensive against malformed output).
    refined_text = response.get("hypothesis") or response.get(
        "refined_hypothesis_text", hypothesis.text
    )
    explanation = response.get("explanation", hypothesis.explanation)
    experiment = response.get("experiment", hypothesis.experiment)
    refinement_summary = response.get(
        "refinement_summary", "no refinement summary provided"
    )
    return refined_text, explanation, experiment, refinement_summary


def _apply_refined_hypothesis(
    hypothesis: Hypothesis,
    refined_text: str,
    explanation: str | None,
    experiment: str | None,
    refinement_summary: str,
    max_similarity: float,
) -> tuple[Hypothesis, dict[str, Any]]:
    """Mutates an accepted refinement onto a hypothesis and logs/details it.

    Args:
        hypothesis: Hypothesis being evolved; mutated in place.
        refined_text: Accepted refined hypothesis text.
        explanation: Refined explanation.
        experiment: Refined experiment.
        refinement_summary: LLM's summary of what changed and why.
        max_similarity: Max similarity to the sampled peer hypotheses, for
            the debug log.

    Returns:
        Updated hypothesis with evolved text, and its evolution detail.
    """
    # Mutates the same Hypothesis object in place (its stable uuid `id` is
    # unaffected, since it is excluded from equality) rather than
    # constructing a new one.
    original_text = hypothesis.text
    hypothesis.text = refined_text
    hypothesis.explanation = explanation
    hypothesis.experiment = experiment
    # Record the pre-evolution text so evolution_history accumulates the
    # lineage of prior phrasings for this hypothesis.
    hypothesis.evolution_history.append(original_text)
    # The text changed materially, so any prior deep-verification probes now
    # describe stale text. Clear them so the next deep_verification pass
    # re-verifies the evolved hypothesis.
    hypothesis.deep_verification_probes = []
    hypothesis.deep_verification_verdict = None

    logger.debug("evolved hypothesis (max similarity: %.2f)", max_similarity)

    # evolution_detail feeds evolution_details in evolve_node's state
    # delta below, which the UI surfaces as the rationale for each change.
    evolution_detail = {
        "original": original_text,
        "evolved": refined_text,
        "rationale": refinement_summary,
    }

    return hypothesis, evolution_detail


def _apply_evolution_result(
    hypothesis: Hypothesis,
    response: dict[str, Any],
    other_hypotheses_texts: list[str],
) -> tuple[Hypothesis, dict[str, Any] | None]:
    """Applies an LLM evolution response to a hypothesis, if acceptable.

    Rejects the refinement (keeping the hypothesis unchanged) if the LLM
    echoed the input back verbatim, or if the refined text converged too
    closely onto one of the peer hypotheses shown as diversity context.

    Args:
        hypothesis: Hypothesis being evolved; mutated in place on success.
        response: Parsed JSON response from the evolution LLM call.
        other_hypotheses_texts: Strategically sampled subset of other
            hypotheses (max 15), used for the similarity check.

    Returns:
        Updated hypothesis with evolved text, and evolution detail (or
        None if the refinement was rejected).
    """
    refined_text, explanation, experiment, refinement_summary = (
        _extract_evolution_fields(hypothesis, response)
    )

    # Check if hypothesis actually changed
    # The LLM sometimes echoes the input back verbatim (e.g. it judges no
    # refinement is warranted); treat this as a no-op rather than
    # recording a spurious evolution_detail entry for identical text.
    if refined_text == hypothesis.text:
        logger.warning("Evolution returned unchanged hypothesis")
        return hypothesis, None  # Keep original, no evolution details

    # Check similarity to other hypotheses
    max_similarity, most_similar_text = _find_most_similar(
        refined_text, other_hypotheses_texts
    )

    # If too similar, keep original
    # DUPLICATE_SIMILARITY_THRESHOLD (0.95) is the same bound proximity.py
    # uses for its high-similarity duplicate clusters; crossing it here
    # means the refinement converged onto a peer, so the evolution is
    # rejected and the pre-evolution hypothesis is kept unchanged.
    if max_similarity > DUPLICATE_SIMILARITY_THRESHOLD:
        logger.warning(
            "Evolution created near-duplicate! Similarity: %.2f."
            " Keeping original hypothesis.",
            max_similarity,
        )
        logger.debug("original: %s...", hypothesis.text[:100])
        assert most_similar_text is not None
        logger.debug("similar to: %s...", most_similar_text[:100])
        return hypothesis, None  # Keep original, no evolution details

    return _apply_refined_hypothesis(
        hypothesis,
        refined_text,
        explanation,
        experiment,
        refinement_summary,
        max_similarity,
    )


def _collect_evolution_results(
    results: list[tuple[Hypothesis, dict[str, Any] | None]],
) -> tuple[list[Hypothesis], list[dict[str, Any]]]:
    """Unpacks gathered evolution results into hypotheses and details.

    Args:
        results: Per-hypothesis (hypothesis, evolution_detail or None)
            pairs, in the same order as the dispatched evolution tasks.

    Returns:
        Tuple of (evolved hypotheses, evolution details); evolution_details
        only includes entries for hypotheses that actually changed.
    """
    evolved_hypotheses = []
    evolution_details = []

    for hyp, detail in results:
        evolved_hypotheses.append(hyp)
        # detail is None when evolve_single_hypothesis rejected the
        # refinement (unchanged text or near-duplicate); only genuine
        # changes are recorded in evolution_details.
        if detail is not None:  # Only add if hypothesis actually evolved
            evolution_details.append(detail)

    return evolved_hypotheses, evolution_details


def _build_evolve_state_delta(
    evolved_hypotheses: list[Hypothesis],
    evolution_details: list[dict[str, Any]],
) -> dict[str, Any]:
    """Builds the evolve_node state delta: metrics update plus payload.

    Args:
        evolved_hypotheses: Hypotheses returned by this round's evolution.
        evolution_details: Evolution detail entries for hypotheses that
            actually changed.

    Returns:
        The evolve_node state delta dictionary.
    """
    # Update metrics (deltas only, merge_metrics will add to existing state)
    # Both deltas count every hypothesis attempted, not just those whose
    # evolution was accepted: evolve_single_hypothesis always calls the
    # LLM once before deciding whether to keep the refinement.
    metrics = create_metrics_update(
        llm_calls_delta=len(evolved_hypotheses),
        evolutions_count_delta=len(evolved_hypotheses),
    )
    logger.debug(
        "evolve node creating metrics delta: evolutions=%s, llm_calls=%s",
        len(evolved_hypotheses),
        len(evolved_hypotheses),
    )

    # deduplicate_hypotheses (state.py) recognizes this as a replacement
    # because every returned hypothesis id already exists in state, so the
    # pool reliably shrinks to just the evolved list even when evolution
    # rewrote every text.
    return {
        "hypotheses": evolved_hypotheses,
        "evolution_details": evolution_details,
        "metrics": metrics,
        "messages": phase_message(
            "evolve",
            f"Evolved {len(evolved_hypotheses)} hypotheses",
            evolved_count=len(evolved_hypotheses),
        ),
    }
