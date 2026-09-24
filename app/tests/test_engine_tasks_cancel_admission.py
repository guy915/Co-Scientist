"""Cancellation and lease races at the durable bootstrap boundary."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app import engine_tasks, store, task_worker
from tests._client import make_client


def _cancel_after_second_run_read(run_id: str, client: Any) -> Any:
    """Cancel immediately after bootstrap's final pre-running status read."""
    real_get_run = store.get_run
    run_reads = 0

    def cancel_after_read(
        requested_run_id: str,
        db_path: str | None = None,
        conn: Any | None = None,
    ) -> Any:
        nonlocal run_reads
        run = real_get_run(requested_run_id, db_path=db_path, conn=conn)
        if requested_run_id == run_id:
            run_reads += 1
            if run_reads == 2:
                response = client.post(f"/api/runs/{run_id}/cancel")
                assert response.status_code == 200
        return run

    return cancel_after_read


@pytest.mark.asyncio
async def test_cancel_after_bootstrap_read_cannot_be_overwritten(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bootstrap's RUNNING write cannot reverse a completed cancellation."""
    from app.config import settings

    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = make_client()
    created = client.post(
        "/api/runs", json={"research_goal": "Cancel before bootstrap starts"}
    )
    run_id = created.json()["id"]
    assert client.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
    task = store.claim_task("bootstrap-worker", run_id=run_id)
    assert task is not None

    real_get_run = store.get_run
    monkeypatch.setattr(
        store, "get_run", _cancel_after_second_run_read(run_id, client)
    )
    prepared: list[bool] = []

    async def no_intake_work(*_: Any, **__: Any) -> None:
        return None

    async def prepare_without_providers(*_: Any, **__: Any) -> tuple[Any, ...]:
        prepared.append(True)
        return {}, object()

    async def emit_without_persisting(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(
        engine_tasks, "_screen_bootstrap_intake", no_intake_work
    )
    monkeypatch.setattr(
        engine_tasks, "_prepare_bootstrap_state", prepare_without_providers
    )
    monkeypatch.setattr(
        engine_tasks, "_save_state_and_enqueue", lambda *_: (1, "successor")
    )
    monkeypatch.setattr(
        engine_tasks,
        "make_emitter",
        lambda *_args, **_kwargs: emit_without_persisting,
    )
    monkeypatch.setattr(
        engine_tasks, "sync_engine_llm_backend", lambda *_: None
    )

    result = await engine_tasks.execute_bootstrap(task, db_path=isolated_db)

    refreshed = real_get_run(run_id, db_path=isolated_db)
    assert refreshed is not None and refreshed.status == "cancelled"
    assert result.get("status") == "cancelled"
    assert prepared == []
    persisted = store.get_task(task.id, db_path=isolated_db)
    assert persisted is not None and persisted.status == "cancelled"


@pytest.mark.parametrize("decision", ["block", "hold"])
@pytest.mark.asyncio
async def test_cancel_during_bootstrap_safety_gate_keeps_cancelled_status(
    decision: str,
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A late intake verdict cannot overwrite completed cancellation."""
    from app.config import settings
    from app.safety_types import SafetyDecision

    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = make_client()
    created = client.post(
        "/api/runs", json={"research_goal": "Cancel during safety screening"}
    )
    run_id = created.json()["id"]
    assert client.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
    task = store.claim_task("gate-worker", run_id=run_id)
    assert task is not None

    screening_started = asyncio.Event()
    release_screening = asyncio.Event()
    verdict = SafetyDecision(
        stage="intake",
        decision=decision,
        reason=f"injected {decision}",
    )

    async def delayed_screen(*_: Any, **__: Any) -> SafetyDecision:
        screening_started.set()
        await release_screening.wait()
        return verdict

    monkeypatch.setattr(engine_tasks, "screen_with_escalation", delayed_screen)
    bootstrap = asyncio.create_task(
        engine_tasks.execute_bootstrap(task, db_path=isolated_db)
    )
    await asyncio.wait_for(screening_started.wait(), timeout=5)
    cancelled = client.post(f"/api/runs/{run_id}/cancel")
    assert cancelled.status_code == 200
    cancel_seq = next(
        event["seq"]
        for event in store.list_events(run_id, db_path=isolated_db)
        if event["type"] == "status"
        and event["payload"].get("status") == "cancelled"
    )
    release_screening.set()

    if decision == "hold":
        with pytest.raises(engine_tasks.SafetyHoldError):
            await bootstrap
    else:
        assert (await bootstrap)["status"] == "withheld"

    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "cancelled"
    assert not any(
        event["type"] == "status"
        and event["seq"] > cancel_seq
        and event["payload"].get("status") in {"blocked", "paused"}
        for event in store.list_events(run_id, db_path=isolated_db)
    )


@pytest.mark.parametrize("decision", ["block", "hold"])
@pytest.mark.asyncio
async def test_stale_bootstrap_lease_cannot_apply_intake_stop(
    decision: str,
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A late verdict from a replaced bootstrap lease cannot stop the run."""
    from app.config import settings
    from app.safety_types import SafetyDecision

    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = make_client()
    created = client.post(
        "/api/runs", json={"research_goal": "Replace intake lease"}
    )
    run_id = created.json()["id"]
    assert client.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
    original = store.claim_task("old-bootstrap", run_id=run_id)
    assert original is not None

    screening_started = asyncio.Event()
    release_screening = asyncio.Event()

    async def delayed_screen(*_: Any, **__: Any) -> SafetyDecision:
        screening_started.set()
        await release_screening.wait()
        return SafetyDecision(stage="intake", decision=decision, reason="late")

    monkeypatch.setattr(engine_tasks, "screen_with_escalation", delayed_screen)
    bootstrap = asyncio.create_task(
        engine_tasks.execute_bootstrap(original, db_path=isolated_db)
    )
    await asyncio.wait_for(screening_started.wait(), timeout=5)
    with store.transaction(isolated_db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET lease_expires_at=0 WHERE id=?",
            (original.id,),
        )
    replacement = store.claim_task("new-bootstrap", run_id=run_id)
    assert replacement is not None
    assert replacement.attempt == original.attempt + 1
    release_screening.set()

    if decision == "hold":
        with pytest.raises(engine_tasks.SafetyHoldError):
            await bootstrap
    else:
        assert (await bootstrap)["status"] == "withheld"

    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == "queued"
    assert not any(
        event["type"] == "status"
        and event["payload"].get("status") in {"blocked", "paused"}
        for event in store.list_events(run_id, db_path=isolated_db)
    )


@pytest.mark.asyncio
async def test_replaced_bootstrap_lease_cannot_prepare_paused_run(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale worker cannot prepare or sync a run that is already paused."""
    from app.config import settings
    from app.store import RunStatus

    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = make_client()
    created = client.post(
        "/api/runs", json={"research_goal": "Pause after lease replacement"}
    )
    run_id = created.json()["id"]
    assert client.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
    original = store.claim_task("old-paused-worker", run_id=run_id)
    assert original is not None
    with store.transaction(isolated_db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET lease_expires_at=0 WHERE id=?",
            (original.id,),
        )
    replacement = store.claim_task("current-paused-worker", run_id=run_id)
    assert replacement is not None
    assert replacement.attempt == original.attempt + 1
    store.update_run_status(run_id, RunStatus.PAUSED, db_path=isolated_db)
    prepared: list[bool] = []
    synced: list[bool] = []

    async def no_intake_work(*_: Any, **__: Any) -> None:
        return None

    async def fake_prepare(*_: Any, **__: Any) -> tuple[Any, ...]:
        prepared.append(True)
        return {}, object()

    monkeypatch.setattr(
        engine_tasks, "_screen_bootstrap_intake", no_intake_work
    )
    monkeypatch.setattr(engine_tasks, "_prepare_bootstrap_state", fake_prepare)
    monkeypatch.setattr(
        engine_tasks, "sync_engine_llm_backend", lambda *_: synced.append(True)
    )

    with pytest.raises(task_worker._LeaseLostError):
        await engine_tasks.execute_bootstrap(original, db_path=isolated_db)

    assert prepared == []
    assert synced == []
    assert (
        store.mark_bootstrap_running(
            run_id,
            replacement.id,
            replacement.lease_owner,
            replacement.attempt,
            db_path=isolated_db,
        )
        == RunStatus.PAUSED.value
    )
