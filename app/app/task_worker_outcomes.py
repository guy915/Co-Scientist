"""Durable task outcome classification for the worker loop.

Holds the worker's failure taxonomy and outcome recorders: the two
exception types the loop keys on (``_LeaseLostError``,
``UnsupportedTaskError``) and the helpers that durably record a settled
task -- success, superseded-checkpoint completion, the single permanent
failure, and the retryable default. Split from ``task_worker`` by concern;
``task_worker`` re-exports every name so its namespace (the seam tests and
callers patch/import against) keeps resolving.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from co_scientist.exceptions import (
    LLMCallBudgetExceededError,
    LLMRateLimitParkError,
)

from app import engine_tasks, store
from app.engine_tasks_portfolio import cancel_downstream_portfolio_chain
from app.store import ScientificTask

logger = logging.getLogger(__name__)

# Mirrors store.events._stage_logger's own name, so a rate-limit park reads
# in the Logs panel/`cosci logs` exactly like an ordinary run-stage line
# (see store/events.py's module docstring) without going through the
# run_events/SSE path -- there is nothing here a live viewer needs to see
# mid-stream, only a durable record of why the task is waiting.
_stage_logger = logging.getLogger("app.run_stage")

# Spreads several tasks parked at the same platform-cap reset instant
# across a few seconds of claim polling instead of all becoming due, and
# racing to claim, in the same tick.
_RATE_LIMIT_PARK_JITTER_SECONDS = 15.0


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
    (``app.store.runs_reconcile``) sees the cancelled chain already gone
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


def _fail_unsupported_task(
    task: ScientificTask, worker_id: str, exc: Exception, db_path: str | None
) -> None:
    """Permanently fail a task type no worker branch can execute.

    The only failure retrying cannot fix. Everything else reaching the
    worker boundary -- notably a provider returning empty content, which the
    engine raises as a bare ValueError -- falls through to the retryable
    branch instead.
    """
    _cancel_downstream_before_terminal_failure(
        task, retryable=False, db_path=db_path
    )
    store.fail_task(
        task.id, worker_id, str(exc), retryable=False, db_path=db_path
    )
    logger.error("Task %s rejected: %s", task.id, exc)


def _fail_llm_budget_exceeded_task(
    task: ScientificTask, worker_id: str, exc: Exception, db_path: str | None
) -> None:
    """Permanently fail a task whose run overran its LLM-call ceiling.

    The run has already spent past ``max_llm_calls``; nothing a retry
    could do reduces that spend, so this is the same shape as
    ``_fail_unsupported_task`` -- retry budget skipped outright, not
    exhausted one attempt at a time -- rather than the default retryable
    branch. ``fail_task``'s error text becomes the run's terminal reason
    (see ``store.runs_reconcile._settle_run_for_failed_task``), and
    ``LLMCallBudgetExceededError.__str__`` names the count and the
    ceiling, so the run's recorded failure reads as a ceiling hit rather
    than a generic task failure.
    """
    from co_scientist.llm_call_budget import release_run_call_budget

    _cancel_downstream_before_terminal_failure(
        task, retryable=False, db_path=db_path
    )
    store.fail_task(
        task.id, worker_id, str(exc), retryable=False, db_path=db_path
    )
    release_run_call_budget(task.run_id)
    logger.error("Task %s aborted: %s", task.id, exc)


def _fail_retryable_task(
    task: ScientificTask, worker_id: str, exc: Exception, db_path: str | None
) -> None:
    """Fail one task while preserving its retry budget.

    Worker boundary isolates one task failure from the rest of the cohort.
    """
    _cancel_downstream_before_terminal_failure(
        task, retryable=True, db_path=db_path
    )
    store.fail_task(
        task.id, worker_id, str(exc), retryable=True, db_path=db_path
    )
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
    (UnsupportedTaskError, _fail_unsupported_task),
    (LLMCallBudgetExceededError, _fail_llm_budget_exceeded_task),
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
