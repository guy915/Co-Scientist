"""Applying evolution LLM responses and building the evolve state delta."""

import logging
from typing import Any

from co_scientist.constants import (
    DUPLICATE_SIMILARITY_THRESHOLD,
    INITIAL_ELO_RATING,
)
from co_scientist.models import (
    Hypothesis,
    HypothesisOrigin,
    create_metrics_update,
    phase_message,
)
from co_scientist.nodes.evolve_context import _find_most_similar
from co_scientist.state import AppendHypotheses

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


def _build_evolution_child(
    parent: Hypothesis,
    refined_text: str,
    explanation: str | None,
    experiment: str | None,
    creation_iteration: int | None,
) -> Hypothesis:
    """Construct an immutable evolution child from an accepted refinement.

    Paper invariant (SSR §4, §12; TE §5): the Evolution agent *generates a new
    hypothesis*; it never modifies or replaces its parent. The child therefore
    gets a fresh id, points at its parent, increments the generation depth,
    resets Elo to the initial rating with zero matches, and starts with no
    reviews or deep-verification state so it must be reviewed before it can be
    ranked. The parent object is not touched.

    Args:
        parent: The hypothesis being evolved; left byte-for-byte unchanged.
        refined_text: Accepted refined hypothesis text for the child.
        explanation: Refined explanation for the child.
        experiment: Refined experiment for the child.
        creation_iteration: Workflow iteration that produced the child.

    Returns:
        A new child ``Hypothesis`` linked to ``parent``.
    """
    return Hypothesis(
        text=refined_text,
        parent_id=parent.id,
        generation=parent.generation + 1,
        origin=HypothesisOrigin.EVOLUTION,
        creation_iteration=creation_iteration,
        category=parent.category,
        explanation=explanation,
        experiment=experiment,
        # Inherit grounding context, but not competition state.
        literature_grounding=parent.literature_grounding,
        citation_map=dict(parent.citation_map),
        # Fresh tournament entrant: Elo 1200, zero matches, unreviewed.
        elo_rating=INITIAL_ELO_RATING,
        win_count=0,
        loss_count=0,
        reviews=[],
        # evolution_history records the derivation chain without mutating the
        # parent: the parent's prior texts plus the parent's own text.
        evolution_history=[*parent.evolution_history, parent.text],
    )


def _apply_refined_hypothesis(
    hypothesis: Hypothesis,
    refined_text: str,
    explanation: str | None,
    experiment: str | None,
    refinement_summary: str,
    max_similarity: float,
    creation_iteration: int | None = None,
) -> tuple[Hypothesis, dict[str, Any]]:
    """Builds an immutable child for an accepted refinement and its detail.

    Args:
        hypothesis: Parent hypothesis being evolved; NOT mutated.
        refined_text: Accepted refined hypothesis text.
        explanation: Refined explanation.
        experiment: Refined experiment.
        refinement_summary: LLM's summary of what changed and why.
        max_similarity: Max similarity to the sampled peer hypotheses, for
            the debug log.
        creation_iteration: Workflow iteration that produced the child.

    Returns:
        The new child hypothesis, and its evolution detail.
    """
    child = _build_evolution_child(
        hypothesis,
        refined_text,
        explanation,
        experiment,
        creation_iteration,
    )

    logger.debug(
        "evolved hypothesis into child %s (max similarity: %.2f)",
        child.id,
        max_similarity,
    )

    # evolution_detail feeds evolution_details in evolve_node's state delta
    # below, which the UI surfaces as the rationale for each change. It now
    # records both parent and child ids so the lineage edge is explicit.
    evolution_detail = {
        "parent_id": hypothesis.id,
        "child_id": child.id,
        "original": hypothesis.text,
        "evolved": refined_text,
        "rationale": refinement_summary,
    }

    return child, evolution_detail


def _apply_evolution_result(
    hypothesis: Hypothesis,
    response: dict[str, Any],
    other_hypotheses_texts: list[str],
    creation_iteration: int | None = None,
) -> tuple[Hypothesis | None, dict[str, Any] | None]:
    """Turns an LLM evolution response into a child hypothesis, if acceptable.

    Rejects the refinement (creating NO child) if the LLM echoed the input
    back verbatim, or if the refined text converged too closely onto one of
    the peer hypotheses shown as diversity context. A rejected evolution is a
    genuine no-op: the parent stays unchanged and no fake child is minted
    (PLAN.md M1.2).

    Args:
        hypothesis: Parent hypothesis being evolved; never mutated.
        response: Parsed JSON response from the evolution LLM call.
        other_hypotheses_texts: Strategically sampled subset of other
            hypotheses (max 15), used for the similarity check.
        creation_iteration: Workflow iteration that produced any child.

    Returns:
        A ``(child, detail)`` pair on acceptance, or ``(None, None)`` when the
        refinement is rejected (no child created).
    """
    refined_text, explanation, experiment, refinement_summary = (
        _extract_evolution_fields(hypothesis, response)
    )

    # Check if the refinement actually changed the text.
    # The LLM sometimes echoes the input back verbatim (e.g. it judges no
    # refinement is warranted); treat this as a no-op that creates no child
    # rather than minting a duplicate of the parent.
    if refined_text == hypothesis.text:
        logger.warning("Evolution returned unchanged hypothesis; no child")
        return None, None

    # Check similarity to other hypotheses
    max_similarity, most_similar_text = _find_most_similar(
        refined_text, other_hypotheses_texts
    )

    # If too similar to a peer, create no child.
    # DUPLICATE_SIMILARITY_THRESHOLD (0.95) is the same bound proximity.py
    # uses for its high-similarity duplicate clusters; crossing it here
    # means the refinement converged onto a peer, so the evolution is
    # rejected and no child is minted.
    if max_similarity > DUPLICATE_SIMILARITY_THRESHOLD:
        logger.warning(
            "Evolution created near-duplicate! Similarity: %.2f."
            " Creating no child.",
            max_similarity,
        )
        logger.debug("original: %s...", hypothesis.text[:100])
        assert most_similar_text is not None
        logger.debug("similar to: %s...", most_similar_text[:100])
        return None, None

    return _apply_refined_hypothesis(
        hypothesis,
        refined_text,
        explanation,
        experiment,
        refinement_summary,
        max_similarity,
        creation_iteration,
    )


def _collect_evolution_results(
    results: list[tuple[Hypothesis | None, dict[str, Any] | None]],
) -> tuple[list[Hypothesis], list[dict[str, Any]]]:
    """Unpacks gathered evolution results into children and details.

    Args:
        results: Per-attempt (child or None, evolution_detail or None) pairs,
            in the same order as the dispatched evolution tasks.

    Returns:
        Tuple of (evolution children, evolution details). A rejected
        refinement contributes neither a child nor a detail, so producing a
        child cannot accidentally resurrect or duplicate a parent.
    """
    children: list[Hypothesis] = []
    evolution_details: list[dict[str, Any]] = []

    for child, detail in results:
        # child/detail are both None when evolve_single_hypothesis rejected
        # the refinement (unchanged text or near-duplicate): no child is
        # minted and nothing is recorded.
        if child is not None:
            children.append(child)
        if detail is not None:
            evolution_details.append(detail)

    return children, evolution_details


def _build_evolve_state_delta(
    children: list[Hypothesis],
    evolution_details: list[dict[str, Any]],
    attempt_count: int,
) -> dict[str, Any]:
    """Builds the evolve_node state delta: metrics update plus payload.

    Args:
        children: New evolution children produced this round.
        evolution_details: Evolution detail entries, one per created child.
        attempt_count: Number of parents evolution attempted this round (one
            LLM call each), used for the llm_calls metric.

    Returns:
        The evolve_node state delta dictionary.
    """
    # llm_calls counts every attempt (one LLM call per parent, regardless of
    # accept/reject); evolutions_count counts children actually created.
    metrics = create_metrics_update(
        llm_calls_delta=attempt_count,
        evolutions_count_delta=len(children),
    )
    logger.debug(
        "evolve node creating metrics delta: children=%s, llm_calls=%s",
        len(children),
        attempt_count,
    )

    # AppendHypotheses tells the reducer to ADD these children to the pool
    # rather than replace it: parents (and every other hypothesis) stay in the
    # active pool and both parent and child compete in the next tournament
    # (paper invariant SSR §4, §12).
    return {
        "hypotheses": AppendHypotheses(children),
        "evolution_details": evolution_details,
        "metrics": metrics,
        "messages": phase_message(
            "evolve",
            f"Evolved {len(children)} new child hypotheses",
            evolved_count=len(children),
        ),
    }
