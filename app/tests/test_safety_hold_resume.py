"""An approved safety hold must leave the run claimable work again.

Finding F2: the task that observed an intake or final hold *succeeded* --
it had recorded the decision and paused the run, which is not a failure --
so the run kept no claimable successor. Approving the hold then re-enqueued
the same ``{task_type}:{checkpoint_seq}`` (or the constant bootstrap key)
against a row already marked succeeded, ``ON CONFLICT DO NOTHING`` created
nothing, and the run announced a resume it never performed.

These tests drive the real durable path -- the offline-backed engine, the
worker cohort ``/start`` uses, and the adjudication endpoint the UI calls --
through a hold at each gate, and assert the run reaches a published report
once a reviewer approves.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import store, task_worker
from app.safety import POLICY_VERSION, SafetyDecision, ScreenSubject
from app.store import RunStatus
from tests._client import make_client

CLIENT_ID = "hold-e2e"
HEADERS = {"X-Client-ID": CLIENT_ID}


def _held_decision(stage: str) -> SafetyDecision:
    """Return the hold a contextual screen returns for uncertain content."""
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
    """Build a ``screen_with_escalation`` stand-in holding one stage once.

    Mirrors the real contract rather than bypassing it: the deterministic
    policy never returns ``hold`` (only the contextual model's ``uncertain``
    does), and ``screen_with_escalation`` skips escalation for a stage a
    reviewer already approved, returning the deterministic verdict. So the
    stage under test holds until it is approved and allows afterwards.
    """

    async def _screen(
        run_id: str,
        subject: ScreenSubject,
        *,
        provider: str,
        db_path: str | None = None,
    ) -> SafetyDecision:
        approved = store.safety_stage_is_approved(
            run_id, stage, POLICY_VERSION, db_path=db_path
        )
        if subject.stage != stage or approved:
            return subject.deterministic
        return _held_decision(stage)

    return _screen


def start_offline_run(db_path: str) -> Any:
    """Persist and enqueue an offline-backed express run on the engine path."""
    run = store.create_run(
        "Explain how protein X folds under crowding.",
        "express",
        "engine",
        {"tier": "express", "enable_literature_review": False},
        store.RunCreateOptions(
            client_id=CLIENT_ID, llm_backend="offline", db_path=db_path
        ),
    )
    task_worker.enqueue_run_workflow(run.id, db_path=db_path)
    return run


def drain(run_id: str, db_path: str, worker: str = "hold-e2e") -> None:
    """Drive the run's worker cohort until nothing claimable remains."""
    asyncio.run(
        task_worker.run_run_worker_pool(
            run_id,
            worker,
            policy=task_worker.WorkerPolicy(db_path=db_path),
        )
    )


def held_decision_id(run_id: str, stage: str, db_path: str) -> int:
    """Return the id of the run's unresolved hold at ``stage``."""
    held = [
        row
        for row in store.list_safety_decisions(run_id, db_path=db_path)
        if row["stage"] == stage
        and row["decision"] == "hold"
        and row["resolution"] is None
    ]
    assert held, f"no unresolved {stage} hold was recorded"
    return int(held[-1]["id"])


def claimable_engine_tasks(run_id: str, db_path: str) -> list[str]:
    """Return the run's engine tasks a worker could still reach."""
    return [
        task.task_type
        for task in store.list_tasks(run_id, db_path=db_path)
        if task.task_type.startswith("engine.")
        and task.status in {"queued", "leased", "paused"}
    ]


def approve(client: TestClient, run_id: str, decision_id: int) -> None:
    """Approve one held decision through the endpoint the reviewer uses."""
    response = client.post(
        f"/api/runs/{run_id}/safety/{decision_id}/adjudicate",
        headers=HEADERS,
        json={"resolution": "approved"},
    )
    assert response.status_code == 200, response.text


@pytest.fixture()
def held_run(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Keep the safety screen and the resume launcher off other threads.

    The contextual screen is stubbed per test, so the real one must not
    also fire; and the embedded worker is disabled so each test drains the
    cohort itself instead of racing a detached one (production splits the
    same way when the worker runs as its own service).
    """
    from app.config import settings

    monkeypatch.setattr(settings, "semantic_safety_enabled", False)
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    return make_client()


def test_intake_hold_keeps_claimable_work_and_resumes(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, held_run: TestClient
) -> None:
    """An intake hold parks the bootstrap; approval runs it to a report."""
    from app import engine_tasks

    monkeypatch.setattr(
        engine_tasks, "screen_with_escalation", hold_until_approved("intake")
    )
    run = start_offline_run(isolated_db)
    drain(run.id, isolated_db)

    paused = store.get_run(run.id, db_path=isolated_db)
    assert paused is not None and paused.status == RunStatus.PAUSED.value
    # A hold is a waiting state, not the end of the run: the boundary it
    # stopped at must still be on the queue for a reviewer to release.
    assert claimable_engine_tasks(run.id, isolated_db) == ["engine.bootstrap"]

    approve(held_run, run.id, held_decision_id(run.id, "intake", isolated_db))
    drain(run.id, isolated_db, worker="hold-e2e-resume")

    final = store.get_run(run.id, db_path=isolated_db)
    assert final is not None
    assert final.status == RunStatus.COMPLETED.value
    assert store.get_latest_report(run.id, db_path=isolated_db) is not None


def test_final_hold_keeps_claimable_work_and_resumes(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, held_run: TestClient
) -> None:
    """A final-report hold parks finalization until a reviewer approves it."""
    from app import report_render

    monkeypatch.setattr(
        report_render, "screen_with_escalation", hold_until_approved("final")
    )
    run = start_offline_run(isolated_db)
    drain(run.id, isolated_db)

    paused = store.get_run(run.id, db_path=isolated_db)
    assert paused is not None and paused.status == RunStatus.PAUSED.value
    assert store.get_latest_report(run.id, db_path=isolated_db) is None
    assert claimable_engine_tasks(run.id, isolated_db) == ["engine.finalize"]

    approve(held_run, run.id, held_decision_id(run.id, "final", isolated_db))
    drain(run.id, isolated_db, worker="hold-e2e-resume")

    final = store.get_run(run.id, db_path=isolated_db)
    assert final is not None
    assert final.status == RunStatus.COMPLETED.value
    assert store.get_latest_report(run.id, db_path=isolated_db) is not None


def test_parked_task_is_released_with_a_fresh_budget(
    isolated_db: str,
) -> None:
    """Parking makes a leased task waiting work, not dead or finished work.

    The two properties the hold path depends on: ``resume_run_tasks``
    reaches a parked row (a succeeded one it can never reach), and the
    released task can still be claimed, because waiting for a reviewer
    does not spend the retry budget.
    """
    run = store.create_run(
        "goal",
        "express",
        "engine",
        {},
        store.RunCreateOptions(db_path=isolated_db),
    )
    store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type="engine.finalize",
            inputs={},
            idempotency_key="engine.finalize:1",
        ),
        db_path=isolated_db,
    )
    leased = store.claim_task("w1", run_id=run.id, db_path=isolated_db)
    assert leased is not None and leased.attempt == 1

    assert store.park_task(leased.id, "w1", "held", db_path=isolated_db)
    parked = store.get_task(leased.id, db_path=isolated_db)
    assert parked is not None and parked.status == "paused"
    # A worker must not be able to pick it back up before it is released.
    assert store.claim_task("w2", run_id=run.id, db_path=isolated_db) is None

    assert store.resume_run_tasks(run.id, db_path=isolated_db) == 1
    released = store.claim_task("w3", run_id=run.id, db_path=isolated_db)
    assert released is not None and released.id == leased.id
    assert released.attempt == 1


def test_rejected_final_hold_blocks_the_run(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, held_run: TestClient
) -> None:
    """Rejecting a held report blocks the run instead of releasing it."""
    from app import report_render

    monkeypatch.setattr(
        report_render, "screen_with_escalation", hold_until_approved("final")
    )
    run = start_offline_run(isolated_db)
    drain(run.id, isolated_db)

    decision_id = held_decision_id(run.id, "final", isolated_db)
    response = held_run.post(
        f"/api/runs/{run.id}/safety/{decision_id}/adjudicate",
        headers=HEADERS,
        json={"resolution": "rejected"},
    )
    assert response.status_code == 200

    blocked = store.get_run(run.id, db_path=isolated_db)
    assert blocked is not None
    assert blocked.status == RunStatus.BLOCKED.value
    assert store.get_latest_report(run.id, db_path=isolated_db) is None
