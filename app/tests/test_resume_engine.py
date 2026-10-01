"""App-level resume launcher over the durable run path.

The streaming resume surface (``run_workflow`` with ``resume=True``) has been
retired; every real run now resumes through the durable node executor. These
tests cover the app's resume *launcher* (``runs.lifecycle._launch_resume`` and
its ``_prepare_resume_state`` decision): an engine checkpoint is a true resume
that preserves derived data, a legacy mock envelope re-bootstraps a fresh
offline run, and neither drives blocking run work on the API event loop. The
durable node executor's own checkpoint/resume mechanics are covered in
``test_task_worker_resume.py`` and ``test_engine_tasks.py``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app import engine_adapter, store
from app.runs import lifecycle as runs_lifecycle
from app.runs.resume_admission import _prepare_resume_state
from tests._resume_engine_helpers import _install_fake_engine_llm


def _seed_stale_mock_run(run_id: str) -> str:
    """Persist stale mock-era artifacts a re-bootstrap must clear.

    Returns the id of the stale agent-authored hypothesis.
    """
    stale_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run_id,
            title="Stale agent idea",
            statement="A hypothesis from the retired mock run.",
            created_by_agent="generation",
        )
    )
    store.add_evidence(
        store.NewEvidence(
            run_id=run_id, title="Old mock paper", source="pubmed", abstract="x"
        )
    )
    return stale_id


def _save_legacy_mock_checkpoint(run_id: str) -> None:
    """Save a pre-flip mock envelope checkpoint (not engine WorkflowState)."""
    store.save_checkpoint(
        run_id,
        store.NewCheckpoint(
            stage="iteration_1",
            schema_version=1,
            last_event_seq=store.latest_event_seq(run_id),
            state={
                "provider": "mock",
                "run_mode": "express",
                "iteration": 1,
                "config": {"tier": "express"},
            },
        ),
    )


def _save_engine_checkpoint(run_id: str) -> None:
    """Save an engine-tagged checkpoint (``provider="engine"``).

    ``_prepare_resume_state`` only inspects the checkpoint's provider tag to
    decide the resume mode; it never restores the state (the durable worker
    does that later), so a minimal engine-tagged envelope is enough to
    exercise the true-resume branch.
    """
    store.save_checkpoint(
        run_id,
        store.NewCheckpoint(
            stage="engine_task:node",
            schema_version=1,
            last_event_seq=store.latest_event_seq(run_id),
            state={"provider": "engine", "state": {"hypotheses": []}},
        ),
    )


def _assert_rebootstrapped_completed(run_id: str, stale_id: str) -> None:
    """Assert a legacy resume cleared stale data and completed durably.

    (1) the stale mock-era hypothesis is gone, (2) durable engine tasks drove
    the run, (3) fresh hypotheses were generated, ranked, and published.
    """
    final_hyps = store.list_hypotheses(run_id)
    assert stale_id not in {h["id"] for h in final_hyps}
    assert any(
        task.task_type.startswith("engine.")
        for task in store.list_tasks(run_id)
    )
    assert final_hyps
    report = store.get_latest_report(run_id)
    assert report is not None
    assert report["payload"]["leaderboard"]
    final = store.get_run(run_id)
    assert final is not None
    assert final.status == store.RunStatus.COMPLETED.value


def _enqueue_paused_blocking_task(run_id: str, db_path: str) -> None:
    """Enqueue one blocking engine task and leave the run paused."""
    store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type="engine.test.blocking",
            inputs={},
            idempotency_key="blocking:0",
        ),
        db_path=db_path,
    )
    store.pause_run_tasks(run_id, db_path=db_path)
    store.update_run_status(run_id, store.RunStatus.PAUSED)


def _install_blocking_execute(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the task executor with a synchronous ~1s blocking cost.

    Stands in for the worker's real synchronous cost: a large json.dumps plus
    a committed SQLite write, run directly on the caller's loop.
    """
    import time as _time

    from app import engine_tasks

    async def _execute(
        _task: Any, *, db_path: str | None = None
    ) -> dict[str, bool]:
        _time.sleep(1.0)
        return {"completed": True}

    monkeypatch.setattr(engine_tasks, "execute_engine_task", _execute)


async def _worst_loop_stall(stop: asyncio.Event) -> float:
    """Return the worst delay the loop imposed on a 10ms sleep until stopped."""
    import time as _time

    worst = 0.0
    while not stop.is_set():
        started = _time.monotonic()
        await asyncio.sleep(0.01)
        worst = max(worst, _time.monotonic() - started - 0.01)
    return worst


def test_prepare_resume_state_keeps_derived_data_for_engine_checkpoint(
    isolated_db: str,
) -> None:
    """An engine checkpoint is a true resume that preserves derived data.

    The engine persists artifacts only at the final drain, so a mid-run
    interruption left only events + the checkpoint; clearing would discard the
    pre-orchestrator events a true resume never re-emits.
    """
    run = store.create_run("Engine checkpoint resume", "standard", "engine", {})
    stale_id = _seed_stale_mock_run(run.id)
    _save_engine_checkpoint(run.id)
    assert engine_adapter.is_engine_checkpoint(
        store.get_latest_checkpoint(run.id)
    )

    true_resume = _prepare_resume_state(run.id)

    assert true_resume is True
    # Derived data survives (not cleared) and the checkpoint is retained.
    assert stale_id in {h["id"] for h in store.list_hypotheses(run.id)}
    assert store.get_latest_checkpoint(run.id) is not None


async def test_launch_resume_rebootstraps_legacy_mock_checkpoint(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A legacy mock-envelope resume re-runs fresh through the durable path.

    Covers ``runs.lifecycle._launch_resume``'s non-engine-checkpoint fallback
    -- the exact path a production resume of an old ``provider="mock"`` run
    takes after the mock's retirement. There is no persisted engine
    WorkflowState to restore, so the launcher clears the run's stale derived
    data and re-bootstraps it through the durable worker as a fresh offline
    engine run, rather than the old in-process re-derive. Proves (1) the
    stale mock-era artifacts are cleared, (2) the durable bootstrap task
    drives the run, and
    (3) it completes with a ranked, published report.
    """
    _install_fake_engine_llm(monkeypatch)
    run = store.create_run(
        "Legacy mock resume", "express", "mock", {"tier": "express"}
    )

    # Stale mock-era artifacts a re-bootstrap must clear, plus a legacy mock
    # envelope checkpoint (not an engine WorkflowState) -- the fallback trigger.
    stale_id = _seed_stale_mock_run(run.id)
    _save_legacy_mock_checkpoint(run.id)
    assert not engine_adapter.is_engine_checkpoint(
        store.get_latest_checkpoint(run.id)
    )
    # An interrupted run is left non-terminal; the launcher requires that.
    store.update_run_status(run.id, store.RunStatus.PAUSED)

    await runs_lifecycle._launch_resume(run.id)
    await asyncio.gather(*list(runs_lifecycle._resume_tasks))

    # Legacy checkpoint => stale data cleared; re-bootstrapped run completes.
    _assert_rebootstrapped_completed(run.id, stale_id)


async def test_resume_does_not_execute_run_work_on_the_event_loop(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resuming a run must leave the API's event loop free to serve requests.

    The durable worker does synchronous SQLite writes and serializes whole
    WorkflowState blobs, so driving it with ``create_task`` runs that
    blocking work on the API loop. Starting a run has always handed the
    cohort to a thread; resume did not, so a boot carrying interrupted runs
    stopped answering /health, Railway killed the container mid-run, and the
    next boot inherited one more interrupted run -- a spiral in which runs
    only advanced during the doomed startup window.
    """
    run = store.create_run("loop freedom", "standard", "engine", {})
    _enqueue_paused_blocking_task(run.id, isolated_db)
    _install_blocking_execute(monkeypatch)

    stop = asyncio.Event()
    probe = asyncio.create_task(_worst_loop_stall(stop))
    await runs_lifecycle._launch_resume(run.id)
    await asyncio.gather(*list(runs_lifecycle._resume_tasks))
    stop.set()
    worst_stall = await probe

    assert worst_stall < 0.5, (
        f"event loop stalled {worst_stall:.2f}s while a resumed run executed"
    )
