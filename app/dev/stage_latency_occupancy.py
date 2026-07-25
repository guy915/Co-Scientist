"""Task spans, interval segmentation, and worker-cohort occupancy.

Owns the two primitives both latency analyses are built on -- one durable
task's ``TaskSpan`` and the ``_segments`` sweep that cuts a run into
elementary intervals -- plus the occupancy analysis that reads them. Split
from ``stage_latency_analysis``, which imports and re-exports every public
name here so its namespace keeps resolving for existing callers.

Occupancy answers the question wall-share attribution cannot: while a stage
was on the critical path, was the worker cohort saturated or idling?

That distinction decides which fix applies, and the two prescribe opposite
work. A stage running with free worker slots can be overlapped with a stage
it has no data dependency on for nothing -- the cohort was going to sit
partly idle anyway, so the second stage costs no wall clock. A stage
already at the cohort ceiling cannot: overlapping only requeues the same
work behind the same workers, and its latency has to come from a wider
cohort or a shorter dependency chain instead.

The load a stage is credited with is *every* task in flight beside it, not
just its own. Whether another stage could have run alongside depends on
whether any slot was free at all, so a single-task node sharing the cohort
with a seven-wide fan-out has no headroom despite contributing one task.
Counting only a stage's own tasks would report that node as having the
cohort to itself and send optimization effort somewhere it cannot help.
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from collections.abc import Iterator, Sequence
from typing import Any

# Worker slots a run's cohort is assumed to have when the caller does not
# say. Mirrors app.config's worker_pool_size default; the CLI reads the
# live setting and passes it, so this only covers direct library use.
DEFAULT_COHORT_SIZE = 8


@dataclasses.dataclass(frozen=True)
class TaskSpan:
    """One durable task's occupancy of wall-clock time.

    Attributes:
        task_type: Durable task type, e.g. ``engine.node.generate``.
        started_at: Epoch seconds the worker began the task.
        completed_at: Epoch seconds the worker finished it.
    """

    task_type: str
    started_at: float
    completed_at: float

    @property
    def duration_s(self) -> float:
        """Return the span's length in seconds, never negative."""
        return max(0.0, self.completed_at - self.started_at)


def _boundaries(spans: Sequence[TaskSpan]) -> list[float]:
    """Return the sorted distinct instants at which occupancy can change."""
    points: set[float] = set()
    for span in spans:
        points.add(span.started_at)
        points.add(span.completed_at)
    return sorted(points)


def _segments(
    spans: Sequence[TaskSpan],
) -> Iterator[tuple[float, float, list[TaskSpan]]]:
    """Yield elementary ``(start, end, running)`` segments.

    Between two consecutive boundary instants the set of running tasks
    cannot change, so each segment can be attributed as a unit. The running
    *spans* are yielded rather than their type names because the two
    analyses need different projections of them: latency attribution counts
    distinct stage kinds, occupancy counts individual tasks.
    """
    points = _boundaries(spans)
    for start, end in zip(points, points[1:]):
        if end <= start:
            continue
        running = [
            span
            for span in spans
            if span.started_at <= start and span.completed_at > start
        ]
        yield start, end, running


@dataclasses.dataclass(frozen=True)
class StageOccupancy:
    """How much of the worker cohort was busy while one stage ran.

    Attributes:
        task_type: The durable task type these figures describe.
        mean_concurrency: Time-weighted mean of *all* tasks in flight during
            this stage's segments, not just this stage's own.
        peak_concurrency: The most tasks in flight during those segments.
        saturated_s: Time this stage ran with the cohort at its ceiling.
        headroom: Mean unused worker slots while this stage ran.
    """

    task_type: str
    mean_concurrency: float
    peak_concurrency: int
    saturated_s: float
    headroom: float

    def to_dict(self) -> dict[str, Any]:
        """Serialize for cohort JSON."""
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class RunOccupancy:
    """Worker-cohort utilization for one run.

    Attributes:
        cohort_size: Worker slots assumed available, from configuration.
        mean_concurrency: Time-weighted mean tasks in flight over busy time.
        peak_concurrency: Most tasks ever in flight at once.
        saturated_s: Busy time spent at or above ``cohort_size``.
        stages: Per-stage occupancy, widest headroom first.
    """

    cohort_size: int
    mean_concurrency: float
    peak_concurrency: int
    saturated_s: float
    stages: tuple[StageOccupancy, ...]

    def to_dict(self) -> dict[str, Any]:
        """Serialize for cohort JSON."""
        data = dataclasses.asdict(self)
        data["stages"] = [stage.to_dict() for stage in self.stages]
        return data


@dataclasses.dataclass
class _StageLoad:
    """Mutable per-stage accumulator for the occupancy sweep."""

    busy_s: float = 0.0
    concurrency_s: float = 0.0
    peak: int = 0
    saturated_s: float = 0.0


def _accumulate_load(
    load: _StageLoad, length: float, count: int, cohort_size: int
) -> None:
    """Fold one segment's occupancy into a stage's running totals."""
    load.busy_s += length
    load.concurrency_s += length * count
    load.peak = max(load.peak, count)
    if count >= cohort_size:
        load.saturated_s += length


def _stage_occupancy(
    loads: dict[str, _StageLoad], cohort_size: int
) -> tuple[StageOccupancy, ...]:
    """Build per-stage occupancy, most idle worker slots first."""
    stats = []
    for task_type, load in loads.items():
        busy = load.busy_s or 1.0
        mean = load.concurrency_s / busy
        stats.append(
            StageOccupancy(
                task_type=task_type,
                mean_concurrency=mean,
                peak_concurrency=load.peak,
                saturated_s=load.saturated_s,
                headroom=max(0.0, cohort_size - mean),
            )
        )
    return tuple(sorted(stats, key=lambda s: -s.headroom))


def occupancy(spans: Sequence[TaskSpan], cohort_size: int) -> RunOccupancy:
    """Measure how loaded the worker cohort was, overall and per stage.

    Args:
        spans: The run's completed task spans.
        cohort_size: Worker slots the run had available.

    Returns:
        The run's occupancy profile.
    """
    overall = _StageLoad()
    loads: dict[str, _StageLoad] = defaultdict(_StageLoad)
    for start, end, running in _segments(spans):
        if not running:
            continue
        length, count = end - start, len(running)
        _accumulate_load(overall, length, count, cohort_size)
        for task_type in {span.task_type for span in running}:
            _accumulate_load(loads[task_type], length, count, cohort_size)
    busy = overall.busy_s or 1.0
    return RunOccupancy(
        cohort_size=cohort_size,
        mean_concurrency=overall.concurrency_s / busy,
        peak_concurrency=overall.peak,
        saturated_s=overall.saturated_s,
        stages=_stage_occupancy(loads, cohort_size),
    )
