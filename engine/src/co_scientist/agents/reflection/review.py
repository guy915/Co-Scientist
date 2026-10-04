"""Initial hypothesis review, criteria projection and result assembly."""

import asyncio
import dataclasses
import logging
from collections.abc import Coroutine
from typing import Any

from co_scientist.agents.reflection.review_gate import (
    apply_initial_review_gate,
)
from co_scientist.agents.reflection.review_gate import (
    refresh_review_dispositions as refresh_review_dispositions,
)
from co_scientist.constants import (
    COMPARATIVE_BATCH_THRESHOLD,
    EXTENDED_MAX_TOKENS,
    HIGH_TEMPERATURE,
    PROGRESS_REVIEW_COMPLETE,
    PROGRESS_REVIEW_START,
    REVIEW_BATCH_FREE_HYPOTHESES,
    REVIEW_BATCH_MAX_TOKENS_CAP,
    REVIEW_BATCH_TOKENS_PER_HYPOTHESIS,
    THINKING_MAX_TOKENS,
    scaled_max_tokens,
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
from co_scientist.prompts import (
    PromptRunContext,
    get_review_batch_prompt,
    get_review_prompt,
)
from co_scientist.schemas.review import (
    REVIEW_SCORE_MAXIMUM,
    REVIEW_SCORE_MINIMUM,
)
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class ReviewContext:
    """Run-level context shared by every review call this pass.

    Threaded unchanged into each hypothesis review (single, batch, or
    parallel) so the prompt sees the same research goal and guidance
    regardless of which hypotheses are being reviewed.
    """

    research_goal: str
    model_name: str
    run_id: str | None = None
    supervisor_guidance: dict[str, Any] | None = None
    meta_review: dict[str, Any] | None = None
    tool_registry: Any | None = None
    run_setup_guidance: str | None = None
    run_focus_guidance: str | None = None

    @classmethod
    def from_state(cls, state: WorkflowState) -> "ReviewContext":
        """Builds the review context from the current workflow state."""
        return cls(
            research_goal=state["research_goal"],
            model_name=state["model_name"],
            run_id=state.get("run_id"),
            supervisor_guidance=state.get("supervisor_guidance"),
            meta_review=state.get("meta_review"),
            tool_registry=state.get("tool_registry"),
            run_setup_guidance=state.get("run_setup_guidance"),
            run_focus_guidance=state.get("run_focus_guidance"),
        )


@dataclasses.dataclass(frozen=True)
class _BatchReviewCall:
    """A prepared batch-review prompt and its token/retry budget."""

    prompt: str
    schema: dict[str, Any] | None
    max_tokens: int
    max_attempts: int


def _sanitize_review_scores(scores: Any) -> dict[str, int]:
    """Keeps only rubric-valid criterion scores from an LLM payload.

    The schema bounds scores to the rubric's integer range, but
    production routes structured output through providers whose
    json_object mode does not enforce a schema, so out-of-range or
    non-numeric values arrive anyway. An invalid value is dropped rather
    than clamped: the initial review gate reads a missing score as
    neutral, and clamping a schema violation onto the rubric floor would
    let a parse defect masquerade as the worst possible review.

    Args:
        scores: The raw ``scores`` value from a review payload (any
            shape; a non-dict yields no scores).

    Returns:
        Criterion -> integer score, restricted to the rubric range.
    """
    if not isinstance(scores, dict):
        return {}
    sanitized: dict[str, int] = {}
    for name, value in scores.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            logger.debug("dropping non-numeric review score %s=%r", name, value)
            continue
        if not REVIEW_SCORE_MINIMUM <= value <= REVIEW_SCORE_MAXIMUM:
            logger.debug(
                "dropping out-of-range review score %s=%r", name, value
            )
            continue
        sanitized[str(name)] = round(value)
    return sanitized


def _sanitize_novelty_list(value: Any) -> list[str]:
    """Keeps only non-empty string entries from a novelty-review list.

    Production routes structured output through providers whose json_object
    mode does not enforce a schema, so a malformed or missing list must
    degrade to empty rather than raise.

    Args:
        value: The raw ``already_explored``/``novel_aspects`` value.

    Returns:
        Non-empty, whitespace-stripped string entries, in order.
    """
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := str(item).strip())]


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
    scores = _sanitize_review_scores(data.get("scores"))
    novelty_review = data.get("novelty_review")
    if not isinstance(novelty_review, dict):
        novelty_review = {}
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
        already_explored=_sanitize_novelty_list(
            novelty_review.get("already_explored")
        ),
        novel_aspects=_sanitize_novelty_list(
            novelty_review.get("novel_aspects")
        ),
    )


def _prepare_batch_review_call(
    hypotheses: list[Hypothesis],
    context: ReviewContext,
) -> _BatchReviewCall:
    """Builds the batch-review prompt and derives its token/retry budget.

    Args:
        hypotheses: Hypotheses to include in the batch prompt.
        context: Run-level review context (research goal, guidance, tool
            registry).

    Returns:
        The prepared batch-review call (prompt, schema, token/retry budget).
    """
    prompt, schema = get_review_batch_prompt(
        research_goal=context.research_goal,
        hypotheses_list=_build_hypotheses_list_text(hypotheses),
        context=PromptRunContext(
            supervisor_guidance=context.supervisor_guidance,
            meta_review=context.meta_review,
            tool_registry=context.tool_registry,
            run_setup_guidance=context.run_setup_guidance,
            run_focus_guidance=context.run_focus_guidance,
        ),
    )
    hypothesis_count = len(hypotheses)
    max_tokens, max_attempts = _scaled_batch_review_budget(hypothesis_count)
    logger.debug(
        "batch review: %s hypotheses, max_tokens=%s",
        hypothesis_count,
        max_tokens,
    )
    return _BatchReviewCall(
        prompt=prompt,
        schema=schema,
        max_tokens=max_tokens,
        max_attempts=max_attempts,
    )


def _build_hypotheses_list_text(hypotheses: list[Hypothesis]) -> str:
    """Formats hypotheses as a 1-based numbered list for the batch prompt.

    The numbering is load-bearing: each review entry in the response names
    its hypothesis by this number (``hypothesis_index``), and the parser
    maps entries back by it. 1-based, like every scientist-facing label
    (see meta_review's identical convention) -- never count from 0.
    """
    return "\n\n".join(
        [
            f"**Hypothesis {number}:**\n{hyp.text}"
            for number, hyp in enumerate(hypotheses, start=1)
        ]
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
            "Inspect review_batch call diagnostics for run %s",
            len(hypotheses),
            len(reviews_data),
            run_id,
        )


def _match_batch_entries_to_hypotheses(
    reviews_data: list[Any],
    hypothesis_count: int,
) -> list[Any]:
    """Associates batch-review entries with hypotheses by their number.

    Each entry's ``hypothesis_index`` is the number the prompt assigned
    (1-based). Entries with a valid, not-yet-claimed number land on that
    hypothesis regardless of list order; entries whose number is absent,
    non-integer, out of range, or duplicated fall back to filling the
    still-empty slots in list order. Surplus entries are dropped.

    Args:
        reviews_data: the "reviews" list pulled from the batch response.
        hypothesis_count: number of hypotheses in the batch.

    Returns:
        One entry (raw item or None) per hypothesis, in hypothesis order.
    """
    slots: list[Any] = [None] * hypothesis_count
    unplaced: list[Any] = []
    claimed: set[int] = set()
    for entry in reviews_data:
        number = (
            entry.get("hypothesis_index") if isinstance(entry, dict) else None
        )
        if (
            isinstance(number, int)
            and not isinstance(number, bool)
            and 1 <= number <= hypothesis_count
            and number not in claimed
        ):
            slots[number - 1] = entry
            claimed.add(number)
        else:
            unplaced.append(entry)

    remaining = iter(unplaced)
    for index in range(hypothesis_count):
        if slots[index] is None:
            slots[index] = next(remaining, None)
    return slots


def _convert_matched_entry(
    entry: Any, position: int
) -> HypothesisReview | None:
    """Converts one matched batch entry, isolating its parse failures.

    A malformed entry (a non-dict item, an unparseable payload) is logged
    and recorded as None rather than raised: one bad entry must not abort
    the batch the other entries belong to (audit E15). The caller counts
    the Nones and leaves those hypotheses for the next review pass.

    Args:
        entry: The batch entry matched to this position, or None when the
            LLM produced no entry for it.
        position: 1-based hypothesis number, for logging.

    Returns:
        The parsed review, or None when the entry is missing or malformed.
    """
    if entry is None:
        logger.error("No review data for hypothesis %s", position)
        return None
    try:
        return _review_from_response(entry)
    except (AttributeError, KeyError, TypeError, ValueError):
        logger.warning(
            "Malformed review entry for hypothesis %s; recording it as"
            " a failed review instead of aborting the batch",
            position,
        )
        return None


def _parse_batch_review_response(
    response: dict[str, Any],
    hypotheses: list[Hypothesis],
    run_id: str | None,
) -> list[HypothesisReview | None]:
    """Parses a batch-review LLM response into per-hypothesis reviews.

    Entries are associated with hypotheses by their ``hypothesis_index``
    (the number the prompt assigned), not by list order; a missing or
    malformed entry is recorded as None for its hypothesis while the rest
    of the batch still applies (audit E15).

    Args:
        response: raw LLM JSON response from the batch review call.
        hypotheses: hypotheses that were reviewed, in prompt order.
        run_id: optional run ID, referenced in the mismatch log message.

    Returns:
        One review per hypothesis in hypothesis order, None where the
        entry was missing or malformed.
    """
    reviews_data = response.get("reviews", [])
    _log_batch_review_response_shape(response, reviews_data, hypotheses, run_id)
    matched = _match_batch_entries_to_hypotheses(reviews_data, len(hypotheses))
    return [
        _convert_matched_entry(entry, position)
        for position, entry in enumerate(matched, start=1)
    ]


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


def _split_reviews_by_result(
    hypotheses: list[Hypothesis],
    reviews: list[HypothesisReview | None],
) -> tuple[list[tuple[Hypothesis, HypothesisReview]], int]:
    """Partitions reviewed hypotheses into successes and failures.

    A None marks a hypothesis whose review failed (a missing or malformed
    entry, or a failed individual call). Failed hypotheses get nothing
    attached -- they stay unreviewed, so the next review pass picks them
    up again rather than ranking them on a placeholder scored 0.0 (the
    defect the old fail-loud placeholder validation existed to prevent).

    Args:
        hypotheses: Hypotheses that went into this review pass.
        reviews: One review (or None) per hypothesis, same order.

    Returns:
        Tuple of (successful (hypothesis, review) pairs, failure count).
    """
    pairs = [
        (hypothesis, review)
        for hypothesis, review in zip(hypotheses, reviews, strict=True)
        if review is not None
    ]
    return pairs, len(hypotheses) - len(pairs)


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


_apply_initial_review_gate = apply_initial_review_gate


async def review_single_hypothesis(
    hypothesis_text: str,
    context: ReviewContext,
    hypothesis_index: int | None = None,
) -> HypothesisReview:
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
    """Gathered failures leave peer reviews running."""
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
    """Relative scoring shares a token budget; malformed entries fail alone."""
    response = await _run_batch_review_call(hypotheses, context)
    return _parse_batch_review_response(response, hypotheses, context.run_id)


async def _run_batch_review_call(
    hypotheses: list[Hypothesis],
    context: ReviewContext,
) -> dict[str, Any]:
    call = _prepare_batch_review_call(hypotheses, context)
    return await _call_batch_review_llm(call, context)


async def _call_batch_review_llm(
    call: _BatchReviewCall,
    context: ReviewContext,
) -> dict[str, Any]:
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
