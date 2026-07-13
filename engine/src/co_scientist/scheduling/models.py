"""Data models for the adaptive orchestration scheduler.

These are plain, serializable dataclasses so a scheduling decision — and the
observable statistics behind it — travel through ``WorkflowState``, the
streaming snapshots, and (eventually) the durable checkpoint as data, not as
log lines (PLAN.md M2.1).
"""

from __future__ import annotations

import dataclasses
import enum
from typing import Any


class TaskType(str, enum.Enum):
    """A schedulable unit of work in the workflow.

    The loop-point routes the scheduler may return are constrained to
    ``ALLOWED_LOOP_TASKS`` in ``policy``; the full set is enumerated here so
    task history and future scheduling can name every phase explicitly.
    """

    GENERATE = "generate"
    REFLECT = "reflect"
    RANK = "rank"
    EVOLVE = "evolve"
    PROXIMITY = "proximity"
    META_REVIEW = "meta_review"
    SYNTHESIZE = "synthesize"
    TERMINATE = "terminate"


class TaskStatus(str, enum.Enum):
    """Lifecycle state of a scheduled task (represented as data, not logs)."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    RETRIED = "retried"
    FAILED = "failed"


class TerminationReason(str, enum.Enum):
    """Why the workflow stopped.

    ``BUDGET``/``WALL_CLOCK``/``MAX_TASKS`` are hard resource limits;
    ``COMPLETED`` is the satisfied iteration budget; ``CONVERGED`` is the
    clone-defined stability predicate; ``CANCELLED`` is external cancellation;
    ``SAFETY`` is a safety block (Milestone 6 hook).
    """

    BUDGET = "budget"
    WALL_CLOCK = "wall_clock"
    MAX_TASKS = "max_tasks"
    COMPLETED = "completed"
    CONVERGED = "converged"
    CANCELLED = "cancelled"
    SAFETY = "safety"


@dataclasses.dataclass(frozen=True)
class Budget:
    """Configurable compute budget and its termination limits.

    ``max_iterations`` is the satisfied-completion cap (existing behavior).
    The others are optional hard ceilings; ``None`` means "no limit". The
    scheduler enforces all of them as real termination predicates (PLAN.md
    M2.6), not just ``max_iterations``.
    """

    max_iterations: int
    max_llm_calls: int | None = None
    max_tasks: int | None = None
    max_wall_clock_s: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize for state/checkpoint transport."""
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Budget:
        """Rebuild from a ``to_dict`` payload, ignoring unknown keys."""
        fields = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in fields})


@dataclasses.dataclass(frozen=True)
class SchedulerStats:
    """Observable statistics the scheduling policy reads.

    Computed from ``WorkflowState`` before each loop-point decision. Every
    field is a plain scalar so the decision is a pure function of these
    numbers and the :class:`Budget` (fully deterministic, order-independent).
    """

    # Pool / review backlog.
    pool_size: int = 0
    reviewed_count: int = 0
    unreviewed_count: int = 0
    # Tournament coverage: average tournament participations per hypothesis
    # (sum of per-hypothesis match counts / pool size). Average rather than
    # minimum so the gate is reachable by a bounded tournament; guaranteeing a
    # per-child minimum is the matchmaking work in Milestone 3.
    total_matches: int = 0
    match_coverage: float = 0.0
    # Proximity refresh: pool grew (generate/evolve added rows) since the last
    # proximity pass, so clustering/matchmaking should be refreshed.
    pool_grew_since_proximity: bool = False
    # Convergence signal.
    top_elo: int = 0
    rank_stable_cycles: int = 0
    # Yield since the previous cycle.
    generation_yield: float = 0.0
    evolution_yield: float = 0.0
    # Loop bookkeeping.
    iteration: int = 0
    # The last GENERATE/EVOLVE work task run, used to break a yield tie by
    # alternating so later cycles still explore new regions (not only evolve).
    last_work_task: TaskType | None = None
    # Budget counters.
    llm_calls: int = 0
    tasks_run: int = 0
    elapsed_s: float = 0.0
    # External signals.
    pending_steering: bool = False
    cancelled: bool = False
    safety_blocked: bool = False
    last_task_failed: TaskType | None = None
    retries_remaining: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize for event/state transport (enums -> values)."""
        data = dataclasses.asdict(self)
        for key in ("last_task_failed", "last_work_task"):
            value = data.get(key)
            if isinstance(value, TaskType):
                data[key] = value.value
        return data


@dataclasses.dataclass(frozen=True)
class SupervisorDecision:
    """The scheduler's chosen next task, with its recorded reason.

    ``terminate`` and ``termination_reason`` are set together with
    ``next_task == TaskType.TERMINATE``. ``reason`` is always a human-readable
    justification persisted to the task history (PLAN.md M2.6 requires a
    recorded reason for every scheduled task and the final stop).
    """

    next_task: TaskType
    reason: str
    priority: int = 50
    terminate: bool = False
    termination_reason: TerminationReason | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize for event/state transport (enums -> values)."""
        data = dataclasses.asdict(self)
        data["next_task"] = self.next_task.value
        if self.termination_reason is not None:
            data["termination_reason"] = self.termination_reason.value
        return data


@dataclasses.dataclass
class TaskRecord:
    """One durable entry in the task history ledger.

    Records a scheduled task, its status, the reason it was chosen, and the
    iteration it belonged to — so the schedule is inspectable as data.
    """

    task_type: TaskType
    status: TaskStatus
    reason: str
    iteration: int
    termination_reason: TerminationReason | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize for state/event transport (enums -> values)."""
        data = dataclasses.asdict(self)
        data["task_type"] = self.task_type.value
        data["status"] = self.status.value
        if self.termination_reason is not None:
            data["termination_reason"] = self.termination_reason.value
        return data
