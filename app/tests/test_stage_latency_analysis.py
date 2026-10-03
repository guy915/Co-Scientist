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


def test_fanout_width_counts_items_per_wave() -> None:
    spans = [TaskSpan("engine.fanout.review.item", 0.0, 1.0) for _ in range(6)]
    spans += [
        TaskSpan("engine.fanout.review.aggregate", 1.0, 2.0),
        TaskSpan("engine.fanout.review.aggregate", 2.0, 3.0),
    ]
    profile = profile_run("r", "standard", "completed", spans)

    assert profile is not None
    assert profile.items_per_invocation["engine.fanout.review"] == 3.0


def test_ranking_width_counts_matches_per_finalize() -> None:
    spans = [TaskSpan("engine.ranking.match", 0.0, 1.0) for _ in range(12)]
    spans.append(TaskSpan("engine.ranking.finalize", 1.0, 2.0))
    profile = profile_run("r", "standard", "completed", spans)

    assert profile is not None
    assert profile.items_per_invocation["engine.ranking"] == 12.0


def test_headroom_reports_the_slots_a_stage_left_unused() -> None:
    spans = [
        TaskSpan("engine.fanout.verification.item", 0.0, 10.0) for _ in range(3)
    ]

    stage = _occupancy_stages(spans, 8)["engine.fanout.verification.item"]

    assert stage.mean_concurrency == 3.0
    assert stage.peak_concurrency == 3
    assert stage.headroom == 5.0
    assert stage.saturated_s == 0.0


def test_a_stage_at_the_ceiling_reports_no_headroom() -> None:
    # A saturated cohort cannot overlap another stage.
    spans = [TaskSpan("engine.fanout.review.item", 0.0, 10.0) for _ in range(8)]

    stage = _occupancy_stages(spans, 8)["engine.fanout.review.item"]

    assert stage.mean_concurrency == 8.0
    assert stage.headroom == 0.0
    assert stage.saturated_s == 10.0


def test_occupancy_counts_every_task_in_flight_not_just_the_stage_s() -> None:
    # Occupancy includes every stage rather than only the measured stage.
    spans = [TaskSpan("engine.node.orchestrator", 0.0, 10.0)]
    spans += [
        TaskSpan("engine.fanout.review.item", 0.0, 10.0) for _ in range(7)
    ]

    stages = _occupancy_stages(spans, 8)

    assert stages["engine.node.orchestrator"].mean_concurrency == 8.0
    assert stages["engine.node.orchestrator"].headroom == 0.0


def test_occupancy_is_time_weighted_across_changing_width() -> None:
    spans = [
        TaskSpan("engine.fanout.review.item", 0.0, 90.0),
        TaskSpan("engine.fanout.review.item", 0.0, 10.0),
    ]

    stage = _occupancy_stages(spans, 8)["engine.fanout.review.item"]

    assert round(stage.mean_concurrency, 3) == round(100.0 / 90.0, 3)


def test_profile_run_rejects_an_unmeasurable_run() -> None:
    assert profile_run("r", "standard", "completed", []) is None


def test_percentile_uses_nearest_rank() -> None:
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.95) == 4.0
    assert percentile([], 0.5) == 0.0
