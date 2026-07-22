"""Pure helpers for the review node's adaptive peer-review strategy.

Batch-prompt preparation, response parsing, strategy selection, review
validation, and hypothesis attachment - the non-LLM building blocks the
review node composes. The LLM-calling functions and the node itself live in
the sibling ``review.py``.
"""

import logging
from typing import Any

from co_scientist.constants import (
    COMPARATIVE_BATCH_THRESHOLD,
    REVIEW_BATCH_FREE_HYPOTHESES,
    REVIEW_BATCH_MAX_TOKENS_CAP,
    REVIEW_BATCH_TOKENS_PER_HYPOTHESIS,
    THINKING_MAX_TOKENS,
    scaled_max_tokens,
)
from co_scientist.exceptions import GenerationError
from co_scientist.models import Hypothesis, HypothesisReview
from co_scientist.prompts import get_review_batch_prompt

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
    prompt, schema = get_review_batch_prompt(
        research_goal=research_goal,
        hypotheses_list=_build_hypotheses_list_text(hypotheses),
        supervisor_guidance=supervisor_guidance,
        meta_review=meta_review,
        tool_registry=tool_registry,
        run_setup_guidance=run_setup_guidance,
        run_focus_guidance=run_focus_guidance,
    )
    hypothesis_count = len(hypotheses)
    max_tokens, max_attempts = _scaled_batch_review_budget(hypothesis_count)
    logger.debug(
        "batch review: %s hypotheses, max_tokens=%s",
        hypothesis_count,
        max_tokens,
    )
    return prompt, schema, max_tokens, max_attempts


def _build_hypotheses_list_text(hypotheses: list[Hypothesis]) -> str:
    """Formats hypotheses as a numbered list for the batch review prompt."""
    return "\n\n".join(
        [f"**Hypothesis {i}:**\n{hyp.text}" for i, hyp in enumerate(hypotheses)]
    )


def _scaled_batch_review_budget(hypothesis_count: int) -> tuple[int, int]:
    """Scales the batch review token budget and retry count by batch size.

    Base budget covers the first REVIEW_BATCH_FREE_HYPOTHESES hypotheses;
    more retries are allotted for large batches.
    """
    max_tokens = scaled_max_tokens(
        THINKING_MAX_TOKENS,
        hypothesis_count,
        per_item=REVIEW_BATCH_TOKENS_PER_HYPOTHESIS,
        cap=REVIEW_BATCH_MAX_TOKENS_CAP,
        free_count=REVIEW_BATCH_FREE_HYPOTHESES,
    )
    max_attempts = 7 if hypothesis_count > 10 else 5
    return max_tokens, max_attempts


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
    logger.info(
        "Reviews data type: %s, length: %s",
        type(reviews_data),
        len(reviews_data) if isinstance(reviews_data, list) else "N/A",
    )
    logger.info(
        "Expected %s reviews, received %s", len(hypotheses), len(reviews_data)
    )

    if len(reviews_data) != len(hypotheses):
        logger.error(
            "MISMATCH: Expected %s reviews but got %s. "
            "This indicates the LLM may have hit output token limits"
            " or failed to generate all reviews. "
            "Check the saved prompt at"
            " .coscientist_prompts/%s/review_batch.txt",
            len(hypotheses),
            len(reviews_data),
            run_id,
        )


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
                )
            )

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
        logger.info(
            "Reviewing %s hypotheses via comparative batch (≤%s)",
            num_hypotheses,
            COMPARATIVE_BATCH_THRESHOLD,
        )
        strategy_name = "comparative batch"
    else:
        logger.info(
            "Reviewing %s hypotheses via parallel individual (>%s)",
            num_hypotheses,
            COMPARATIVE_BATCH_THRESHOLD,
        )
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
        i
        for i, r in enumerate(reviews)
        if r.review_summary == "Review unavailable"
    ]
    if invalid_reviews:
        error_msg = (
            f"review node failed: {len(invalid_reviews)}"
            f"/{len(reviews)} reviews invalid"
        )
        logger.error(error_msg)
        raise GenerationError(error_msg)


def _attach_reviews_to_hypotheses(
    hypotheses: list[Hypothesis],
    reviews: list[HypothesisReview],
) -> None:
    """Attaches each review to its hypothesis and mirrors its overall score.

    Args:
        hypotheses: Hypotheses to update, in the same order as reviews.
        reviews: Reviews to attach, in the same order as hypotheses.
    """
    for hypothesis, review in zip(hypotheses, reviews, strict=True):
        hypothesis.reviews.append(review)
        hypothesis.score = review.overall_score
