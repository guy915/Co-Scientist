"""A run whose terminal overview degraded still publishes its report.

Production run 49a509b0 committed 146 tasks and published nothing: the
terminal ``engine.node.research_overview`` task spent its three durable
attempts on an unreachable provider, ``store.fail_task`` settled the run
``failed``, and ``engine.finalize`` -- enqueued only ever as that node's
``None`` successor -- was never created, so ``GET /report.md`` 404'd on a
run with a full tournament behind it.

The engine half (the node degrading instead of raising) is pinned in
``engine/tests/test_node_provider_degradation.py``. This is the
consequence on the durable path the production run actually took: the
successor is still enqueued, the report is still written, the run does
not settle ``failed``, and the report payload names the section that went
missing -- through the existing ``degraded_sections`` seam, not a new
field.
"""

import dataclasses
from typing import Any

import pytest
from co_scientist.agents.meta_review import research_overview as ro
from co_scientist.models import Article, Hypothesis
from litellm.exceptions import APIError

from app import engine_tasks, store, task_worker
from tests._engine_tasks_helpers import (
    _Generator,
    _patch_generator,
    _seed_checkpoint,
    _task_state,
)

_UPSTREAM = APIError(
    status_code=500,
    message="OpenrouterException - Upstream error from Nvidia: overloaded",
    llm_provider="openrouter",
    model="minimax/minimax-m3:free",
)


def _grounded_state(run_id: str) -> dict[str, Any]:
    """One publishable hypothesis whose claim an article's abstract carries."""
    claim = "Astrocyte lactate accelerates synaptic ATP recovery."
    hypothesis = Hypothesis(text=claim, literature_grounding=claim)
    hypothesis.review_disposition = "viable"
    state = _task_state(run_id)
    state["hypotheses"] = [hypothesis]
    state["articles"] = [
        Article(
            title="Synaptic energetics",
            url="https://example.org/synaptic",
            abstract=claim,
        )
    ]
    return state


def _seed_overview_task(
    run_id: str, monkeypatch: pytest.MonkeyPatch, db_path: str
) -> None:
    """Seed the terminal overview task with an unreachable provider."""
    state = _grounded_state(run_id)
    checkpoint_seq = _seed_checkpoint(run_id, state, db_path=db_path)
    store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type="engine.node.research_overview",
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key="overview",
        ),
        db_path=db_path,
    )
    _patch_generator(monkeypatch, _Generator(state), restore=True, screen=True)

    async def _unreachable(*_: Any, **__: Any) -> dict[str, Any]:
        raise _UPSTREAM

    monkeypatch.setattr(ro, "call_llm_json", _unreachable)


@pytest.mark.asyncio
async def test_degraded_overview_still_reaches_a_written_report(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The overview task completes, finalize runs, and a report exists."""
    run = store.create_run("Task-level science", "standard", "engine", {})
    _seed_overview_task(run.id, monkeypatch, isolated_db)

    await task_worker.run_run_until_idle(run.id, "worker", db_path=isolated_db)

    by_type = {
        task.task_type: task.status
        for task in store.list_tasks(run.id, db_path=isolated_db)
    }
    assert by_type["engine.node.research_overview"] == "completed"
    assert by_type[engine_tasks.FINALIZE_TASK] == "completed"

    report = store.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert report["markdown_text"]

    run_row = store.get_run(run.id, db_path=isolated_db)
    assert run_row is not None
    assert run_row.status != store.RunStatus.FAILED.value


@pytest.mark.asyncio
async def test_the_report_names_the_overview_as_a_degraded_section(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The degradation is visible in the run record, not just the log."""
    run = store.create_run("Task-level science", "standard", "engine", {})
    _seed_overview_task(run.id, monkeypatch, isolated_db)

    await task_worker.run_run_until_idle(run.id, "worker", db_path=isolated_db)

    report = store.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert "research_overview" in report["payload"]["degraded_sections"]


@pytest.mark.asyncio
async def test_the_overview_degrades_only_once_its_retries_are_spent(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every durable attempt is spent before the blank section is accepted.

    The earlier extended run bc77950f met the same provider trouble and
    synthesized a full overview on its third durable attempt. Degrading on
    the first would trade that recovery for a permanently blank section,
    so the task must arrive at its fallback with its budget exhausted.
    """
    run = store.create_run("Task-level science", "standard", "engine", {})
    _seed_overview_task(run.id, monkeypatch, isolated_db)

    await task_worker.run_run_until_idle(run.id, "worker", db_path=isolated_db)

    overview = next(
        task
        for task in store.list_tasks(run.id, db_path=isolated_db)
        if task.task_type == "engine.node.research_overview"
    )
    assert overview.status == "completed"
    assert overview.attempt == overview.max_attempts == 3
    assert len(overview.attempts) == 2


def _restored_state(attempt: int, run_id: str, db_path: str) -> dict[str, Any]:
    """Restore a node task's state the way the worker does on ``attempt``."""
    from co_scientist.checkpoint import serialize_workflow_state

    state = _task_state(run_id)
    task = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type="engine.node.research_overview",
            inputs={},
            idempotency_key=f"overlay-{attempt}",
        ),
        db_path=db_path,
    )
    checkpoint = {
        "state": {
            "provider": "engine",
            **serialize_workflow_state(state, last_event_seq=0),
        }
    }
    return engine_tasks._restore_node_task_state(
        dataclasses.replace(task, attempt=attempt),
        checkpoint,
        _Generator(state),
        {},
        db_path,
    )


def test_the_restored_state_names_the_task_s_last_attempt(
    isolated_db: str,
) -> None:
    """The flag the node reads is the worker's own retry-left formula.

    Mirrors ``task_worker_outcomes._is_terminal_failure``: an attempt at
    the ceiling is the one whose failure settles the task, so it is the
    one that must degrade rather than raise.
    """
    run = store.create_run("Task-level science", "standard", "engine", {})

    first = _restored_state(1, run.id, isolated_db)
    last = _restored_state(3, run.id, isolated_db)

    assert first["durable_retries_remain"] is True
    assert last["durable_retries_remain"] is False
