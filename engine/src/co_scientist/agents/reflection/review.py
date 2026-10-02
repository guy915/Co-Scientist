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

from co_scientist.agents.reflection.review_gate import (
    apply_initial_review_gate,
)
from co_scientist.agents.reflection.review_gate import (
    refresh_review_dispositions as refresh_review_dispositions,
)
from co_scientist.agents.reflection.review_helpers import (
    ReviewContext as ReviewContext,
)
from co_scientist.agents.reflection.review_helpers import (
    _attach_reviews_to_hypotheses as _attach_reviews_to_hypotheses,
)
from co_scientist.agents.reflection.review_helpers import (
    _BatchReviewCall as _BatchReviewCall,
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
    _split_reviews_by_result as _split_reviews_by_result,
)
from co_scientist.constants import (
    EXTENDED_MAX_TOKENS,
    HIGH_TEMPERATURE,
    PROGRESS_REVIEW_COMPLETE,
    PROGRESS_REVIEW_START,
)
from co_scientist.exceptions import TASK_CONTROL_FLOW_ERRORS
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    call_llm_json,
    indexed_prompt_name,
)
from co_scientist.models import (
    Hypothesis,
    HypothesisReview,
    MetricDeltas,
    create_metrics_update,
    has_peer_review,
    phase_message,
)
from co_scientist.progress import emit_progress
from co_scientist.prompts import PromptRunContext, get_review_prompt
from co_scientist.state import WorkflowState

_apply_initial_review_gate = apply_initial_review_gate

logger = logging.getLogger(__name__)


async def review_single_hypothesis(
    hypothesis_text: str,
    context: ReviewContext,
    hypothesis_index: int | None = None,
) -> HypothesisReview:
    """Reviews a single hypothesis and returns its ``HypothesisReview``.

    ``context`` supplies the research goal, model, run id, and the optional
    guidance (supervisor, meta-review, run setup/focus) and tool registry
    that feed the prompt; ``hypothesis_index`` only names the saved prompt.
    """
    prompt, schema = get_review_prompt(
        research_goal=context.research_goal,
        hypothesis_text=hypothesis_text,
        context=PromptRunContext(
            supervisor_guidance=context.supervisor_guidance,
            meta_review=context.meta_review,
            tool_registry=context.tool_registry,
            run_setup_guidance=context.run_setup_guidance,
            run_focus_guidance=context.run_focus_guidance,
        ),
    )
    response = await _call_review_llm(
        prompt, schema, context.model_name, context.run_id, hypothesis_index
    )
    return _review_from_response(response)


async def _call_review_llm(
    prompt: str,
    schema: dict[str, Any] | None,
    model_name: str,
    run_id: str | None,
    hypothesis_index: int | None,
) -> dict[str, Any]:
    """Calls the LLM to review a single hypothesis.

    Failures raise out of this coroutine; review_parallel_individual
    gathers with return_exceptions and records the failure against that
    one hypothesis, so a single failed call no longer aborts the rest of
    the batch (audit E15).
    """
    return await call_llm_json(
        prompt=prompt,
        spec=CompletionSpec(
            model_name=model_name,
            max_tokens=EXTENDED_MAX_TOKENS,
            temperature=HIGH_TEMPERATURE,
            json_schema=schema,
        ),
        options=LLMCallOptions(
            run_id=run_id,
            prompt_name=indexed_prompt_name(
                "review_individual", hypothesis_index
            ),
            prompt_metadata={
                "hypothesis_index": hypothesis_index,
                "prompt_length_chars": len(prompt),
            },
        ),
    )


async def review_parallel_individual(
    hypotheses: list[Hypothesis],
    context: ReviewContext,
) -> list[HypothesisReview | None]:
    """Reviews hypotheses in parallel (original approach), one call each.

    Per-hypothesis failures are isolated (audit E15): gather collects
    exceptions instead of letting one raise abort the whole batch, and a
    failed call is recorded as None for its hypothesis while the other
    reviews still apply.

    Args:
        hypotheses: List of hypotheses to review
        context: Run-level review context threaded into every review

    Returns:
        One review per hypothesis (None where the call failed), aligned
        with `hypotheses`. No concurrency semaphore is applied.
    """
    review_tasks = _build_parallel_review_tasks(hypotheses, context)
    results = await asyncio.gather(*review_tasks, return_exceptions=True)
    return [
        _individual_review_result(result, index)
        for index, result in enumerate(results)
    ]


def _individual_review_result(
    result: HypothesisReview | BaseException,
    hypothesis_index: int,
) -> HypothesisReview | None:
    """Maps one gathered individual-review result, logging failures.

    ``gather(return_exceptions=True)`` collects a control-flow error as a
    value, which swallows it exactly as a bare handler would, so it is
    re-raised rather than recorded as a missing review: a rate-limit park
    is the worker's to wait out and a spent call budget ends the run, and
    neither describes *this* hypothesis (see ``TASK_CONTROL_FLOW_ERRORS``).

    Raises:
        LLMRateLimitParkError: A platform cap the worker must park on.
        LLMCallBudgetExceededError: The run's spend ceiling is exhausted.
    """
    if isinstance(result, TASK_CONTROL_FLOW_ERRORS):
        raise result
    if isinstance(result, BaseException):
        logger.warning(
            "Review failed for hypothesis %s: %s", hypothesis_index, result
        )
        return None
    return result


def _build_parallel_review_tasks(
    hypotheses: list[Hypothesis],
    context: ReviewContext,
) -> list[Coroutine[Any, Any, HypothesisReview]]:
    """Builds one review_single_hypothesis coroutine per hypothesis."""
    return [
        review_single_hypothesis(
            hypothesis_text=hyp.text,
            context=context,
            hypothesis_index=i,
        )
        for i, hyp in enumerate(hypotheses)
    ]


async def review_comparative_batch(
    hypotheses: list[Hypothesis],
    context: ReviewContext,
) -> list[HypothesisReview | None]:
    """Reviews hypotheses in a single comparative batch (one LLM call).

    All hypotheses are shown together for relative comparison, producing
    more differentiated scores but limited by token constraints. Returns
    one review per hypothesis, None where an entry was missing or
    malformed (audit E15 -- the rest of the batch still applies).
    ``context`` supplies the research goal, guidance, and tool registry
    as prompt context; its ``run_id`` only names saved prompts.
    """
    response = await _run_batch_review_call(hypotheses, context)
    return _parse_batch_review_response(response, hypotheses, context.run_id)


async def _run_batch_review_call(
    hypotheses: list[Hypothesis],
    context: ReviewContext,
) -> dict[str, Any]:
    """Prepares the batch-review prompt and calls the LLM for it."""
    call = _prepare_batch_review_call(hypotheses, context)
    return await _call_batch_review_llm(call, context, hypotheses)


async def _call_batch_review_llm(
    call: _BatchReviewCall,
    context: ReviewContext,
    hypotheses: list[Hypothesis],
) -> dict[str, Any]:
    """Calls the LLM to review a comparative batch of hypotheses."""
    return await call_llm_json(
        prompt=call.prompt,
        spec=CompletionSpec(
            model_name=context.model_name,
            max_tokens=call.max_tokens,
            temperature=HIGH_TEMPERATURE,
            json_schema=call.schema,
        ),
        max_attempts=call.max_attempts,
        options=LLMCallOptions(
            run_id=context.run_id,
            prompt_name="review_batch",
            prompt_metadata={
                "hypotheses_count": len(hypotheses),
                "scaled_max_tokens": call.max_tokens,
                "prompt_length_chars": len(call.prompt),
            },
        ),
    )


async def _run_review_strategy(
    state: WorkflowState,
    hypotheses: list[Hypothesis],
    use_comparative: bool,
) -> tuple[list[HypothesisReview | None], int]:
    """Gathers guidance from state and runs the chosen review strategy.

    Args:
        state: Current workflow state.
        hypotheses: Hypotheses to review.
        use_comparative: True to run comparative batch review, False to run
            parallel individual review.

    Returns:
        Tuple of (one review or None per hypothesis, llm_calls_used).
    """
    context = ReviewContext.from_state(state)
    if use_comparative:
        # Single batch call.
        return await review_comparative_batch(hypotheses, context), 1
    # One call per hypothesis.
    return (
        await review_parallel_individual(hypotheses, context),
        len(hypotheses),
    )


async def review_node(state: WorkflowState) -> dict[str, Any]:
    """Reviews unreviewed hypotheses using adaptive strategy.

    Only hypotheses without an existing review are sent to the LLM: evolution
    appends immutable children to an ever-growing pool, so re-reviewing the
    whole pool on every pass would cost O(n^2) LLM calls across a run. The
    already-reviewed hypotheses keep their reviews and are returned unchanged.
    Their *dispositions* are not: every pass re-derives those from the record
    each hypothesis holds (``refresh_review_dispositions``), which costs no
    LLM calls and is what stops one early review deciding an idea's standing
    for the rest of the run. That has to happen before the early return
    below, because a pass with nothing left to review is exactly when a
    verdict recorded since the last pass is waiting to be honoured.

    **Batching here is a reference-only simplification (FIX-9).**
    ``02-generation.md`` L24-26 and ``01-supervisor.md`` L34-38 create one
    ``Reflection / ReviewHypothesis`` task per hypothesis and queue each
    independently, and ``03-reflection.md`` L12 then fetches that one
    hypothesis by id. The
    canonical mirror of that chaining is the durable path
    (``app/app/engine_tasks/fanout.py::_enqueue_review_fanout``), which
    materializes one leasable task per unreviewed hypothesis and is what
    production runs. This node reviews a batch behind one synchronous
    barrier instead: for a pool of ≤5 that is a single comparative call
    against N, and this path carries no production cost pressure to justify
    the 5x. The divergence is deliberate and belongs to the reference
    engine; do not "fix" it by fanning out here.

    Strategy selection (by unreviewed count):
    - Small batches (≤5): Comparative batch review for differentiated scores
    - Large batches (>5): Parallel individual reviews for scalability

    Args:
        state: Current workflow state

    Returns:
        Dictionary with updated state fields
    """
    hypotheses = state["hypotheses"]
    refresh_review_dispositions(hypotheses, state.get("criteria"))
    unreviewed = [hyp for hyp in hypotheses if not has_peer_review(hyp)]
    _log_review_intake(hypotheses, unreviewed)

    if not unreviewed:
        return _skipped_review_result(hypotheses)

    reviews, llm_calls, strategy_name, failed_count = await _run_review_phase(
        state, unreviewed
    )

    return _review_node_result(
        hypotheses, reviews, llm_calls, strategy_name, failed_count
    )


async def _run_review_phase(
    state: WorkflowState, unreviewed: list[Hypothesis]
) -> tuple[list[HypothesisReview], int, str, int]:
    """Selects a strategy, runs it, and finalizes the review results.

    Emits progress before and after; emit_progress is a no-op unless a
    progress_callback was wired into state.

    Returns:
        Tuple of (successfully attached reviews, llm_calls_used,
        strategy_name, count of hypotheses whose review failed).
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

    attached, failed_count = _finalize_reviews(
        unreviewed, reviews, strategy_name, state.get("criteria")
    )

    await emit_progress(
        state,
        "review_complete",
        f"Completed {len(attached)} reviews",
        PROGRESS_REVIEW_COMPLETE,
        reviews_count=len(attached),
    )

    return attached, llm_calls, strategy_name, failed_count


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
    reviews: list[HypothesisReview | None],
    strategy_name: str,
    criteria: list[str] | None = None,
) -> tuple[list[HypothesisReview], int]:
    """Attaches and gates the successful reviews, counting the failures.

    A hypothesis whose review failed (None) gets nothing attached and
    keeps no disposition, so it stays unreviewed for the next review
    pass instead of aborting the whole batch (audit E15) or entering the
    tournament on a zero-scored placeholder.

    ``criteria`` are the scientist's evaluation criteria, which select the
    scored axes the gate consults (finding K4); absent criteria keep the
    built-in soundness/novelty pair.

    Returns:
        Tuple of (the attached reviews, count of failed reviews).
    """
    reviewed_pairs, failed_count = _split_reviews_by_result(unreviewed, reviews)
    if failed_count:
        logger.warning(
            "%s/%s reviews failed using %s strategy; those hypotheses"
            " stay unreviewed for the next review pass",
            failed_count,
            len(unreviewed),
            strategy_name,
        )
    reviewed_hypotheses = [hypothesis for hypothesis, _ in reviewed_pairs]
    attached_reviews = [review for _, review in reviewed_pairs]
    _attach_reviews_to_hypotheses(reviewed_hypotheses, attached_reviews)
    apply_initial_review_gate(reviewed_hypotheses, attached_reviews, criteria)
    logger.info(
        "Completed %s reviews using %s strategy",
        len(attached_reviews),
        strategy_name,
    )
    return attached_reviews, failed_count


def _review_node_result(
    hypotheses: list[Hypothesis],
    reviews: list[HypothesisReview],
    llm_calls: int,
    strategy_name: str,
    failed_count: int = 0,
) -> dict[str, Any]:
    """Builds the final review_node state delta with metrics."""
    # Update metrics (deltas only, merge_metrics will add to existing state)
    metrics = create_metrics_update(
        deltas=MetricDeltas(reviews=len(reviews), llm_calls=llm_calls)
    )
    logger.debug(
        "review node creating metrics delta: reviews=%s, llm_calls=%s",
        len(reviews),
        llm_calls,
    )

    summary = f"Reviewed {len(reviews)} hypotheses ({strategy_name})"
    if failed_count:
        summary += f"; {failed_count} review(s) failed and will be retried"

    return {
        "hypotheses": hypotheses,
        "metrics": metrics,
        "messages": phase_message(
            "review",
            summary,
            strategy=strategy_name,
            review_failures=failed_count,
        ),
    }
