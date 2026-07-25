"""Tests for the durable-spine latency attribution used by benchmarking.

The load-bearing property is that concurrent work is never summed: the
report exists to stop optimization effort going to wide, already-overlapped
fan-outs instead of the narrow serial spine that sets the deadline.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__))))

from dev.stage_latency_analysis import (
    RunProfile,
    StageOccupancy,
    StageStats,
    TaskSpan,
    occupancy,
    percentile,
    profile_run,
)


def _stages(profile: RunProfile) -> dict[str, StageStats]:
    """Index a profile's stage stats by task type."""
    return {stage.task_type: stage for stage in profile.stages}


def _occupancy_stages(
    spans: list[TaskSpan], size: int
) -> dict[str, StageOccupancy]:
    """Index a span set's per-stage occupancy by task type."""
    return {stage.task_type: stage for stage in occupancy(spans, size).stages}


def test_concurrent_items_are_not_summed() -> None:
    """Four items overlapping for 10s cost the run 10s, not 40s."""
    spans = [TaskSpan("engine.fanout.review.item", 0.0, 10.0) for _ in range(4)]
    profile = profile_run("r", "standard", "completed", spans)

    assert profile is not None
    assert profile.wall_s == 10.0
    assert profile.active_s == 10.0
    stage = _stages(profile)["engine.fanout.review.item"]
    assert stage.wall_share_s == 10.0
    # The naive sum is retained only as a diagnostic, and must show the
    # 4x inflation the wall share avoids.
    assert stage.worker_s == 40.0


def test_wall_shares_partition_active_time() -> None:
    """Overlapping stage kinds split the shared segment, summing to active."""
    spans = [
        TaskSpan("engine.node.ranking", 0.0, 20.0),
        TaskSpan("engine.ranking.match", 10.0, 20.0),
    ]
    profile = profile_run("r", "standard", "completed", spans)

    assert profile is not None
    stages = _stages(profile)
    # 0-10s ranking alone, 10-20s split evenly between the two kinds.
    assert stages["engine.node.ranking"].wall_share_s == 15.0
    assert stages["engine.ranking.match"].wall_share_s == 5.0
    total = sum(stage.wall_share_s for stage in profile.stages)
    assert total == profile.active_s == 20.0


def test_solo_time_isolates_the_serial_spine() -> None:
    """Solo time counts only what ran with nothing else running."""
    spans = [
        TaskSpan("engine.node.orchestrator", 0.0, 5.0),
        TaskSpan("engine.node.ranking", 5.0, 25.0),
        TaskSpan("engine.ranking.match", 15.0, 25.0),
    ]
    profile = profile_run("r", "standard", "completed", spans)

    assert profile is not None
    stages = _stages(profile)
    assert stages["engine.node.orchestrator"].solo_s == 5.0
    # Ranking is alone for 5-15s only; it overlaps matches after that.
    assert stages["engine.node.ranking"].solo_s == 10.0
    assert stages["engine.ranking.match"].solo_s == 0.0


def test_gaps_between_tasks_are_idle_not_attributed() -> None:
    """Dead time between tasks belongs to no stage."""
    spans = [
        TaskSpan("engine.node.supervisor", 0.0, 10.0),
        TaskSpan("engine.node.generate", 30.0, 40.0),
    ]
    profile = profile_run("r", "standard", "completed", spans)

    assert profile is not None
    assert profile.wall_s == 40.0
    assert profile.active_s == 20.0
    assert profile.idle_s == 20.0


def test_fanout_width_counts_items_per_wave() -> None:
    """Fan-out width is items divided by the waves that closed them."""
    spans = [TaskSpan("engine.fanout.review.item", 0.0, 1.0) for _ in range(6)]
    spans += [
        TaskSpan("engine.fanout.review.aggregate", 1.0, 2.0),
        TaskSpan("engine.fanout.review.aggregate", 2.0, 3.0),
    ]
    profile = profile_run("r", "standard", "completed", spans)

    assert profile is not None
    assert profile.items_per_invocation["engine.fanout.review"] == 3.0


def test_ranking_width_counts_matches_per_finalize() -> None:
    """Ranking waves are measured against their finalize task."""
    spans = [TaskSpan("engine.ranking.match", 0.0, 1.0) for _ in range(12)]
    spans.append(TaskSpan("engine.ranking.finalize", 1.0, 2.0))
    profile = profile_run("r", "standard", "completed", spans)

    assert profile is not None
    assert profile.items_per_invocation["engine.ranking"] == 12.0


def test_headroom_reports_the_slots_a_stage_left_unused() -> None:
    """A 3-wide stage on an 8-slot cohort reports five free slots."""
    spans = [
        TaskSpan("engine.fanout.verification.item", 0.0, 10.0) for _ in range(3)
    ]

    stage = _occupancy_stages(spans, 8)["engine.fanout.verification.item"]

    assert stage.mean_concurrency == 3.0
    assert stage.peak_concurrency == 3
    assert stage.headroom == 5.0
    assert stage.saturated_s == 0.0


def test_a_stage_at_the_ceiling_reports_no_headroom() -> None:
    """A stage filling the cohort is saturated for its whole duration.

    This is the reading that rules *out* overlapping a stage with an
    independent one: there is no slot for the other stage to run in, so
    overlapping would only requeue the same work.
    """
    spans = [TaskSpan("engine.fanout.review.item", 0.0, 10.0) for _ in range(8)]

    stage = _occupancy_stages(spans, 8)["engine.fanout.review.item"]

    assert stage.mean_concurrency == 8.0
    assert stage.headroom == 0.0
    assert stage.saturated_s == 10.0


def test_occupancy_counts_every_task_in_flight_not_just_the_stage_s() -> None:
    """A stage's concurrency includes work from other stages beside it.

    The question occupancy answers is whether the cohort had a free slot,
    which depends on everything running -- so a narrow stage sharing the
    cohort with a wide one must not read as having the cohort to itself.
    """
    spans = [TaskSpan("engine.node.orchestrator", 0.0, 10.0)]
    spans += [
        TaskSpan("engine.fanout.review.item", 0.0, 10.0) for _ in range(7)
    ]

    stages = _occupancy_stages(spans, 8)

    assert stages["engine.node.orchestrator"].mean_concurrency == 8.0
    assert stages["engine.node.orchestrator"].headroom == 0.0


def test_occupancy_is_time_weighted_across_changing_width() -> None:
    """Concurrency is weighted by duration, not averaged over segments."""
    spans = [
        TaskSpan("engine.fanout.review.item", 0.0, 90.0),
        TaskSpan("engine.fanout.review.item", 0.0, 10.0),
    ]

    stage = _occupancy_stages(spans, 8)["engine.fanout.review.item"]

    # 10s at width 2 and 80s at width 1 -> (20 + 80) / 90.
    assert round(stage.mean_concurrency, 3) == round(100.0 / 90.0, 3)


def test_profile_run_rejects_an_unmeasurable_run() -> None:
    """A run with no completed spans yields no profile rather than zeros."""
    assert profile_run("r", "standard", "completed", []) is None


def test_percentile_uses_nearest_rank() -> None:
    """Percentiles select an observed value, never an interpolated one."""
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.95) == 4.0
    assert percentile([], 0.5) == 0.0
