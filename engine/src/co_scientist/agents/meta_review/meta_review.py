"""Meta-review node - synthesize insights from all reviews."""

import dataclasses
import json
import logging
from typing import Any

from co_scientist.constants import (
    MEDIUM_TEMPERATURE,
    PROGRESS_META_REVIEW_COMPLETE,
    PROGRESS_META_REVIEW_START,
    THINKING_MAX_TOKENS,
    truncate,
)
from co_scientist.llm import call_llm_json
from co_scientist.models import Hypothesis, create_metrics_update, phase_message
from co_scientist.progress import emit_progress
from co_scientist.prompts import get_meta_review_prompt
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


async def meta_review_node(state: WorkflowState) -> dict[str, Any]:
    """Synthesizes insights from all reviews across all hypotheses.

    This node analyzes all the reviews collectively to identify:
    - Common strengths and weaknesses
    - Promising research directions
    - Areas needing improvement
    - Strategic guidance for evolution

    Args:
        state: Current workflow state

    Returns:
        Dictionary with updated state fields (meta_review)
    """
    hypotheses = state["hypotheses"]
    logger.info("Synthesizing meta-review from %s hypotheses", len(hypotheses))

    # Emit progress
    await emit_progress(
        state,
        "meta_review_start",
        "Synthesizing insights from all reviews...",
        PROGRESS_META_REVIEW_START,
    )

    # Collect the complete feedback history: every review and every ranking
    # debate. Later feedback does not erase earlier failure patterns.
    all_reviews = _collect_feedback_records(
        hypotheses, state.get("tournament_matchups", [])
    )

    # Edge case: no hypothesis has been reviewed yet (e.g. review node was
    # skipped or failed for all hypotheses). Skip the LLM call and return a
    # minimal meta_review instead; downstream readers (evolve, ranking
    # prompts) use dict.get() with defaults, so the omitted
    # "emerging_themes" key here is still handled safely.
    if not all_reviews:
        logger.warning("No reviews available for meta-review")
        return _empty_meta_review_result()

    # Call LLM to synthesize meta-review
    prompt_context = _build_meta_review_prompt_context(state, all_reviews)
    prompt, schema = get_meta_review_prompt(**prompt_context)
    response = await _call_meta_review_llm(
        state, prompt, schema, len(hypotheses), len(all_reviews)
    )

    meta_review = _build_meta_review(response)
    _log_meta_review_summary(meta_review)

    # Emit progress
    await emit_progress(
        state,
        "meta_review_complete",
        "Meta-review synthesis complete",
        PROGRESS_META_REVIEW_COMPLETE,
        strengths_count=len(meta_review["common_strengths"]),
        recommendations_count=len(meta_review["strategic_recommendations"]),
    )

    return _build_meta_review_result(meta_review)


async def _call_meta_review_llm(
    state: WorkflowState,
    prompt: str,
    schema: dict[str, Any] | None,
    hypotheses_count: int,
    reviews_count: int,
) -> dict[str, Any]:
    """Calls the LLM to synthesize the meta-review.

    Uses supervisor_model_name (the stronger strategic model), not the
    regular worker model_name used by ranking/review -- synthesizing
    cross-hypothesis insights that steer evolution benefits from the more
    capable model.

    Args:
        state: Current workflow state.
        prompt: Rendered meta-review prompt.
        schema: JSON schema the response must conform to.
        hypotheses_count: Total hypotheses, recorded in prompt_metadata.
        reviews_count: Total collected reviews, recorded in
            prompt_metadata.

    Returns:
        The raw LLM JSON response.
    """
    return await call_llm_json(
        prompt=prompt,
        model_name=state["supervisor_model_name"],
        max_tokens=THINKING_MAX_TOKENS,  # more space to aggregate all reviews
        temperature=MEDIUM_TEMPERATURE,
        json_schema=schema,
        run_id=state.get("run_id"),
        prompt_name="meta_review",
        prompt_metadata={
            "prompt_length_chars": len(prompt),
            "hypotheses_count": hypotheses_count,
            "reviews_count": reviews_count,
        },
    )


def _build_meta_review_result(meta_review: dict[str, Any]) -> dict[str, Any]:
    """Assembles the meta_review_node return dict.

    Args:
        meta_review: Assembled meta_review dict.

    Returns:
        Dict with updated state fields (meta_review, metrics, messages).
    """
    # Update metrics (deltas only, merge_metrics will add to existing state)
    metrics = create_metrics_update(llm_calls_delta=1)

    return {
        "meta_review": meta_review,
        "metrics": metrics,
        "messages": phase_message(
            "meta_review",
            "Synthesized meta-review from all hypotheses",
            themes=len(meta_review.get("emerging_themes", [])),
        ),
    }


def _empty_meta_review_result() -> dict[str, Any]:
    """Builds the fallback return value when no hypothesis has a review.

    Returns:
        Dict with a minimal meta_review, matching the shape downstream
        readers (evolve, ranking prompts) expect via dict.get() with
        defaults.
    """
    return {
        "meta_review": {
            "summary": "No reviews available",
            "common_strengths": [],
            "common_weaknesses": [],
            "strategic_recommendations": [],
        }
    }


def _build_meta_review_prompt_context(
    state: WorkflowState, all_reviews: list[dict[str, Any]]
) -> dict[str, Any]:
    """Extracts the state fields needed to build the meta-review prompt.

    Args:
        state: Current workflow state.
        all_reviews: Per-hypothesis review summaries from
            _collect_review_summaries.

    Returns:
        Dict of keyword arguments ready to spread into
        get_meta_review_prompt.
    """
    return {
        "research_goal": state["research_goal"],
        "all_reviews": json.dumps(all_reviews, indent=2),
        "supervisor_guidance": state.get("supervisor_guidance"),
        "instructions": None,  # for the future
        "tool_registry": state.get("tool_registry"),
        "run_setup_guidance": state.get("run_setup_guidance"),
        "run_focus_guidance": state.get("run_focus_guidance"),
    }


def _log_meta_review_summary(meta_review: dict[str, Any]) -> None:
    """Logs a summary of the completed meta-review.

    Args:
        meta_review: assembled meta_review dict.
    """
    logger.info("Meta-review complete")
    logger.info("Common strengths: %s", len(meta_review["common_strengths"]))
    logger.info(
        "Strategic recommendations: %s",
        len(meta_review["strategic_recommendations"]),
    )


def _collect_review_summaries(
    hypotheses: list[Hypothesis],
) -> list[dict[str, Any]]:
    """Build complete per-hypothesis review histories for the LLM.

    Every review is retained in chronological order, plus current tournament
    standing and verification status, so recurring critiques remain visible.

    Args:
        hypotheses: hypotheses to summarize.

    Returns:
        List of review summary dicts, one per reviewed hypothesis
        (hypotheses with no reviews are skipped).
    """
    all_reviews = []
    for i, hyp in enumerate(hypotheses):
        if not hyp.reviews:
            continue

        review_data = {
            "record_type": "review_history",
            "hypothesis_index": i,
            "hypothesis_text": truncate(hyp.text),
            "reviews": [dataclasses.asdict(review) for review in hyp.reviews],
            "elo_rating": hyp.elo_rating,
            "win_loss_record": f"{hyp.win_count}W-{hyp.loss_count}L",
            "deep_verification_verdict": hyp.deep_verification_verdict,
        }
        all_reviews.append(review_data)
    return all_reviews


def _collect_debate_records(
    matchups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return every tournament debate and its full turn transcript."""
    return [
        {
            "record_type": "ranking_debate",
            "match_index": index,
            "hypothesis_a_id": matchup.get("hypothesis_a_id"),
            "hypothesis_b_id": matchup.get("hypothesis_b_id"),
            "hypothesis_a": matchup.get("hypothesis_a"),
            "hypothesis_b": matchup.get("hypothesis_b"),
            "winner_id": matchup.get("winner_id"),
            "winner": matchup.get("winner"),
            "reasoning": matchup.get("reasoning"),
            "confidence": matchup.get("confidence"),
            "debate_turns": matchup.get("debate_turns", 1),
            "debate_transcript": matchup.get("debate_transcript", []),
        }
        for index, matchup in enumerate(matchups)
    ]


def _collect_feedback_records(
    hypotheses: list[Hypothesis],
    matchups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Combine all review histories and ranking debates for meta-analysis."""
    return [
        *_collect_review_summaries(hypotheses),
        *_collect_debate_records(matchups),
    ]


def _build_meta_review(response: dict[str, Any]) -> dict[str, Any]:
    """Assembles the meta_review state dict from the LLM response.

    This dict becomes state["meta_review"], consumed downstream by the
    evolve node (to steer refinement) and by ranking's judge_matchup
    (included in the tournament-judging prompt), so its shape is a de
    facto cross-node contract.

    Args:
        response: raw LLM JSON response from the meta-review call.

    Returns:
        The assembled meta_review dict.
    """
    # Schema returns recurring_themes as objects {theme, description,
    # frequency}; flatten to strings.
    # The isinstance check tolerates a model that ignores the schema and
    # returns bare strings instead of {theme, description, frequency}
    # objects, coercing either shape into a plain string list.
    recurring_themes = response.get("recurring_themes", [])
    emerging_themes = [
        t["theme"] if isinstance(t, dict) else str(t) for t in recurring_themes
    ]

    return {
        "summary": response.get("meta_review_summary", ""),
        "common_strengths": response.get("strengths", []),
        "common_weaknesses": response.get("weaknesses", []),
        "emerging_themes": emerging_themes,
        "strategic_recommendations": response.get(
            "strategic_recommendations", []
        ),
    }
