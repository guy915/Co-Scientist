"""Startup and shutdown helpers for the FastAPI ``lifespan`` hook.

Split out of ``app.main``, which re-exports the names the test suite uses so
``main._launch_embedded_recovery_workers`` and friends keep resolving for
it. The ``lifespan`` async generator itself stays in
``app.main`` -- see the module docstring there and AGENTS.md's "Gotchas"
section for the load-bearing ordering constraints (startup work runs
before uvicorn binds a port; the checkpoint sweep must stay inline;
nothing here may be fatal) -- this module holds only the helper bodies
each lifespan phase calls.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3

from app import engine_adapter, store
from app.config import settings

logger = logging.getLogger(__name__)


def _reclaim_disk_space() -> None:
    """Prune the checkpoint history no run could resume from.

    Only the newest checkpoint per run is ever loaded, so the rest is
    unreadable state that nonetheless filled the production volume until
    every write failed. Runs remain resumable: each keeps its newest.

    Deliberately does not VACUUM. Reclaiming the freed pages would shrink
    the file, but VACUUM needs exclusive access and SQLite makes a writer
    waiting for it block every other writer behind it -- and this process
    can never grant it, because the log-capture thread writes a row for
    every record the app emits. The VACUUM waits for a quiet moment that
    never arrives, and while it waits nothing else can write. Production
    wedged that way from both sides of the lifespan: an idle database, no
    writes for minutes, and every run creation failing with "database is
    locked". Pruning reclaims what actually grows without bound, commits in
    small batches, and never blocks a reader; the file keeps its high-water
    mark, which a 5 GB volume holding a 53 MB database can afford.

    Never fatal. This is opportunistic housekeeping, and the disk-full state
    it exists to relieve is exactly the state in which a DELETE cannot get
    its journal written -- so the first deploy carrying this sweep crashed on
    boot against the very database it was meant to reclaim. Serving with a
    bloated table beats not serving at all.
    """
    try:
        superseded = store.prune_superseded_checkpoints()
    except sqlite3.Error:
        logger.warning("Could not prune superseded checkpoints", exc_info=True)
    else:
        if superseded:
            logger.info(
                "Pruned %s superseded checkpoint(s) no run could resume from",
                superseded,
            )


def _startup_engine_setup() -> None:
    """Install the offline router, log engine config, validate tools_config.

    The offline LLM router is installed unconditionally: it is a harmless
    passthrough for real models -- only ``offline/``-prefixed calls are
    answered locally -- so no offline traffic flows until a run requests
    the offline backend. ``select_provider()`` always returns "engine" now
    (or raises if the engine is not importable) -- there is no mock
    fallback, logged once here. Validation fails loudly if a configured
    tools_config path is unreadable rather than silently running the
    engine's default tools (the historical bug: the setting was logged but
    never forwarded to the generator, so a bad path went unnoticed); the
    generator is built per run, so this is checked here at startup, once.
    """
    from co_scientist.offline.llm import install_offline_router

    install_offline_router()
    logger.info("Model: %s", settings.model_name)
    if settings.tools_config:
        logger.info("Tools config: %s", settings.tools_config)
    else:
        logger.info("Tools config: not set (generator defaults)")
    provider = engine_adapter.select_provider()
    logger.info("Workflow provider: %s", provider)
    engine_adapter.validate_tools_config(settings.tools_config)


def _reconcile_and_log_interrupted_runs() -> dict[str, list[str]]:
    """Reconcile runs left non-terminal by a previous process, and log it.

    A fresh process has no workflow tasks running, so anything still
    queued/running was interrupted by a crash or restart and would
    otherwise be stuck forever.
    """
    from app.outcome_refinement.action import (
        materialize_pending_outcome_refinements,
    )

    try:
        materialize_pending_outcome_refinements()
    except Exception:
        logger.warning(
            "Could not materialize pending outcome-refinement intents",
            exc_info=True,
        )
    reconciled = store.reconcile_interrupted_runs()
    if reconciled["failed"]:
        logger.info(
            "Reconciled %s interrupted run(s) to failed: %s",
            len(reconciled["failed"]),
            ", ".join(r[:8] for r in reconciled["failed"]),
        )
    if reconciled["resumable"]:
        logger.info(
            "Found %s resumable interrupted run(s) with a checkpoint: %s",
            len(reconciled["resumable"]),
            ", ".join(r[:8] for r in reconciled["resumable"]),
        )
    return reconciled


async def _resume_checkpointed_runs(resumable: list[str]) -> None:
    """Relaunch every run left with a resumable checkpoint.

    Auto-resume launcher: relaunches each resumable run from its last
    checkpoint so an interrupted run finishes rather than staying stuck.
    """
    if not resumable:
        return
    from app.runs import resume_interrupted_runs

    await resume_interrupted_runs(resumable)


def _launch_embedded_recovery_workers(
    recovery_workers: list[asyncio.Task[None]],
) -> None:
    """Start one recovery worker-pool task per run with an active engine task.

    A per-run recovery cohort waits out any unexpired lease and then
    resumes the same durable queue. Scientific effects remain exactly-once
    because every claim is lease- and checkpoint-gated. It runs on a
    thread because the cohort's SQLite writes and state serialization are
    synchronous: on the event loop they starve request handling, which is
    how a boot with runs to recover stopped answering its healthcheck.
    """
    if not settings.coscientist_embedded_worker:
        return
    from app import task_worker

    for run_id in store.list_active_engine_task_run_ids():
        recovery_workers.append(
            asyncio.create_task(
                asyncio.to_thread(
                    task_worker.run_run_worker_pool_sync,
                    run_id,
                    f"embedded-recovery:{os.getpid()}",
                )
            )
        )


async def _shutdown_recovery(
    recovery: asyncio.Task[None],
    recovery_workers: list[asyncio.Task[None]],
) -> None:
    """Cancel and await the recovery task and its embedded worker tasks."""
    recovery.cancel()
    await asyncio.gather(recovery, return_exceptions=True)
    for worker in recovery_workers:
        worker.cancel()
    if recovery_workers:
        await asyncio.gather(*recovery_workers, return_exceptions=True)


def _start_recovery_task(
    reconciled: dict[str, list[str]],
) -> tuple[asyncio.Task[None], list[asyncio.Task[None]]]:
    """Fire off the recovery task, off the startup critical path.

    Returns the task itself alongside the (initially empty, later
    populated) list of embedded recovery-worker tasks it launches, so the
    caller can cancel and await both at shutdown.
    """
    recovery_workers: list[asyncio.Task[None]] = []

    async def _recover_runs() -> None:
        """Relaunch interrupted runs, off the startup critical path.

        Restarting a run means executing it, so awaiting this before the
        hook yields put provider calls ahead of binding a port. Production
        deploys failed their five-minute healthcheck exactly that way, and
        because a failed healthcheck kills the container mid-run, each
        attempt left another interrupted run for the next boot to resume --
        a spiral in which runs only ever advanced during the doomed startup
        window. Recovery is not a precondition for serving, so it runs
        alongside it.
        """
        await _resume_checkpointed_runs(reconciled["resumable"])
        _launch_embedded_recovery_workers(recovery_workers)

    recovery = asyncio.create_task(_recover_runs())
    return recovery, recovery_workers
