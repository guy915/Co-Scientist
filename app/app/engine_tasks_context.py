"""Value bundles threaded through the durable engine-task modules.

Two small frozen records the ``engine_tasks_*`` commit helpers share:
where a task commits (``TaskCommit``) and what it enqueues next when the
successor is not a graph node (``ExactSuccessor``). They live in their own
module so ``engine_tasks_support`` and the fan-out/ranking modules can
import them without an import cycle. The two helpers that build a commit
target and settle what it owes at commit time live here with it.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from app import store
from app.engine_adapter.opts import CONSUMED_STEERING_IDS_OPT
from app.store import ScientificTask


@dataclass(frozen=True)
class TaskCommit:
    """One durable task's commit target.

    Every commit helper needs the same three values -- the leased task, the
    checkpoint sequence it was scheduled against, and the optional database
    override -- so they travel together rather than being re-declared on
    each signature.

    Attributes:
        task: The leased scientific task being committed.
        current_seq: Checkpoint sequence the task was scheduled against.
        db_path: Optional override for the SQLite database path.
        steering_ids: Steering messages whose guidance this task's state
            already carries. They are acknowledged inside the checkpoint
            transaction, never before it, so a crash mid-task leaves the
            steer claimable rather than applied to nothing. Empty for every
            task that does not read the steering queue (only bootstrap and
            node tasks do).
    """

    task: ScientificTask
    current_seq: int
    db_path: str | None
    steering_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class ExactSuccessor:
    """The non-node task an exact-checkpoint commit enqueues next.

    Attributes:
        task_type: Durable task type to enqueue.
        inputs: Scheduling inputs, merged with the committed checkpoint seq.
        idempotency_key: Key template formatted with ``checkpoint_seq``; its
            ``{task_type}:{checkpoint_seq}`` shape is what makes redelivery
            a no-op, so it is never derived from anything else.
    """

    task_type: str
    inputs: dict[str, Any]
    idempotency_key: str


def _task_commit(
    task: ScientificTask,
    current_seq: int,
    db_path: str | None,
    opts: dict[str, Any],
) -> TaskCommit:
    """Bind a task's commit target to the steering its opts folded in.

    Only the two executors that read the steering queue (bootstrap and node
    tasks) build their commit this way; every other commit target carries
    no steering and acknowledges none.
    """
    consumed = opts.get(CONSUMED_STEERING_IDS_OPT) or []
    return TaskCommit(
        task, current_seq, db_path, tuple(int(item) for item in consumed)
    )


def _ack_consumed_steering(
    commit: TaskCommit, conn: sqlite3.Connection
) -> None:
    """Retire the steering this commit's state carries, in its transaction.

    Called from inside every checkpoint transaction rather than where the
    guidance was read: the acknowledgement and the state that honors it
    have to land or roll back together, or a worker lost between them
    retires a steer the run never acted on.
    """
    store.mark_steering_applied(list(commit.steering_ids), conn=conn)
