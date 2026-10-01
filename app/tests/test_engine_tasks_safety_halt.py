"""A mid-flight safety halt reaching the run's terminal state (J6).

The engine's safety monitor writes ``safety_blocked`` into the workflow
state when the run's own meta-review synthesis reaches prohibited content,
and the durable runtime then schedules finalize instead of more science.
These tests pin what the app does with that: a halted run must not publish
a report, must settle as ``blocked`` rather than ``completed``, and must
say why -- an unexplained blocked run is indistinguishable from a crash.
"""

from typing import Any

import pytest
from co_scientist.models import Hypothesis

from app import engine_tasks, store
from app.engine_tasks import support as engine_tasks_support
from app.safety import ScreenSubject
from tests._engine_tasks_helpers import (
    _Generator,
    _install_runtime,
    _patch_restore_generator,
    _seed_checkpoint,
    _task_state,
)


async def _deterministic_final_screen(
    _run_id: str, subject: ScreenSubject, *_: Any, **__: Any
) -> Any:
    """Stand in for the final escalation, returning its deterministic half."""
    return subject.deterministic


def _seed_halted_finalize(
    run_id: str, monkeypatch: pytest.MonkeyPatch, db_path: str, *, halted: bool
) -> Any:
    """Seed a finalize task whose checkpoint carries the monitor's verdict."""
    state = _task_state(run_id)
    state["hypotheses"] = [
        Hypothesis(
            text="Astrocyte lactate accelerates synaptic ATP recovery.",
            literature_grounding=(
                "Astrocyte lactate accelerates synaptic ATP recovery."
            ),
        )
    ]
    if halted:
        state["safety_blocked"] = True
        state["safety_decisions"] = [
            {
                "stage": "research_direction",
                "outcome": "prohibited",
                "reason": "Content matches a prohibited policy rule.",
                "matches": ["engineer smallpox for greater transmiss"],
                "policy_version": "coscientist-safety-v5",
            }
        ]
    _seed_checkpoint(run_id, state, db_path=db_path)
    queued = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=engine_tasks_support.FINALIZE_TASK,
            inputs={},
            idempotency_key="finalize",
        ),
        db_path=db_path,
    )
    task = store.claim_task(
        "finalize-safety-worker", run_id=run_id, db_path=db_path
    )
    assert task is not None and task.id == queued.id
    _patch_restore_generator(monkeypatch, _Generator(state))
    return task


@pytest.mark.asyncio
async def test_a_halted_run_blocks_instead_of_publishing(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The halt is terminal and visible, and no report is released."""
    run = store.create_run("Task-level science", "standard", "engine", {})
    task = _seed_halted_finalize(run.id, monkeypatch, isolated_db, halted=True)

    result = await engine_tasks.execute_finalize(task, db_path=isolated_db)

    assert result["status"] == store.RunStatus.BLOCKED.value
    assert store.get_latest_report(run.id, db_path=isolated_db) is None

    settled = store.get_run(run.id, db_path=isolated_db)
    assert settled is not None
    assert settled.status == store.RunStatus.BLOCKED.value
    assert settled.error

    decisions = store.list_safety_decisions(run.id, db_path=isolated_db)
    monitor = [d for d in decisions if d["stage"] == "research_direction"]
    assert len(monitor) == 1
    assert monitor[0]["decision"] == "block"
    assert monitor[0]["matches"]

    events = store.list_events(run.id, db_path=isolated_db)
    types = [event["type"] for event in events]
    assert "safety.research_direction" in types
    assert "report" not in types


@pytest.mark.asyncio
async def test_an_unhalted_run_still_publishes(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The halt check is the only thing that withholds the report."""
    run = store.create_run("Task-level science", "standard", "engine", {})
    task = _seed_halted_finalize(run.id, monkeypatch, isolated_db, halted=False)
    _install_runtime(monkeypatch).screen = _deterministic_final_screen

    result = await engine_tasks.execute_finalize(task, db_path=isolated_db)

    assert result["status"] == store.RunStatus.COMPLETED.value
    assert store.get_latest_report(run.id, db_path=isolated_db) is not None
