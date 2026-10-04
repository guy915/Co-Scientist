# Succeeded tasks cannot be re-enqueued under existing idempotency keys; holds
# must park claimable work.

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import task_worker
from app.safety import POLICY_VERSION, SafetyDecision, ScreenSubject
from app.store import records, reports, runs, tasks
from app.store import tasks_lifecycle as lifecycle
from app.store.models import RunStatus
from app.store.runs import RunCreateOptions
from app.store.tasks import NewTask
from tests._client import make_client
from tests._engine_tasks_helpers import _install_runtime

CLIENT_ID = "hold-e2e"
HEADERS = {"X-Client-ID": CLIENT_ID}


def _held_decision(stage: str) -> SafetyDecision:
    return SafetyDecision(
        stage=stage,
        decision="hold",
        reason="Contextual safety assessment was uncertain.",
        category="uncertain",
        risk_domains=["uncertain"],
        requires_review=True,
        assessor="semantic:test",
    )


def hold_until_approved(stage: str) -> Any:
    # Reviewer approval bypasses escalation, so this stub must hold only until
    # that stage is approved.

    async def _screen(
        run_id: str,
        subject: ScreenSubject,
        *,
        provider: str,
        db_path: str | None = None,
    ) -> SafetyDecision:
        approved = records.safety_stage_is_approved(
            run_id, stage, POLICY_VERSION, db_path=db_path
        )
        if subject.stage != stage or approved:
            return subject.deterministic
        return _held_decision(stage)

    return _screen


def start_offline_run(db_path: str) -> Any:
    run = runs.create_run(
        "Explain how protein X folds under crowding.",
        "express",
        "engine",
        {"tier": "express", "enable_literature_review": False},
        RunCreateOptions(
            client_id=CLIENT_ID, llm_backend="offline", db_path=db_path
        ),
    )
    task_worker.enqueue_run_workflow(run.id, db_path=db_path)
    return run


def drain(run_id: str, db_path: str, worker: str = "hold-e2e") -> None:
    asyncio.run(
        task_worker.run_run_worker_pool(
            run_id,
            worker,
            policy=task_worker.WorkerPolicy(db_path=db_path),
        )
    )


def held_decision_id(run_id: str, stage: str, db_path: str) -> int:
    held = [
        row
        for row in records.list_safety_decisions(run_id, db_path=db_path)
        if row["stage"] == stage
        and row["decision"] == "hold"
        and row["resolution"] is None
    ]
    assert held, f"no unresolved {stage} hold was recorded"
    return int(held[-1]["id"])


def claimable_engine_tasks(run_id: str, db_path: str) -> list[str]:
    return [
        task.task_type
        for task in tasks.list_tasks(run_id, db_path=db_path)
        if task.task_type.startswith("engine.")
        and task.status in {"queued", "leased", "paused"}
    ]


def approve(client: TestClient, run_id: str, decision_id: int) -> None:
    response = client.post(
        f"/api/runs/{run_id}/safety/{decision_id}/adjudicate",
        headers=HEADERS,
        json={"resolution": "approved"},
    )
    assert response.status_code == 200, response.text


@pytest.fixture()
def held_run(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Disable detached workers to avoid racing the cohort this test drains
    # directly.
    from app.config import settings

    monkeypatch.setattr(settings, "semantic_safety_enabled", False)
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    return make_client()


def test_intake_hold_keeps_claimable_work_and_resumes(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, held_run: TestClient
) -> None:
    _install_runtime(monkeypatch).screen = hold_until_approved("intake")
    run = start_offline_run(isolated_db)
    drain(run.id, isolated_db)

    paused = runs.get_run(run.id, db_path=isolated_db)
    assert paused is not None and paused.status == RunStatus.PAUSED.value
    # A hold is waiting work; its boundary must remain queued for reviewer
    # release.
    assert claimable_engine_tasks(run.id, isolated_db) == ["engine.bootstrap"]

    approve(held_run, run.id, held_decision_id(run.id, "intake", isolated_db))
    drain(run.id, isolated_db, worker="hold-e2e-resume")

    final = runs.get_run(run.id, db_path=isolated_db)
    assert final is not None
    assert final.status == RunStatus.COMPLETED.value
    assert reports.get_latest_report(run.id, db_path=isolated_db) is not None


def test_final_hold_keeps_claimable_work_and_resumes(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, held_run: TestClient
) -> None:
    _install_runtime(monkeypatch).screen = hold_until_approved("final")
    run = start_offline_run(isolated_db)
    drain(run.id, isolated_db)

    paused = runs.get_run(run.id, db_path=isolated_db)
    assert paused is not None and paused.status == RunStatus.PAUSED.value
    assert reports.get_latest_report(run.id, db_path=isolated_db) is None
    assert claimable_engine_tasks(run.id, isolated_db) == ["engine.finalize"]

    approve(held_run, run.id, held_decision_id(run.id, "final", isolated_db))
    drain(run.id, isolated_db, worker="hold-e2e-resume")

    final = runs.get_run(run.id, db_path=isolated_db)
    assert final is not None
    assert final.status == RunStatus.COMPLETED.value
    assert reports.get_latest_report(run.id, db_path=isolated_db) is not None


def test_parked_task_is_released_with_a_fresh_budget(
    isolated_db: str,
) -> None:
    # Waiting for a reviewer must preserve claimable work without spending its
    # retry budget.
    run = runs.create_run(
        "goal",
        "express",
        "engine",
        {},
        RunCreateOptions(db_path=isolated_db),
    )
    tasks.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type="engine.finalize",
            inputs={},
            idempotency_key="engine.finalize:1",
        ),
        db_path=isolated_db,
    )
    leased = tasks.claim_task("w1", run_id=run.id, db_path=isolated_db)
    assert leased is not None and leased.attempt == 1

    assert lifecycle.park_task(leased.id, "w1", "held", db_path=isolated_db)
    parked = tasks.get_task(leased.id, db_path=isolated_db)
    assert parked is not None and parked.status == "paused"
    assert tasks.claim_task("w2", run_id=run.id, db_path=isolated_db) is None

    assert lifecycle.resume_run_tasks(run.id, db_path=isolated_db) == 1
    released = tasks.claim_task("w3", run_id=run.id, db_path=isolated_db)
    assert released is not None and released.id == leased.id
    assert released.attempt == 1


def test_rejected_final_hold_blocks_the_run(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, held_run: TestClient
) -> None:
    _install_runtime(monkeypatch).screen = hold_until_approved("final")
    run = start_offline_run(isolated_db)
    drain(run.id, isolated_db)

    decision_id = held_decision_id(run.id, "final", isolated_db)
    response = held_run.post(
        f"/api/runs/{run.id}/safety/{decision_id}/adjudicate",
        headers=HEADERS,
        json={"resolution": "rejected"},
    )
    assert response.status_code == 200

    blocked = runs.get_run(run.id, db_path=isolated_db)
    assert blocked is not None
    assert blocked.status == RunStatus.BLOCKED.value
    assert reports.get_latest_report(run.id, db_path=isolated_db) is None
