"""Evolve node - refine top hypotheses with context-aware evolution."""
# pylint: disable=inconsistent-quotes

import asyncio
import json
import logging
import random
from typing import Any, Coroutine

from co_scientist.constants import (
    EXTENDED_MAX_TOKENS,
    HIGH_TEMPERATURE,
    DUPLICATE_SIMILARITY_THRESHOLD,
    EVOLVE_TOKENS_PER_CONTEXT_HYPOTHESIS,
    EVOLVE_MAX_TOKENS_CAP,
    PROGRESS_EVOLVE_START,
    PROGRESS_EVOLVE_COMPLETE,
    scaled_max_tokens,
)
from co_scientist.llm import call_llm_json
from co_scientist.models import (Hypothesis, create_metrics_update,
                                 phase_message, rank_by_elo)
from co_scientist.nodes.progress import emit_progress
from co_scientist.prompts import load_prompt_with_schema
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


def _hypothesis_texts(hypotheses: list[Hypothesis]) -> list[str]:
    """Extract the .text field from a list of hypotheses."""
    return [h.text for h in hypotheses]


def _sample_up_to(pool: list[Hypothesis], count: int) -> list[Hypothesis]:
    """Randomly sample up to count items from pool (all of it if smaller).

    No-op (returns []) on an empty pool, matching the caller's original
    `... if pool else []` short-circuit so no random state is consumed when
    there is nothing to sample from.
    """
    if not pool:
        return []
    return random.sample(pool, min(count, len(pool)))


def sample_context_hypotheses(all_hypotheses: list[Hypothesis],
                              exclude_hypothesis: Hypothesis,
                              max_context: int = 15) -> list[str]:
    """Strategically sample a subset of other hypotheses for evolution context.

    To prevent token explosion with large hypothesis pools, we sample:
    - Top 5 by Elo rating (avoid copying winners)
    - Up to 10 random samples from the rest (diversity check)

    Args:
        all_hypotheses: all hypotheses being evolved
        exclude_hypothesis: the hypothesis being evolved (exclude from context)
        max_context: maximum context hypotheses to include (default 15)

    Returns:
        List of hypothesis texts to use as context
    """
    # Filter out the current hypothesis
    others = [h for h in all_hypotheses if h.text != exclude_hypothesis.text]

    if len(others) <= max_context:
        # Small pool, include all
        return _hypothesis_texts(others)

    # Sort by Elo rating (descending)
    others_sorted = rank_by_elo(others)

    # Take top 5 by Elo (the best ones to avoid copying)
    top_performers = others_sorted[:5]
    remaining = others_sorted[5:]

    # Sample up to 10 more from the rest
    sampled_others = _sample_up_to(remaining, 10)

    # Combine: top 5 + sampled 10 = max 15
    context_hypotheses = top_performers + sampled_others

    logger.debug(
        "sampled %s context hypotheses (top 5 + %s random) from %s total",
        len(context_hypotheses), len(sampled_others), len(others))

    return _hypothesis_texts(context_hypotheses)


def calculate_text_similarity(text1: str, text2: str) -> float:
    """Calculates simple similarity between two texts.

    This is a basic implementation using word overlap. TODO: For production,
    consider using embeddings or more sophisticated similarity metrics.

    Args:
        text1: First text
        text2: Second text

    Returns:
        Similarity score between 0 and 1
    """
    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())

    # Degenerate case: an empty text has no words to overlap with, so
    # treat it as maximally dissimilar rather than dividing by zero below.
    if not words1 or not words2:
        return 0.0

    # Jaccard similarity: size of the word-set intersection over the
    # word-set union. Cheap and order-insensitive, but purely lexical (no
    # synonym/paraphrase awareness) -- see the TODO above about upgrading
    # to embeddings.
    intersection = words1.intersection(words2)
    union = words1.union(words2)

    return len(intersection) / len(union) if union else 0.0


def _log_truncated_items(label: str, items: list[str]) -> None:
    """Logs a debug header and up to 3 items, each truncated to 100 chars.

    Args:
        label: Human-readable field label (e.g. "common Strengths").
        items: Meta-review items to log.
    """
    if not items:
        return
    logger.debug("%s (%s):", label, len(items))
    for item in items[:3]:  # Show first 3
        logger.debug("- %s%s", item[:100], '...' if len(item) > 100 else '')


def _log_items(label: str, items: list[str]) -> None:
    """Logs a debug header and up to 3 items verbatim.

    Args:
        label: Human-readable field label (e.g. "strategic Recommendations").
        items: Meta-review items to log.
    """
    if not items:
        return
    logger.debug("%s (%s):", label, len(items))
    for item in items[:3]:  # Show first 3
        logger.debug("- %s", item)


def _log_meta_review_debug(meta_review: dict[str, Any]) -> None:
    """Logs meta-review signals used during evolution, for debugging.

    The same fields are also formatted into the prompt itself (see
    _build_meta_review_insights); this only logs them for visibility.

    Args:
        meta_review: Meta-review insights for strategic guidance.
    """
    logger.debug("\n=== evolve single hypothesis ===")
    logger.debug("using meta review for evolution")

    _log_truncated_items("common Strengths",
                         meta_review.get("common_strengths", []))
    _log_truncated_items("common Weaknesses",
                         meta_review.get("common_weaknesses", []))
    _log_items("strategic Recommendations",
               meta_review.get("strategic_recommendations", []))
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
    if not hypothesis.reviews:
        return ""
    latest_review = hypothesis.reviews[-1]
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
            "common_strengths":
                meta_review.get("common_strengths", []),
            "common_weaknesses":
                meta_review.get("common_weaknesses", []),
            "strategic_recommendations":
                meta_review.get("strategic_recommendations", []),
            "emerging_themes":
                meta_review.get("emerging_themes", []),
        },
        indent=2,
    )


def _format_refinement_priorities(
        evolution_phase: dict[str, Any]) -> str | None:
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
        evolution_phase: dict[str, Any]) -> list[str]:
    """Format the non-empty evolution-phase guidance lines."""
    lines = []
    for formatter in (_format_refinement_priorities,
                      _format_iteration_strategy):
        section = formatter(evolution_phase)
        if section:
            lines.append(section)
    return lines


def _build_supervisor_guidance_text(
        supervisor_guidance: dict[str, Any] | None) -> str:
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
    guidance_sections.append("\nUse this guidance to align your refinement"
                             " with the research plan.\n")
    return "".join(guidance_sections)


def _format_diversity_instruction(other_hypotheses_texts: list[str],
                                  removed_duplicates: list[str]) -> str:
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
    # Truncate each listed hypothesis to 200 chars: enough for the LLM to
    # recognize overlap without materially growing the prompt.
    other_hyps_formatted = "\n".join(
        [f"- {text[:200]}..." for text in other_hypotheses_texts])
    # Only the 5 most recently removed duplicates are shown, keeping this
    # section bounded regardless of how many duplicates accumulate over a
    # run.
    removed_dups_formatted = "\n".join(
        [f"- {text[:200]}..." for text in removed_duplicates[-5:]])  # Last 5

    return f"""

## CRITICAL: Preserve Diversity

**Other hypotheses being evolved simultaneously:**
{other_hyps_formatted if other_hyps_formatted else "None"}

**Previously removed duplicates (DO NOT recreate these):**
{removed_dups_formatted if removed_dups_formatted else "None"}

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


def _find_most_similar(
        refined_text: str,
        other_hypotheses_texts: list[str]) -> tuple[float, str | None]:
    """Finds the other hypothesis text most similar to the refined text.

    Guards against evolution converging this hypothesis toward one of the
    peers it was shown as diversity context, using the same word-overlap
    metric as calculate_text_similarity.

    Args:
        refined_text: The newly evolved hypothesis text.
        other_hypotheses_texts: Strategically sampled subset of other
            hypotheses (max 15).

    Returns:
        Tuple of (max_similarity, most_similar_text); most_similar_text is
        None if other_hypotheses_texts is empty.
    """
    max_similarity = 0.0
    most_similar_text = None
    for other_text in other_hypotheses_texts:
        similarity = calculate_text_similarity(refined_text, other_text)
        if similarity > max_similarity:
            max_similarity = similarity
            most_similar_text = other_text
    return max_similarity, most_similar_text


def _build_evolution_variables(
    hypothesis: Hypothesis,
    meta_review: dict[str, Any],
    supervisor_guidance: dict[str, Any] | None,
    articles_with_reasoning: str | None,
    tool_registry: Any | None,
    run_setup_guidance: str | None,
    run_focus_guidance: str | None,
) -> dict[str, Any]:
    """Builds the template variables for the "evolution" prompt.

    Unlike most nodes, evolve has no dedicated get_evolution_prompt()
    wrapper in prompts.py, so _build_evolution_prompt calls
    load_prompt_with_schema directly and this helper pulls in these
    normally-internal helpers itself to build the same
    run-guidance/domain variables the wrappers assemble.

    Args:
        hypothesis: Hypothesis to evolve.
        meta_review: Meta-review insights for strategic guidance.
        supervisor_guidance: Optional supervisor guidance for evolution
            phase.
        articles_with_reasoning: Optional literature review synthesis for
            context.
        tool_registry: Optional ToolRegistry for dynamic tool instructions.
        run_setup_guidance: Optional durable setup guidance.
        run_focus_guidance: Optional selected focus guidance.

    Returns:
        Template variables for the "evolution" prompt.
    """
    from co_scientist.prompts import _format_run_guidance, _get_domain_variables  # pylint: disable=import-outside-toplevel

    variables = {
        "original_hypothesis":
            hypothesis.text,
        "review_feedback":
            _build_review_feedback(hypothesis),
        "meta_review_insights":
            _build_meta_review_insights(meta_review),
        "supervisor_guidance":
            _build_supervisor_guidance_text(supervisor_guidance),
        "run_guidance":
            _format_run_guidance(run_setup_guidance, run_focus_guidance),
        "articles_with_reasoning":
            articles_with_reasoning or "",
    }
    variables.update(_get_domain_variables(tool_registry))
    return variables


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
) -> tuple[str, dict[str, Any] | None]:
    """Assembles the full evolution prompt (and schema) for one hypothesis.

    Args:
        hypothesis: Hypothesis to evolve.
        other_hypotheses_texts: Strategically sampled subset of other
            hypotheses (max 15).
        meta_review: Meta-review insights for strategic guidance.
        removed_duplicates: Previously removed duplicate texts to avoid.
        supervisor_guidance: Optional supervisor guidance for evolution
            phase.
        articles_with_reasoning: Optional literature review synthesis for
            context.
        tool_registry: Optional ToolRegistry for dynamic tool instructions.
        run_setup_guidance: Optional durable setup guidance.
        run_focus_guidance: Optional selected focus guidance.

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
    )

    prompt, schema = load_prompt_with_schema("evolution", variables)

    # Add critical diversity instruction
    diversity_instruction = _format_diversity_instruction(
        other_hypotheses_texts, removed_duplicates)
    full_prompt = prompt + diversity_instruction

    return full_prompt, schema


async def _call_evolution_llm(
    full_prompt: str,
    schema: dict[str, Any] | None,
    other_hypotheses_texts: list[str],
    model_name: str,
    run_id: str | None,
    hypothesis_index: int | None,
) -> dict[str, Any]:
    """Calls the LLM to evolve a hypothesis from a prepared prompt.

    Args:
        full_prompt: The evolution prompt, including the diversity
            instruction.
        schema: JSON schema for the expected LLM response.
        other_hypotheses_texts: Strategically sampled subset of other
            hypotheses (max 15), used only to size the token budget.
        model_name: LLM model to use.
        run_id: Optional run ID for saving prompts.
        hypothesis_index: Optional index for naming saved prompts.

    Returns:
        Parsed JSON response from the LLM.
    """
    # Fixed token budget since we strategically sample max 15 context
    # hypotheses: 8000 base + 15 * 800 = 20,000 tokens at the cap, so the
    # budget is bounded for any pool size.
    evolve_max_tokens = scaled_max_tokens(
        EXTENDED_MAX_TOKENS,
        len(other_hypotheses_texts),
        per_item=EVOLVE_TOKENS_PER_CONTEXT_HYPOTHESIS,
        cap=EVOLVE_MAX_TOKENS_CAP,
    )

    logger.debug("evolution token budget: %s (%s context hypotheses)",
                 evolve_max_tokens, len(other_hypotheses_texts))

    prompt_name = (f"evolve_{hypothesis_index}"
                   if hypothesis_index is not None else "evolve")

    # Call LLM to evolve hypothesis
    return await call_llm_json(
        prompt=full_prompt,
        model_name=model_name,
        max_tokens=evolve_max_tokens,
        temperature=HIGH_TEMPERATURE,
        json_schema=schema,
        max_attempts=7,  # increase retries for evolution (critical node)
        run_id=run_id,
        prompt_name=prompt_name,
        prompt_metadata={
            "hypothesis_index": hypothesis_index,
            "prompt_length_chars": len(full_prompt),
            "context_hypotheses_count": len(other_hypotheses_texts),
        },
    )


def _extract_evolution_fields(
        hypothesis: Hypothesis,
        response: dict[str, Any]) -> tuple[str, str | None, str | None, str]:
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
        "refined_hypothesis_text", hypothesis.text)
    explanation = response.get("explanation", hypothesis.explanation)
    experiment = response.get("experiment", hypothesis.experiment)
    refinement_summary = response.get("refinement_summary",
                                      "no refinement summary provided")
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
        _extract_evolution_fields(hypothesis, response))

    # Check if hypothesis actually changed
    # The LLM sometimes echoes the input back verbatim (e.g. it judges no
    # refinement is warranted); treat this as a no-op rather than
    # recording a spurious evolution_detail entry for identical text.
    if refined_text == hypothesis.text:
        logger.warning("Evolution returned unchanged hypothesis")
        return hypothesis, None  # Keep original, no evolution details

    # Check similarity to other hypotheses
    max_similarity, most_similar_text = _find_most_similar(
        refined_text, other_hypotheses_texts)

    # If too similar, keep original
    # DUPLICATE_SIMILARITY_THRESHOLD (0.95) is the same bound proximity.py
    # uses for its high-similarity duplicate clusters; crossing it here
    # means the refinement converged onto a peer, so the evolution is
    # rejected and the pre-evolution hypothesis is kept unchanged.
    if max_similarity > DUPLICATE_SIMILARITY_THRESHOLD:
        logger.warning(
            "Evolution created near-duplicate! Similarity: %.2f."
            " Keeping original hypothesis.", max_similarity)
        logger.debug("original: %s...", hypothesis.text[:100])
        assert most_similar_text is not None
        logger.debug("similar to: %s...", most_similar_text[:100])
        return hypothesis, None  # Keep original, no evolution details

    return _apply_refined_hypothesis(hypothesis, refined_text, explanation,
                                     experiment, refinement_summary,
                                     max_similarity)


async def evolve_single_hypothesis(
    hypothesis: Hypothesis,
    other_hypotheses_texts: list[str],
    meta_review: dict[str, Any],
    model_name: str,
    removed_duplicates: list[str],
    supervisor_guidance: dict[str, Any] | None = None,
    articles_with_reasoning: str | None = None,
    run_id: str | None = None,
    hypothesis_index: int | None = None,
    tool_registry: Any | None = None,
    run_setup_guidance: str | None = None,
    run_focus_guidance: str | None = None,
) -> tuple[Hypothesis, dict[str, Any] | None]:
    """Evolve a single hypothesis with strategically sampled context.

    This is the CRITICAL anti-duplicate strategy: we pass a subset of other
    hypotheses (top 5 by Elo + random samples) so the LLM knows what to
    avoid while keeping token budget manageable for large hypothesis pools.

    Args:
        hypothesis: Hypothesis to evolve
        other_hypotheses_texts: Strategically sampled subset of other
            hypotheses (max 15)
        meta_review: Meta-review insights for strategic guidance
        model_name: LLM model to use
        removed_duplicates: Previously removed duplicate texts to avoid
        supervisor_guidance: Optional supervisor guidance for evolution phase
        articles_with_reasoning: Optional literature review synthesis
            for context
        run_id: Optional run ID for saving prompts
        hypothesis_index: Optional index for naming saved prompts
        tool_registry: Optional ToolRegistry for dynamic tool instructions
        run_setup_guidance: Optional durable setup guidance
        run_focus_guidance: Optional selected focus guidance

    Returns:
        Updated hypothesis with evolved text
    """
    # The following call only logs meta-review signals (common
    # strengths/weaknesses, strategic recommendations, emerging themes)
    # for debugging; the same fields are formatted into the prompt itself
    # further below via _build_meta_review_insights.
    _log_meta_review_debug(meta_review)

    full_prompt, schema = _build_evolution_prompt(
        hypothesis=hypothesis,
        other_hypotheses_texts=other_hypotheses_texts,
        meta_review=meta_review,
        removed_duplicates=removed_duplicates,
        supervisor_guidance=supervisor_guidance,
        articles_with_reasoning=articles_with_reasoning,
        tool_registry=tool_registry,
        run_setup_guidance=run_setup_guidance,
        run_focus_guidance=run_focus_guidance,
    )

    response = await _call_evolution_llm(
        full_prompt=full_prompt,
        schema=schema,
        other_hypotheses_texts=other_hypotheses_texts,
        model_name=model_name,
        run_id=run_id,
        hypothesis_index=hypothesis_index,
    )

    return _apply_evolution_result(hypothesis, response, other_hypotheses_texts)


def _collect_evolution_results(
    results: list[tuple[Hypothesis, dict[str, Any] | None]]
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


def _select_evolution_pool(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
) -> tuple[int, list[Hypothesis]]:
    """Determines how many hypotheses to evolve and selects the top-k pool.

    Args:
        state: Current workflow state.
        hypotheses: Hypothesis pool entering evolution; assumed already
            sorted by descending Elo rating (set by ranking_node).

    Returns:
        Tuple of (actual number of hypotheses to evolve, top_k hypotheses
        to evolve).
    """
    evolution_max_count = state.get("evolution_max_count", 10)

    # Calculate actual number to evolve (may be less than max if fewer
    # hypotheses available)
    # evolution_max_count doubles as the size of the pool going forward
    # (see "Keep ONLY the evolved hypotheses" in _finalize_evolve_result),
    # so clamp it to the available count rather than evolving hypotheses
    # that do not exist.
    actual_count = min(len(hypotheses), evolution_max_count)

    # Get top-k hypotheses
    # hypotheses arrives already sorted by descending Elo rating (set by
    # ranking_node's return), so a plain slice selects the top performers
    # without needing to re-sort here.
    top_k = hypotheses[:evolution_max_count]

    return actual_count, top_k


async def _prepare_evolution_round(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
) -> tuple[list[Hypothesis], list[str], dict[str, Any] | None]:
    """Selects the evolution pool and emits the start-of-phase progress.

    Args:
        state: Current workflow state.
        hypotheses: Hypothesis pool entering evolution; assumed already
            sorted by descending Elo rating (set by ranking_node).

    Returns:
        Tuple of (top_k hypotheses to evolve, flattened previously removed
        duplicate texts, supervisor guidance for the evolution phase).
    """
    actual_count, top_k = _select_evolution_pool(state, hypotheses)

    logger.info("Evolving top %s hypotheses", actual_count)

    # Emit progress
    await emit_progress(state, "evolve_start",
                        f"Evolving top {actual_count} hypotheses...",
                        PROGRESS_EVOLVE_START)

    logger.info(
        "Evolving %s hypotheses with strategic context sampling "
        "(max 15 context hypotheses per evolution)", len(top_k))

    # Get previously removed duplicates
    # Flatten proximity.py's removed_duplicates dicts down to bare text;
    # used below to steer evolution away from recreating hypotheses that
    # were already pruned as duplicates in an earlier iteration.
    removed_duplicates = [
        dup.get("text", "") for dup in state.get("removed_duplicates", [])
    ]

    # Get supervisor guidance from state
    supervisor_guidance = state.get("supervisor_guidance")

    return top_k, removed_duplicates, supervisor_guidance


def _build_evolution_tasks(
    state: WorkflowState,
    top_k: list[Hypothesis],
    removed_duplicates: list[str],
    supervisor_guidance: dict[str, Any] | None,
) -> list[Coroutine[Any, Any, tuple[Hypothesis, dict[str, Any] | None]]]:
    """Builds the per-hypothesis evolution coroutines for this round.

    Evolve each hypothesis with strategically sampled context (PARALLEL):
    instead of including ALL other hypotheses, we sample a subset to
    control token budget.

    Args:
        state: Current workflow state.
        top_k: Hypotheses selected for evolution this round.
        removed_duplicates: Flattened previously removed duplicate texts.
        supervisor_guidance: Supervisor guidance for the evolution phase.

    Returns:
        List of evolve_single_hypothesis coroutines, one per hypothesis in
        top_k, ready to be awaited via asyncio.gather.
    """
    return [
        evolve_single_hypothesis(
            hypothesis=hyp,
            # Context is sampled from top_k (the peers also being evolved
            # this round), not the full hypothesis pool, so the diversity
            # check is scoped to hypotheses that could end up adjacent in
            # the final kept-only-evolved pool.
            other_hypotheses_texts=sample_context_hypotheses(
                all_hypotheses=top_k,
                exclude_hypothesis=hyp,
                max_context=15,  # cap at 15 for fixed token budget
            ),
            meta_review=state.get("meta_review", {}),
            model_name=state["model_name"],
            removed_duplicates=removed_duplicates,
            supervisor_guidance=supervisor_guidance,
            articles_with_reasoning=state.get("articles_with_reasoning"),
            run_id=state.get("run_id"),
            hypothesis_index=i,
            tool_registry=state.get("tool_registry"),
            run_setup_guidance=state.get("run_setup_guidance"),
            run_focus_guidance=state.get("run_focus_guidance"),
        ) for i, hyp in enumerate(top_k)
    ]


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
        evolutions_count_delta=len(evolved_hypotheses))
    logger.debug(
        "evolve node creating metrics delta: evolutions=%s, llm_calls=%s",
        len(evolved_hypotheses), len(evolved_hypotheses))

    # deduplicate_hypotheses (state.py) recognizes this as a replacement
    # because every returned hypothesis id already exists in state, so the
    # pool reliably shrinks to just the evolved list even when evolution
    # rewrote every text.
    return {
        "hypotheses":
            evolved_hypotheses,
        "evolution_details":
            evolution_details,
        "metrics":
            metrics,
        "messages":
            phase_message("evolve",
                          f"Evolved {len(evolved_hypotheses)} hypotheses",
                          evolved_count=len(evolved_hypotheses)),
    }


async def _finalize_evolve_result(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
    evolved_hypotheses: list[Hypothesis],
    evolution_details: list[dict[str, Any]],
) -> dict[str, Any]:
    """Applies the evolved pool, emits completion progress, and builds the
    evolve_node state delta.

    Args:
        state: Current workflow state.
        hypotheses: Hypothesis pool before evolution (for the
            discarded-count log).
        evolved_hypotheses: Hypotheses returned by this round's evolution.
        evolution_details: Evolution detail entries for hypotheses that
            actually changed.

    Returns:
        The evolve_node state delta dictionary.
    """
    # Keep ONLY the evolved hypotheses (discard lower-ranked ones)
    # This makes evolution_max_count the final pool size
    # Hypotheses ranked below top_k are not carried forward here; this is
    # how the pool shrinks across iterations rather than growing without
    # bound.
    original_count = len(hypotheses)
    discarded_count = original_count - len(evolved_hypotheses)
    logger.info(
        "Keeping only %s evolved hypotheses (discarded %s lower-ranked)",
        len(evolved_hypotheses), discarded_count)

    logger.info("Evolved %s hypotheses, %s with changes",
                len(evolved_hypotheses), len(evolution_details))

    # Emit progress
    await emit_progress(state,
                        "evolve_complete",
                        f"Evolved {len(evolved_hypotheses)} hypotheses",
                        PROGRESS_EVOLVE_COMPLETE,
                        evolved_count=len(evolved_hypotheses))

    return _build_evolve_state_delta(evolved_hypotheses, evolution_details)


async def evolve_node(state: WorkflowState) -> dict[str, Any]:
    """Evolve top-k hypotheses with context-aware refinement.

    This node implements the most impactful anti-duplicate strategy:
    context-aware evolution where each LLM call knows what all other
    hypotheses are to prevent convergence.

    Args:
        state: Current workflow state

    Returns:
        Dictionary with updated state fields (evolved hypotheses)
    """
    hypotheses = state["hypotheses"]

    top_k, removed_duplicates, supervisor_guidance = (await
                                                      _prepare_evolution_round(
                                                          state, hypotheses))

    evolution_tasks = _build_evolution_tasks(state, top_k, removed_duplicates,
                                             supervisor_guidance)
    results = await asyncio.gather(*evolution_tasks)

    # Unpack results: (hypothesis, evolution_detail or None)
    evolved_hypotheses, evolution_details = _collect_evolution_results(results)

    return await _finalize_evolve_result(state, hypotheses, evolved_hypotheses,
                                         evolution_details)
