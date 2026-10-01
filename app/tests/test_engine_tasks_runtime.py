"""The engine-task runtime seam: production wiring and per-task resolution."""

from __future__ import annotations

from typing import Any

import pytest

from app import engine_tasks, safety, store
from app.engine_tasks import node as engine_tasks_node
from app.engine_tasks import runtime as engine_tasks_runtime
from app.engine_tasks import support as engine_tasks_support
from app.engine_tasks.runtime import ProductionEngineTaskRuntime
from tests._engine_tasks_helpers import FakeEngineTaskRuntime, _install_runtime


def test_production_adapter_is_the_default() -> None:
    """With nothing installed a task resolves the production adapter."""
    assert isinstance(
        engine_tasks_runtime.active(), ProductionEngineTaskRuntime
    )


@pytest.mark.asyncio
async def test_production_adapter_reaches_the_real_collaborators(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each production slot calls the collaborator it stands in front of."""
    calls: list[str] = []

    def stub(name: str, result: Any) -> Any:
        def call(*_: Any, **__: Any) -> Any:
            calls.append(name)
            return result

        async def acall(*_: Any, **__: Any) -> Any:
            return call()

        return acall if name in {"screen", "drain"} else call

    monkeypatch.setattr(
        engine_tasks_support, "_generator_and_opts", stub("new", ("g", {}))
    )
    monkeypatch.setattr(
        engine_tasks_support, "_generator_for_restore", stub("restore", "g")
    )
    monkeypatch.setattr(safety, "screen_with_escalation", stub("screen", 1))
    monkeypatch.setattr(
        engine_tasks_node, "_drain_and_persist_final_state", stub("drain", 2)
    )
    adapter = ProductionEngineTaskRuntime()
    anything: Any = object()

    assert adapter.generator_and_opts(anything, None) == ("g", {})
    assert adapter.generator_for_restore(anything, None) == "g"
    screened: Any = await adapter.screen("run", anything, provider="p")
    drained: Any = await adapter.drain_final_state(anything, {}, None)

    assert (screened, drained) == (1, 2)

    assert calls == ["new", "restore", "screen", "drain"]


@pytest.mark.asyncio
async def test_dispatcher_binds_the_adapter_it_resolved_once(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A task keeps the adapter it started with, whatever is installed later."""
    started_with = _install_runtime(monkeypatch)
    replacement = FakeEngineTaskRuntime()
    seen: list[Any] = []

    async def handler(task: Any, **_: Any) -> dict[str, Any]:
        seen.append(engine_tasks_runtime.active())
        monkeypatch.setattr(engine_tasks_runtime, "_installed", replacement)
        seen.append(engine_tasks_runtime.active())
        return {}

    monkeypatch.setitem(
        engine_tasks._ENGINE_TASK_DISPATCH,
        engine_tasks_support.FINALIZE_TASK,
        handler,
    )
    run = store.create_run("Task-level science", "standard", "engine", {})
    task = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=engine_tasks_support.FINALIZE_TASK,
            inputs={},
            idempotency_key="finalize",
        ),
        db_path=isolated_db,
    )

    await engine_tasks.execute_engine_task(task, db_path=isolated_db)

    assert seen == [started_with, started_with]
    installed: Any = engine_tasks_runtime.active()
    assert installed is replacement
