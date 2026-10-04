"""Durable task outcome classification for the worker loop.

Holds the worker's failure taxonomy and outcome recorders: the two
exception types the loop keys on (``_LeaseLostError``,
``UnsupportedTaskError``) and the helpers that durably record a settled
task -- success, superseded-checkpoint completion, the single permanent
failure, and the retryable default. Split from ``task_worker`` by concern;
``task_worker`` re-exports the names tests and callers use so its namespace
(the seam they patch/import against) keeps resolving.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from co_scientist.exceptions import (
    LLMCallBudgetExceededError,
    LLMRateLimitParkError,
    LLMTimeoutError,
)

from app import engine_tasks, store
from app.engine_tasks.portfolio import cancel_downstream_portfolio_chain
from app.store import ScientificTask
from app.store.models import UNKNOWN_PROVIDER_OUTCOME_ERROR

logger = logging.getLogger(__name__)

# Persist rate-limit parks beside stage records without inventing SSE progress.
_stage_logger = logging.getLogger("app.run_stage")

# Spreads several tasks parked at the same platform-cap reset instant
# across a few seconds of claim polling instead of all becoming due, and
# racing to claim, in the same tick.
_RATE_LIMIT_PARK_JITTER_SECONDS = 15.0

_FAILURE_KINDS = {
    LLMCallBudgetExceededError: "llm_call_budget_exceeded",
    LLMTimeoutError: "llm_timeout",
}


def _failure_kind(exc: Exception) -> str | None:
    """Classify only the exact provider failure types with user guidance."""
    if isinstance(exc, LLMTimeoutError):
        return (
            "llm_timeout" if exc.zero_cost_admitted else "llm_timeout_unknown"
        )
    return _FAILURE_KINDS.get(type(exc))


def _failure_error(exc: Exception) -> str | store.TaskFailure:
    """Carry a typed kind and safe error text to task storage."""
    if isinstance(exc, LLMTimeoutError) and not exc.zero_cost_admitted:
        return store.TaskFailure(
            UNKNOWN_PROVIDER_OUTCOME_ERROR, "llm_timeout_unknown"
        )
    kind = _failure_kind(exc)
    return store.TaskFailure(str(exc), kind) if kind is not None else str(exc)


class _LeaseLostError(RuntimeError):
    """Signals that durable ownership ended while task code was running."""


class UnsupportedTaskError(ValueError):
    """A task type no worker knows how to execute.

    The one genuinely permanent failure a worker can hit: retrying cannot
    teach it a task type it has no branch for. Everything else reaching the
    worker boundary -- above all a provider returning empty content, which
    the engine signals with a bare ValueError -- is transient and must keep
    its retry budget. Subclasses ValueError so existing callers that catch
    ValueError still see it.
    """


def _complete_superseded_task(
    task: ScientificTask, worker_id: str, exc: Exception, db_path: str | None
) -> None:
    """Record a superseded task as a successful idempotent outcome.

    Competing durable branches can finish after another branch advances the
    checkpoint. Obsolescence is a successful idempotent outcome, not a
    scientific failure, and must not consume the retry budget.
    """
    result = {"superseded": True, "reason": str(exc)}
    if not store.complete_task(task.id, worker_id, result, db_path=db_path):
        logger.warning("Task %s lost its lease while superseded", task.id)
    else:
        logger.info("Task %s superseded by a newer checkpoint", task.id)


def _park_held_task(
    task: ScientificTask, worker_id: str, exc: Exception, db_path: str | None
) -> None:
    """Park a task a safety gate held, awaiting a reviewer's decision.

    Not a failure: nothing this worker can do resolves a hold, so the
    wait must not spend the retry budget. Not a success either --
    recording it as one is what stranded the run, since a succeeded row is
    never revived and the boundary's idempotency key cannot change while
    the run makes no progress, so approval re-enqueued nothing. Parked,
    the row is what ``resume_run_tasks`` releases once the hold is
    approved.
    """
    if not store.park_task(task.id, worker_id, str(exc), db_path=db_path):
        logger.warning("Task %s lost its lease while held", task.id)
    else:
        logger.info("Task %s parked pending safety review", task.id)


def _log_rate_limit_park(run_id: str, resume_at: float, reason: str) -> None:
    """Mirror a rate-limit park into the app log as a run-stage record.

    Imported lazily like ``store.events._log_stage``'s own helper does,
    for the same reason: ``app.logging_setup`` imports ``app.store``, so a
    module-level import back the other way would cycle.
    """
    from app.logging_setup import run_log_context

    parked_until = datetime.fromtimestamp(
        resume_at, tz=timezone.utc
    ).isoformat()
    with run_log_context(run_id):
        _stage_logger.info(
            "rate_limit parked_until=%s reason=%s",
            parked_until,
            reason,
            extra={"run_id": run_id},
        )


def _park_rate_limited_task(
    task: ScientificTask,
    worker_id: str,
    exc: LLMRateLimitParkError,
    db_path: str | None,
) -> None:
    """Return a task to the queue until a platform rate-limit cap resets.

    Neither a failure nor a retry. Not a failure: nothing this worker can
    do makes the cap reset sooner, so the wait must not spend the retry
    budget -- the same reasoning ``_park_held_task`` applies to a safety
    hold, except this one resumes on its own once the clock passes rather
    than waiting on a person. Not a retry either: the call that raised
    this already counted itself against ``record_provider_request`` when
    it made its one doomed attempt, and parking makes no further call, so
    nothing here double-counts it.
    """
    resume_at = exc.resume_at + random.uniform(
        0, _RATE_LIMIT_PARK_JITTER_SECONDS
    )
    if not store.park_task_for_rate_limit(
        task.id, worker_id, str(exc), resume_at, db_path=db_path
    ):
        logger.warning(
            "Task %s lost its lease while rate-limit parked", task.id
        )
        return
    _log_rate_limit_park(task.run_id, resume_at, exc.reason)
    logger.info(
        "Task %s parked for a platform rate-limit cap (%s) until %.0f",
        task.id,
        exc.reason,
        resume_at,
    )


def _is_terminal_failure(task: ScientificTask, *, retryable: bool) -> bool:
    """Mirror ``app.store.tasks.fail_task``'s own retry-left formula.

    That function decides queued-for-retry versus failed from this exact
    task snapshot and ``retryable`` flag, inside its own transaction this
    module has no access to. Computing the same answer here, read-only,
    lets a permanently failing task's downstream portfolio chain
    (finding F4) be cancelled *before* ``fail_task`` commits, so its own
    "settle the run if nothing claimable remains" check
    (``app.store.runs_views``) sees the cancelled chain already gone
    rather than finding a queued row and silently declining to settle --
    its one chance to fire, since nothing revisits that decision later.
    """
    return not retryable or task.attempt >= task.max_attempts


def _cancel_downstream_before_terminal_failure(
    task: ScientificTask, *, retryable: bool, db_path: str | None
) -> None:
    """Cancel a permanently failing task's downstream chain, if any.

    Skipped for an ordinary retry: cancelling ahead of one would strand
    the chain a *successful* retry still needs to reuse, since a
    cancelled row is never revived by a later idempotent enqueue attempt
    (finding F4's terminal-path gap -- see ``cancel_downstream_
    portfolio_chain``).
    """
    if _is_terminal_failure(task, retryable=retryable):
        cancel_downstream_portfolio_chain(task, db_path)


def _fail_permanent_task(
    task: ScientificTask, worker_id: str, exc: Exception, db_path: str | None
) -> None:
    """Fail unsupported work or an exhausted call budget without retrying."""
    _cancel_downstream_before_terminal_failure(
        task, retryable=False, db_path=db_path
    )
    store.fail_task(
        task.id,
        worker_id,
        _failure_error(exc),
        retryable=False,
        db_path=db_path,
    )
    if isinstance(exc, LLMCallBudgetExceededError):
        from co_scientist.llm import release_run_call_budget

        release_run_call_budget(task.run_id)
        logger.error("Task %s aborted: %s", task.id, exc)
    else:
        logger.error("Task %s rejected: %s", task.id, exc)


def _fail_retryable_task(
    task: ScientificTask, worker_id: str, exc: Exception, db_path: str | None
) -> None:
    """Fail one task while preserving its retry budget.

    Worker boundary isolates one task failure from the rest of the cohort.
    """
    retryable = not isinstance(exc, LLMTimeoutError) or exc.zero_cost_admitted
    retry_at = None
    if isinstance(exc, LLMTimeoutError) and exc.zero_cost_admitted:
        from co_scientist.llm import provider_outage_backoff_seconds

        retry_at = time.time() + provider_outage_backoff_seconds(task.attempt)
    unknown_provider_outcome = (
        isinstance(exc, LLMTimeoutError) and not exc.zero_cost_admitted
    )
    if not unknown_provider_outcome:
        _cancel_downstream_before_terminal_failure(
            task, retryable=retryable, db_path=db_path
        )
    store.fail_task(
        task.id,
        worker_id,
        _failure_error(exc),
        retryable=retryable,
        retry_at=retry_at,
        stop_run=unknown_provider_outcome,
        db_path=db_path,
    )
    if isinstance(exc, LLMTimeoutError) and not exc.zero_cost_admitted:
        logger.exception(
            "Task %s failed with an unknown provider outcome", task.id
        )
    else:
        logger.exception("Task %s failed", task.id)


# Ordered exactly like the except-clause chain this replaced: the first
# matching type wins, and an exception matching none of them falls through
# to the retryable default below. A table rather than an if/elif chain
# keeps this dispatch's own complexity flat as failure kinds are added --
# the classification lives in the table, not in a growing branch count.
_FailureHandler = Callable[[ScientificTask, str, Any, "str | None"], None]
_FAILURE_HANDLERS: tuple[tuple[type[Exception], _FailureHandler], ...] = (
    (engine_tasks.SupersededTaskError, _complete_superseded_task),
    (engine_tasks.SafetyHoldError, _park_held_task),
    (LLMRateLimitParkError, _park_rate_limited_task),
    (UnsupportedTaskError, _fail_permanent_task),
    (LLMCallBudgetExceededError, _fail_permanent_task),
)


def _handle_task_failure(
    task: ScientificTask, worker_id: str, exc: Exception, db_path: str | None
) -> None:
    """Classify one task failure and record its outcome accordingly.

    Preserves the original except-clause priority exactly: a superseded
    checkpoint is a successful idempotent outcome, a safety hold is a
    durable wait for a person, a platform rate-limit cap is a durable wait
    for a clock, an unsupported task type or an exceeded LLM-call ceiling
    are the two permanent failures, and everything else keeps its retry
    budget.
    """
    for exc_type, handler in _FAILURE_HANDLERS:
        if isinstance(exc, exc_type):
            handler(task, worker_id, exc, db_path)
            return
    _fail_retryable_task(task, worker_id, exc, db_path)


def _record_success(
    task: ScientificTask,
    worker_id: str,
    result: dict[str, Any],
    db_path: str | None,
) -> None:
    """Persist a task's result if this worker still owns its lease."""
    if not store.complete_task(task.id, worker_id, result, db_path=db_path):
        logger.warning("Task %s lost its lease before completion", task.id)
