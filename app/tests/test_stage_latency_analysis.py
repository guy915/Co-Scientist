# Concurrent stage durations cannot be summed as serial latency.

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__))))

from dev.stage_latency_analysis import (
    RunProfile,
    StageStats,
    TaskSpan,
    profile_run,
)


def _stages(profile: RunProfile) -> dict[str, StageStats]:
    return {stage.task_type: stage for stage in profile.stages}


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
