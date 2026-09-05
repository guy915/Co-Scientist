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
from typing import Any

from co_scientist.exceptions import LLMCallBudgetExceededError

from app import engine_tasks, store
from app.engine_tasks_portfolio import cancel_downstream_portfolio_chain
from app.store import ScientificTask

logger = logging.getLogger(__name__)


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


def _handle_task_failure(
    task: ScientificTask, worker_id: str, exc: Exception, db_path: str | None
) -> None:
    """Classify one task failure and record its outcome accordingly.

    Preserves the original except-clause priority exactly: a superseded
    checkpoint is a successful idempotent outcome, a safety hold is a
    durable wait, an unsupported task type or an exceeded LLM-call
    ceiling are the two permanent failures, and everything else keeps its
    retry budget.
    """
    if isinstance(exc, engine_tasks.SupersededTaskError):
        _complete_superseded_task(task, worker_id, exc, db_path)
    elif isinstance(exc, engine_tasks.SafetyHoldError):
        _park_held_task(task, worker_id, exc, db_path)
    elif isinstance(exc, UnsupportedTaskError):
        _fail_unsupported_task(task, worker_id, exc, db_path)
    elif isinstance(exc, LLMCallBudgetExceededError):
        _fail_llm_budget_exceeded_task(task, worker_id, exc, db_path)
    else:
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
