"""Standalone durable worker for queued Co-Scientist run tasks."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import socket
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app import engine_tasks, store
from app.config import settings
from app.logging_setup import run_log_context
from app.notifications import deliver_completion_notification
from app.store import ScientificTask

# Run-level enqueue moved verbatim to ``task_worker_enqueue``; every moved
# name is re-exported so this module's namespace keeps resolving.
from app.task_worker_enqueue import (
    _enqueue_resume_task as _enqueue_resume_task,
)
from app.task_worker_enqueue import (
    enqueue_run_workflow as enqueue_run_workflow,
)

# The failure taxonomy and outcome recorders moved verbatim to
# ``task_worker_outcomes``; every moved name is re-exported so this module's
# namespace (the seam tests and callers patch/import against) keeps
# resolving.
from app.task_worker_outcomes import (
    UnsupportedTaskError as UnsupportedTaskError,
)
from app.task_worker_outcomes import (
    _complete_superseded_task as _complete_superseded_task,
)
from app.task_worker_outcomes import (
    _fail_retryable_task as _fail_retryable_task,
)
from app.task_worker_outcomes import (
    _fail_unsupported_task as _fail_unsupported_task,
)
from app.task_worker_outcomes import (
    _handle_task_failure as _handle_task_failure,
)
from app.task_worker_outcomes import (
    _LeaseLostError as _LeaseLostError,
)
from app.task_worker_outcomes import (
    _record_success as _record_success,
)

logger = logging.getLogger(__name__)

_EMAIL_TASK = "notification.email"


@dataclass(frozen=True)
class _HeartbeatSignals:
    """The two events one task's lease heartbeat rides on.

    Attributes:
        stop: Set by the executor once the task settles, ending renewal.
        lease_lost: Set by the heartbeat when a renewal finds the lease is
            no longer owned, so the executor stops the revoked task.
    """

    stop: asyncio.Event
    lease_lost: asyncio.Event


@dataclass(frozen=True)
class WorkerPolicy:
    """Timing knobs a worker cohort applies to the tasks it leases.

    Attributes:
        db_path: Optional override for the SQLite database path.
        poll_seconds: Idle sleep between claim attempts.
        lease_seconds: Lease duration each claim and renewal writes.
    """

    db_path: str | None = None
    poll_seconds: float = 0.05
    lease_seconds: float = 300.0


async def _execute_task_payload(
    task: ScientificTask, *, db_path: str | None
) -> dict[str, Any]:
    """Execute one leased task without committing its durable outcome."""
    if task.task_type.startswith(engine_tasks.ENGINE_TASK_PREFIX):
        return await engine_tasks.execute_engine_task(task, db_path=db_path)
    if task.task_type == _EMAIL_TASK:
        return await deliver_completion_notification(task.inputs)
    raise UnsupportedTaskError(f"unsupported task type: {task.task_type}")


async def _execute_until_lease_lost(
    task: ScientificTask,
    lease_lost: asyncio.Event,
    *,
    db_path: str | None,
) -> dict[str, Any]:
    """Run task code while durable ownership remains valid.

    Cancellation revokes leased rows immediately. The heartbeat reports that
    revocation through ``lease_lost``; cancelling the local coroutine then
    stops in-flight provider and retrieval work instead of letting a revoked
    task consume compute until its natural return.
    """
    execution = asyncio.create_task(
        _execute_task_payload(task, db_path=db_path)
    )
    ownership = asyncio.create_task(lease_lost.wait())
    try:
        done, _ = await asyncio.wait(
            {execution, ownership}, return_when=asyncio.FIRST_COMPLETED
        )
        if execution in done:
            return await execution

        execution.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await execution
        raise _LeaseLostError(f"task {task.id} no longer owns its lease")
    finally:
        if not execution.done():
            execution.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await execution
        ownership.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await ownership


async def _execute_and_record(
    task: ScientificTask,
    worker_id: str,
    lease_lost: asyncio.Event,
    db_path: str | None,
) -> None:
    """Execute a claimed task and durably record its outcome."""
    try:
        # Tag every record emitted while this task runs with its run id. The
        # execution coroutine is created inside this context, so the copied
        # contextvar propagates to it (and to any node task it spawns).
        with run_log_context(task.run_id):
            result = await _execute_until_lease_lost(
                task, lease_lost, db_path=db_path
            )
    except _LeaseLostError:
        # The durable row already records cancellation, pause, or competing
        # ownership; the revoked worker must not overwrite that outcome.
        logger.info("Task %s stopped after lease revocation", task.id)
        return
    except Exception as exc:  # Worker boundary isolates one task failure.
        _handle_task_failure(task, worker_id, exc, db_path)
        return
    _record_success(task, worker_id, result, db_path)


async def _run_claimed_task(
    task: ScientificTask,
    worker_id: str,
    *,
    db_path: str | None,
    lease_seconds: float,
) -> None:
    """Execute one claimed task, renewing its lease until it settles."""
    stop_heartbeat = asyncio.Event()
    lease_lost = asyncio.Event()
    heartbeat = asyncio.create_task(
        _heartbeat_lease(
            task,
            worker_id,
            _HeartbeatSignals(stop=stop_heartbeat, lease_lost=lease_lost),
            db_path=db_path,
            lease_seconds=lease_seconds,
        )
    )
    try:
        await _execute_and_record(task, worker_id, lease_lost, db_path)
    finally:
        stop_heartbeat.set()
        await heartbeat


async def run_once(
    worker_id: str,
    *,
    run_id: str | None = None,
    db_path: str | None = None,
    lease_seconds: float = 300.0,
) -> bool:
    """Lease and execute one ready task, returning whether work was found."""
    task = store.claim_task(
        worker_id,
        lease_seconds=lease_seconds,
        run_id=run_id,
        db_path=db_path,
    )
    if task is None:
        return False
    await _run_claimed_task(
        task, worker_id, db_path=db_path, lease_seconds=lease_seconds
    )
    return True


async def run_run_until_idle(
    run_id: str,
    worker_id: str,
    *,
    db_path: str | None = None,
    lease_seconds: float = 300.0,
) -> None:
    """Consume a run's task chain until no ready task remains."""
    while True:
        worked = await run_once(
            worker_id,
            run_id=run_id,
            db_path=db_path,
            lease_seconds=lease_seconds,
        )
        if not worked:
            return


async def _cohort_worker_step(
    run_id: str,
    worker_id: str,
    policy: WorkerPolicy,
) -> bool:
    """Run one poll/claim/idle cycle for a cohort worker.

    One read-only snapshot answers both idle-tick questions -- claim only
    when work is visible, and exit only when neither claimable work nor a
    sibling's live lease remains. Other cohort members may still be
    executing parent tasks that will materialize new fan-out work; remain
    available until every lease is acknowledged. Queued-but-unclaimable
    work with no live lease cannot make progress and is left for
    retry/reconciliation. Existence checks rather than listings: this runs
    twenty times a second per idle worker, and decoding every row of a
    late-stage run's task table to compute one boolean is work that grows
    as the run does.

    Args:
        run_id: Run whose queue this cohort member drains.
        worker_id: This cohort member's identity.
        policy: Database path and the poll/lease timings.

    Returns:
        Whether the worker should keep polling.
    """
    db_path = policy.db_path
    claimable, active_lease = store.cohort_poll(run_id, db_path=db_path)
    if claimable and await run_once(
        worker_id,
        run_id=run_id,
        db_path=db_path,
        lease_seconds=policy.lease_seconds,
    ):
        return True
    if claimable or active_lease:
        await asyncio.sleep(policy.poll_seconds)
        return True
    return False


def _abandon_dead_leases_at_exit(run_id: str, db_path: str | None) -> None:
    """Settle the run if idle-exit left a lease nobody will ever finish.

    The cohort exits when no claimable work and no live lease remain. A
    lease that outlived its worker with its retry budget spent satisfies
    that condition while still sitting ``leased``, and nothing else will
    ever touch it -- so this is the last moment anything can. Best
    effort: a run is already ending here, and a store error must not
    replace that outcome with a worker crash.
    """
    try:
        abandoned = store.abandon_dead_leases(run_id, db_path=db_path)
    except Exception:
        logger.exception("Abandoning dead leases failed for run %s", run_id)
        return
    if abandoned:
        logger.warning(
            "Run %s: failed %d task(s) whose lease outlived its worker "
            "with no retries left.",
            run_id,
            abandoned,
        )


async def run_run_worker_pool(
    run_id: str,
    worker_prefix: str,
    *,
    worker_count: int | None = None,
    policy: WorkerPolicy | None = None,
) -> None:
    """Consume one run with a bounded cohort that survives dynamic fan-out.

    Args:
        run_id: Run whose queue the cohort drains.
        worker_prefix: Prefix each cohort member's worker id is built from.
        worker_count: Cohort size; defaults to ``worker_pool_size``.
        policy: Database path and the poll/lease timings.

    Raises:
        ValueError: When ``worker_count`` is not positive.
    """
    policy = policy or WorkerPolicy()
    if worker_count is None:
        worker_count = settings.worker_pool_size
    if worker_count < 1:
        raise ValueError("worker_count must be positive")

    async def _worker(index: int) -> None:
        """Poll and claim work for one cohort member until idle-exit."""
        worker_id = f"{worker_prefix}:{index}"
        while await _cohort_worker_step(run_id, worker_id, policy):
            continue

    await asyncio.gather(*(_worker(index) for index in range(worker_count)))
    _abandon_dead_leases_at_exit(run_id, policy.db_path)


def run_run_worker_pool_sync(run_id: str, worker_prefix: str) -> None:
    """Run the embedded cohort on a worker thread, outside the API loop."""
    asyncio.run(run_run_worker_pool(run_id, worker_prefix))


async def _heartbeat_lease(
    task: ScientificTask,
    worker_id: str,
    signals: _HeartbeatSignals,
    *,
    db_path: str | None,
    lease_seconds: float,
) -> None:
    """Renew periodically until execution finishes or ownership is lost.

    Args:
        task: The leased task whose lease is being renewed.
        worker_id: Identity that must still own the lease.
        signals: The stop and lease-lost events this heartbeat waits on
            and sets.
        db_path: Optional override for the SQLite database path.
        lease_seconds: Lease duration each renewal writes.
    """
    # Two different cadences. Wake at least once a second so explicit
    # cancellation interrupts expensive provider calls promptly even when
    # production leases are long -- but that check is an in-memory event.
    # Only the renewal touches the database, and it is due on the lease's
    # own schedule: a 300-second lease does not need rewriting every second.
    # Tying the two together cost one write per second per in-flight task,
    # and SQLite's single writer has no fair queuing, so a cohort of them
    # starved ordinary API writes until creating a run failed outright.
    renew_every = max(0.05, lease_seconds / 3)
    interval = min(1.0, renew_every)
    due = time.monotonic() + renew_every
    while True:
        try:
            await asyncio.wait_for(signals.stop.wait(), timeout=interval)
            return
        except TimeoutError:
            if time.monotonic() < due:
                continue
            due = time.monotonic() + renew_every
            if not store.renew_task_lease(
                task.id,
                worker_id,
                lease_seconds,
                db_path=db_path,
            ):
                logger.warning(
                    "Task %s lease heartbeat lost ownership", task.id
                )
                signals.lease_lost.set()
                return


async def run_forever(
    worker_id: str,
    *,
    db_path: str | None = None,
    poll_seconds: float = 0.5,
) -> None:
    """Continuously execute leased tasks until the process is cancelled."""
    # The standalone worker runs in its own process without the app lifespan,
    # so install the offline LLM router here too. Idempotent and a harmless
    # passthrough for real models (see main.lifespan).
    from co_scientist.offline_llm import install_offline_router

    install_offline_router()
    while True:
        worked = await run_once(worker_id, db_path=db_path)
        if not worked:
            await asyncio.sleep(poll_seconds)


def _worker_id() -> str:
    """Return a unique, operator-readable worker identity."""
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def main(argv: Sequence[str] | None = None) -> int:
    """Run the standalone durable worker process."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-id", default=_worker_id())
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    args = parser.parse_args(argv)
    asyncio.run(run_forever(args.worker_id, poll_seconds=args.poll_seconds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
