"""Review node - adaptive peer review strategy based on hypothesis count.

- Small batches (≤5): Comparative batch review for differentiated scores
- Large batches (>5): Parallel individual reviews for scalability
"""
# pylint: disable=inconsistent-quotes

import asyncio
import logging
from typing import Any

from co_scientist.constants import (
    THINKING_MAX_TOKENS,
    EXTENDED_MAX_TOKENS,
    HIGH_TEMPERATURE,
    PROGRESS_REVIEW_START,
    PROGRESS_REVIEW_COMPLETE,
    COMPARATIVE_BATCH_THRESHOLD,
    REVIEW_BATCH_TOKENS_PER_HYPOTHESIS,
    REVIEW_BATCH_FREE_HYPOTHESES,
    REVIEW_BATCH_MAX_TOKENS_CAP,
    scaled_max_tokens,
)
from co_scientist.exceptions import GenerationError
from co_scientist.llm import call_llm_json
from co_scientist.models import (
    Hypothesis,
    HypothesisReview,
    create_metrics_update,
    phase_message,
)
from co_scientist.nodes.progress import emit_progress
from co_scientist.prompts import get_review_batch_prompt, get_review_prompt
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


def _review_from_response(data: dict[str, Any]) -> HypothesisReview:
    """Builds a HypothesisReview from an LLM review payload.

    The overall score is calculated from the criterion scores (more
    consistent than an LLM-provided value), falling back to the payload's
    overall_score when no criterion scores are present.

    Args:
        data: Review payload from the LLM response

    Returns:
        HypothesisReview object
    """
    scores = data.get("scores", {})
    if scores:
        # Deriving overall_score as the mean of the per-criterion scores
        # (rather than trusting an LLM-supplied overall_score) keeps the
        # value internally consistent with the criteria shown to the user,
        # even if the model's own aggregate judgment drifts from them.
        overall_score = sum(scores.values()) / len(scores)
    else:
        # No structured criterion scores at all (e.g. a malformed
        # response): fall back to whatever overall_score the payload
        # provides, defaulting to 0.0 if that is also absent.
        overall_score = data.get("overall_score", 0.0)

    return HypothesisReview(
        review_summary=data.get("review_summary", ""),
        scores=scores,
        safety_ethical_concerns=data.get("safety_ethical_concerns", ""),
        detailed_feedback=data.get("detailed_feedback", {}),
        constructive_feedback=data.get("constructive_feedback", ""),
        overall_score=overall_score,
    )


async def review_single_hypothesis(
    hypothesis_text: str,
    research_goal: str,
    model_name: str,
    supervisor_guidance: dict[str, Any] | None = None,
    meta_review: dict[str, Any] | None = None,
    run_id: str | None = None,
    hypothesis_index: int | None = None,
    tool_registry: Any | None = None,
    run_setup_guidance: str | None = None,
    run_focus_guidance: str | None = None,
) -> HypothesisReview:
    """Reviews a single hypothesis.

    Args:
        hypothesis_text: The hypothesis to review
        research_goal: The research goal for context
        model_name: LLM model to use
        supervisor_guidance: Optional planning guidance from the supervisor
        meta_review: Optional meta-review feedback for context
        run_id: Optional run ID for saving prompts
        hypothesis_index: Optional index for naming saved prompts
        tool_registry: Optional ToolRegistry for dynamic tool instructions
        run_setup_guidance: Optional run-setup guidance for the prompt
        run_focus_guidance: Optional run-focus guidance for the prompt

    Returns:
        HypothesisReview object
    """
    # Note: meta_review is not available in this function
    # They would need to be passed as parameters if needed
    prompt, schema = get_review_prompt(
        research_goal=research_goal,
        hypothesis_text=hypothesis_text,
        supervisor_guidance=supervisor_guidance,
        meta_review=meta_review,
        tool_registry=tool_registry,
        run_setup_guidance=run_setup_guidance,
        run_focus_guidance=run_focus_guidance,
    )

    # prompt_name distinguishes each hypothesis's saved prompt artifact on
    # disk (when COSCIENTIST_SAVE_PROMPTS is enabled) for debugging.
    prompt_name = (f"review_individual_{hypothesis_index}"
                   if hypothesis_index is not None else "review_individual")
    # Unlike analyze_single_hypothesis in reflection.py, this call is not
    # wrapped in a try/except: a failure here (e.g. exhausted retries)
    # raises out of this coroutine and, via asyncio.gather in
    # review_parallel_individual, aborts the whole review batch rather than
    # degrading to a per-hypothesis fallback.
    response = await call_llm_json(
        prompt=prompt,
        model_name=model_name,
        max_tokens=EXTENDED_MAX_TOKENS,
        temperature=HIGH_TEMPERATURE,
        json_schema=schema,
        run_id=run_id,
        prompt_name=prompt_name,
        prompt_metadata={
            "hypothesis_index": hypothesis_index,
            "prompt_length_chars": len(prompt),
        },
    )

    return _review_from_response(response)


async def review_parallel_individual(
    hypotheses: list[Hypothesis],
    research_goal: str,
    model_name: str,
    supervisor_guidance: dict[str, Any] | None = None,
    meta_review: dict[str, Any] | None = None,
    run_id: str | None = None,
    tool_registry: Any | None = None,
    run_setup_guidance: str | None = None,
    run_focus_guidance: str | None = None,
) -> list[HypothesisReview]:
    """Reviews hypotheses in parallel (original approach).

    Each hypothesis is reviewed independently without seeing others.
    Fast but may produce similar scores for high-quality hypotheses.

    Args:
        hypotheses: List of hypotheses to review
        research_goal: Research goal for context
        model_name: LLM model to use
        supervisor_guidance: Optional planning guidance from the supervisor
        meta_review: Optional meta-review feedback for context
        run_id: Optional run ID for saving prompts
        tool_registry: Optional ToolRegistry for dynamic tool instructions
        run_setup_guidance: Optional run-setup guidance for the prompt
        run_focus_guidance: Optional run-focus guidance for the prompt

    Returns:
        List of reviews (one per hypothesis)
    """
    # No concurrency semaphore is applied here, so every per-hypothesis
    # review is dispatched at once; the count-based strategy in review_node
    # is what bounds fan-out. gather preserves input order, so the returned
    # reviews line up positionally with `hypotheses`.
    review_tasks = [
        review_single_hypothesis(
            hypothesis_text=hyp.text,
            research_goal=research_goal,
            model_name=model_name,
            supervisor_guidance=supervisor_guidance,
            meta_review=meta_review,
            run_id=run_id,
            hypothesis_index=i,
            tool_registry=tool_registry,
            run_setup_guidance=run_setup_guidance,
            run_focus_guidance=run_focus_guidance,
        ) for i, hyp in enumerate(hypotheses)
    ]

    return await asyncio.gather(*review_tasks)


def _prepare_batch_review_call(
    hypotheses: list[Hypothesis],
    research_goal: str,
    supervisor_guidance: dict[str, Any] | None,
    meta_review: dict[str, Any] | None,
    tool_registry: Any | None,
    run_setup_guidance: str | None,
    run_focus_guidance: str | None,
) -> tuple[str, dict[str, Any] | None, int, int]:
    """Builds the batch-review prompt and derives its token/retry budget.

    Args:
        hypotheses: Hypotheses to include in the batch prompt.
        research_goal: Research goal for context.
        supervisor_guidance: Optional planning guidance from the supervisor.
        meta_review: Optional meta-review feedback for context.
        tool_registry: Optional ToolRegistry for dynamic tool instructions.
        run_setup_guidance: Optional run-setup guidance for the prompt.
        run_focus_guidance: Optional run-focus guidance for the prompt.

    Returns:
        Tuple of (prompt, schema, max_tokens, max_attempts).
    """
    hypotheses_list = "\n\n".join([
        f"**Hypothesis {i}:**\n{hyp.text}" for i, hyp in enumerate(hypotheses)
    ])
    prompt, schema = get_review_batch_prompt(
        research_goal=research_goal,
        hypotheses_list=hypotheses_list,
        supervisor_guidance=supervisor_guidance,
        meta_review=meta_review,
        tool_registry=tool_registry,
        run_setup_guidance=run_setup_guidance,
        run_focus_guidance=run_focus_guidance,
    )

    # Scale max_tokens based on hypothesis count in batch (base budget covers
    # the first REVIEW_BATCH_FREE_HYPOTHESES hypotheses).
    hypothesis_count = len(hypotheses)
    max_tokens = scaled_max_tokens(
        THINKING_MAX_TOKENS,
        hypothesis_count,
        per_item=REVIEW_BATCH_TOKENS_PER_HYPOTHESIS,
        cap=REVIEW_BATCH_MAX_TOKENS_CAP,
        free_count=REVIEW_BATCH_FREE_HYPOTHESES,
    )
    # More retries for large batches.
    max_attempts = 7 if hypothesis_count > 10 else 5

    logger.debug("batch review: %s hypotheses, max_tokens=%s", hypothesis_count,
                 max_tokens)

    return prompt, schema, max_tokens, max_attempts


async def review_comparative_batch(
    hypotheses: list[Hypothesis],
    research_goal: str,
    model_name: str,
    supervisor_guidance: dict[str, Any] | None = None,
    meta_review: dict[str, Any] | None = None,
    run_id: str | None = None,
    tool_registry: Any | None = None,
    run_setup_guidance: str | None = None,
    run_focus_guidance: str | None = None,
) -> list[HypothesisReview]:
    """Reviews hypotheses in a single comparative batch.

    All hypotheses are shown to one LLM call for relative comparison.
    Produces more differentiated scores but limited by token constraints.

    Args:
        hypotheses: List of hypotheses to review
        research_goal: Research goal for context
        model_name: LLM model to use
        supervisor_guidance: Optional planning guidance from the supervisor
        meta_review: Optional meta-review feedback for context
        run_id: Optional run ID for saving prompts
        tool_registry: Optional ToolRegistry for dynamic tool instructions
        run_setup_guidance: Optional run-setup guidance for the prompt
        run_focus_guidance: Optional run-focus guidance for the prompt

    Returns:
        List of reviews (one per hypothesis)
    """
    prompt, schema, max_tokens, max_attempts = _prepare_batch_review_call(
        hypotheses,
        research_goal,
        supervisor_guidance,
        meta_review,
        tool_registry,
        run_setup_guidance,
        run_focus_guidance,
    )

    response = await call_llm_json(
        prompt=prompt,
        model_name=model_name,
        max_tokens=max_tokens,
        temperature=HIGH_TEMPERATURE,
        json_schema=schema,
        max_attempts=max_attempts,
        run_id=run_id,
        prompt_name="review_batch",
        prompt_metadata={
            "hypotheses_count": len(hypotheses),
            "scaled_max_tokens": max_tokens,
            "prompt_length_chars": len(prompt),
        },
    )

    return _parse_batch_review_response(response, hypotheses, run_id)


def _log_batch_review_response_shape(
    response: dict[str, Any],
    reviews_data: list[Any],
    hypotheses: list[Hypothesis],
    run_id: str | None,
) -> None:
    """Logs batch-review response diagnostics and any count mismatch.

    Args:
        response: raw LLM JSON response from the batch review call.
        reviews_data: the "reviews" list pulled from response.
        hypotheses: hypotheses that were reviewed, for count/logging only.
        run_id: optional run ID, referenced in the mismatch log message.
    """
    logger.info("Batch review response keys: %s", list(response.keys()))
    logger.info("Reviews data type: %s, length: %s", type(reviews_data),
                len(reviews_data) if isinstance(reviews_data, list) else 'N/A')
    logger.info("Expected %s reviews, received %s", len(hypotheses),
                len(reviews_data))

    if len(reviews_data) != len(hypotheses):
        logger.error(
            "MISMATCH: Expected %s reviews but got %s. "
            "This indicates the LLM may have hit output token limits"
            " or failed to generate all reviews. "
            "Check the saved prompt at"
            " .coscientist_prompts/%s/review_batch.txt", len(hypotheses),
            len(reviews_data), run_id)


def _build_reviews_with_placeholders(
    hypotheses: list[Hypothesis],
    reviews_data: list[Any],
) -> list[HypothesisReview]:
    """Converts batch-review entries into HypothesisReview objects.

    Iterates by index over `hypotheses` (not `reviews_data`) so every
    hypothesis gets a review object even if the LLM under-produced entries;
    missing entries are padded with an "unavailable" placeholder rather than
    raising here -- review_node detects that placeholder via its
    review_summary text and raises instead of silently scoring the
    hypothesis at 0.

    Args:
        hypotheses: hypotheses that were reviewed.
        reviews_data: the "reviews" list pulled from the batch response.

    Returns:
        List of reviews, one per hypothesis, in the same order.
    """
    reviews = []
    for i in range(len(hypotheses)):
        if i < len(reviews_data):
            reviews.append(_review_from_response(reviews_data[i]))
        else:
            logger.error("No review data for hypothesis %s", i)
            reviews.append(
                HypothesisReview(
                    review_summary="Review unavailable",
                    scores={},
                    safety_ethical_concerns="",
                    detailed_feedback={},
                    constructive_feedback="",
                    overall_score=0.0,
                ))

    return reviews


def _parse_batch_review_response(
    response: dict[str, Any],
    hypotheses: list[Hypothesis],
    run_id: str | None,
) -> list[HypothesisReview]:
    """Parses a batch-review LLM response into per-hypothesis reviews.

    Args:
        response: raw LLM JSON response from the batch review call.
        hypotheses: hypotheses that were reviewed, for count/logging only.
        run_id: optional run ID, referenced in the mismatch log message.

    Returns:
        List of reviews, one per hypothesis, in the same order.
    """
    reviews_data = response.get("reviews", [])
    _log_batch_review_response_shape(response, reviews_data, hypotheses, run_id)
    return _build_reviews_with_placeholders(hypotheses, reviews_data)


def _select_review_strategy(num_hypotheses: int) -> tuple[bool, str]:
    """Chooses the review strategy for a batch of hypotheses.

    Comparative batch review puts every hypothesis in one prompt so the
    judge can differentiate scores relative to its peers, but a single
    response has a token ceiling; above the threshold, parallel individual
    review trades that relative differentiation for scalability (one
    bounded-size call per hypothesis, no shared token budget).

    Args:
        num_hypotheses: number of hypotheses to be reviewed.

    Returns:
        Tuple of (use_comparative, strategy_name).
    """
    use_comparative = num_hypotheses <= COMPARATIVE_BATCH_THRESHOLD
    if use_comparative:
        logger.info("Reviewing %s hypotheses via comparative batch (≤%s)",
                    num_hypotheses, COMPARATIVE_BATCH_THRESHOLD)
        strategy_name = "comparative batch"
    else:
        logger.info("Reviewing %s hypotheses via parallel individual (>%s)",
                    num_hypotheses, COMPARATIVE_BATCH_THRESHOLD)
        strategy_name = "parallel"
    return use_comparative, strategy_name


def _validate_reviews(reviews: list[HypothesisReview]) -> None:
    """Raises if any review is an unavailable placeholder.

    Unlike reflection_node/proximity_node, which degrade gracefully on
    partial LLM failures, a hypothesis reaching ranking without a real
    review would silently rank at score 0.0, so this fails loudly instead.

    Args:
        reviews: reviews to validate.

    Raises:
        GenerationError: if one or more reviews is unavailable.
    """
    invalid_reviews = [
        i for i, r in enumerate(reviews)
        if r.review_summary == "Review unavailable"
    ]
    if invalid_reviews:
        error_msg = (f"review node failed: {len(invalid_reviews)}"
                     f"/{len(reviews)} reviews invalid")
        logger.error(error_msg)
        raise GenerationError(error_msg)


async def _execute_review_strategy(
    use_comparative: bool,
    hypotheses: list[Hypothesis],
    research_goal: str,
    model_name: str,
    supervisor_guidance: dict[str, Any] | None,
    meta_review: dict[str, Any] | None,
    run_id: str | None,
    tool_registry: Any | None,
    run_setup_guidance: str | None,
    run_focus_guidance: str | None,
) -> tuple[list[HypothesisReview], int]:
    """Runs the chosen review strategy and reports how many LLM calls it used.

    Args:
        use_comparative: True to run comparative batch review, False to run
            parallel individual review.
        hypotheses: List of hypotheses to review.
        research_goal: Research goal for context.
        model_name: LLM model to use.
        supervisor_guidance: Optional planning guidance from the supervisor.
        meta_review: Optional meta-review feedback for context.
        run_id: Optional run ID for saving prompts.
        tool_registry: Optional ToolRegistry for dynamic tool instructions.
        run_setup_guidance: Optional run-setup guidance for the prompt.
        run_focus_guidance: Optional run-focus guidance for the prompt.

    Returns:
        Tuple of (reviews, llm_calls_used).
    """
    if use_comparative:
        reviews = await review_comparative_batch(
            hypotheses=hypotheses,
            research_goal=research_goal,
            model_name=model_name,
            supervisor_guidance=supervisor_guidance,
            meta_review=meta_review,
            run_id=run_id,
            tool_registry=tool_registry,
            run_setup_guidance=run_setup_guidance,
            run_focus_guidance=run_focus_guidance,
        )
        return reviews, 1  # Single batch call

    reviews = await review_parallel_individual(
        hypotheses=hypotheses,
        research_goal=research_goal,
        model_name=model_name,
        supervisor_guidance=supervisor_guidance,
        meta_review=meta_review,
        run_id=run_id,
        tool_registry=tool_registry,
        run_setup_guidance=run_setup_guidance,
        run_focus_guidance=run_focus_guidance,
    )
    return reviews, len(hypotheses)  # One call per hypothesis


async def _run_review_strategy(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
    use_comparative: bool,
) -> tuple[list[HypothesisReview], int]:
    """Gathers guidance from state and runs the chosen review strategy.

    Args:
        state: Current workflow state.
        hypotheses: Hypotheses to review.
        use_comparative: True to run comparative batch review, False to run
            parallel individual review.

    Returns:
        Tuple of (reviews, llm_calls_used).
    """
    supervisor_guidance = state.get("supervisor_guidance")
    meta_review = state.get("meta_review")
    run_setup_guidance = state.get("run_setup_guidance")
    run_focus_guidance = state.get("run_focus_guidance")
    tool_registry = state.get("tool_registry")

    return await _execute_review_strategy(
        use_comparative,
        hypotheses,
        state["research_goal"],
        state["model_name"],
        supervisor_guidance,
        meta_review,
        state.get("run_id"),
        tool_registry,
        run_setup_guidance,
        run_focus_guidance,
    )


def _attach_reviews_to_hypotheses(
    hypotheses: list[Hypothesis],
    reviews: list[HypothesisReview],
) -> None:
    """Attaches each review to its hypothesis and mirrors its overall score.

    Args:
        hypotheses: Hypotheses to update, in the same order as reviews.
        reviews: Reviews to attach, in the same order as hypotheses.
    """
    for hypothesis, review in zip(hypotheses, reviews):
        hypothesis.reviews.append(review)
        hypothesis.score = review.overall_score


async def review_node(state: WorkflowState) -> dict[str, Any]:
    """Reviews all hypotheses using adaptive strategy.

    Strategy selection:
    - Small batches (≤5): Comparative batch review for differentiated scores
    - Large batches (>5): Parallel individual reviews for scalability

    Args:
        state: Current workflow state

    Returns:
        Dictionary with updated state fields
    """
    logger.info("Starting review node")

    hypotheses = state["hypotheses"]
    num_hypotheses = len(hypotheses)

    logger.info("Reviewing %s hypotheses", num_hypotheses)

    use_comparative, strategy_name = _select_review_strategy(num_hypotheses)

    await emit_progress(state, "review_start",
                        f"Reviewing {num_hypotheses} hypotheses...",
                        PROGRESS_REVIEW_START)

    reviews, llm_calls = await _run_review_strategy(state, hypotheses,
                                                    use_comparative)

    _validate_reviews(reviews)
    _attach_reviews_to_hypotheses(hypotheses, reviews)

    logger.info("Completed %s reviews using %s strategy", len(reviews),
                strategy_name)

    await emit_progress(state,
                        "review_complete",
                        f"Completed {len(reviews)} reviews",
                        PROGRESS_REVIEW_COMPLETE,
                        reviews_count=len(reviews))

    # Update metrics (deltas only, merge_metrics will add to existing state)
    metrics = create_metrics_update(reviews_count_delta=len(reviews),
                                    llm_calls_delta=llm_calls)
    logger.debug("review node creating metrics delta: reviews=%s, llm_calls=%s",
                 len(reviews), llm_calls)

    return {
        "hypotheses":
            hypotheses,
        "metrics":
            metrics,
        "messages":
            phase_message(
                "review",
                f"Reviewed {len(reviews)} hypotheses ({strategy_name})",
                strategy=strategy_name),
    }
