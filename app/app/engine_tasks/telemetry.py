"""Shared fold for fan-out/ranking item telemetry snapshots.

Every durable fan-out item and ranking-match wave captures its own LLM
usage via ``co_scientist.llm.telemetry.scoped_telemetry`` and carries the
snapshot home in its own task result or successor inputs -- an item task
never commits workflow state itself (see ``app.engine_tasks.fanout_items``
and ``app.engine_tasks.ranking_wave``). The family's aggregate (or, for
ranking, the next wave/finalize task) folds those snapshots back into one
``ExecutionMetrics.model_usage`` delta here, so every family reuses the
identical additive merge instead of re-deriving it per family.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def merge_usage_snapshots(
    snapshots: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Fold per-item ``llm.telemetry`` snapshots into one usage dict.

    Args:
        snapshots: One ``TelemetryAccumulator.snapshot()`` per fan-out item
            or ranking wave, in any order; empty snapshots are skipped.

    Returns:
        The combined per-(phase, model) usage, additive across snapshots --
        the same rule ``models_metrics.merge_metrics`` applies to a node's
        own ``model_usage`` delta.
    """
    from co_scientist.models import (
        ExecutionMetrics,
        create_metrics_update,
        merge_metrics,
    )

    merged = ExecutionMetrics()
    for snapshot in snapshots:
        if not snapshot:
            continue
        merged = merge_metrics(
            merged, create_metrics_update(model_usage=dict(snapshot))
        )
    # The app's mypy config skips following ``co_scientist`` imports, so
    # ``merged.model_usage`` arrives here as ``Any``; restate the engine's
    # declared field type on the return rather than passing it on unchecked.
    usage: dict[str, dict[str, Any]] = merged.model_usage
    return usage
