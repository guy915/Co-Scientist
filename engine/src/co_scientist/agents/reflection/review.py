"""Review node - adaptive peer review strategy based on hypothesis count.

Reviews are incremental: only hypotheses without an existing review are sent
to the LLM (the pool only ever grows, so re-reviewing it would be quadratic).

- Small batches (≤5): Comparative batch review for differentiated scores
- Large batches (>5): Parallel individual reviews for scalability
"""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

from co_scientist.agents.reflection.review_helpers import (
    _attach_reviews_to_hypotheses as _attach_reviews_to_hypotheses,
)
from co_scientist.agents.reflection.review_helpers import (
    _build_reviews_with_placeholders as _build_reviews_with_placeholders,
)
from co_scientist.agents.reflection.review_helpers import (
    _log_batch_review_response_shape as _log_batch_review_response_shape,
)
from co_scientist.agents.reflection.review_helpers import (
    _parse_batch_review_response as _parse_batch_review_response,
)
from co_scientist.agents.reflection.review_helpers import (
    _prepare_batch_review_call as _prepare_batch_review_call,
)
from co_scientist.agents.reflection.review_helpers import (
    _review_from_response as _review_from_response,
)
from co_scientist.agents.reflection.review_helpers import (
    _select_review_strategy as _select_review_strategy,
)
from co_scientist.agents.reflection.review_helpers import (
    _validate_reviews as _validate_reviews,
)
from co_scientist.constants import (
    EXTENDED_MAX_TOKENS,
    HIGH_TEMPERATURE,
    PROGRESS_REVIEW_COMPLETE,
    PROGRESS_REVIEW_START,
)
from co_scientist.llm import call_llm_json
from co_scientist.models import (
    Hypothesis,
    HypothesisReview,
    create_metrics_update,
    phase_message,
)
from co_scientist.progress import emit_progress
from co_scientist.prompts import get_review_prompt
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


def _apply_initial_review_gate(
    hypotheses: list[Hypothesis], reviews: list[HypothesisReview]
) -> None:
    """Classify ideas that fail Google's early accuracy/novelty screen."""
    for hypothesis, review in zip(hypotheses, reviews, strict=True):
        soundness = review.scores.get("scientific_soundness", 0)
        novelty = review.scores.get("novelty", 0)
        inaccurate = soundness <= 3
        non_novel = novelty <= 3
        if inaccurate and non_novel:
            hypothesis.review_disposition = "inaccurate_and_non_novel"
        elif inaccurate:
            hypothesis.review_disposition = "inaccurate"
        elif non_novel:
            hypothesis.review_disposition = "non_novel"
        else:
            hypothesis.review_disposition = "viable"


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
    """Reviews a single hypothesis and returns its ``HypothesisReview``.

    The optional guidance parameters (supervisor, meta-review, run
    setup/focus) and the tool registry feed the prompt as context;
    ``run_id`` and ``hypothesis_index`` only name saved prompts.
    """
    prompt, schema = get_review_prompt(
        research_goal=research_goal,
        hypothesis_text=hypothesis_text,
        supervisor_guidance=supervisor_guidance,
        meta_review=meta_review,
        tool_registry=tool_registry,
        run_setup_guidance=run_setup_guidance,
        run_focus_guidance=run_focus_guidance,
    )
    response = await _call_review_llm(
        prompt, schema, model_name, run_id, hypothesis_index
    )
    return _review_from_response(response)


def _review_prompt_name(hypothesis_index: int | None) -> str:
    """Builds the per-hypothesis prompt name used for saved-prompt debugging."""
    return (
        f"review_individual_{hypothesis_index}"
        if hypothesis_index is not None
        else "review_individual"
    )


async def _call_review_llm(
    prompt: str,
    schema: dict[str, Any] | None,
    model_name: str,
    run_id: str | None,
    hypothesis_index: int | None,
) -> dict[str, Any]:
    """Calls the LLM to review a single hypothesis.

    Unlike analyze_single_hypothesis in reflection.py, this call is not
    wrapped in a try/except: a failure here raises out of this coroutine
    and, via asyncio.gather in review_parallel_individual, aborts the
    whole review batch rather than degrading to a per-hypothesis fallback.
    """
    return await call_llm_json(
        prompt=prompt,
        model_name=model_name,
        max_tokens=EXTENDED_MAX_TOKENS,
        temperature=HIGH_TEMPERATURE,
        json_schema=schema,
        run_id=run_id,
        prompt_name=_review_prompt_name(hypothesis_index),
        prompt_metadata={
            "hypothesis_index": hypothesis_index,
            "prompt_length_chars": len(prompt),
        },
    )


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
    """Reviews hypotheses in parallel (original approach), one call each.

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
        List of reviews (one per hypothesis). No concurrency semaphore is
        applied; gather preserves order so results align with `hypotheses`.
    """
    review_tasks = _build_parallel_review_tasks(
        hypotheses,
        research_goal,
        model_name,
        supervisor_guidance,
        meta_review,
        run_id,
        tool_registry,
        run_setup_guidance,
        run_focus_guidance,
    )
    return await asyncio.gather(*review_tasks)


def _build_parallel_review_tasks(
    hypotheses: list[Hypothesis],
    research_goal: str,
    model_name: str,
    supervisor_guidance: dict[str, Any] | None,
    meta_review: dict[str, Any] | None,
    run_id: str | None,
    tool_registry: Any | None,
    run_setup_guidance: str | None,
    run_focus_guidance: str | None,
) -> list[Coroutine[Any, Any, HypothesisReview]]:
    """Builds one review_single_hypothesis coroutine per hypothesis."""
    return [
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
        )
        for i, hyp in enumerate(hypotheses)
    ]


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
    """Reviews hypotheses in a single comparative batch (one LLM call).

    All hypotheses are shown together for relative comparison, producing
    more differentiated scores but limited by token constraints. Returns
    one review per hypothesis. The optional guidance parameters and the
    tool registry feed the prompt as context; ``run_id`` only names saved
    prompts.
    """
    response = await _run_batch_review_call(
        hypotheses,
        research_goal,
        model_name,
        supervisor_guidance,
        meta_review,
        run_id,
        tool_registry,
        run_setup_guidance,
        run_focus_guidance,
    )
    return _parse_batch_review_response(response, hypotheses, run_id)


async def _run_batch_review_call(
    hypotheses: list[Hypothesis],
    research_goal: str,
    model_name: str,
    supervisor_guidance: dict[str, Any] | None,
    meta_review: dict[str, Any] | None,
    run_id: str | None,
    tool_registry: Any | None,
    run_setup_guidance: str | None,
    run_focus_guidance: str | None,
) -> dict[str, Any]:
    """Prepares the batch-review prompt and calls the LLM for it."""
    prompt, schema, max_tokens, max_attempts = _prepare_batch_review_call(
        hypotheses,
        research_goal,
        supervisor_guidance,
        meta_review,
        tool_registry,
        run_setup_guidance,
        run_focus_guidance,
    )
    return await _call_batch_review_llm(
        prompt, schema, max_tokens, max_attempts, model_name, run_id, hypotheses
    )


async def _call_batch_review_llm(
    prompt: str,
    schema: dict[str, Any] | None,
    max_tokens: int,
    max_attempts: int,
    model_name: str,
    run_id: str | None,
    hypotheses: list[Hypothesis],
) -> dict[str, Any]:
    """Calls the LLM to review a comparative batch of hypotheses."""
    return await call_llm_json(
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
    kwargs: dict[str, Any] = {
        "hypotheses": hypotheses,
        "research_goal": state["research_goal"],
        "model_name": state["model_name"],
        "supervisor_guidance": state.get("supervisor_guidance"),
        "meta_review": state.get("meta_review"),
        "run_id": state.get("run_id"),
        "tool_registry": state.get("tool_registry"),
        "run_setup_guidance": state.get("run_setup_guidance"),
        "run_focus_guidance": state.get("run_focus_guidance"),
    }
    if use_comparative:
        # Single batch call.
        return await review_comparative_batch(**kwargs), 1
    # One call per hypothesis.
    return await review_parallel_individual(**kwargs), len(hypotheses)


async def review_node(state: WorkflowState) -> dict[str, Any]:
    """Reviews unreviewed hypotheses using adaptive strategy.

    Only hypotheses without an existing review are sent to the LLM: evolution
    appends immutable children to an ever-growing pool, so re-reviewing the
    whole pool on every pass would cost O(n^2) LLM calls across a run. The
    already-reviewed hypotheses keep their reviews and are returned unchanged.

    Strategy selection (by unreviewed count):
    - Small batches (≤5): Comparative batch review for differentiated scores
    - Large batches (>5): Parallel individual reviews for scalability

    Args:
        state: Current workflow state

    Returns:
        Dictionary with updated state fields
    """
    hypotheses = state["hypotheses"]
    unreviewed = [hyp for hyp in hypotheses if not hyp.reviews]
    _log_review_intake(hypotheses, unreviewed)

    if not unreviewed:
        return _skipped_review_result(hypotheses)

    reviews, llm_calls, strategy_name = await _run_review_phase(
        state, unreviewed
    )

    return _review_node_result(hypotheses, reviews, llm_calls, strategy_name)


async def _run_review_phase(
    state: WorkflowState, unreviewed: list[Hypothesis]
) -> tuple[list[HypothesisReview], int, str]:
    """Selects a strategy, runs it, and finalizes the review results.

    Emits progress before and after; emit_progress is a no-op unless a
    progress_callback was wired into state.
    """
    use_comparative, strategy_name = _select_review_strategy(len(unreviewed))

    await emit_progress(
        state,
        "review_start",
        f"Reviewing {len(unreviewed)} hypotheses...",
        PROGRESS_REVIEW_START,
    )

    reviews, llm_calls = await _run_review_strategy(
        state, unreviewed, use_comparative
    )

    _finalize_reviews(unreviewed, reviews, strategy_name)

    await emit_progress(
        state,
        "review_complete",
        f"Completed {len(reviews)} reviews",
        PROGRESS_REVIEW_COMPLETE,
        reviews_count=len(reviews),
    )

    return reviews, llm_calls, strategy_name


def _log_review_intake(
    hypotheses: list[Hypothesis], unreviewed: list[Hypothesis]
) -> None:
    """Logs the incoming review batch size."""
    logger.info("Starting review node")
    logger.info(
        "Reviewing %s unreviewed of %s hypotheses",
        len(unreviewed),
        len(hypotheses),
    )


def _skipped_review_result(hypotheses: list[Hypothesis]) -> dict[str, Any]:
    """Builds the review_node result when there are no unreviewed hypotheses."""
    return {
        "hypotheses": hypotheses,
        "messages": phase_message(
            "review",
            "No unreviewed hypotheses; review skipped",
            strategy="skipped",
        ),
    }


def _finalize_reviews(
    unreviewed: list[Hypothesis],
    reviews: list[HypothesisReview],
    strategy_name: str,
) -> None:
    """Validates, attaches, and gates completed reviews in place."""
    _validate_reviews(reviews)
    _attach_reviews_to_hypotheses(unreviewed, reviews)
    _apply_initial_review_gate(unreviewed, reviews)
    logger.info(
        "Completed %s reviews using %s strategy", len(reviews), strategy_name
    )


def _review_node_result(
    hypotheses: list[Hypothesis],
    reviews: list[HypothesisReview],
    llm_calls: int,
    strategy_name: str,
) -> dict[str, Any]:
    """Builds the final review_node state delta with metrics."""
    # Update metrics (deltas only, merge_metrics will add to existing state)
    metrics = create_metrics_update(
        reviews_count_delta=len(reviews), llm_calls_delta=llm_calls
    )
    logger.debug(
        "review node creating metrics delta: reviews=%s, llm_calls=%s",
        len(reviews),
        llm_calls,
    )

    return {
        "hypotheses": hypotheses,
        "metrics": metrics,
        "messages": phase_message(
            "review",
            f"Reviewed {len(reviews)} hypotheses ({strategy_name})",
            strategy=strategy_name,
        ),
    }
