from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app import task_worker
from app.config import settings
from app.engine_tasks import support as engine_tasks_support
from app.report import build as report_build
from app.report import finalize as report_finalize
from app.runs import lifecycle as runs_lifecycle
from app.safety import SafetyDecision
from app.store import checkpoints, hypotheses, reports, runs
from app.store import events as store_events
from app.store import records as store
from app.store import runs_views as views
from app.store import tasks as store_tasks
from app.store import tasks_lifecycle as lifecycle
from app.store.hypotheses import NewHypothesis
from app.store.models import RunStatus as StoreRunStatus
from app.store.records import NewEvidence, NewReview
from tests._client import create_run as _create_run
from tests._client import make_client
from tests._client import make_client as _client
from tests._engine_tasks_helpers import (
    _Generator,
    _install_runtime,
    _patch_restore_generator,
    _seed_checkpoint,
    _task_state,
    fake_final_drain,
)
from tests._store_helpers import (
    enqueue_task,
    event_seqs,
    seed_checkpoint,
    seed_run,
)


def _new_run(client: Any, headers: dict[str, str] | None = None) -> str:
    res = _create_run(client, "Scientist-in-the-loop goal", headers=headers)
    return str(res.json()["id"])


def test_resume_and_pause_need_a_checkpoint_or_an_active_run(
    isolated_db: str,
) -> None:
    client = _client()
    run_id = _create_run(client, "No checkpoint yet").json()["id"]

    assert client.post(f"/api/runs/{run_id}/resume").status_code == 409
    assert client.post(f"/api/runs/{run_id}/pause").status_code == 404


def _seed_agent_artifacts(run_id: str) -> str:
    agent_id = hypotheses.add_hypothesis(
        NewHypothesis(
            run_id=run_id,
            title="Agent idea",
            statement="An agent-generated hypothesis.",
            created_by_agent="generation",
        )
    )
    store.add_review(
        NewReview(
            run_id=run_id,
            hypothesis_id=agent_id,
            reviewer_agent="reflection",
            summary="agent review",
            critique="agent critique",
        )
    )
    store.add_evidence(
        NewEvidence(
            run_id=run_id,
            title="Retrieved paper",
            source="pubmed",
            abstract="x",
        )
    )
    return agent_id


def _seed_scientist_artifacts(run_id: str) -> str:
    manual_id = hypotheses.add_hypothesis(
        NewHypothesis(
            run_id=run_id,
            title="Human idea",
            statement="A scientist-authored hypothesis.",
            created_by_agent="scientist_manual",
            author="dr-who",
        )
    )
    store.add_review(
        NewReview(
            run_id=run_id,
            hypothesis_id=manual_id,
            reviewer_agent="scientist",
            summary="human review",
            critique="looks promising",
        )
    )
    store.add_evidence(
        NewEvidence(
            run_id=run_id,
            title="Attached doc",
            source="attachment",
            abstract="notes",
        )
    )
    return manual_id


def test_resume_preserves_scientist_contributions(isolated_db: str) -> None:
    run = seed_run("Human input survives resume", profile="express")
    _seed_agent_artifacts(run.id)
    manual_id = _seed_scientist_artifacts(run.id)

    views.clear_run_derived_data(run.id)

    hyps = hypotheses.list_hypotheses(run.id)
    assert [h["id"] for h in hyps] == [manual_id]
    reviews = store.list_reviews(run.id)
    assert len(reviews) == 1 and reviews[0]["reviewer_agent"] == "scientist"
    evidence = store.list_evidence(run.id)
    assert [e["source"] for e in evidence] == ["attachment"]


def test_resuming_a_pre_engine_checkpoint_restarts_from_a_fresh_bootstrap(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = _client()
    run_id = _new_run(client)
    _seed_agent_artifacts(run_id)
    manual_id = _seed_scientist_artifacts(run_id)
    seed_checkpoint(
        run_id,
        {"provider": "mock", "legacy": True},
        stage="iteration_1",
        last_event_seq=store_events.latest_event_seq(run_id),
    )
    runs.update_run_status(run_id, StoreRunStatus.PAUSED)

    resumed = client.post(f"/api/runs/{run_id}/resume")

    assert resumed.status_code == 200, resumed.text
    assert [h["id"] for h in hypotheses.list_hypotheses(run_id)] == [manual_id]
    assert checkpoints.get_latest_checkpoint(run_id) is None
    assert event_seqs(run_id, "lifecycle", event="legacy_resume_cleanup")
    [task] = store_tasks.list_tasks(run_id)
    assert (task.task_type, task.status) == ("engine.bootstrap", "queued")


def test_resume_reassigns_event_seqs_above_last_checkpoint(
    isolated_db: str,
) -> None:
    # Clients retain after=N cursors; resumed event sequences must exceed
    # checkpoint high-water marks.
    run = seed_run("Seq continuity", profile="express")
    for i in range(5):
        store_events.append_event(run.id, "log", {"i": i})
    high_water = store_events.latest_event_seq(run.id)
    assert high_water == 5

    seed_checkpoint(run.id, {}, stage="pause", last_event_seq=high_water)
    views.clear_run_derived_data(run.id)
    assert store_events.list_events(run.id) == []

    seq = store_events.append_event(run.id, "status", {"status": "resuming"})
    assert seq == high_water + 1
    assert (
        store_events.list_events(run.id, after_seq=high_water)[0]["seq"] == seq
    )


_WORKER = "double-resume-test"


async def _advance(run_id: str, count: int, db_path: str) -> None:
    for _ in range(count):
        worked = await task_worker.run_once(
            _WORKER, run_id=run_id, db_path=db_path
        )
        assert worked, "run finished (or stalled) earlier than the test expects"


async def _advance_until_pool_nonempty(
    run_id: str, db_path: str, *, cap: int = 30
) -> set[str]:
    # Wait for a populated checkpoint rather than a task count tied to
    # generation fan-out topology.
    for _ in range(cap):
        worked = await task_worker.run_once(
            _WORKER, run_id=run_id, db_path=db_path
        )
        assert worked, "run finished before its pool ever grew"
        pool = _checkpoint_hypothesis_ids(run_id, db_path)
        if pool:
            return pool
    raise AssertionError(f"pool still empty after {cap} tasks")


def _pause_and_resume(client: Any, run_id: str) -> None:
    paused = client.post(f"/api/runs/{run_id}/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    resumed = client.post(f"/api/runs/{run_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "queued"


def _checkpoint_hypothesis_ids(run_id: str, db_path: str) -> set[str]:
    checkpoint = checkpoints.get_latest_checkpoint(run_id, db_path=db_path)
    assert checkpoint is not None
    payload = checkpoint["state"]["state"]
    return {str(h["id"]) for h in payload.get("hypotheses") or []}


@pytest.mark.asyncio
async def test_two_resume_cycles_still_complete_with_pool_intact(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Disable the embedded worker so two interruption boundaries cannot race
    # detached execution.
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = _client()
    created = _create_run(client, "Double resume coverage", tier="express")
    assert created.status_code == 200
    run_id = created.json()["id"]
    started = client.post(f"/api/runs/{run_id}/start", json={})
    assert started.status_code == 200

    await _advance(run_id, 1, isolated_db)
    _pause_and_resume(client, run_id)

    pool_before = await _advance_until_pool_nonempty(run_id, isolated_db)
    _pause_and_resume(client, run_id)

    await task_worker.run_run_until_idle(run_id, _WORKER, db_path=isolated_db)

    final_run = runs.get_run(run_id, db_path=isolated_db)
    assert final_run is not None
    assert final_run.status == "completed", final_run.error
    report = reports.get_latest_report(run_id, db_path=isolated_db)
    assert report is not None
    final_ids = {
        str(row["id"])
        for row in hypotheses.list_hypotheses(run_id, db_path=isolated_db)
    }
    assert pool_before <= final_ids


def _enqueue_paused_blocking_task(run_id: str, db_path: str) -> None:
    enqueue_task(run_id, "engine.test.blocking", "blocking:0", db_path=db_path)
    lifecycle.pause_run_tasks(run_id, db_path=db_path)
    runs.update_run_status(run_id, StoreRunStatus.PAUSED)


def _install_blocking_execute(monkeypatch: pytest.MonkeyPatch) -> None:
    import time as _time

    from app import engine_tasks

    async def _execute(
        _task: Any, *, db_path: str | None = None
    ) -> dict[str, bool]:
        _time.sleep(1.0)
        return {"completed": True}

    monkeypatch.setattr(engine_tasks, "execute_engine_task", _execute)


async def _worst_loop_stall(stop: asyncio.Event) -> float:
    import time as _time

    worst = 0.0
    while not stop.is_set():
        started = _time.monotonic()
        await asyncio.sleep(0.01)
        worst = max(worst, _time.monotonic() - started - 0.01)
    return worst


async def test_resume_does_not_execute_run_work_on_the_event_loop(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Resume cohorts must run off the API loop; synchronous state/SQLite work
    # otherwise starves health checks.
    run = seed_run("loop freedom")
    _enqueue_paused_blocking_task(run.id, isolated_db)
    _install_blocking_execute(monkeypatch)

    stop = asyncio.Event()
    probe = asyncio.create_task(_worst_loop_stall(stop))
    await runs_lifecycle._launch_resume(run.id)
    await asyncio.gather(*list(runs_lifecycle._resume_tasks))
    stop.set()
    worst_stall = await probe

    assert worst_stall < 0.5, (
        f"event loop stalled {worst_stall:.2f}s while a resumed run executed"
    )


@pytest.mark.asyncio
async def test_resume_rejects_final_safety_block_after_finalize_succeeded(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    owner = make_client()
    owner_headers = {"X-Client-ID": "final-safety-block-owner"}
    created = _create_run(
        owner,
        "Study a final-stage safety block",
        headers=owner_headers,
        tier="express",
    )
    assert created.status_code == 200, created.text
    run_id = str(created.json()["id"])
    runs.update_run_status(run_id, StoreRunStatus.RUNNING, db_path=isolated_db)

    predecessor = enqueue_task(
        run_id,
        "engine.node.overview",
        "completed-overview",
        db_path=isolated_db,
    )
    previous_claim = store_tasks.claim_task(
        "resume-safety-fixture", run_id=run_id, db_path=isolated_db
    )
    assert previous_claim is not None and previous_claim.id == predecessor.id
    assert lifecycle.complete_task(
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
    checkpoint = checkpoints.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert checkpoint is not None
    checkpoint_seq = seed_checkpoint(
        run_id,
        {
            **checkpoint["state"],
            "resume_successor": engine_tasks_support.FINALIZE_TASK,
        },
        stage=f"engine_task:{predecessor.id}",
        schema_version=checkpoint["schema_version"],
        last_event_seq=checkpoint["last_event_seq"],
        db_path=isolated_db,
    )
    finalizer = enqueue_task(
        run_id,
        engine_tasks_support.FINALIZE_TASK,
        f"{engine_tasks_support.FINALIZE_TASK}:after:{predecessor.id}",
        inputs={"checkpoint_seq": checkpoint_seq},
        dependencies=(predecessor.id,),
        db_path=isolated_db,
    )
    _patch_restore_generator(monkeypatch, _Generator(state))

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

    _install_runtime(monkeypatch).drain_final_state = fake_final_drain
    monkeypatch.setattr(
        report_finalize, "build_report_content", fake_build_report
    )
    _install_runtime(monkeypatch).screen = block_final_report

    assert await task_worker.run_once(
        "final-safety-worker", run_id=run_id, db_path=isolated_db
    )
    blocked = runs.get_run(run_id, db_path=isolated_db)
    completed_finalize = store_tasks.get_task(finalizer.id, db_path=isolated_db)
    assert (
        blocked is not None and blocked.status == StoreRunStatus.BLOCKED.value
    )
    assert completed_finalize is not None
    assert completed_finalize.status == "completed"
    final_decision = [
        item
        for item in store.list_safety_decisions(run_id, db_path=isolated_db)
        if item["stage"] == "final"
    ]
    assert len(final_decision) == 1 and final_decision[0]["decision"] == "block"
    assert reports.get_latest_report(run_id, db_path=isolated_db) is None

    outsider = owner.post(
        f"/api/runs/{run_id}/resume",
        headers={"X-Client-ID": "different-owner"},
    )
    assert outsider.status_code == 404

    response = owner.post(f"/api/runs/{run_id}/resume", headers=owner_headers)
    assert response.status_code == 409
    assert response.json()["detail"] == "run was blocked; create a new run"
    saved = runs.get_run(run_id, db_path=isolated_db)
    assert saved is not None and saved.status == StoreRunStatus.BLOCKED.value
    tasks = store_tasks.list_tasks(run_id, db_path=isolated_db)
    assert [(task.task_type, task.status) for task in tasks] == [
        ("engine.node.overview", "completed"),
        (engine_tasks_support.FINALIZE_TASK, "completed"),
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
