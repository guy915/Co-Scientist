"""Data models for the adaptive orchestration scheduler.

These are plain, serializable dataclasses so a scheduling decision — and the
observable statistics behind it — travel through ``WorkflowState``, the
streaming snapshots, and (eventually) the durable checkpoint as data, not as
log lines.
"""

from __future__ import annotations

import dataclasses
import enum
from collections.abc import Iterable
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
    ``MAX_IDEAS``/``MAX_MATCHES_PER_IDEA`` are the paper's own named
    termination predicates (Supervisor §4: ``MaxIdeas``,
    ``MaxMatchesPerIdea``); ``COMPLETED`` is the satisfied iteration budget;
    ``CONVERGED`` is the clone-defined stability predicate; ``SAFETY`` is a
    safety block (Milestone 6 hook).

    There is deliberately no ``CANCELLED`` member: the durable executor
    (``app/app/engine_tasks/node.py``) enforces cancellation by never
    dispatching another node once a run is marked cancelled, so a
    graph-internal predicate for it would be a second, weaker enforcement
    point rather than a real signal -- no writer anywhere in this codebase
    ever set the ``cancel_requested`` state key the old predicate read, so
    it could never fire on a real run. See ``docs/fidelity-audit`` (F12).
    """

    BUDGET = "budget"
    WALL_CLOCK = "wall_clock"
    MAX_TASKS = "max_tasks"
    MAX_IDEAS = "max_ideas"
    MAX_MATCHES_PER_IDEA = "max_matches_per_idea"
    COMPLETED = "completed"
    CONVERGED = "converged"
    SAFETY = "safety"


@dataclasses.dataclass(frozen=True)
class Budget:
    """Configurable compute budget and its termination limits.

    ``max_iterations`` is the satisfied-completion cap (existing behavior).
    The others are optional hard ceilings; ``None`` means "no limit". The
    scheduler enforces all of them as real termination predicates, not just
    ``max_iterations``.

    ``max_ideas``/``max_matches_per_idea`` are the paper's own named limits
    (Supervisor §4). ``max_ideas`` caps the hypothesis pool
    (``SchedulerStats.pool_size``); ``max_matches_per_idea`` caps average
    tournament participation (``SchedulerStats.match_coverage``) rather than
    a true per-idea maximum, matching the average-coverage observable the
    rest of the scheduler already reads (see
    ``policy_checks._check_tournament_coverage``). Setting
    ``max_matches_per_idea`` at or below ``min_match_coverage`` is a
    degenerate configuration: the run would hit this ceiling before the
    tournament ever reaches its own minimum-coverage requirement, so a
    caller combining both should keep this one strictly larger.
    """

    max_iterations: int
    max_llm_calls: int | None = None
    max_tasks: int | None = None
    max_wall_clock_s: float | None = None
    max_ideas: int | None = None
    max_matches_per_idea: float | None = None

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
    # Hypotheses currently owed the scheduler's budget-overriding review
    # pass (``agents.reflection.owed_review.owed_review_count``): unreviewed
    # and not yet issued their one override. Bounded per-hypothesis (an
    # enrichment marker set the moment the override fires, whether or not
    # the ensuing review succeeds) and by a run-wide ceiling, so this can
    # only ever fall to zero, never grow without bound. See
    # ``policy_checks._check_owed_review``.
    owed_review_count: int = 0
    # Hypotheses eligible for the Elo tournament (not undermined / review- or
    # evidence-gate-rejected). Coverage and the ranking-coverage gate are
    # measured over this count, not ``pool_size``, so a pool full of
    # un-rankable ideas cannot hold average coverage below the threshold and
    # loop the orchestrator on ranking.
    rankable_count: int = 0
    # Rankable hypotheses with zero tournament matches. Tracked alongside the
    # average below because an average cannot see them: 35 ideas at two
    # matches each averages 1.46 across 48 and clears a 1.0 threshold while
    # 13 have never played once. Reported to the planner and named in the
    # settlement reason as the sharpest form of the backlog; the settlement
    # gate itself reads ``owed_coverage_rounds``, which is the one that
    # decides.
    unmatched_rankable_count: int = 0
    # Ranking rounds the rankable pool still owes to bring every idea to the
    # tournament's minimum match count -- ``ranking_lifecycle._coverage_floor``
    # over the same pool. It both opens a settlement episode and sizes it, and
    # it is deliberately one number for both: a trigger coarser than the size
    # never lets the size apply. Ten ideas sitting at one match each owe five
    # rounds, and a gate reading the zero-match count above saw none of them.
    owed_coverage_rounds: int = 0
    # Remaining tournament rounds the scheduler may spend overriding a budget
    # ceiling to settle owed coverage. None means the override has not fired
    # yet and may; 0 means the allowance is spent and it never fires again.
    # Strictly decreasing and never refilled, which is what bounds the
    # override rather than any assumption that ranking makes progress.
    settlement_allowance: int | None = None
    # Owed rounds observed at the previous settlement round, or None if there
    # was none. Lets the scheduler stop early when a round changed nothing. A
    # cost optimisation only -- termination rests on the allowance. Measured
    # in the same units as the trigger so a round that covered half the
    # backlog reads as progress rather than as a stall.
    owed_at_last_settlement: int | None = None
    # Tournament coverage: average tournament participations per RANKABLE
    # hypothesis (sum of their match counts / rankable_count). Average rather
    # than minimum so the gate is reachable by a bounded tournament.
    total_matches: int = 0
    match_coverage: float = 0.0
    # Matches the run's tournament budget can still afford. The coverage
    # check must see this: coverage is a property of the pool and can sit
    # below its threshold forever, so once the budget is spent a scheduler
    # blind to it would request ranking every cycle and get a no-op back.
    # None means the caller did not compute a budget, which must read as
    # "unbounded" -- a numeric default would make every stats object built
    # without this field look exhausted and silently stop ranking.
    tournament_rounds_remaining: int | None = None
    # Proximity refresh: pool grew (generate/evolve added rows) since the last
    # proximity pass, so clustering/matchmaking should be refreshed.
    pool_grew_since_proximity: bool = False
    # Meta-review cadence (listing 01 L60-63, "IF enough time has passed").
    # Two observables rather than a wall clock: how many work cycles have
    # completed since the last firing, and how much new critique material
    # (reviews plus tournament participations) has accumulated since it.
    # The iteration clock is what keeps this to at most one firing per work
    # cycle -- a decision-count clock fires once before a ranking wave and
    # again the moment it returns with new matches. The material count is
    # what terminates it: meta-review is not a work task, so it never
    # advances the iteration counter itself.
    iterations_since_meta_review: int = 0
    feedback_since_meta_review: int = 0
    # Whether the periodic meta-review cadence may fire at all. Default True;
    # an ablation arm sets it False to run with no meta-review cadence
    # (``state["enable_meta_review"]`` -> ``orchestrator_stats``). Read by
    # ``policy_cadence._check_meta_review_cadence``, which covers both the
    # ordered-check step and the companion path, so this one field disables
    # both. The EVOLVE branch still enters the meta_review node, so this is
    # "no periodic feedback", not "no node".
    meta_review_enabled: bool = True
    # Research-overview cadence (listing 01 L65-69, the periodic sibling of
    # the terminal synthesis). Work cycles completed since the last firing,
    # anchored and reset exactly like the meta-review clock above and for
    # the same termination reason -- a periodic overview is not a work task
    # either. No material counter beside it: the overview synthesizes the
    # hypothesis pool itself, which a completed work cycle has by
    # definition changed.
    iterations_since_research_overview: int = 0
    # Convergence signal.
    top_elo: int = 0
    rank_stable_cycles: int = 0
    # Whether EVOLVE has been scheduled since the leaderboard settled.
    # Listing 01 L55-58 answers stagnation with evolution, so convergence
    # may not terminate a run that has not yet tried it (see
    # ``policy_checks._check_convergence``). Reset whenever the leaderboard
    # moves again, so each stagnation episode earns its own evolve attempt.
    evolved_since_stable: bool = False
    # Yield since the previous cycle.
    generation_yield: float = 0.0
    evolution_yield: float = 0.0
    # Loop bookkeeping.
    iteration: int = 0
    # The last GENERATE/EVOLVE work task run. The orchestrator uses this to
    # attribute a pool-size delta to the right yield counter above. The
    # scheduling policy also reads it in ``policy_checks._tie_break``: a
    # yield tie evolves only on the transition into a stagnant leaderboard
    # (``rank_stable_cycles >= 1`` and this field is not already EVOLVE), so
    # stagnation triggers at most one evolve before the next tie generates
    # instead -- a standing (rather than edge-triggered) stagnation reading
    # would otherwise evolve every remaining tie for the rest of the run.
    last_work_task: TaskType | None = None
    # Budget counters.
    llm_calls: int = 0
    tasks_run: int = 0
    elapsed_s: float = 0.0
    # External signals.
    pending_steering: bool = False
    # Unread by the scheduling policy: no writer anywhere sets the
    # ``cancel_requested`` state key this is built from
    # (``agents.supervisor.orchestrator_stats``), so it is always False on a
    # real run (finding F12). Retained here rather than removed because that
    # orchestrator-side constructor call is out of this module's ownership;
    # a false-positive stop is worse than an inert field, so nothing in
    # ``policy_checks``/``supervisor_decision`` reads it any longer.
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
    justification persisted to the task history: every scheduled task and
    the final stop record a reason.
    """

    next_task: TaskType
    reason: str
    priority: int = 50
    queue_actions: tuple[dict[str, Any], ...] = ()
    terminate: bool = False
    termination_reason: TerminationReason | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize for event/state transport (enums -> values)."""
        data = dataclasses.asdict(self)
        data["next_task"] = self.next_task.value
        if self.termination_reason is not None:
            data["termination_reason"] = self.termination_reason.value
        return data


# The queue-action kind that *stacks* a follow-up task rather than mutating
# an existing queue row. Listing 01's DecideNextSteps queues several tasks
# from one pass; our precedence chain returns one, and this is how the rest
# of that pass travels with it (see ``policy.stack_companions``).
ENQUEUE_ACTION = "enqueue"


def stacked_task_values(
    queue_actions: Iterable[dict[str, Any]],
) -> tuple[str, ...]:
    """Return the task values a pass stacked alongside its primary decision.

    One reader in each place the shape is consumed -- the graph's loop-point
    router, the durable route table, and the orchestrator's own bookkeeping
    -- so the action vocabulary is stated once here rather than three times.

    Args:
        queue_actions: A decision's ``queue_actions``, or the same list as
            it travels on ``WorkflowState["supervisor_queue_actions"]``.

    Returns:
        The stacked ``TaskType`` values, in the order they were requested.
    """
    return tuple(
        str(action["task_type"])
        for action in queue_actions
        if action.get("action") == ENQUEUE_ACTION and action.get("task_type")
    )


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
