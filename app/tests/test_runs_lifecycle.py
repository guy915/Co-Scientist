from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from itertools import pairwise
from threading import Event, Timer
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app import engine_tasks, task_worker
from app.config import settings
from app.engine_tasks import node as engine_tasks_node
from app.engine_tasks.support import TaskCommit
from app.runs import events as runs_events
from app.store import checkpoints, runs
from app.store import events as store_events
from app.store import tasks as store
from app.store import tasks_lifecycle as lifecycle
from app.store.models import RunRow, RunStatus, ScientificTask
from tests._client import DEFAULT_TEST_CLIENT_ID, make_client
from tests._client import create_run as _create_run
from tests._client import drain as _drain
from tests._client import make_client as _client
from tests._engine_tasks_helpers import _seed_checkpoint, _task_state
from tests._store_helpers import enqueue_task, seed_checkpoint, seed_run


def _new_run(c: TestClient, goal: str, *, tier: str = "express") -> str:
    response = _create_run(c, goal, tier=tier)
    return cast(str, response.json()["id"])


def test_cancel_after_capacity_reservation_prevents_bootstrap_admission(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    start_client = _client()
    cancel_client = _client()
    rid = _new_run(start_client, "Cancel between start admission steps")
    capacity_reserved = Event()
    cancel_entered_transaction = Event()
    continue_start = Event()
    reserve_capacity = runs.reserve_run_capacity_in_transaction
    cancel_tasks = lifecycle.cancel_run_tasks

    def reserve_then_wait(*args: object, **kwargs: object) -> bool:
        reserved = reserve_capacity(*args, **kwargs)  # type: ignore[arg-type]
        capacity_reserved.set()
        if not continue_start.wait(timeout=10):
            raise TimeoutError("test did not release the start barrier")
        return reserved

    def observe_cancel_tasks(*args: object, **kwargs: object) -> int:
        cancel_entered_transaction.set()
        return cancel_tasks(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        runs, "reserve_run_capacity_in_transaction", reserve_then_wait
    )
    monkeypatch.setattr(lifecycle, "cancel_run_tasks", observe_cancel_tasks)
    with ThreadPoolExecutor(max_workers=2) as executor:
        pending_start = executor.submit(
            start_client.post, f"/api/runs/{rid}/start", json={}
        )
        early_cancel = None
        try:
            assert capacity_reserved.wait(timeout=5)
            pending_cancel = executor.submit(
                cancel_client.post, f"/api/runs/{rid}/cancel"
            )
            if cancel_entered_transaction.wait(timeout=0.5):
                early_cancel = pending_cancel.result(timeout=5)
        finally:
            continue_start.set()
        started = pending_start.result(timeout=5)
        cancelled = (
            early_cancel
            if early_cancel is not None
            else pending_cancel.result(timeout=5)
        )

    assert started.status_code == 200
    assert cancelled.status_code == 200
    assert start_client.get(f"/api/runs/{rid}").json()["status"] == "cancelled"
    [task] = store.list_tasks(rid, db_path=isolated_db)
    assert task.status == "cancelled"
    events = store_events.list_events(rid, db_path=isolated_db)
    cancelled_event = next(
        event
        for event in events
        if event["type"] == "status"
        and event["payload"].get("status") == "cancelled"
    )
    queued_event = next(
        event
        for event in events
        if event["type"] == "lifecycle"
        and event["payload"].get("event") == "queued"
    )
    assert queued_event["seq"] < cancelled_event["seq"]


def test_cancel_before_capacity_reservation_is_not_a_restart(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    start_client = _client()
    cancel_client = _client()
    rid = _new_run(start_client, "Cancel before the start reservation")
    start_reached_reservation = Event()
    continue_start = Event()
    from app.runs import lifecycle as runs_lifecycle

    admit_workflow = runs_lifecycle._enqueue_workflow_and_maybe_launch_worker

    def wait_before_admission(*args: object, **kwargs: object) -> object:
        start_reached_reservation.set()
        if not continue_start.wait(timeout=10):
            raise TimeoutError("test did not release the start barrier")
        return admit_workflow(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        runs_lifecycle,
        "_enqueue_workflow_and_maybe_launch_worker",
        wait_before_admission,
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending_start = executor.submit(
            start_client.post, f"/api/runs/{rid}/start", json={}
        )
        try:
            assert start_reached_reservation.wait(timeout=5)
            cancelled = cancel_client.post(f"/api/runs/{rid}/cancel")
            assert cancelled.status_code == 200
        finally:
            continue_start.set()
        started = pending_start.result(timeout=5)

    assert started.status_code == 409
    assert start_client.get(f"/api/runs/{rid}").json()["status"] == "cancelled"
    assert not any(
        task.status == "queued"
        for task in store.list_tasks(rid, db_path=isolated_db)
    )
    events = store_events.list_events(rid, db_path=isolated_db)
    cancelled_event = next(
        event
        for event in events
        if event["type"] == "status"
        and event["payload"].get("status") == "cancelled"
    )
    assert not any(
        event["type"] == "lifecycle"
        and event["payload"].get("event") == "queued"
        and event["seq"] > cancelled_event["seq"]
        for event in events
    )


@pytest.mark.parametrize("paused_first", [False, True])
def test_cancelled_bootstrap_is_requeued_by_a_second_start(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, paused_first: bool
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = _client()
    rid = _new_run(client, "Restart a cancelled bootstrap")
    assert client.post(f"/api/runs/{rid}/start", json={}).status_code == 200
    [bootstrap] = store.list_tasks(rid, db_path=isolated_db)
    if paused_first:
        assert client.post(f"/api/runs/{rid}/pause").status_code == 200
    assert client.post(f"/api/runs/{rid}/cancel").status_code == 200
    cancelled = store.get_task(bootstrap.id, db_path=isolated_db)
    assert cancelled is not None and cancelled.status == "cancelled"

    restarted = client.post(f"/api/runs/{rid}/start", json={})

    assert restarted.status_code == 200
    assert restarted.json()["task_id"] == bootstrap.id
    [requeued] = store.list_tasks(rid, db_path=isolated_db)
    assert requeued.id == bootstrap.id
    assert requeued.status == "queued"


@pytest.mark.parametrize("status", [RunStatus.CANCELLED, RunStatus.FAILED])
def test_checkpointed_run_is_resumed_not_restarted(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, status: RunStatus
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = _client()
    rid = _new_run(client, "Continue a checkpointed run")
    _seed_checkpoint(rid, _task_state(rid), db_path=isolated_db)
    runs.update_run_status(rid, status, db_path=isolated_db)

    restart = client.post(f"/api/runs/{rid}/start", json={})

    assert restart.status_code == 409
    assert "use /resume" in restart.json()["detail"]
    assert store.list_tasks(rid, db_path=isolated_db) == []

    resumed = client.post(f"/api/runs/{rid}/resume")

    assert resumed.status_code == 200
    assert runs.get_run(rid, db_path=isolated_db).status == "queued"  # type: ignore[union-attr]
    [task] = store.list_tasks(rid, db_path=isolated_db)
    assert task.task_type == "engine.node.orchestrator"
    assert task.status == "queued"


def test_blocked_bootstrap_without_checkpoint_requires_new_run(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.store.models import RunStatus

    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = _client()
    rid = _new_run(client, "Do not revive an intake block")
    assert client.post(f"/api/runs/{rid}/start", json={}).status_code == 200
    task = store.claim_task("blocked-bootstrap", run_id=rid)
    assert task is not None
    assert lifecycle.complete_task(
        task.id,
        "blocked-bootstrap",
        {"status": "withheld"},
        db_path=isolated_db,
    )
    runs.update_run_status(rid, RunStatus.BLOCKED, db_path=isolated_db)

    restart = client.post(f"/api/runs/{rid}/start", json={})

    assert restart.status_code == 409
    assert "create a new run" in restart.json()["detail"]
    saved = store.get_task(task.id, db_path=isolated_db)
    assert saved is not None and saved.status == "completed"


def test_start_rolls_back_capacity_when_bootstrap_enqueue_fails(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import HTTPException

    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = _client()
    rid = _new_run(client, "Rollback an incomplete start")

    def fail_enqueue(*_: object, **__: object) -> object:
        raise HTTPException(status_code=503, detail="injected enqueue failure")

    monkeypatch.setattr(engine_tasks, "enqueue_bootstrap", fail_enqueue)
    response = client.post(f"/api/runs/{rid}/start", json={})

    assert response.status_code == 503
    run = runs.get_run(rid, db_path=isolated_db)
    assert run is not None and run.status == "draft"
    assert store.list_tasks(rid, db_path=isolated_db) == []
    assert not any(
        event["type"] == "lifecycle"
        and event["payload"].get("event") == "queued"
        for event in store_events.list_events(rid, db_path=isolated_db)
    )


@pytest.mark.parametrize("terminal_event", [True, False])
def test_event_stream_tails_a_live_run_until_it_ends(
    isolated_db: str, terminal_event: bool
) -> None:
    run = seed_run(
        "Tail a live run",
        client_id=DEFAULT_TEST_CLIENT_ID,
        db_path=isolated_db,
    )
    runs.update_run_status(run.id, RunStatus.RUNNING, db_path=isolated_db)
    store_events.append_event(run.id, "log", {"i": 0}, db_path=isolated_db)

    def finish() -> None:
        # Without a terminal status event the stream must notice the run row.
        store_events.append_event(
            run.id, "status", {"status": "running"}, db_path=isolated_db
        )
        if terminal_event:
            store_events.append_event(
                run.id, "status", {"status": "completed"}, db_path=isolated_db
            )
        runs.update_run_status(run.id, RunStatus.COMPLETED, db_path=isolated_db)

    timer = Timer(0.3, finish)
    timer.start()
    body = make_client().get(f"/api/runs/{run.id}/events").text
    timer.join()

    frames = [json.loads(line[6:]) for line in body.splitlines() if line]
    assert [frame["type"] for frame in frames] == [
        "log",
        "status",
        *(["status"] if terminal_event else []),
        "_terminal",
    ]
    assert frames[-1]["payload"]["status"] == "completed"


def test_live_tail_stops_when_the_client_disconnects(isolated_db: str) -> None:
    class _Gone:
        async def is_disconnected(self) -> bool:
            return True

    run = seed_run("Abandoned stream", db_path=isolated_db)

    assert _drain(runs_events._stream_live_tail(run.id, _Gone(), 0)) == []  # type: ignore[arg-type]


def test_events_endpoint_serves_json_snapshot_when_stream_false(
    isolated_db: str,
) -> None:
    from tests._client import DEFAULT_TEST_CLIENT_ID, make_client

    run = seed_run(
        "JSON events goal",
        profile="default",
        provider="mock",
        client_id=DEFAULT_TEST_CLIENT_ID,
        db_path=isolated_db,
    )
    store_events.append_event(run.id, "lifecycle", {"event": "created"})
    store_events.append_event(run.id, "status", {"status": "running"})

    client = make_client()
    res = client.get(f"/api/runs/{run.id}/events?stream=false")

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/json")
    events = res.json()["events"]
    assert [e["type"] for e in events] == ["lifecycle", "status"]
    assert events[0]["seq"] == 1
    assert events[1]["payload"] == {"status": "running", "activity": "other"}

    after = client.get(f"/api/runs/{run.id}/events?stream=false&after=1")
    assert [e["seq"] for e in after.json()["events"]] == [2]


_OWNER = {"X-Client-ID": "pause-cohort-owner"}


def _owned_running_run(db_path: str) -> tuple[TestClient, str]:
    client = make_client()
    created = _create_run(
        client, "Pause a durable engine cohort", headers=_OWNER, tier="express"
    )
    assert created.status_code == 200, created.text
    run_id = str(created.json()["id"])
    runs.update_run_status(run_id, RunStatus.RUNNING, db_path=db_path)
    return client, run_id


def _leased_supervisor(
    run_id: str, db_path: str
) -> tuple[dict[str, Any], int, ScientificTask]:
    state = _task_state(run_id)
    checkpoint_seq = _seed_checkpoint(run_id, state, db_path=db_path)
    writer = enqueue_task(
        run_id,
        f"{engine_tasks.NODE_TASK_PREFIX}supervisor",
        "pause-cohort:supervisor",
        inputs={"checkpoint_seq": checkpoint_seq},
        db_path=db_path,
    )
    leased = store.claim_task(
        "pause-cohort-writer", run_id=run_id, db_path=db_path
    )
    assert leased is not None and leased.id == writer.id
    return state, checkpoint_seq, leased


async def _complete_supervisor_after_pause(
    client: TestClient,
    run_id: str,
    writer: tuple[dict[str, Any], int, ScientificTask],
    db_path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, checkpoint_seq, leased = writer
    monkeypatch.setattr(
        engine_tasks_node,
        "_prepare_node_task",
        lambda *_: (
            state,
            TaskCommit(leased, checkpoint_seq, db_path),
            "supervisor",
        ),
    )

    async def execute_node(
        _name: str, node_state: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        return {**node_state, "committed_after_pause": True}, "generate"

    from co_scientist import task_runtime

    monkeypatch.setattr(task_runtime, "execute_task_node", execute_node)
    commit_node_result = engine_tasks_node._commit_node_result

    async def pause_then_commit(
        commit: TaskCommit,
        run: RunRow,
        node_name: str,
        committed: dict[str, Any],
        successor: str | None,
    ) -> dict[str, Any]:
        response = client.post(f"/api/runs/{run_id}/pause", headers=_OWNER)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "paused"
        return await commit_node_result(
            commit, run, node_name, committed, successor
        )

    monkeypatch.setattr(
        engine_tasks_node, "_commit_node_result", pause_then_commit
    )
    result = await engine_tasks.execute_node_task(leased, db_path=db_path)
    assert result["status"] == "paused"
    assert lifecycle.complete_task(
        leased.id, "pause-cohort-writer", result, db_path=db_path
    )


@pytest.mark.asyncio
async def test_owned_pause_fences_late_checkpoint_successor_until_resume(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client, run_id = _owned_running_run(isolated_db)
    writer = _leased_supervisor(run_id, isolated_db)
    _, checkpoint_seq, leased = writer
    await _complete_supervisor_after_pause(
        client,
        run_id,
        writer,
        isolated_db,
        monkeypatch,
    )

    checkpoint = checkpoints.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert checkpoint is not None
    assert checkpoint["seq"] == checkpoint_seq + 1
    assert checkpoint["stage"] == f"engine_task_paused:{leased.id}"
    successor_type = f"{engine_tasks.NODE_TASK_PREFIX}generate"
    assert checkpoint["state"]["resume_successor"] == successor_type

    successor = enqueue_task(
        run_id,
        successor_type,
        f"{successor_type}:after:{leased.id}",
        inputs={"checkpoint_seq": checkpoint["seq"]},
        dependencies=(leased.id,),
        provenance={"scheduled_by": leased.task_type},
        db_path=isolated_db,
    )
    queued_successor = store.get_task(successor.id, db_path=isolated_db)
    paused_run = runs.get_run(run_id, db_path=isolated_db)
    assert (
        paused_run is not None and paused_run.status == RunStatus.PAUSED.value
    )
    assert queued_successor is not None and queued_successor.status == "queued"
    assert (
        store.claim_task(
            "claim-late-queued-successor",
            run_id=run_id,
            db_path=isolated_db,
        )
        is None
    )
    claimable, active, _parked_until = lifecycle.cohort_poll(
        run_id, db_path=isolated_db
    )
    assert not claimable and not active

    resumed = client.post(f"/api/runs/{run_id}/resume", headers=_OWNER)
    assert resumed.status_code == 200, resumed.text
    tasks = store.list_tasks(run_id, db_path=isolated_db)
    task_ids = [task.id for task in tasks]
    assert len(task_ids) == len(set(task_ids))
    assert len(task_ids) == 2
    assert set(task_ids) == {leased.id, successor.id}
    assert (
        sum(
            task.idempotency_key == f"{successor_type}:after:{leased.id}"
            for task in tasks
        )
        == 1
    )

    claimed = store.claim_task(
        "claim-after-resume", run_id=run_id, db_path=isolated_db
    )
    assert claimed is not None and claimed.id == successor.id
    assert claimed.task_type == successor_type
    assert claimed.inputs["checkpoint_seq"] == checkpoint["seq"]
    assert claimed.dependencies == (leased.id,)
    assert (
        store.claim_task(
            "claim-after-resume-again", run_id=run_id, db_path=isolated_db
        )
        is None
    )

    events = store_events.list_events(run_id, db_path=isolated_db)
    pause = next(
        event
        for event in events
        if event["type"] == "lifecycle"
        and event["payload"].get("event") == "pause_requested"
    )
    completion = next(
        event
        for event in events
        if event["type"] == "scientific_task"
        and event["payload"].get("task") == "supervisor"
        and event["payload"].get("status") == "completed"
    )
    resuming = next(
        event
        for event in events
        if event["type"] == "status"
        and event["payload"].get("status") == "resuming"
    )
    assert pause["seq"] < completion["seq"] < resuming["seq"]
    assert not any(
        pause["seq"] < event["seq"] < resuming["seq"]
        and event["payload"].get("status") == "running"
        for event in events
    )


_OLD_OWNER = "pre-restart-worker"


@dataclass
class _StartupProbe:
    recovery_finished: Event = field(default_factory=Event)
    worker_started: Event = field(default_factory=Event)
    task_scans: list[list[str]] = field(default_factory=list)
    cohort_run_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _PausedRestart:
    run_id: str
    writer_id: str
    successor_id: str
    paused_seq: int


def _seed_paused_restart(db_path: str) -> _PausedRestart:
    run = seed_run(
        "Pause restart acceptance",
        profile="express",
        client_id=DEFAULT_TEST_CLIENT_ID,
        db_path=db_path,
    )
    runs.update_run_status(run.id, RunStatus.RUNNING, db_path=db_path)
    writer = enqueue_task(
        run.id,
        f"{engine_tasks.NODE_TASK_PREFIX}generate",
        "pause-restart:writer",
        inputs={"checkpoint_seq": 0},
        db_path=db_path,
    )
    claimed = store.claim_task(
        _OLD_OWNER, run_id=run.id, lease_seconds=3600, db_path=db_path
    )
    assert claimed is not None and claimed.id == writer.id
    successor_id, paused_seq = _append_late_successor(run.id, writer, db_path)
    return _PausedRestart(run.id, writer.id, successor_id, paused_seq)


def _append_late_successor(
    run_id: str, writer: ScientificTask, db_path: str
) -> tuple[str, int]:
    successor_type = f"{engine_tasks.NODE_TASK_PREFIX}ranking"
    runs.update_run_status(run_id, RunStatus.PAUSED, db_path=db_path)
    paused_seq = store_events.append_event(
        run_id, "status", {"status": "paused"}, db_path=db_path
    )
    checkpoint_seq = seed_checkpoint(
        run_id,
        {"provider": "engine", "resume_successor": successor_type},
        stage=f"engine_task_paused:{writer.id}",
        last_event_seq=paused_seq,
        db_path=db_path,
    )
    successor = enqueue_task(
        run_id,
        successor_type,
        f"{successor_type}:after:{writer.id}",
        inputs={"checkpoint_seq": checkpoint_seq},
        dependencies=(writer.id,),
        provenance={"scheduled_by": writer.task_type},
        db_path=db_path,
    )
    return successor.id, paused_seq


def _observe_startup(monkeypatch: pytest.MonkeyPatch) -> _StartupProbe:
    from app import main as main_module

    probe = _StartupProbe()
    original_start = main_module._start_recovery_task
    original_scan = store.list_active_engine_task_run_ids

    async def no_seed() -> None:
        return None

    def start_recovery(
        reconciled: dict[str, list[str]],
    ) -> tuple[asyncio.Task[None], list[asyncio.Task[None]]]:
        recovery, workers = original_start(reconciled)
        recovery.add_done_callback(lambda _: probe.recovery_finished.set())
        return recovery, workers

    def scan_active(db_path: str | None = None) -> list[str]:
        run_ids = original_scan(db_path)
        probe.task_scans.append(run_ids)
        return run_ids

    def record_cohort(run_id: str, _worker_id: str) -> None:
        probe.cohort_run_ids.append(run_id)
        probe.worker_started.set()

    monkeypatch.setattr(main_module, "seed_demo_runs", no_seed)
    monkeypatch.setattr(main_module, "_start_recovery_task", start_recovery)
    monkeypatch.setattr(store, "list_active_engine_task_run_ids", scan_active)
    monkeypatch.setattr(task_worker, "run_run_worker_pool_sync", record_cohort)
    return probe


def _assert_startup_left_run_paused(
    probe: _StartupProbe,
    state: _PausedRestart,
    db_path: str,
) -> None:
    assert probe.recovery_finished.wait(5), "startup recovery did not finish"
    assert probe.task_scans
    assert all(state.run_id not in run_ids for run_ids in probe.task_scans)
    assert probe.cohort_run_ids == []
    run = runs.get_run(state.run_id, db_path=db_path)
    writer = store.get_task(state.writer_id, db_path=db_path)
    successor = store.get_task(state.successor_id, db_path=db_path)
    assert run is not None and run.status == RunStatus.PAUSED.value
    assert writer is not None and writer.status == "leased"
    assert successor is not None and successor.status == "queued"
    assert (
        store.claim_task(
            "before-explicit-resume", run_id=state.run_id, db_path=db_path
        )
        is None
    )


def _assert_resume_reuses_successor(
    client: TestClient,
    probe: _StartupProbe,
    state: _PausedRestart,
    db_path: str,
) -> None:
    before = store.list_tasks(state.run_id, db_path=db_path)
    before_ids = {task.id for task in before}
    assert before_ids == {state.writer_id, state.successor_id}
    response = client.post(f"/api/runs/{state.run_id}/resume")
    assert response.status_code == 200, response.text
    assert probe.worker_started.wait(5), "explicit resume did not launch"
    assert probe.cohort_run_ids == [state.run_id]
    after = store.list_tasks(state.run_id, db_path=db_path)
    assert {task.id for task in after} == before_ids
    successors = [
        task
        for task in after
        if task.task_type == f"{engine_tasks.NODE_TASK_PREFIX}ranking"
    ]
    assert len(successors) == 1 and successors[0].id == state.successor_id
    assert successors[0].dependencies == (state.writer_id,)
    assert lifecycle.complete_task(
        state.writer_id, _OLD_OWNER, {}, db_path=db_path
    )
    claimed = store.claim_task(
        "after-explicit-resume", run_id=state.run_id, db_path=db_path
    )
    assert claimed is not None and claimed.id == state.successor_id
    _assert_ordered_event_replay(client, state.run_id, state.paused_seq)


def _assert_ordered_event_replay(
    client: TestClient, run_id: str, paused_seq: int
) -> None:
    events = client.get(f"/api/runs/{run_id}/events?stream=false").json()[
        "events"
    ]
    seqs = [event["seq"] for event in events]
    assert all(left < right for left, right in pairwise(seqs))
    paused = next(event for event in events if event["seq"] == paused_seq)
    assert paused["type"] == "status"
    assert paused["payload"]["status"] == "paused"
    replay = client.get(
        f"/api/runs/{run_id}/events?stream=false&after={paused_seq}"
    ).json()["events"]
    assert replay == [event for event in events if event["seq"] > paused_seq]
    assert [event["payload"].get("status") for event in replay] == ["resuming"]


def test_restart_keeps_paused_successor_idle_until_explicit_resume(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", True)
    restart = _seed_paused_restart(isolated_db)
    probe = _observe_startup(monkeypatch)
    with make_client() as client:
        _assert_startup_left_run_paused(probe, restart, isolated_db)
        _assert_resume_reuses_successor(client, probe, restart, isolated_db)
