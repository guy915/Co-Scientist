"""End-to-end durability of steering and fan-out isolation on a real run.

Both tests drive a whole offline-backed express run through the durable
executor -- the real ``HypothesisGenerator`` on the deterministic offline
backend, the real graph, the real ``_build_engine_opts``, the real task
queue -- and inject one fault into it.

The first queues a scientist steer mid-run and loses the worker between
the moment the steer is read and the moment the checkpoint that honors it
commits. The second fails one matchup of the tournament fan-out and
checks that its siblings were committed rather than re-judged.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app import (
    engine_tasks,
    engine_tasks_node,
    engine_tasks_support,
    store,
    task_worker,
)
from app.store import RunStatus

_STEER = "Prioritise chaperone co-expression over temperature shifts"


def _persist_offline_run(isolated_db: str) -> Any:
    """Persist an offline-backed express run on the engine path."""
    return store.create_run(
        "Explain how protein X folds under crowding.",
        "express",
        "mock",
        {"tier": "express", "enable_literature_review": False},
        store.RunCreateOptions(
            client_id="steering-e2e",
            llm_backend="offline",
            db_path=isolated_db,
        ),
    )


def _drive(run_id: str, isolated_db: str) -> None:
    """Run the whole durable cohort for one run to settlement."""
    asyncio.run(
        task_worker.run_run_worker_pool(
            run_id,
            "steering-e2e-worker",
            policy=task_worker.WorkerPolicy(db_path=isolated_db),
        )
    )


def _steer_mid_run_then_crash(
    monkeypatch: pytest.MonkeyPatch, run_id: str, db_path: str
) -> dict[str, int]:
    """Queue a steer after the run is under way, then lose the next commit.

    The steer is appended from the second successor commit, so it enters a
    run already past bootstrap. The first commit that then *carries* it
    dies before its transaction, which is exactly the window between
    reading the steering queue and committing the checkpoint that honors
    it. Patched in all three namespaces the helper is imported into, since
    each caller resolves its own module-level name.
    """
    real = engine_tasks_support._save_state_and_enqueue
    box = {"commits": 0, "crashes": 0}

    def crashing(
        commit: Any,
        state: Any,
        successor: Any,
        *,
        pause_if_requested: bool = False,
    ) -> Any:
        box["commits"] += 1
        if box["commits"] == 2:
            store.append_message(
                store.NewMessage(
                    run_id=run_id,
                    sender="user",
                    content=_STEER,
                    kind="steering",
                ),
                db_path=db_path,
            )
        if commit.steering_ids and not box["crashes"]:
            box["crashes"] += 1
            raise RuntimeError("worker lost before the checkpoint committed")
        return real(
            commit,
            state,
            successor,
            pause_if_requested=pause_if_requested,
        )

    for module in (engine_tasks_support, engine_tasks, engine_tasks_node):
        monkeypatch.setattr(module, "_save_state_and_enqueue", crashing)
    return box


def test_mid_run_steering_survives_a_crash_and_applies_once(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A steer queued mid-run reaches the engine exactly once, crash or not."""
    from app.config import settings

    monkeypatch.setattr(settings, "semantic_safety_enabled", False)
    run = _persist_offline_run(isolated_db)
    task_worker.enqueue_run_workflow(run.id, db_path=isolated_db)
    box = _steer_mid_run_then_crash(monkeypatch, run.id, isolated_db)

    _drive(run.id, isolated_db)

    assert box["crashes"] == 1, "the crash window was never exercised"
    assert store.get_pending_steering(run.id, db_path=isolated_db) == []
    steers = [
        message
        for message in store.list_messages(run.id, db_path=isolated_db)
        if message.kind == "steering"
    ]
    assert [message.applied for message in steers] == [True]
    final = store.get_run(run.id, db_path=isolated_db)
    assert final is not None
    assert final.status == RunStatus.COMPLETED.value
    assert store.get_latest_report(run.id, db_path=isolated_db) is not None


def _fail_one_judged_matchup(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Make one tournament matchup's judge raise, the rest go through."""
    import co_scientist.agents.ranking.ranking as ranking_module

    real = ranking_module.judge_matchup
    box = {"calls": 0, "failed": 0}

    async def flaky(*args: Any, **kwargs: Any) -> Any:
        box["calls"] += 1
        if box["calls"] == 2:
            box["failed"] += 1
            raise RuntimeError("judge provider refused this matchup")
        return await real(*args, **kwargs)

    monkeypatch.setattr(ranking_module, "judge_matchup", flaky)
    return box


def test_one_failed_matchup_leaves_the_rest_of_the_run_intact(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A per-item fault in the tournament fan-out settles the run anyway."""
    from app.config import settings

    monkeypatch.setattr(settings, "semantic_safety_enabled", False)
    run = _persist_offline_run(isolated_db)
    task_worker.enqueue_run_workflow(run.id, db_path=isolated_db)
    box = _fail_one_judged_matchup(monkeypatch)

    _drive(run.id, isolated_db)

    assert box["failed"] == 1, "the failure window was never exercised"
    final = store.get_run(run.id, db_path=isolated_db)
    assert final is not None
    assert final.status == RunStatus.COMPLETED.value
    matches = store.list_matches(run.id, db_path=isolated_db)
    assert len(matches) > 1
    # Every judged matchup but the failed one was committed, and none was
    # judged twice: an aborted wave would have re-judged its siblings on
    # the task's retry, so the call count would exceed the match count by
    # a whole wave rather than by the single failure.
    assert box["calls"] == len(matches) + 1
    failed_tasks = [
        task
        for task in store.list_tasks(run.id, db_path=isolated_db)
        if task.status == "failed"
    ]
    assert failed_tasks == []
