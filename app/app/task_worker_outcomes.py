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

from app import engine_tasks, store
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


def _fail_unsupported_task(
    task: ScientificTask, worker_id: str, exc: Exception, db_path: str | None
) -> None:
    """Permanently fail a task type no worker branch can execute.

    The only failure retrying cannot fix. Everything else reaching the
    worker boundary -- notably a provider returning empty content, which the
    engine raises as a bare ValueError -- falls through to the retryable
    branch instead.
    """
    store.fail_task(
        task.id, worker_id, str(exc), retryable=False, db_path=db_path
    )
    logger.error("Task %s rejected: %s", task.id, exc)


def _fail_retryable_task(
    task: ScientificTask, worker_id: str, exc: Exception, db_path: str | None
) -> None:
    """Fail one task while preserving its retry budget.

    Worker boundary isolates one task failure from the rest of the cohort.
    """
    store.fail_task(
        task.id, worker_id, str(exc), retryable=True, db_path=db_path
    )
    logger.exception("Task %s failed", task.id)


def _handle_task_failure(
    task: ScientificTask, worker_id: str, exc: Exception, db_path: str | None
) -> None:
    """Classify one task failure and record its outcome accordingly.

    Preserves the original except-clause priority exactly: a superseded
    checkpoint is a successful idempotent outcome, an unsupported task type
    is the one permanent failure, and everything else keeps its retry
    budget.
    """
    if isinstance(exc, engine_tasks.SupersededTaskError):
        _complete_superseded_task(task, worker_id, exc, db_path)
    elif isinstance(exc, UnsupportedTaskError):
        _fail_unsupported_task(task, worker_id, exc, db_path)
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
