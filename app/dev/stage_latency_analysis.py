"""Partition busy time by stage kind; summed task durations double-count
concurrency. Unoccupied time is idle latency, not attributable to any
stage.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from itertools import pairwise
from typing import Any

# Default matches app worker_pool_size; the CLI supplies its live setting.
DEFAULT_COHORT_SIZE = 8


@dataclasses.dataclass(frozen=True)
class TaskSpan:
    task_type: str
    started_at: float
    completed_at: float

    @property
    def duration_s(self) -> float:
        return max(0.0, self.completed_at - self.started_at)


def _boundaries(spans: Sequence[TaskSpan]) -> list[float]:
    points: set[float] = set()
    for span in spans:
        points.add(span.started_at)
        points.add(span.completed_at)
    return sorted(points)


def _segments(
    spans: Sequence[TaskSpan],
) -> Iterator[tuple[float, float, list[TaskSpan]]]:
    """Stage attribution counts distinct kinds; occupancy counts every
    individual task.
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
    task_type: str
    mean_concurrency: float
    peak_concurrency: int
    saturated_s: float
    headroom: float

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class RunOccupancy:
    cohort_size: int
    mean_concurrency: float
    peak_concurrency: int
    saturated_s: float
    stages: tuple[StageOccupancy, ...]

    def to_dict(self) -> dict[str, Any]:
        data = dataclasses.asdict(self)
        data["stages"] = [stage.to_dict() for stage in self.stages]
        return data


@dataclasses.dataclass
class _StageLoad:
    busy_s: float = 0.0
    concurrency_s: float = 0.0
    peak: int = 0
    saturated_s: float = 0.0


def _accumulate_load(
    load: _StageLoad, length: float, count: int, cohort_size: int
) -> None:
    load.busy_s += length
    load.concurrency_s += length * count
    load.peak = max(load.peak, count)
    if count >= cohort_size:
        load.saturated_s += length


def _stage_occupancy(
    loads: dict[str, _StageLoad], cohort_size: int
) -> tuple[StageOccupancy, ...]:
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


# Bookkeeping tasks remain reported so structural overhead stays
# distinguishable.
AGGREGATE_SUFFIX = ".aggregate"

# Failed/cancelled task spans do not measure successful stage duration.
_MEASURED_STATUS = "completed"


@dataclasses.dataclass(frozen=True)
class StageStats:
    task_type: str
    invocations: int
    wall_share_s: float
    solo_s: float
    worker_s: float
    p50_s: float
    p95_s: float

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class RunProfile:
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
        data = dataclasses.asdict(self)
        data["stages"] = [stage.to_dict() for stage in self.stages]
        data["occupancy"] = self.occupancy.to_dict()
        return data


def percentile(values: Sequence[float], fraction: float) -> float:
    """Nearest-rank avoids inventing unobserved durations between tiny
    samples.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, min(len(ordered), round(fraction * len(ordered) + 0.5)))
    return ordered[rank - 1]


@dataclasses.dataclass
class _Attribution:
    wall_share: dict[str, float] = dataclasses.field(
        default_factory=lambda: defaultdict(float)
    )
    solo: dict[str, float] = dataclasses.field(
        default_factory=lambda: defaultdict(float)
    )
    active_s: float = 0.0


def _sweep(spans: Sequence[TaskSpan]) -> _Attribution:
    """Equal shares among active stage kinds partition busy time instead of
    multiplying it by workers.
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
    """Each wave has one aggregate (ranking: finalize); items per aggregate
    measures width.
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
    try:
        config = json.loads(config_json)
    except (TypeError, ValueError):
        return profile
    tier = config.get("tier") or config.get("setup", {}).get("tier")
    return str(tier or profile)


def load_spans(
    conn: sqlite3.Connection, run_ids: Iterable[str]
) -> dict[str, list[TaskSpan]]:
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
