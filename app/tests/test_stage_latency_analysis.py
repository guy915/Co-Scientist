# Concurrent stage durations cannot be summed as serial latency.

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
    return {stage.task_type: stage for stage in profile.stages}


def _occupancy_stages(
    spans: list[TaskSpan], size: int
) -> dict[str, StageOccupancy]:
    return {stage.task_type: stage for stage in occupancy(spans, size).stages}


def test_concurrent_items_are_not_summed() -> None:
    spans = [TaskSpan("engine.fanout.review.item", 0.0, 10.0) for _ in range(4)]
    profile = profile_run("r", "standard", "completed", spans)

    assert profile is not None
    assert profile.wall_s == 10.0
    assert profile.active_s == 10.0
    stage = _stages(profile)["engine.fanout.review.item"]
    assert stage.wall_share_s == 10.0
    assert stage.worker_s == 40.0


def test_wall_shares_partition_active_time() -> None:
    spans = [
        TaskSpan("engine.node.ranking", 0.0, 20.0),
        TaskSpan("engine.ranking.match", 10.0, 20.0),
    ]
    profile = profile_run("r", "standard", "completed", spans)

    assert profile is not None
    stages = _stages(profile)
    assert stages["engine.node.ranking"].wall_share_s == 15.0
    assert stages["engine.ranking.match"].wall_share_s == 5.0
    total = sum(stage.wall_share_s for stage in profile.stages)
    assert total == profile.active_s == 20.0


def test_solo_time_isolates_the_serial_spine() -> None:
    spans = [
        TaskSpan("engine.node.orchestrator", 0.0, 5.0),
        TaskSpan("engine.node.ranking", 5.0, 25.0),
        TaskSpan("engine.ranking.match", 15.0, 25.0),
    ]
    profile = profile_run("r", "standard", "completed", spans)

    assert profile is not None
    stages = _stages(profile)
    assert stages["engine.node.orchestrator"].solo_s == 5.0
    assert stages["engine.node.ranking"].solo_s == 10.0
    assert stages["engine.ranking.match"].solo_s == 0.0


def test_gaps_between_tasks_are_idle_not_attributed() -> None:
    spans = [
        TaskSpan("engine.node.supervisor", 0.0, 10.0),
        TaskSpan("engine.node.generate", 30.0, 40.0),
    ]
    profile = profile_run("r", "standard", "completed", spans)

    assert profile is not None
    assert profile.wall_s == 40.0
    assert profile.active_s == 20.0
    assert profile.idle_s == 20.0


def test_stage_width_counts_items_per_invocation() -> None:
    spans = [TaskSpan("engine.fanout.review.item", 0.0, 1.0) for _ in range(6)]
    spans += [
        TaskSpan("engine.fanout.review.aggregate", 1.0, 2.0),
        TaskSpan("engine.fanout.review.aggregate", 2.0, 3.0),
    ]
    spans += [TaskSpan("engine.ranking.match", 0.0, 1.0) for _ in range(12)]
    spans.append(TaskSpan("engine.ranking.finalize", 1.0, 2.0))

    profile = profile_run("r", "standard", "completed", spans)

    assert profile is not None
    assert profile.items_per_invocation["engine.fanout.review"] == 3.0
    assert profile.items_per_invocation["engine.ranking"] == 12.0
    assert profile_run("r", "standard", "completed", []) is None


def test_occupancy_counts_every_task_in_flight_and_weights_by_time() -> None:
    spare = _occupancy_stages(
        [TaskSpan("engine.fanout.verification.item", 0.0, 10.0)] * 3, 8
    )["engine.fanout.verification.item"]
    assert spare.mean_concurrency == 3.0
    assert spare.peak_concurrency == 3
    assert spare.headroom == 5.0
    assert spare.saturated_s == 0.0

    # A saturated cohort cannot overlap another stage, and occupancy includes
    # every stage rather than only the measured one.
    full = _occupancy_stages(
        [TaskSpan("engine.node.orchestrator", 0.0, 10.0)]
        + [TaskSpan("engine.fanout.review.item", 0.0, 10.0)] * 7,
        8,
    )
    assert full["engine.node.orchestrator"].mean_concurrency == 8.0
    assert full["engine.fanout.review.item"].headroom == 0.0
    assert full["engine.fanout.review.item"].saturated_s == 10.0

    changing = _occupancy_stages(
        [
            TaskSpan("engine.fanout.review.item", 0.0, 90.0),
            TaskSpan("engine.fanout.review.item", 0.0, 10.0),
        ],
        8,
    )["engine.fanout.review.item"]
    assert round(changing.mean_concurrency, 3) == round(100.0 / 90.0, 3)


def test_percentile_uses_nearest_rank() -> None:
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.95) == 4.0
    assert percentile([], 0.5) == 0.0
