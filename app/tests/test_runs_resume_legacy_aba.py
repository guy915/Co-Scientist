"""Legacy resume cleanup must not erase lifecycle admission revisions."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Any

import pytest

from app import engine_tasks, store
from app.config import settings
from app.store import NewCheckpoint, RunCreateOptions, RunStatus, ScientificTask
from tests._client import DEFAULT_TEST_CLIENT_ID, make_client


def _paused_legacy_run(db_path: str) -> tuple[str, int]:
    run = store.create_run(
        "Legacy resume lifecycle race",
        "express",
        "engine",
        {},
        options=RunCreateOptions(
            client_id=DEFAULT_TEST_CLIENT_ID,
            db_path=db_path,
        ),
    )
    run_id = run.id
    store.update_run_status(run_id, RunStatus.RUNNING, db_path=db_path)
    store.save_checkpoint(
        run_id,
        NewCheckpoint(
            stage="legacy-envelope",
            schema_version=1,
            last_event_seq=store.latest_event_seq(run_id, db_path=db_path),
            state={"provider": "mock", "legacy": True},
        ),
        db_path=db_path,
    )
    status_seq = store.append_event(
        run_id,
        "status",
        {"status": "running"},
        db_path=db_path,
    )
    pause_seq = store.append_event(
        run_id,
        "lifecycle",
        {"event": "pause_requested"},
        db_path=db_path,
    )
    log_seq = store.append_event(
        run_id, "log", {"message": "generated"}, db_path=db_path
    )
    assert (status_seq, pause_seq, log_seq) == (1, 2, 3)
    store.update_run_status(run_id, RunStatus.PAUSED, db_path=db_path)
    return run_id, store.latest_event_seq(run_id, db_path=db_path)


def test_legacy_cleanup_preserves_lifecycle_revision_for_stale_resume(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A legacy cleanup cannot recycle the revision of an admitted pause."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    owner = make_client()
    later_resumer = make_client()
    run_id, old_high_water = _paused_legacy_run(isolated_db)

    from app import runs_lifecycle

    queue_reached = Event()
    release_queue = Event()
    original_queue = runs_lifecycle._queue_resume_workflow

    def hold_first_resume(*args: Any, **kwargs: Any) -> ScientificTask:
        if not queue_reached.is_set():
            queue_reached.set()
            assert release_queue.wait(timeout=5), (
                "resume barrier was not released"
            )
        return original_queue(*args, **kwargs)

    monkeypatch.setattr(
        runs_lifecycle, "_queue_resume_workflow", hold_first_resume
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        stale_resume = pool.submit(owner.post, f"/api/runs/{run_id}/resume")
        assert queue_reached.wait(timeout=5), (
            "resume did not reach admission barrier"
        )
        cancelled = owner.post(f"/api/runs/{run_id}/cancel")
        assert cancelled.status_code == 200, cancelled.text
        store.append_event(
            run_id,
            "log",
            {"message": "late generated event"},
            db_path=isolated_db,
        )
        pre_cleanup_high_water = store.latest_event_seq(
            run_id, db_path=isolated_db
        )

        explicit_resume = later_resumer.post(f"/api/runs/{run_id}/resume")
        assert explicit_resume.status_code == 200, explicit_resume.text
        events = store.list_events(run_id, db_path=isolated_db)
        assert not any(event["type"] == "log" for event in events)
        resumed_seq = max(
            event["seq"]
            for event in events
            if event["type"] == "status"
            and event["payload"].get("status") == "resuming"
        )

        paused = owner.post(f"/api/runs/{run_id}/pause")
        assert paused.status_code == 200, paused.text
        release_queue.set()
        stale = stale_resume.result(timeout=5)

    assert stale.status_code == 409, stale.text
    assert resumed_seq > pre_cleanup_high_water > old_high_water
    assert any(
        event["type"] == "lifecycle"
        and event["payload"].get("event") == "pause_requested"
        and event["seq"] < resumed_seq
        for event in events
    )
    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == RunStatus.PAUSED.value
    bootstrap = next(
        task
        for task in store.list_tasks(run_id, db_path=isolated_db)
        if task.task_type == engine_tasks.BOOTSTRAP_TASK
    )
    assert bootstrap.status == "paused"
