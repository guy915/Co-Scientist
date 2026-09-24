"""Resume and recovery tests for the durable workflow worker."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import pytest

from app import engine_tasks, store, task_worker
from app.store import RunStatus


@dataclass(frozen=True)
class _ResumeShape:
    """The optional shape of a saved resume checkpoint.

    Attributes:
        stage: Stage name written on the checkpoint row.
        last_event_seq: Event high-water mark the checkpoint records.
        provider: Provider tag to write, or ``None`` to omit it.
    """

    stage: str = "post_generation"
    last_event_seq: int = 1
    provider: str | None = None


def _save_resume_checkpoint(
    run_id: str,
    successor: str,
    db: str,
    shape: _ResumeShape | None = None,
) -> None:
    """Save a checkpoint that records ``successor`` as the resume target."""
    shape = shape or _ResumeShape()
    state: dict[str, Any] = {"resume_successor": successor}
    if shape.provider is not None:
        state["provider"] = shape.provider
    store.save_checkpoint(
        run_id,
        store.NewCheckpoint(
            stage=shape.stage,
            schema_version=1,
            last_event_seq=shape.last_event_seq,
            state=state,
        ),
        db_path=db,
    )


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


def test_resume_uses_recorded_successor_not_orchestrator_default(
    isolated_db: str,
) -> None:
    """A crash-resume re-enters at the checkpoint's recorded successor.

    Regression: a run interrupted right after bootstrap held only the
    bootstrap checkpoint, whose state has no supervisor_guidance. Resume
    defaulted to the orchestrator, which routed straight into generation and
    raised GenerationError('No supervisor_guidance in state'). Bootstrap's
    checkpoint now records resume_successor=engine.supervisor, and resume must
    honour it. The idempotency key matches the successor bootstrap already
    enqueued, so no duplicate task is created.
    """
    supervisor_type = f"{engine_tasks.NODE_TASK_PREFIX}supervisor"
    run = store.create_run("worker goal", "standard", "engine", {})
    # The successor bootstrap enqueues in the same commit as its checkpoint.
    enqueued = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=supervisor_type,
            inputs={"checkpoint_seq": 1},
            idempotency_key=f"{supervisor_type}:1",
        ),
        db_path=isolated_db,
    )
    _save_resume_checkpoint(
        run.id,
        supervisor_type,
        isolated_db,
        _ResumeShape(
            stage="engine_task:bootstrap",
            last_event_seq=0,
            provider="engine",
        ),
    )

    resumed = task_worker.enqueue_run_workflow(
        run.id, resume=True, db_path=isolated_db
    )

    assert resumed.task_type == supervisor_type
    assert resumed.id == enqueued.id, "must resolve to the already-queued task"


def test_resume_defaults_to_orchestrator_when_successor_unrecorded(
    isolated_db: str,
) -> None:
    """A checkpoint without a recorded successor keeps the legacy default.

    Older checkpoints (pre-fix) and the fan-out planning checkpoints do not
    record a successor; by then supervisor_guidance is in state, so the
    orchestrator re-entry is valid and must be preserved.
    """
    run = store.create_run("worker goal", "standard", "engine", {})
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage="engine_task:orchestrator",
            schema_version=1,
            last_event_seq=0,
            state={"provider": "engine"},
        ),
        db_path=isolated_db,
    )

    resumed = task_worker.enqueue_run_workflow(
        run.id, resume=True, db_path=isolated_db
    )

    assert resumed.task_type == f"{engine_tasks.NODE_TASK_PREFIX}orchestrator"


def test_resume_reuses_post_pause_fanout_rows_for_latest_checkpoint(
    isolated_db: str,
) -> None:
    """A queued fan-out wave is already the continuation for its checkpoint."""
    run = store.create_run("paused fanout", "standard", "engine", {})
    parent = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}generate",
            inputs={"checkpoint_seq": 0},
            idempotency_key="pause:generate-parent",
        ),
        db_path=isolated_db,
    )
    leased = store.claim_task(
        "parent-worker", run_id=run.id, db_path=isolated_db
    )
    assert leased is not None and leased.id == parent.id
    assert store.complete_task(
        parent.id, "parent-worker", {}, db_path=isolated_db
    )
    store.update_run_status(run.id, RunStatus.PAUSED, db_path=isolated_db)
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage=f"engine_task:{parent.id}",
            schema_version=1,
            last_event_seq=1,
            state={"provider": "engine"},
        ),
        db_path=isolated_db,
    )

    # A stale queued lookahead from another checkpoint must not mask the
    # actual fan-out rows attached to the newest checkpoint.
    stale = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}review",
            inputs={"checkpoint_seq": 0},
            idempotency_key="pause:stale-lookahead",
            provenance={"scheduled_by": "engine.node.old"},
        ),
        db_path=isolated_db,
    )
    fanout = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type="engine.fanout.generation.strategy",
            inputs={"checkpoint_seq": 1},
            idempotency_key="generation:debate_only:1:0:1",
            dependencies=(parent.id,),
            provenance={"scheduled_by": parent.task_type},
        ),
        db_path=isolated_db,
    )
    store.update_run_status(run.id, RunStatus.QUEUED, db_path=isolated_db)

    resumed = task_worker.enqueue_run_workflow(
        run.id, resume=True, db_path=isolated_db
    )

    assert resumed.id == fanout.id
    assert resumed.id != stale.id
    assert not any(
        task.task_type == f"{engine_tasks.NODE_TASK_PREFIX}orchestrator"
        and task.status == "queued"
        for task in store.list_tasks(run.id, db_path=isolated_db)
    )


def _wedge_task_at(
    run_id: str, task_type: str, checkpoint_seq: int, status: str, db: str
) -> str:
    """Leave the boundary's task in a terminal, unclaimable state.

    Reproduces what the disk-full outage did in production: the boundary's
    task burned its retry budget and settled as ``failed``.
    """
    task = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=task_type,
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key=f"{task_type}:{checkpoint_seq}",
        ),
        db_path=db,
    )
    with store.connect(db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET status=?, attempt=max_attempts "
            "WHERE id=?",
            (status, task.id),
        )
    return task.id


def _queued(run_id: str, db: str) -> list[Any]:
    return [
        t for t in store.list_tasks(run_id, db_path=db) if t.status == "queued"
    ]


@pytest.mark.parametrize("dead_status", ["failed", "cancelled"])
def test_resume_revives_a_boundary_whose_task_died(
    isolated_db: str, dead_status: str
) -> None:
    """A resume must give a dead boundary a fresh attempt, not silently no-op.

    Regression: the resume enqueue is idempotent on
    ``{task_type}:{checkpoint_seq}``, and that key cannot change while the run
    makes no progress -- the checkpoint it names is exactly the one it failed
    at. Once that task reached a terminal state, every later resume hit
    ON CONFLICT DO NOTHING and enqueued nothing, so the worker had nothing to
    claim. In production the run announced "resuming from specialist
    checkpoint" on every restart and then sat silent forever: no LLM call, no
    tool call, no task ever leased. Neither escape hatch reached it either --
    resume_run_tasks only requeues 'paused', and claim_task's expired-lease
    rescue skips tasks whose attempts are spent.
    """
    run = store.create_run("wedged goal", "standard", "engine", {})
    task_type = f"{engine_tasks.NODE_TASK_PREFIX}orchestrator"
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage="post_generation",
            schema_version=1,
            last_event_seq=1,
            state={"resume_successor": task_type},
        ),
        db_path=isolated_db,
    )
    task_id = _wedge_task_at(run.id, task_type, 1, dead_status, isolated_db)
    assert not _queued(run.id, isolated_db)

    task_worker.enqueue_run_workflow(run.id, resume=True, db_path=isolated_db)

    # The boundary is runnable again, with a budget to run on.
    queued = _queued(run.id, isolated_db)
    assert len(queued) == 1
    assert queued[0].id == task_id
    assert queued[0].task_type == task_type
    assert queued[0].attempt < queued[0].max_attempts


def test_resume_does_not_rerun_completed_work(isolated_db: str) -> None:
    """A boundary that already succeeded is left alone.

    Reviving it would redo work the run has already paid for and committed.
    """
    run = store.create_run("done goal", "standard", "engine", {})
    task_type = f"{engine_tasks.NODE_TASK_PREFIX}orchestrator"
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage="post_generation",
            schema_version=1,
            last_event_seq=1,
            state={"resume_successor": task_type},
        ),
        db_path=isolated_db,
    )
    _wedge_task_at(run.id, task_type, 1, "succeeded", isolated_db)

    task_worker.enqueue_run_workflow(run.id, resume=True, db_path=isolated_db)

    assert not _queued(run.id, isolated_db)


def test_resume_revives_a_lease_stranded_by_a_dead_worker(
    isolated_db: str,
) -> None:
    """A resume rescues a boundary whose worker died holding it.

    Regression, and the state production actually reached: the run's
    engine.node.ranking task sat 'leased' by a process that no longer existed.
    Every recovery path declined it -- claim_task requeues expired leases only
    "unless their retry budget is spent", resume_run_tasks handles just
    'paused', and the resume enqueue collided with the existing row. The run
    announced "resuming from specialist checkpoint" on every restart for
    hours and never leased a task.
    """
    run = store.create_run("stranded goal", "standard", "engine", {})
    task_type = f"{engine_tasks.NODE_TASK_PREFIX}ranking"
    _save_resume_checkpoint(run.id, task_type, isolated_db)
    task = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=task_type,
            inputs={"checkpoint_seq": 1},
            idempotency_key=f"{task_type}:1",
        ),
        db_path=isolated_db,
    )
    _mark_leased(
        task.id,
        isolated_db,
        owner="dead",
        expires_at=time.time() - 3600,
        spend_budget=True,
    )
    assert not _queued(run.id, isolated_db)

    task_worker.enqueue_run_workflow(run.id, resume=True, db_path=isolated_db)

    queued = _queued(run.id, isolated_db)
    assert len(queued) == 1
    assert queued[0].id == task.id
    assert queued[0].attempt < queued[0].max_attempts


def test_resume_leaves_a_live_lease_alone(isolated_db: str) -> None:
    """A boundary another worker is actively running is not stolen.

    Only an *expired* lease means its owner is gone. Reviving a live one
    would run the same boundary twice concurrently.
    """
    run = store.create_run("busy goal", "standard", "engine", {})
    task_type = f"{engine_tasks.NODE_TASK_PREFIX}ranking"
    store.save_checkpoint(
        run.id,
        store.NewCheckpoint(
            stage="post_generation",
            schema_version=1,
            last_event_seq=1,
            state={"resume_successor": task_type},
        ),
        db_path=isolated_db,
    )
    task = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=task_type,
            inputs={"checkpoint_seq": 1},
            idempotency_key=f"{task_type}:1",
        ),
        db_path=isolated_db,
    )
    with store.connect(isolated_db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET status='leased', lease_owner='alive', "
            "lease_expires_at=? WHERE id=?",
            (time.time() + 3600, task.id),
        )

    task_worker.enqueue_run_workflow(run.id, resume=True, db_path=isolated_db)

    assert not _queued(run.id, isolated_db)
    with store.connect(isolated_db) as conn:
        row = conn.execute(
            "SELECT status, lease_owner FROM scientific_tasks WHERE id=?",
            (task.id,),
        ).fetchone()
    assert (row["status"], row["lease_owner"]) == ("leased", "alive")
