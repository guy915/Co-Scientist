"""``execute_engine_task`` scopes the run's LLM-call ceiling around dispatch.

Mirrors ``test_byok_flow.py::test_execute_engine_task_scopes_the_credential``:
that test pins the credential scope entered around dispatch, this one pins
the LLM-call-budget scope entered beside it -- every completion the
dispatched task makes is attributed to the run whose ``max_llm_calls`` came
from its own resolved tier config, and the scope is gone once the task
returns.
"""

from __future__ import annotations

from typing import Any

from co_scientist.llm_call_budget import (
    current_run_call_count,
    record_provider_request,
    release_run_call_budget,
)

from app import engine_tasks, store
from app.run_modes import RUN_TIER_DEFAULTS, resolved_run_config


def _node_task(run_id: str) -> store.ScientificTask:
    """Shape a minimal node-task row for the dispatch/scope test."""
    return store.ScientificTask(
        id="task-1",
        run_id=run_id,
        task_type="engine.node.generate",
        status="leased",
        priority=90,
        inputs={},
        dependencies=(),
        provenance={},
        idempotency_key="engine.node.generate:0",
        budget={},
        attempt=1,
        max_attempts=3,
        lease_owner="test",
        lease_expires_at=None,
        result=None,
        error=None,
        created_at=0.0,
        updated_at=0.0,
        started_at=None,
        completed_at=None,
    )


async def test_execute_engine_task_scopes_the_llm_call_ceiling(
    monkeypatch: Any,
) -> None:
    run = store.create_run(
        "Budget scoping",
        "express",
        "engine",
        resolved_run_config({"tier": "express"}),
    )
    try:
        seen: dict[str, int] = {}

        async def fake_node_task(
            task: Any, *, db_path: str | None = None
        ) -> dict[str, Any]:
            record_provider_request()
            record_provider_request()
            seen["count_during"] = current_run_call_count(run.id)
            return {"status": "completed"}

        monkeypatch.setattr(engine_tasks, "execute_node_task", fake_node_task)
        await engine_tasks.execute_engine_task(_node_task(run.id))

        assert seen["count_during"] == 2
        # A second task on the same run must see the running count carried
        # forward, not reset -- a durable run is many short-lived tasks.
        seen2: dict[str, int] = {}

        async def fake_node_task_2(
            task: Any, *, db_path: str | None = None
        ) -> dict[str, Any]:
            record_provider_request()
            seen2["count_during"] = current_run_call_count(run.id)
            return {"status": "completed"}

        monkeypatch.setattr(engine_tasks, "execute_node_task", fake_node_task_2)
        await engine_tasks.execute_engine_task(_node_task(run.id))
        assert seen2["count_during"] == 3

        # The scope is gone once the task returns: an ambient call outside
        # any task must not attribute to the last-dispatched run.
        record_provider_request()
        assert current_run_call_count(run.id) == 3
    finally:
        release_run_call_budget(run.id)


async def test_execute_engine_task_enforces_the_ceiling(
    monkeypatch: Any,
) -> None:
    """A run already over its ceiling refuses the next request outright."""
    tier_ceiling = RUN_TIER_DEFAULTS["express"]["max_llm_calls"]
    run = store.create_run(
        "Budget enforcement",
        "express",
        "engine",
        resolved_run_config({"tier": "express"}),
    )
    try:
        from co_scientist.exceptions import LLMCallBudgetExceededError

        async def spend_to_ceiling(
            task: Any, *, db_path: str | None = None
        ) -> dict[str, Any]:
            for _ in range(tier_ceiling):
                record_provider_request()
            return {"status": "completed"}

        monkeypatch.setattr(engine_tasks, "execute_node_task", spend_to_ceiling)
        await engine_tasks.execute_engine_task(_node_task(run.id))
        assert current_run_call_count(run.id) == tier_ceiling

        async def one_more(
            task: Any, *, db_path: str | None = None
        ) -> dict[str, Any]:
            record_provider_request()
            return {"status": "completed"}

        monkeypatch.setattr(engine_tasks, "execute_node_task", one_more)
        try:
            await engine_tasks.execute_engine_task(_node_task(run.id))
            raised = False
        except LLMCallBudgetExceededError:
            raised = True
        assert raised, "the request past the ceiling must be refused"
    finally:
        release_run_call_budget(run.id)
