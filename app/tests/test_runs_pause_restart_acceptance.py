"""Restart acceptance for paused runs with late durable successors."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from itertools import pairwise
from threading import Event

import pytest
from fastapi.testclient import TestClient

from app import engine_tasks, store, task_worker
from app.config import settings
from app.store import (
    NewCheckpoint,
    NewTask,
    RunCreateOptions,
    RunStatus,
    ScientificTask,
)
from tests._client import DEFAULT_TEST_CLIENT_ID, make_client

_OLD_OWNER = "pre-restart-worker"


@dataclass
class _StartupProbe:
    """Observe recovery completion and any startup or resume cohorts."""

    recovery_finished: Event = field(default_factory=Event)
    worker_started: Event = field(default_factory=Event)
    task_scans: list[list[str]] = field(default_factory=list)
    cohort_run_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _PausedRestart:
    """Persisted identifiers needed across restart and explicit resume."""

    run_id: str
    writer_id: str
    successor_id: str
    paused_seq: int


def _seed_paused_restart(db_path: str) -> _PausedRestart:
    """Seed a leased writer and its late-committed checkpoint successor."""
    run = store.create_run(
        "Pause restart acceptance",
        "express",
        "engine",
        {},
        RunCreateOptions(client_id=DEFAULT_TEST_CLIENT_ID, db_path=db_path),
    )
    store.update_run_status(run.id, RunStatus.RUNNING, db_path=db_path)
    writer = store.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}generate",
            inputs={"checkpoint_seq": 0},
            idempotency_key="pause-restart:writer",
        ),
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
    """Pause after leasing the writer, then persist its checkpoint successor."""
    successor_type = f"{engine_tasks.NODE_TASK_PREFIX}ranking"
    store.update_run_status(run_id, RunStatus.PAUSED, db_path=db_path)
    paused_seq = store.append_event(
        run_id, "status", {"status": "paused"}, db_path=db_path
    )
    checkpoint_seq = store.save_checkpoint(
        run_id,
        NewCheckpoint(
            stage=f"engine_task_paused:{writer.id}",
            schema_version=1,
            last_event_seq=paused_seq,
            state={"provider": "engine", "resume_successor": successor_type},
        ),
        db_path=db_path,
    )
    successor = store.enqueue_task(
        NewTask(
            run_id=run_id,
            task_type=successor_type,
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key=f"{successor_type}:after:{writer.id}",
            dependencies=(writer.id,),
            provenance={"scheduled_by": writer.task_type},
        ),
        db_path=db_path,
    )
    return successor.id, paused_seq


def _observe_startup(monkeypatch: pytest.MonkeyPatch) -> _StartupProbe:
    """Keep startup offline and record its recovery and cohort boundaries."""
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
    """Check restart leaves paused engine work untouched."""
    assert probe.recovery_finished.wait(5), "startup recovery did not finish"
    assert probe.task_scans
    assert all(state.run_id not in run_ids for run_ids in probe.task_scans)
    assert probe.cohort_run_ids == []
    run = store.get_run(state.run_id, db_path=db_path)
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
    """Resume explicitly, finish the leased writer, and claim one successor."""
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
    assert store.complete_task(state.writer_id, _OLD_OWNER, {}, db_path=db_path)
    claimed = store.claim_task(
        "after-explicit-resume", run_id=state.run_id, db_path=db_path
    )
    assert claimed is not None and claimed.id == state.successor_id
    _assert_ordered_event_replay(client, state.run_id, state.paused_seq)


def _assert_ordered_event_replay(
    client: TestClient, run_id: str, paused_seq: int
) -> None:
    """Check ordered full replay and the ordered post-pause resume suffix."""
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
    """Startup leaves paused work alone; resume reuses its one continuation."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", True)
    restart = _seed_paused_restart(isolated_db)
    probe = _observe_startup(monkeypatch)
    with make_client() as client:
        _assert_startup_left_run_paused(probe, restart, isolated_db)
        _assert_resume_reuses_successor(client, probe, restart, isolated_db)
