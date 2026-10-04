from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from app import engine_tasks, task_worker
from app.diagnostic_events import log_chat_turn
from app.logging_setup import configure_log_capture, shutdown_log_capture
from app.store import logs, runs, tasks
from app.store.logs import LogFilters
from app.store.models import ScientificTask
from app.store.tasks import NewTask


def test_chat_metadata_is_owned_and_excludes_text(
    isolated_db: str, caplog: pytest.LogCaptureFixture
) -> None:
    configure_log_capture()
    try:
        with caplog.at_level(logging.INFO, logger="app.chat_turn"):
            log_chat_turn("user", "private user secret", owner="alice")
            log_chat_turn(
                "agent",
                "private answer secret",
                owner="alice",
                duration_seconds=1.25,
            )
    finally:
        shutdown_log_capture()
    owned = logs.list_logs(filters=LogFilters(scope_client_id="alice"))
    assert len(owned) == 2
    assert logs.list_logs(filters=LogFilters(scope_client_id="bob")) == []
    assert "role=user chars=19" in owned[0]["message"]
    assert (
        "role=agent" in owned[1]["message"]
        and "duration_seconds=1.250" in owned[1]["message"]
    )
    assert "private" not in str(owned)


@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled"])
def test_stage_span_records_duration_and_preserves_execution_outcome(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    outcome: str,
) -> None:
    run = runs.create_run("goal", "express", "engine", {})
    task = tasks.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type="engine.generate",
            inputs={},
            idempotency_key="test-span",
        )
    )
    called: list[str] = []

    async def execute(
        value: ScientificTask, *, db_path: str | None
    ) -> dict[str, Any]:
        called.append(value.id)
        if outcome == "failed":
            raise ValueError("private failure details")
        if outcome == "cancelled":
            raise asyncio.CancelledError()
        return {"completed": True}

    monkeypatch.setattr(engine_tasks, "execute_engine_task", execute)
    with caplog.at_level(logging.INFO, logger="app.run_stage"):
        if outcome == "failed":
            with pytest.raises(ValueError):
                asyncio.run(
                    task_worker._execute_task_payload(task, db_path=isolated_db)
                )
        elif outcome == "cancelled":
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(
                    task_worker._execute_task_payload(task, db_path=isolated_db)
                )
        else:
            assert asyncio.run(
                task_worker._execute_task_payload(task, db_path=isolated_db)
            ) == {"completed": True}
    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == "app.run_stage"
    ]
    assert len(messages) == 2 and messages[0].startswith("stage_start")
    assert (
        f"outcome={outcome}" in messages[1]
        and "duration_seconds=" in messages[1]
    )
    assert "private failure" not in str(messages)
    assert called == [task.id]
