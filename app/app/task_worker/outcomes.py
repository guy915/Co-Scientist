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

from app import engine_tasks
from app.engine_tasks.portfolio import cancel_downstream_portfolio_chain
from app.store import tasks
from app.store import tasks_lifecycle as store
from app.store.models import (
    UNKNOWN_PROVIDER_OUTCOME_ERROR,
    ScientificTask,
    TaskFailure,
)

logger = logging.getLogger(__name__)

# Persist rate-limit waits beside stage records without inventing scientific SSE
# progress.
_stage_logger = logging.getLogger("app.run_stage")

# Stagger tasks due at one platform-cap reset to avoid synchronized claim
# contention.
_RATE_LIMIT_PARK_JITTER_SECONDS = 15.0

_FAILURE_KINDS = {
    LLMCallBudgetExceededError: "llm_call_budget_exceeded",
    LLMTimeoutError: "llm_timeout",
}


def _failure_kind(exc: Exception) -> str | None:
    if isinstance(exc, LLMTimeoutError):
        return "llm_timeout" if exc.zero_cost_admitted else "llm_timeout_unknown"
    return _FAILURE_KINDS.get(type(exc))


def _failure_error(exc: Exception) -> str | TaskFailure:
    if isinstance(exc, LLMTimeoutError) and not exc.zero_cost_admitted:
        return TaskFailure(UNKNOWN_PROVIDER_OUTCOME_ERROR, "llm_timeout_unknown")
    kind = _failure_kind(exc)
    return TaskFailure(str(exc), kind) if kind is not None else str(exc)


class _LeaseLostError(RuntimeError):
    """Durable ownership ended while task code was running."""


class UnsupportedTaskError(ValueError):
    """Unknown task types cannot become executable through retry; ordinary
    provider failures remain transient.
    """


def _complete_superseded_task(
    task: ScientificTask, worker_id: str, exc: Exception, db_path: str | None
) -> None:
    """Checkpoint obsolescence is idempotent success, never a scientific
    failure or spent retry.
    """
    result = {"superseded": True, "reason": str(exc)}
    if not store.complete_task(task.id, worker_id, result, db_path=db_path):
        logger.warning("Task %s lost its lease while superseded", task.id)
    else:
        logger.info("Task %s superseded by a newer checkpoint", task.id)


def _park_held_task(
    task: ScientificTask, worker_id: str, exc: Exception, db_path: str | None
) -> None:
    """A human hold spends no retries and is not completion; park its
    boundary so approval can release it.
    """
    if not store.park_task(task.id, worker_id, str(exc), db_path=db_path):
        logger.warning("Task %s lost its lease while held", task.id)
    else:
        logger.info("Task %s parked pending safety review", task.id)


def _log_rate_limit_park(run_id: str, resume_at: float, reason: str) -> None:
    """Import logging lazily to avoid the logging_setup/store cycle."""
    from app.logging_setup import run_log_context

    parked_until = datetime.fromtimestamp(resume_at, tz=timezone.utc).isoformat()
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
    """Waiting for a platform cap is neither failure nor retry and cannot
    double-count the provider request already attempted.
    """
    resume_at = exc.resume_at + random.uniform(0, _RATE_LIMIT_PARK_JITTER_SECONDS)
    if not store.park_task_for_rate_limit(task.id, worker_id, str(exc), resume_at, db_path=db_path):
        logger.warning("Task %s lost its lease while rate-limit parked", task.id)
        return
    _log_rate_limit_park(task.run_id, resume_at, exc.reason)
    logger.info(
        "Task %s parked for a platform rate-limit cap (%s) until %.0f",
        task.id,
        exc.reason,
        resume_at,
    )


def _is_terminal_failure(task: ScientificTask, *, retryable: bool) -> bool:
    """Cancel poisoned lookahead before terminal settlement so queued
    unclaimable dependents cannot keep the run alive.
    """
    return not retryable or task.attempt >= task.max_attempts


def _cancel_downstream_before_terminal_failure(
    task: ScientificTask, *, retryable: bool, db_path: str | None
) -> None:
    """Ordinary retries preserve reusable successors; only terminal failures
    poison their downstream chain.
    """
    if _is_terminal_failure(task, retryable=retryable):
        cancel_downstream_portfolio_chain(task, db_path)


def _fail_permanent_task(
    task: ScientificTask, worker_id: str, exc: Exception, db_path: str | None
) -> None:
    _cancel_downstream_before_terminal_failure(task, retryable=False, db_path=db_path)
    tasks.fail_task(
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
    """One task failure must remain isolated from the rest of its cohort."""
    retryable = not isinstance(exc, LLMTimeoutError) or exc.zero_cost_admitted
    retry_at = None
    if isinstance(exc, LLMTimeoutError) and exc.zero_cost_admitted:
        from co_scientist.llm import provider_outage_backoff_seconds

        retry_at = time.time() + provider_outage_backoff_seconds(task.attempt)
    unknown_provider_outcome = isinstance(exc, LLMTimeoutError) and not exc.zero_cost_admitted
    if not unknown_provider_outcome:
        _cancel_downstream_before_terminal_failure(task, retryable=retryable, db_path=db_path)
    tasks.fail_task(
        task.id,
        worker_id,
        _failure_error(exc),
        retryable=retryable,
        retry_at=retry_at,
        stop_run=unknown_provider_outcome,
        db_path=db_path,
    )
    if isinstance(exc, LLMTimeoutError) and not exc.zero_cost_admitted:
        logger.exception("Task %s failed with an unknown provider outcome", task.id)
    else:
        logger.exception("Task %s failed", task.id)


# First matching failure type wins; unmatched exceptions retain the retryable
# default.
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
    """Supersession succeeds; holds and rate limits park; unsupported types
    and spent budgets fail permanently; other failures retain retry
    budgets.
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
    if not store.complete_task(task.id, worker_id, result, db_path=db_path):
        logger.warning("Task %s lost its lease before completion", task.id)
