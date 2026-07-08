"""Evolve node - refine top hypotheses with context-aware evolution."""
# pylint: disable=inconsistent-quotes

import asyncio
import json
import logging
import random
from typing import Any

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
        return [h.text for h in others]

    # Sort by Elo rating (descending)
    others_sorted = rank_by_elo(others)

    # Take top 5 by Elo (the best ones to avoid copying)
    top_performers = others_sorted[:5]
    remaining = others_sorted[5:]

    # Sample up to 10 more from the rest
    sample_count = min(10, len(remaining))
    sampled_others = random.sample(remaining, sample_count) if remaining else []

    # Combine: top 5 + sampled 10 = max 15
    context_hypotheses = top_performers + sampled_others

    logger.debug(
        "sampled %s context hypotheses (top 5 + %s random) from %s total",
        len(context_hypotheses), len(sampled_others), len(others))

    return [h.text for h in context_hypotheses]


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


def _log_meta_review_debug(meta_review: dict[str, Any]) -> None:
    """Logs meta-review signals used during evolution, for debugging.

    The same fields are also formatted into the prompt itself (see
    _build_meta_review_insights); this only logs them for visibility.

    Args:
        meta_review: Meta-review insights for strategic guidance.
    """
    logger.debug("\n=== evolve single hypothesis ===")
    logger.debug("using meta review for evolution")

    common_strengths = meta_review.get("common_strengths", [])
    common_weaknesses = meta_review.get("common_weaknesses", [])
    strategic_recommendations = meta_review.get("strategic_recommendations", [])
    emerging_themes = meta_review.get("emerging_themes", [])

    if common_strengths:
        logger.debug("common Strengths (%s):", len(common_strengths))
        for strength in common_strengths[:3]:  # Show first 3
            logger.debug("- %s%s", strength[:100],
                         '...' if len(strength) > 100 else '')

    if common_weaknesses:
        logger.debug("common Weaknesses (%s):", len(common_weaknesses))
        for weakness in common_weaknesses[:3]:  # Show first 3
            logger.debug("- %s%s", weakness[:100],
                         '...' if len(weakness) > 100 else '')

    if strategic_recommendations:
        logger.debug("strategic Recommendations (%s):",
                     len(strategic_recommendations))
        for rec in strategic_recommendations[:3]:  # Show first 3
            logger.debug("- %s", rec)

    if emerging_themes:
        logger.debug("emerging Themes (%s):", len(emerging_themes))
        for theme in emerging_themes[:3]:  # Show first 3
            logger.debug("- %s", theme)


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

    guidance_sections = []
    guidance_sections.append("## Supervisor Guidance for Evolution\n")
    if evolution_phase.get("refinement_priorities"):
        priorities = evolution_phase["refinement_priorities"]
        if isinstance(priorities, list):
            priorities = ", ".join(priorities)
        guidance_sections.append(f"**Refinement Priorities:** {priorities}\n")
    if evolution_phase.get("iteration_strategy"):
        strat = evolution_phase['iteration_strategy']
        guidance_sections.append(f"**Iteration Strategy:** {strat}\n")
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

    review_feedback = _build_review_feedback(hypothesis)
    meta_review_insights = _build_meta_review_insights(meta_review)
    supervisor_guidance_text = _build_supervisor_guidance_text(
        supervisor_guidance)

    # Build context-aware evolution prompt with domain variables
    # Unlike most nodes, evolve has no dedicated get_evolution_prompt()
    # wrapper in prompts.py, so it calls load_prompt_with_schema directly
    # below and must pull in these normally-internal helpers itself to
    # build the same run-guidance/domain variables the wrappers assemble.
    from co_scientist.prompts import _format_run_guidance, _get_domain_variables  # pylint: disable=import-outside-toplevel

    variables = {
        "original_hypothesis":
            hypothesis.text,
        "review_feedback":
            review_feedback,
        "meta_review_insights":
            meta_review_insights,
        "supervisor_guidance":
            supervisor_guidance_text,
        "run_guidance":
            _format_run_guidance(run_setup_guidance, run_focus_guidance),
        "articles_with_reasoning":
            articles_with_reasoning or "",
    }
    variables.update(_get_domain_variables(tool_registry))

    prompt, schema = load_prompt_with_schema("evolution", variables)

    # Add critical diversity instruction
    diversity_instruction = _format_diversity_instruction(
        other_hypotheses_texts, removed_duplicates)
    full_prompt = prompt + diversity_instruction

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
    response = await call_llm_json(
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

    # Extract fields from response (match evolution.md prompt format)
    # Prefer the canonical "hypothesis" key; fall back to the legacy
    # "refined_hypothesis_text" name, and finally to the pre-evolution text
    # if the LLM response omits both (defensive against malformed output).
    refined_text = response.get("hypothesis") or response.get(
        "refined_hypothesis_text", hypothesis.text)
    explanation = response.get("explanation", hypothesis.explanation)
    experiment = response.get("experiment", hypothesis.experiment)
    refinement_summary = response.get("refinement_summary",
                                      "no refinement summary provided")

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

    # Update hypothesis
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

    # Return both hypothesis and evolution details
    # evolution_detail feeds evolution_details in evolve_node's state
    # delta below, which the UI surfaces as the rationale for each change.
    evolution_detail = {
        "original": original_text,
        "evolved": refined_text,
        "rationale": refinement_summary,
    }

    return hypothesis, evolution_detail


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
    evolution_max_count = state.get("evolution_max_count", 10)

    # Calculate actual number to evolve (may be less than max if fewer
    # hypotheses available)
    # evolution_max_count doubles as the size of the pool going forward
    # (see "Keep ONLY the evolved hypotheses" below), so clamp it to the
    # available count rather than evolving hypotheses that do not exist.
    actual_count = min(len(hypotheses), evolution_max_count)

    logger.info("Evolving top %s hypotheses", actual_count)

    # Emit progress
    await emit_progress(state, "evolve_start",
                        f"Evolving top {actual_count} hypotheses...",
                        PROGRESS_EVOLVE_START)

    # Get top-k hypotheses
    # hypotheses arrives already sorted by descending Elo rating (set by
    # ranking_node's return), so a plain slice selects the top performers
    # without needing to re-sort here.
    top_k = hypotheses[:evolution_max_count]

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

    # Evolve each hypothesis with strategically sampled context (PARALLEL)
    # instead of including ALL other hypotheses, we sample a subset to control
    # token budget
    evolution_tasks = [
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

    results = await asyncio.gather(*evolution_tasks)

    # Unpack results: (hypothesis, evolution_detail or None)
    evolved_hypotheses = []
    evolution_details = []

    for hyp, detail in results:
        evolved_hypotheses.append(hyp)
        # detail is None when evolve_single_hypothesis rejected the
        # refinement (unchanged text or near-duplicate); only genuine
        # changes are recorded in evolution_details.
        if detail is not None:  # Only add if hypothesis actually evolved
            evolution_details.append(detail)

    # Keep ONLY the evolved hypotheses (discard lower-ranked ones)
    # This makes evolution_max_count the final pool size
    # Hypotheses ranked below top_k are not carried forward here; this is
    # how the pool shrinks across iterations rather than growing without
    # bound.
    original_count = len(hypotheses)
    hypotheses = evolved_hypotheses
    discarded_count = original_count - len(evolved_hypotheses)
    logger.info(
        "Keeping only %s evolved hypotheses (discarded %s lower-ranked)",
        len(hypotheses), discarded_count)

    logger.info("Evolved %s hypotheses, %s with changes",
                len(evolved_hypotheses), len(evolution_details))

    # Emit progress
    await emit_progress(state,
                        "evolve_complete",
                        f"Evolved {len(evolved_hypotheses)} hypotheses",
                        PROGRESS_EVOLVE_COMPLETE,
                        evolved_count=len(evolved_hypotheses))

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
            hypotheses,
        "evolution_details":
            evolution_details,
        "metrics":
            metrics,
        "messages":
            phase_message("evolve",
                          f"Evolved {len(evolved_hypotheses)} hypotheses",
                          evolved_count=len(evolved_hypotheses)),
    }
