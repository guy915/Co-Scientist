"""Pause/resume races around a checkpoint writer and its successor."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import pytest

from app import engine_tasks, store, task_worker
from app.store import RunStatus, ScientificTask


def _mark_leased(
    task_id: str,
    db: str,
    *,
    owner: str,
    expires_at: float,
    spend_budget: bool,
) -> None:
    """Force a task into the leased state held by ``owner``."""
    extra = ", attempt=max_attempts" if spend_budget else ""
    with store.connect(db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET status='leased', lease_owner=?, "
            f"lease_expires_at=?{extra} WHERE id=?",
            (owner, expires_at, task_id),
        )


def _commit_checkpoint_successor(
    db: str, run_id: str, writer: ScientificTask, successor_type: str
) -> None:
    """Atomically write a successor checkpoint and complete its writer."""
    with store.transaction(db) as conn:
        checkpoint_seq = store.save_checkpoint(
            run_id,
            store.NewCheckpoint(
                stage=f"engine_task:{writer.id}",
                schema_version=1,
                last_event_seq=2,
                state={"resume_successor": successor_type},
            ),
            conn=conn,
        )
        store.enqueue_task(
            store.NewTask(
                run_id=run_id,
                task_type=successor_type,
                inputs={"checkpoint_seq": checkpoint_seq},
                idempotency_key=f"{successor_type}:after:{writer.id}",
                dependencies=(writer.id,),
                provenance={"scheduled_by": writer.task_type},
            ),
            conn=conn,
        )
    assert store.complete_task(writer.id, "ranking-worker", {}, db_path=db)


@dataclass
class _CheckpointReadInterleaver:
    """Pause one checkpoint read while a writer attempts its next commit."""

    original_get: Callable[..., dict[str, Any] | None]
    old_checkpoint: dict[str, Any]
    run_id: str
    db: str
    writer: ScientificTask
    successor_type: str
    pool: ThreadPoolExecutor
    future: Future[None] | None = None
    reads: int = 0

    def __call__(
        self,
        check_run_id: str,
        db_path: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        checkpoint = self.original_get(check_run_id, db_path=db_path, conn=conn)
        if check_run_id != self.run_id:
            return checkpoint
        self.reads += 1
        if self.reads == 1:
            self._start_commit(conn)
        if conn is None and self.reads > 1:
            return self.old_checkpoint
        return checkpoint

    def _start_commit(self, conn: sqlite3.Connection | None) -> None:
        """Schedule the atomic checkpoint-and-successor commit."""
        self.future = self.pool.submit(
            _commit_checkpoint_successor,
            self.db,
            self.run_id,
            self.writer,
            self.successor_type,
        )
        if conn is None:
            self.future.result(timeout=5)
        else:
            time.sleep(0.05)

    def wait_for_writer(self) -> None:
        """Surface any racing writer failure after resume releases its lock."""
        assert self.future is not None
        self.future.result(timeout=5)


def test_resume_reuses_live_checkpoint_writer_lease(
    isolated_db: str,
) -> None:
    """A queued child remains the continuation while its writer is live."""
    run = store.create_run("paused live commit", "standard", "engine", {})
    successor_type = f"{engine_tasks.NODE_TASK_PREFIX}ranking"
    task = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}generate",
            inputs={"checkpoint_seq": 0},
            idempotency_key="pause:ranking-parent",
        ),
        db_path=isolated_db,
    )
    _mark_leased(
        task.id,
        isolated_db,
        owner="still-running",
        expires_at=time.time() + 3600,
        spend_budget=False,
    )
    store.update_run_status(run.id, RunStatus.PAUSED, db_path=isolated_db)
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage=f"engine_task:{task.id}",
            schema_version=1,
            last_event_seq=1,
            state={"provider": "engine", "resume_successor": successor_type},
        ),
        db_path=isolated_db,
    )
    child = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=successor_type,
            inputs={"checkpoint_seq": 1},
            idempotency_key=f"{successor_type}:after:{task.id}",
            dependencies=(task.id,),
            provenance={"scheduled_by": "engine.node.generate"},
        ),
        db_path=isolated_db,
    )
    store.update_run_status(run.id, RunStatus.QUEUED, db_path=isolated_db)

    resumed = task_worker.enqueue_run_workflow(
        run.id, resume=True, db_path=isolated_db
    )

    assert resumed.id == child.id
    assert resumed.dependencies == (task.id,)
    assert not store.claim_task(
        "early-child", run_id=run.id, db_path=isolated_db
    )
    assert store.complete_task(
        task.id, "still-running", {}, db_path=isolated_db
    )
    claimed_child = store.claim_task(
        "child-worker", run_id=run.id, db_path=isolated_db
    )
    assert claimed_child is not None and claimed_child.id == child.id


def test_resume_paused_stage_reuses_recorded_successor_not_writer(
    isolated_db: str,
) -> None:
    """A paused-stage writer is a dependency, not the resumed continuation."""
    run = store.create_run("paused checkpoint", "standard", "engine", {})
    successor_type = f"{engine_tasks.NODE_TASK_PREFIX}ranking"
    writer = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}generate",
            inputs={"checkpoint_seq": 0},
            idempotency_key="pause:paused-writer",
        ),
        db_path=isolated_db,
    )
    _mark_leased(
        writer.id,
        isolated_db,
        owner="paused-writer",
        expires_at=time.time() + 3600,
        spend_budget=False,
    )
    store.update_run_status(run.id, RunStatus.PAUSED, db_path=isolated_db)
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage=f"engine_task_paused:{writer.id}",
            schema_version=1,
            last_event_seq=1,
            state={"provider": "engine", "resume_successor": successor_type},
        ),
        db_path=isolated_db,
    )
    store.update_run_status(run.id, RunStatus.QUEUED, db_path=isolated_db)

    resumed = task_worker.enqueue_run_workflow(
        run.id, resume=True, db_path=isolated_db
    )

    assert resumed.task_type == successor_type
    assert resumed.status == "queued"
    assert resumed.dependencies == (writer.id,)
    assert resumed.id != writer.id
    assert not store.claim_task(
        "early-child", run_id=run.id, db_path=isolated_db
    )
    assert store.complete_task(
        writer.id, "paused-writer", {}, db_path=isolated_db
    )
    claimed = store.claim_task(
        "successor-worker", run_id=run.id, db_path=isolated_db
    )
    assert claimed is not None and claimed.id == resumed.id


def test_resume_keeps_rescuable_checkpoint_lease_for_normal_claim(
    isolated_db: str,
) -> None:
    """A retryable expired writer is rescued before its queued child."""
    run = store.create_run("paused expired commit", "standard", "engine", {})
    successor_type = f"{engine_tasks.NODE_TASK_PREFIX}ranking"
    task = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}generate",
            inputs={"checkpoint_seq": 0},
            idempotency_key="pause:expired-generate-parent",
        ),
        db_path=isolated_db,
    )
    _mark_leased(
        task.id,
        isolated_db,
        owner="expired-worker",
        expires_at=time.time() - 3600,
        spend_budget=False,
    )
    store.update_run_status(run.id, RunStatus.PAUSED, db_path=isolated_db)
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage=f"engine_task:{task.id}",
            schema_version=1,
            last_event_seq=1,
            state={"provider": "engine", "resume_successor": successor_type},
        ),
        db_path=isolated_db,
    )
    child = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=successor_type,
            inputs={"checkpoint_seq": 1},
            idempotency_key=f"{successor_type}:after:{task.id}",
            dependencies=(task.id,),
            provenance={"scheduled_by": "engine.node.generate"},
        ),
        db_path=isolated_db,
    )
    store.update_run_status(run.id, RunStatus.QUEUED, db_path=isolated_db)

    resumed = task_worker.enqueue_run_workflow(
        run.id, resume=True, db_path=isolated_db
    )

    assert resumed.id == child.id
    reclaimed = store.claim_task(
        "replacement-worker", run_id=run.id, db_path=isolated_db
    )
    assert reclaimed is not None and reclaimed.id == task.id
    assert store.complete_task(
        task.id, "replacement-worker", {}, db_path=isolated_db
    )
    claimed_child = store.claim_task(
        "child-worker", run_id=run.id, db_path=isolated_db
    )
    assert claimed_child is not None and claimed_child.id == child.id


def test_resume_revives_spent_expired_checkpoint_writer_before_child(
    isolated_db: str,
) -> None:
    """A spent expired writer must replay to release its recorded child."""
    run = store.create_run("paused spent commit", "standard", "engine", {})
    successor_type = f"{engine_tasks.NODE_TASK_PREFIX}ranking"
    writer = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}generate",
            inputs={"checkpoint_seq": 0},
            idempotency_key="pause:spent-writer",
        ),
        db_path=isolated_db,
    )
    _mark_leased(
        writer.id,
        isolated_db,
        owner="dead-writer",
        expires_at=time.time() - 3600,
        spend_budget=True,
    )
    store.update_run_status(run.id, RunStatus.PAUSED, db_path=isolated_db)
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage=f"engine_task:{writer.id}",
            schema_version=1,
            last_event_seq=1,
            state={"provider": "engine", "resume_successor": successor_type},
        ),
        db_path=isolated_db,
    )
    child = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=successor_type,
            inputs={"checkpoint_seq": 1},
            idempotency_key=f"{successor_type}:after:{writer.id}",
            dependencies=(writer.id,),
            provenance={"scheduled_by": "engine.node.generate"},
        ),
        db_path=isolated_db,
    )
    store.update_run_status(run.id, RunStatus.QUEUED, db_path=isolated_db)

    resumed = task_worker.enqueue_run_workflow(
        run.id, resume=True, db_path=isolated_db
    )

    revived_writer = store.get_task(writer.id, db_path=isolated_db)
    assert resumed.id == child.id
    assert revived_writer is not None and revived_writer.status == "queued"
    assert revived_writer.attempt == 0
    replayed = store.claim_task(
        "replacement-worker", run_id=run.id, db_path=isolated_db
    )
    assert replayed is not None and replayed.id == writer.id
    assert store.complete_task(
        writer.id, "replacement-worker", {}, db_path=isolated_db
    )
    claimed_child = store.claim_task(
        "child-worker", run_id=run.id, db_path=isolated_db
    )
    assert claimed_child is not None and claimed_child.id == child.id


def test_resume_serializes_checkpoint_discovery_with_writer_commit(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A writer cannot commit between checkpoint discovery and fallback."""
    run = store.create_run("resume commit race", "standard", "engine", {})
    writer = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type="engine.node.ranking",
            inputs={"checkpoint_seq": 0},
            idempotency_key="resume:ranking-writer",
        ),
        db_path=isolated_db,
    )
    _mark_leased(
        writer.id,
        isolated_db,
        owner="ranking-worker",
        expires_at=time.time() + 3600,
        spend_budget=False,
    )
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage=f"engine_task:{writer.id}",
            schema_version=1,
            last_event_seq=1,
            state={"provider": "engine"},
        ),
        db_path=isolated_db,
    )
    store.update_run_status(run.id, RunStatus.QUEUED, db_path=isolated_db)
    original_get_checkpoint = store.get_latest_checkpoint
    old_checkpoint = original_get_checkpoint(run.id, db_path=isolated_db)
    assert old_checkpoint is not None
    successor_type = "engine.node.orchestrator"
    pool = ThreadPoolExecutor(max_workers=1)
    interleaver = _CheckpointReadInterleaver(
        original_get_checkpoint,
        old_checkpoint,
        run.id,
        isolated_db,
        writer,
        successor_type,
        pool,
    )

    monkeypatch.setattr(
        store,
        "get_latest_checkpoint",
        interleaver,
    )
    try:
        resumed = task_worker.enqueue_run_workflow(
            run.id, resume=True, db_path=isolated_db
        )
    finally:
        interleaver.wait_for_writer()
        pool.shutdown()

    assert resumed.id == writer.id
    orchestrators = [
        task
        for task in store.list_tasks(run.id, db_path=isolated_db)
        if task.task_type == successor_type and task.status == "queued"
    ]
    assert len(orchestrators) == 1
    assert orchestrators[0].idempotency_key == (
        f"{successor_type}:after:{writer.id}"
    )
