"""Finalize drain pause/cancellation acceptance through the owner API."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app import engine_tasks, store, task_worker
from app.engine_tasks import node as engine_tasks_node
from tests._engine_tasks_helpers import _install_runtime
from tests.test_report_cancel_publication import (
    _OWNER,
    _install_report_stubs,
    _seed_owned_finalize,
)


@pytest.mark.asyncio
async def test_early_finalize_pause_skips_final_drain(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pause present before finalize checkpoints without invoking drain."""
    owner, run_id, task, _hypothesis_id = _seed_owned_finalize(
        isolated_db, monkeypatch
    )
    paused = owner.post(f"/api/runs/{run_id}/pause", headers=_OWNER)
    assert paused.status_code == 200, paused.text
    drain_calls: list[bool] = []

    async def unexpected_drain(*_: Any, **__: Any) -> Any:
        drain_calls.append(True)
        raise AssertionError("paused finalize called the final drain")

    _install_runtime(monkeypatch).drain_final_state = unexpected_drain
    result = await engine_tasks.execute_finalize(task, db_path=isolated_db)

    assert result["status"] == "paused"
    assert drain_calls == []
    checkpoint = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert checkpoint is not None
    assert checkpoint["stage"] == f"engine_task_paused:{task.id}"
    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == store.RunStatus.PAUSED.value


@pytest.mark.asyncio
async def test_cancel_during_final_drain_keeps_cancelled_state(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancel committed in drain prevents stage events and checkpointing."""
    real_drain = engine_tasks_node._drain_and_persist_final_state
    owner, run_id, _queued_task, hypothesis_id = _seed_owned_finalize(
        isolated_db, monkeypatch, claim=False
    )
    _install_report_stubs(hypothesis_id, monkeypatch)
    # Restore the real drain replaced by the shared fixture.
    _install_runtime(monkeypatch).drain_final_state = real_drain
    cancel_responses: list[dict[str, Any]] = []

    async def cancel_inside_drain(*_: Any, **__: Any) -> Any:
        response = owner.post(f"/api/runs/{run_id}/cancel", headers=_OWNER)
        assert response.status_code == 200, response.text
        cancel_responses.append(response.json())
        return SimpleNamespace(
            safety_counts={},
            grounding_counts={},
            report_inputs={"citation_summary": {}},
        )

    monkeypatch.setattr(
        engine_tasks_node, "persist_final_state", cancel_inside_drain
    )
    task = store.claim_task(
        "cancel-during-drain-worker", run_id=run_id, db_path=isolated_db
    )
    assert task is not None
    with pytest.raises(task_worker._LeaseLostError):
        await engine_tasks.execute_finalize(task, db_path=isolated_db)

    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == store.RunStatus.CANCELLED.value
    assert cancel_responses == [{"id": run_id, "status": "cancelled"}]
    assert store.get_latest_report(run_id, db_path=isolated_db) is None
    checkpoint = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert checkpoint is not None and checkpoint["stage"] == "fixture"
    events = owner.get(
        f"/api/runs/{run_id}/events?stream=false", headers=_OWNER
    ).json()["events"]
    assert not any(
        event["type"]
        in {
            "safety.hypothesis",
            "citation.grounding",
            "citation_audit",
            "report",
        }
        for event in events
    )


@pytest.mark.asyncio
async def test_resume_after_finalize_pause_read_does_not_write_stale_checkpoint(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A resume committed before the checkpoint transaction wins."""
    owner, run_id, task, hypothesis_id = _seed_owned_finalize(
        isolated_db, monkeypatch
    )
    _install_report_stubs(hypothesis_id, monkeypatch)
    previous = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert previous is not None
    resume_state = {
        **previous["state"],
        "resume_successor": engine_tasks.FINALIZE_TASK,
    }
    store.save_checkpoint(
        run_id,
        store.NewCheckpoint(
            stage=f"engine_task:{task.id}",
            schema_version=previous["schema_version"],
            last_event_seq=store.latest_event_seq(run_id, db_path=isolated_db),
            state=resume_state,
        ),
        db_path=isolated_db,
    )
    paused = owner.post(f"/api/runs/{run_id}/pause", headers=_OWNER)
    assert paused.status_code == 200, paused.text
    get_run = store.get_run
    paused_reads = 0
    resume_responses: list[dict[str, Any]] = []

    def resume_after_pause_snapshot(
        requested: str,
        db_path: str | None = None,
        conn: Any | None = None,
    ) -> Any:
        nonlocal paused_reads
        run = get_run(requested, db_path=db_path, conn=conn)
        if requested == run_id and run is not None and run.status == "paused":
            paused_reads += 1
            if paused_reads == 2:
                response = owner.post(
                    f"/api/runs/{run_id}/resume", headers=_OWNER
                )
                assert response.status_code == 200, response.text
                resume_responses.append(response.json())
        return run

    monkeypatch.setattr(store, "get_run", resume_after_pause_snapshot)
    result = await engine_tasks.execute_finalize(task, db_path=isolated_db)

    assert paused_reads >= 2
    assert resume_responses == [{"id": run_id, "status": "queued"}]
    assert result["status"] == store.RunStatus.COMPLETED.value
    completed = store.get_run(run_id, db_path=isolated_db)
    assert completed is not None
    assert completed.status == store.RunStatus.COMPLETED.value
    checkpoint = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert checkpoint is not None
    assert checkpoint["stage"] == f"engine_task:{task.id}"
    assert store.get_latest_report(run_id, db_path=isolated_db) is not None
    assert store.complete_task(
        task.id,
        str(task.lease_owner),
        result,
        db_path=isolated_db,
    )


@pytest.mark.asyncio
async def test_pause_during_final_drain_waits_for_explicit_resume(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pause committed during drain waits for explicit resume."""
    real_drain = engine_tasks_node._drain_and_persist_final_state
    owner, run_id, original_task, hypothesis_id = _seed_owned_finalize(
        isolated_db, monkeypatch, claim=False
    )
    _install_report_stubs(hypothesis_id, monkeypatch)
    _install_runtime(monkeypatch).drain_final_state = real_drain
    pause_responses: list[dict[str, Any]] = []

    async def pause_inside_drain(*_: Any, **kwargs: Any) -> Any:
        if not pause_responses:
            response = owner.post(f"/api/runs/{run_id}/pause", headers=_OWNER)
            assert response.status_code == 200, response.text
            pause_responses.append(response.json())
        store.add_hypothesis(
            store.NewHypothesis(
                run_id=run_id,
                hypothesis_id=hypothesis_id,
                title="IL-6 feedback",
                statement="IL-6 increases inflammation via STAT3 signaling.",
            ),
            db_path=isolated_db,
        )
        kwargs["final_state"]["metrics"] = {"llm_calls": 3}
        return SimpleNamespace(
            safety_counts={},
            grounding_counts={},
            report_inputs={"citation_summary": {}},
        )

    monkeypatch.setattr(
        engine_tasks_node, "persist_final_state", pause_inside_drain
    )

    assert await task_worker.run_once(
        "pause-during-drain-worker", run_id=run_id, db_path=isolated_db
    )
    paused = store.get_run(run_id, db_path=isolated_db)
    assert pause_responses == [{"id": run_id, "status": "paused"}]
    assert paused is not None and paused.status == store.RunStatus.PAUSED.value
    assert store.get_hypothesis(hypothesis_id, db_path=isolated_db) is None
    assert store.get_latest_report(run_id, db_path=isolated_db) is None
    pre_resume_events = owner.get(
        f"/api/runs/{run_id}/events?stream=false", headers=_OWNER
    ).json()["events"]
    assert not any(
        event["type"]
        in {
            "safety.hypothesis",
            "citation.grounding",
            "citation_audit",
            "report",
        }
        for event in pre_resume_events
    )
    assert (
        owner.get(f"/api/runs/{run_id}/report", headers=_OWNER).status_code
        == 404
    )
    checkpoint = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert checkpoint is not None
    assert checkpoint["stage"] == f"engine_task_paused:{original_task.id}"
    assert checkpoint["state"]["resume_successor"] == engine_tasks.FINALIZE_TASK
    assert store.get_run_metrics(run_id, db_path=isolated_db) == {
        "llm_calls": 3
    }
    assert (
        store.claim_task(
            "before-finalize-resume", run_id=run_id, db_path=isolated_db
        )
        is None
    )

    # Startup settlement leaves a cooperatively paused finalize checkpoint idle.
    from app import main

    recovered = main._reconcile_and_log_interrupted_runs()
    assert run_id not in recovered["failed"]
    assert run_id not in recovered["resumable"]
    assert run_id not in store.list_active_engine_task_run_ids(
        db_path=isolated_db
    )
    assert store.get_latest_report(run_id, db_path=isolated_db) is None

    resumed = owner.post(f"/api/runs/{run_id}/resume", headers=_OWNER)
    assert resumed.status_code == 200, resumed.text
    assert await task_worker.run_once(
        "resumed-finalize-worker", run_id=run_id, db_path=isolated_db
    )
    completed = store.get_run(run_id, db_path=isolated_db)
    assert completed is not None
    assert completed.status == store.RunStatus.COMPLETED.value
    assert store.get_latest_report(run_id, db_path=isolated_db) is not None

    events = owner.get(
        f"/api/runs/{run_id}/events?stream=false", headers=_OWNER
    ).json()["events"]
    pause_event = next(
        event
        for event in events
        if event["type"] == "lifecycle"
        and event["payload"].get("event") == "pause_requested"
    )
    resume_event = next(
        event
        for event in events
        if event["type"] == "status"
        and event["payload"].get("status") == "resuming"
    )
    report_event = next(event for event in events if event["type"] == "report")
    completion_event = next(
        event
        for event in events
        if event["type"] == "status"
        and event["payload"].get("status") == "completed"
    )
    assert pause_event["seq"] < resume_event["seq"]
    stages = [
        event
        for event in events
        if event["type"]
        in {"safety.hypothesis", "citation.grounding", "citation_audit"}
    ]
    assert [event["type"] for event in stages] == [
        "safety.hypothesis",
        "citation.grounding",
        "citation_audit",
    ]
    assert resume_event["seq"] < stages[0]["seq"]
    assert stages[-1]["seq"] < report_event["seq"] < completion_event["seq"]


@pytest.mark.asyncio
async def test_cancel_after_drain_commit_orders_stages_before_cancel(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancellation after drain commit withholds publication and stays last."""
    real_drain = engine_tasks_node._drain_and_persist_final_state
    owner, run_id, _queued_task, hypothesis_id = _seed_owned_finalize(
        isolated_db, monkeypatch, claim=False
    )
    _install_report_stubs(hypothesis_id, monkeypatch)
    _install_runtime(monkeypatch).drain_final_state = real_drain

    async def fake_persist_final_state(*_: Any, **kwargs: Any) -> Any:
        store.add_hypothesis(
            store.NewHypothesis(
                run_id=run_id,
                hypothesis_id=hypothesis_id,
                title="IL-6 feedback",
                statement="IL-6 increases inflammation via STAT3 signaling.",
            ),
            db_path=isolated_db,
        )
        kwargs["final_state"]["metrics"] = {"llm_calls": 5}
        return SimpleNamespace(
            safety_counts={},
            grounding_counts={},
            report_inputs={"citation_summary": {}},
        )

    monkeypatch.setattr(
        engine_tasks_node, "persist_final_state", fake_persist_final_state
    )
    task = store.claim_task(
        "cancel-after-drain-worker", run_id=run_id, db_path=isolated_db
    )
    assert task is not None
    commit_drain = engine_tasks_node._commit_finalize_drain
    cancel_responses: list[dict[str, Any]] = []

    def commit_then_cancel(*args: Any, **kwargs: Any) -> Any:
        outcome = commit_drain(*args, **kwargs)
        if len(args) > 2 and args[2] is not None:
            response = owner.post(f"/api/runs/{run_id}/cancel", headers=_OWNER)
            assert response.status_code == 200, response.text
            cancel_responses.append(response.json())
        return outcome

    monkeypatch.setattr(
        engine_tasks_node, "_commit_finalize_drain", commit_then_cancel
    )
    with pytest.raises(task_worker._LeaseLostError):
        await engine_tasks.execute_finalize(task, db_path=isolated_db)

    persisted = store.get_run(run_id, db_path=isolated_db)
    assert persisted is not None
    assert persisted.status == store.RunStatus.CANCELLED.value
    assert cancel_responses == [{"id": run_id, "status": "cancelled"}]
    assert store.get_latest_report(run_id, db_path=isolated_db) is None
    events = owner.get(
        f"/api/runs/{run_id}/events?stream=false", headers=_OWNER
    ).json()["events"]
    expected_stages = [
        "safety.hypothesis",
        "citation.grounding",
        "citation_audit",
    ]
    stage_events = [
        event for event in events if event["type"] in expected_stages
    ]
    cancelled = next(
        event
        for event in events
        if event["type"] == "status"
        and event["payload"].get("status") == "cancelled"
    )
    assert [event["type"] for event in stage_events] == expected_stages
    assert all(event["seq"] < cancelled["seq"] for event in stage_events)
    assert not any(
        event["type"] == "report"
        or event["payload"].get("status") == "completed"
        for event in events
    )
