"""A final safety block is terminal even when its checkpoint still exists."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app import engine_tasks, store, task_worker
from app.config import settings
from app.report import build as report_build
from app.report import finalize as report_finalize
from app.safety import SafetyDecision
from tests._client import make_client
from tests._engine_tasks_helpers import (
    _Generator,
    _install_runtime,
    _patch_restore_generator,
    _seed_checkpoint,
    _task_state,
)


@pytest.mark.asyncio
async def test_resume_rejects_final_safety_block_after_finalize_succeeded(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resume must preserve a completed finalizer's safety block."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    owner = make_client()
    owner_headers = {"X-Client-ID": "final-safety-block-owner"}
    created = owner.post(
        "/api/runs",
        headers=owner_headers,
        json={
            "research_goal": "Study a final-stage safety block",
            "tier": "express",
        },
    )
    assert created.status_code == 200, created.text
    run_id = str(created.json()["id"])
    store.update_run_status(
        run_id, store.RunStatus.RUNNING, db_path=isolated_db
    )

    predecessor = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type="engine.node.overview",
            inputs={},
            idempotency_key="completed-overview",
        ),
        db_path=isolated_db,
    )
    previous_claim = store.claim_task(
        "resume-safety-fixture", run_id=run_id, db_path=isolated_db
    )
    assert previous_claim is not None and previous_claim.id == predecessor.id
    assert store.complete_task(
        predecessor.id,
        "resume-safety-fixture",
        {},
        db_path=isolated_db,
    )

    state = _task_state(run_id)
    checkpoint_seq = _seed_checkpoint(
        run_id,
        state,
        stage=f"engine_task:{predecessor.id}",
        db_path=isolated_db,
    )
    checkpoint = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert checkpoint is not None
    checkpoint_seq = store.save_checkpoint(
        run_id,
        store.NewCheckpoint(
            stage=f"engine_task:{predecessor.id}",
            schema_version=checkpoint["schema_version"],
            last_event_seq=checkpoint["last_event_seq"],
            state={
                **checkpoint["state"],
                "resume_successor": engine_tasks.FINALIZE_TASK,
            },
        ),
        db_path=isolated_db,
    )
    finalizer = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=engine_tasks.FINALIZE_TASK,
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key=f"{engine_tasks.FINALIZE_TASK}:after:{predecessor.id}",
            dependencies=(predecessor.id,),
        ),
        db_path=isolated_db,
    )
    _patch_restore_generator(monkeypatch, _Generator(state))

    async def fake_drain(
        *_: Any, **__: Any
    ) -> tuple[Any, float, dict[str, Any]]:
        drained = SimpleNamespace(
            safety_counts={},
            grounding_counts={},
            report_inputs={"citation_summary": {}},
        )
        return drained, 1.0, {}

    async def block_final_report(*_: Any, **__: Any) -> SafetyDecision:
        return SafetyDecision(
            stage="final",
            decision="block",
            reason="Final-stage policy blocked this report.",
        )

    built = report_build._BuiltReport(
        payload={
            "idea_count": 1,
            "leaderboard": [
                {"title": "Safe fixture", "statement": "A report."}
            ],
        },
        markdown="# Final safety fixture",
        facts=[],
        exclusion_tally={},
    )

    async def fake_build_report(*_: Any, **__: Any) -> Any:
        return built

    _install_runtime(monkeypatch).drain_final_state = fake_drain
    monkeypatch.setattr(
        report_finalize, "build_report_content", fake_build_report
    )
    _install_runtime(monkeypatch).screen = block_final_report

    assert await task_worker.run_once(
        "final-safety-worker", run_id=run_id, db_path=isolated_db
    )
    blocked = store.get_run(run_id, db_path=isolated_db)
    completed_finalize = store.get_task(finalizer.id, db_path=isolated_db)
    assert (
        blocked is not None and blocked.status == store.RunStatus.BLOCKED.value
    )
    assert completed_finalize is not None
    assert completed_finalize.status == "completed"
    final_decision = [
        item
        for item in store.list_safety_decisions(run_id, db_path=isolated_db)
        if item["stage"] == "final"
    ]
    assert len(final_decision) == 1 and final_decision[0]["decision"] == "block"
    assert store.get_latest_report(run_id, db_path=isolated_db) is None

    outsider = owner.post(
        f"/api/runs/{run_id}/resume",
        headers={"X-Client-ID": "different-owner"},
    )
    assert outsider.status_code == 404

    response = owner.post(f"/api/runs/{run_id}/resume", headers=owner_headers)
    assert response.status_code == 409
    assert response.json()["detail"] == "run was blocked; create a new run"
    saved = store.get_run(run_id, db_path=isolated_db)
    assert saved is not None and saved.status == store.RunStatus.BLOCKED.value
    tasks = store.list_tasks(run_id, db_path=isolated_db)
    assert [(task.task_type, task.status) for task in tasks] == [
        ("engine.node.overview", "completed"),
        (engine_tasks.FINALIZE_TASK, "completed"),
    ]
    events_response = owner.get(
        f"/api/runs/{run_id}/events?stream=false", headers=owner_headers
    )
    assert events_response.status_code == 200
    events = events_response.json()["events"]
    safety_event = next(
        event for event in events if event["type"] == "safety.final"
    )
    blocked_event = next(
        event
        for event in events
        if event["type"] == "status"
        and event["payload"].get("status") == "blocked"
    )
    assert safety_event["seq"] < blocked_event["seq"]
    status_events = [event for event in events if event["type"] == "status"]
    assert status_events[-1]["payload"]["status"] == "blocked"
    assert not any(
        event["payload"].get("status") == "resuming" for event in events
    )
