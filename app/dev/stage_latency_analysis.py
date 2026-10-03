"""Critical-path latency analysis over a run's durable task spine.

A run's wall time is not the sum of its task durations. The durable executor
runs a bounded worker cohort, so fan-out waves overlap: adding up
``completed_at - started_at`` across ``engine.fanout.review.item`` rows
counts the same wall-clock second once per concurrent worker and reports a
run as taking hours when it took thirty minutes. Every optimization decision
made off that number is wrong in the same direction -- it makes wide, cheap
fan-outs look like the bottleneck and hides the narrow serial spine that
actually sets the deadline.

This module therefore attributes time by sweeping the interval union rather
than by summing durations. For each elementary time segment it collects the
set of *stage kinds* running in it and splits the segment equally between
them, which yields three distinct quantities that answer different questions:

  ``wall_share_s``  Partition of the run's busy time. Sums to ``active_s``
                    across stages, so its percentages are comparable and add
                    to 100%. The headline "what is this run spending its
                    time on" number.

  ``solo_s``        Time during which a stage kind was the *only* thing
                    running. This is the serial spine: latency that no
                    amount of extra worker concurrency can remove, because
                    there is nothing else to overlap it with. A stage with
                    high solo time is a latency target; a stage with high
                    wall share but near-zero solo time is already
                    overlapped and optimizing it buys little.

  ``worker_s``      The naive sum of durations. Retained only so a report
                    can show how badly it double-counts; never a headline.

Time inside the run's span that no task occupies at all is reported as
``idle_s``. It is real latency -- queue pickup, lease acquisition, gaps
between checkpoint boundaries -- and it belongs to no stage, so folding it
into one would misattribute it.

Splitting a segment between *kinds* rather than between *tasks* is
deliberate: the question is which stage the run is blocked on, not how many
workers were busy. Attributing per task would rank a 12-wide fan-out above
the single orchestrator call it is waiting behind purely for being wide.

The same interval sweep also measures worker occupancy. A stage with free
worker slots can overlap independent work; a saturated stage needs a wider
cohort or a shorter dependency chain. Occupancy counts every task in flight
beside a stage, so its headroom reflects the whole cohort.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from itertools import pairwise
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
    for start, end in pairwise(points):
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


# Task types that are pure bookkeeping around a fan-out wave rather than
# scientific work. They are still reported, but are named here so a reader
# can tell structural overhead from the work it wraps.
AGGREGATE_SUFFIX = ".aggregate"

# Terminal states worth measuring. A cancelled or failed task's span says
# nothing about how long that stage takes when it works.
_MEASURED_STATUS = "completed"


@dataclasses.dataclass(frozen=True)
class StageStats:
    """Per-stage timing for one run or cohort.

    Attributes:
        task_type: The durable task type these figures describe.
        invocations: How many spans of this type were measured.
        wall_share_s: Share of busy time attributed by the sweep.
        solo_s: Time this stage ran with nothing else running.
        worker_s: Naive sum of durations; double-counts concurrency.
        p50_s: Median single-invocation duration.
        p95_s: 95th-percentile single-invocation duration.
    """

    task_type: str
    invocations: int
    wall_share_s: float
    solo_s: float
    worker_s: float
    p50_s: float
    p95_s: float

    def to_dict(self) -> dict[str, Any]:
        """Serialize for cohort JSON."""
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class RunProfile:
    """One run's critical-path breakdown.

    Attributes:
        run_id: Identifier of the profiled run.
        tier: Run tier (express/standard/extended/ultra) when recorded.
        status: Terminal run status.
        started_at: Epoch seconds of the run's first task start.
        wall_s: First task start to last task completion.
        active_s: Wall time during which at least one task ran.
        idle_s: Wall time occupied by no task at all.
        task_count: Number of measured task spans.
        stages: Per-stage statistics, widest wall share first.
        items_per_invocation: Fan-out width per parent stage invocation.
        occupancy: Worker-cohort utilization, overall and per stage.
    """

    run_id: str
    tier: str
    status: str
    started_at: float
    wall_s: float
    active_s: float
    idle_s: float
    task_count: int
    stages: tuple[StageStats, ...]
    items_per_invocation: dict[str, float]
    occupancy: RunOccupancy

    def to_dict(self) -> dict[str, Any]:
        """Serialize for cohort JSON."""
        data = dataclasses.asdict(self)
        data["stages"] = [stage.to_dict() for stage in self.stages]
        data["occupancy"] = self.occupancy.to_dict()
        return data


def percentile(values: Sequence[float], fraction: float) -> float:
    """Return the nearest-rank percentile of ``values``.

    Nearest-rank rather than interpolated: these samples are small (a stage
    may run four times in a run), and interpolating between two of four
    observations invents a duration that never occurred.

    Args:
        values: Observed durations; may be empty.
        fraction: Percentile in [0, 1], e.g. 0.95.

    Returns:
        The selected observation, or 0.0 when there are none.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, min(len(ordered), round(fraction * len(ordered) + 0.5)))
    return ordered[rank - 1]


@dataclasses.dataclass
class _Attribution:
    """Mutable accumulator for one run's sweep."""

    wall_share: dict[str, float] = dataclasses.field(
        default_factory=lambda: defaultdict(float)
    )
    solo: dict[str, float] = dataclasses.field(
        default_factory=lambda: defaultdict(float)
    )
    active_s: float = 0.0


def _sweep(spans: Sequence[TaskSpan]) -> _Attribution:
    """Attribute busy time across stage kinds by interval sweep.

    Each segment's length is split equally between the stage kinds running
    in it, so the totals partition busy time instead of multiplying it by
    the worker cohort's width.
    """
    acc = _Attribution()
    for start, end, running in _segments(spans):
        if not running:
            continue
        active = {span.task_type for span in running}
        length = end - start
        acc.active_s += length
        share = length / len(active)
        for task_type in active:
            acc.wall_share[task_type] += share
        if len(active) == 1:
            acc.solo[next(iter(active))] += length
    return acc


def _stage_stats(
    spans: Sequence[TaskSpan], acc: _Attribution
) -> tuple[StageStats, ...]:
    """Build per-stage statistics from spans and their sweep attribution."""
    by_type: dict[str, list[float]] = defaultdict(list)
    for span in spans:
        by_type[span.task_type].append(span.duration_s)

    stats = [
        StageStats(
            task_type=task_type,
            invocations=len(durations),
            wall_share_s=acc.wall_share.get(task_type, 0.0),
            solo_s=acc.solo.get(task_type, 0.0),
            worker_s=sum(durations),
            p50_s=percentile(durations, 0.5),
            p95_s=percentile(durations, 0.95),
        )
        for task_type, durations in by_type.items()
    ]
    return tuple(sorted(stats, key=lambda s: -s.wall_share_s))


def _fanout_width(spans: Sequence[TaskSpan]) -> dict[str, float]:
    """Return mean fan-out items per wave, keyed by the wave's family.

    Each fan-out wave closes with exactly one ``.aggregate`` task, so items
    divided by aggregates is the mean width of a wave without needing a
    parent-to-child mapping. Ranking is counted the same way against its
    ``finalize`` task.
    """
    counts: dict[str, int] = defaultdict(int)
    for span in spans:
        counts[span.task_type] += 1

    items = {
        task_type.removesuffix(".item"): count
        for task_type, count in counts.items()
        if task_type.endswith(".item")
    }
    widths = {
        family: count / waves
        for family, count in items.items()
        if (waves := counts.get(f"{family}{AGGREGATE_SUFFIX}", 0))
    }
    matches = counts.get("engine.ranking.match", 0)
    finalizes = counts.get("engine.ranking.finalize", 0)
    if finalizes:
        widths["engine.ranking"] = matches / finalizes
    return widths


def profile_run(
    run_id: str,
    tier: str,
    status: str,
    spans: Sequence[TaskSpan],
    cohort_size: int = DEFAULT_COHORT_SIZE,
) -> RunProfile | None:
    """Build one run's critical-path profile, or None when unmeasurable.

    Args:
        run_id: Identifier of the run.
        tier: Run tier recorded on the run row.
        status: Terminal run status.
        spans: The run's completed task spans.
        cohort_size: Worker slots the run had available, for occupancy.

    Returns:
        The profile, or None when the run has no measurable spans.
    """
    if not spans:
        return None
    started = min(span.started_at for span in spans)
    ended = max(span.completed_at for span in spans)
    wall_s = max(0.0, ended - started)
    acc = _sweep(spans)
    return RunProfile(
        run_id=run_id,
        tier=tier,
        status=status,
        started_at=started,
        wall_s=wall_s,
        active_s=acc.active_s,
        idle_s=max(0.0, wall_s - acc.active_s),
        task_count=len(spans),
        stages=_stage_stats(spans, acc),
        items_per_invocation=_fanout_width(spans),
        occupancy=occupancy(spans, cohort_size),
    )


def run_tier(config_json: str, profile: str) -> str:
    """Read the run tier from its config, falling back to the mode column."""
    try:
        config = json.loads(config_json)
    except (TypeError, ValueError):
        return profile
    tier = config.get("tier") or config.get("setup", {}).get("tier")
    return str(tier or profile)


def load_spans(
    conn: sqlite3.Connection, run_ids: Iterable[str]
) -> dict[str, list[TaskSpan]]:
    """Load completed task spans for the given runs, keyed by run id."""
    spans: dict[str, list[TaskSpan]] = defaultdict(list)
    ids = list(run_ids)
    if not ids:
        return spans
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        "SELECT run_id, task_type, started_at, completed_at "
        "FROM scientific_tasks "
        f"WHERE status = ? AND run_id IN ({placeholders}) "
        "AND started_at IS NOT NULL AND completed_at IS NOT NULL",
        (_MEASURED_STATUS, *ids),
    ).fetchall()
    for row in rows:
        spans[row["run_id"]].append(
            TaskSpan(
                task_type=row["task_type"],
                started_at=float(row["started_at"]),
                completed_at=float(row["completed_at"]),
            )
        )
    return spans
