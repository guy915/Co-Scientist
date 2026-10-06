# Recording redact without scrubbing the stored goal leaks it through every
# later read and report.

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app import engine_tasks, safety, task_worker
from app.config import settings
from app.safety import SafetyDecision
from app.safety.types import REDACTED_PLACEHOLDER
from app.store import db, records, reports, runs, tasks
from app.store.runs import RunCreateOptions
from app.task_worker.outcomes import _LeaseLostError
from tests._client import create_run as _create_run
from tests._client import make_client
from tests._engine_tasks_helpers import _install_runtime
from tests._store_helpers import seed_run

_STRICT_GOAL = "Assess select agent stockpile resilience across regions."


@pytest.fixture(autouse=True)
def _strict_intake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(safety, "SAFETY_MODE", safety.SafetyMode.STRICT)


def _persist_run(db_path: str) -> Any:
    return seed_run(
        _STRICT_GOAL,
        profile="express",
        config={"tier": "express", "enable_literature_review": False},
        options=RunCreateOptions(
            client_id="intake-redaction",
            title=f"Study of {_STRICT_GOAL}",
            llm_backend="offline",
            db_path=db_path,
        ),
    )


@pytest.mark.asyncio
async def test_cancelled_bootstrap_cannot_commit_intake_redaction(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    owner = make_client()
    created = _create_run(owner, _STRICT_GOAL)
    assert created.status_code == 200, created.text
    run_id = str(created.json()["id"])
    runs.set_run_title(run_id, f"Study {_STRICT_GOAL}", db_path=isolated_db)
    runs.set_run_goal_restatement(
        run_id, f"Investigate {_STRICT_GOAL}", db_path=isolated_db
    )
    assert owner.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
    task = tasks.claim_task(
        "cancelled-intake-worker", run_id=run_id, db_path=isolated_db
    )
    assert task is not None

    async def cancel_then_return_redaction(
        *_: Any, **__: Any
    ) -> SafetyDecision:
        response = owner.post(f"/api/runs/{run_id}/cancel")
        assert response.status_code == 200, response.text
        return SafetyDecision(
            stage="intake", decision="redact", matches=["select agent"]
        )

    _install_runtime(monkeypatch).screen = cancel_then_return_redaction

    with pytest.raises(_LeaseLostError):
        await engine_tasks.execute_bootstrap(task, db_path=isolated_db)

    detail = owner.get(f"/api/runs/{run_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "cancelled"
    assert "select agent" in detail.json()["research_goal"].lower()
    stored = runs.get_run(run_id, db_path=isolated_db)
    assert stored is not None
    assert stored.title == f"Study {_STRICT_GOAL}"
    assert stored.goal_restatement == f"Investigate {_STRICT_GOAL}"
    assert [
        decision
        for decision in records.list_safety_decisions(
            run_id, db_path=isolated_db
        )
        if decision["stage"] == "intake"
    ] == []
    events = owner.get(f"/api/runs/{run_id}/events?stream=false")
    assert events.status_code == 200, events.text
    timeline = events.json()["events"]
    assert not any(event["type"] == "safety.intake" for event in timeline)
    assert [
        event["payload"].get("status")
        for event in timeline
        if event["type"] == "status"
    ][-1] == "cancelled"


@pytest.mark.asyncio
async def test_expired_bootstrap_lease_cannot_commit_intake_allow(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    owner = make_client()
    created = _create_run(owner, "Study a benign topic")
    assert created.status_code == 200, created.text
    run_id = str(created.json()["id"])
    assert owner.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
    task = tasks.claim_task(
        "expired-intake-worker", run_id=run_id, db_path=isolated_db
    )
    assert task is not None

    async def expire_then_allow(*_: Any, **__: Any) -> SafetyDecision:
        with db.transaction(isolated_db) as conn:
            conn.execute(
                "UPDATE scientific_tasks SET lease_expires_at=0 WHERE id=?",
                (task.id,),
            )
        return SafetyDecision(stage="intake", decision="allow")

    _install_runtime(monkeypatch).screen = expire_then_allow

    with pytest.raises(_LeaseLostError):
        await engine_tasks.execute_bootstrap(task, db_path=isolated_db)

    persisted = runs.get_run(run_id, db_path=isolated_db)
    assert persisted is not None and persisted.status == "queued"
    assert [
        decision
        for decision in records.list_safety_decisions(
            run_id, db_path=isolated_db
        )
        if decision["stage"] == "intake"
    ] == []
    events = owner.get(f"/api/runs/{run_id}/events?stream=false")
    assert events.status_code == 200, events.text
    assert not any(
        event["type"] == "safety.intake" for event in events.json()["events"]
    )


def test_intake_redaction_survives_into_the_report(isolated_db: str) -> None:
    run = _persist_run(isolated_db)
    owner = make_client()
    headers = {"X-Client-ID": "intake-redaction"}
    task_worker.enqueue_run_workflow(run.id, db_path=isolated_db)
    asyncio.run(
        task_worker.run_run_worker_pool(
            run.id,
            "intake-redaction-e2e",
            policy=task_worker.WorkerPolicy(db_path=isolated_db),
        )
    )

    stored = runs.get_run(run.id, db_path=isolated_db)
    assert stored is not None
    assert "select agent" not in stored.research_goal.lower()
    assert REDACTED_PLACEHOLDER in stored.research_goal
    assert "select agent" not in (stored.title or "").lower()
    report = reports.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert "select agent" not in report["markdown_text"].lower()
    assert "select agent" not in repr(report["payload"]).lower()

    safety_response = owner.get(f"/api/runs/{run.id}/safety", headers=headers)
    assert safety_response.status_code == 200, safety_response.text
    intake = [
        item
        for item in safety_response.json()["safety"]
        if item["stage"] == "intake"
    ]
    assert len(intake) == 1
    assert intake[0]["decision"] == "redact"
    assert intake[0]["matches"] == ["select agent"]

    report_response = owner.get(f"/api/runs/{run.id}/report", headers=headers)
    assert report_response.status_code == 200, report_response.text
    assert "select agent" not in repr(report_response.json()).lower()

    events_response = owner.get(
        f"/api/runs/{run.id}/events?stream=false", headers=headers
    )
    assert events_response.status_code == 200, events_response.text
    events = events_response.json()["events"]
    safety_event = next(
        event for event in events if event["type"] == "safety.intake"
    )
    report_event = next(event for event in events if event["type"] == "report")
    completed_event = next(
        event
        for event in events
        if event["type"] == "status"
        and event["payload"].get("status") == "completed"
    )
    assert safety_event["seq"] < report_event["seq"] < completed_event["seq"]
    assert "select agent" not in repr(report_event["payload"]).lower()
