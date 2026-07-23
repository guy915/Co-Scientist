"""Value bundles threaded through the durable engine-task modules.

Two small frozen records the ``engine_tasks_*`` commit helpers share:
where a task commits (``TaskCommit``) and what it enqueues next when the
successor is not a graph node (``ExactSuccessor``). They live in their own
module so ``engine_tasks_support`` and the fan-out/ranking modules can
import them without an import cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
    """

    task: ScientificTask
    current_seq: int
    db_path: str | None


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
