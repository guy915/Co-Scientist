from __future__ import annotations

import dataclasses
import time

from prometheus_client import (
    CONTENT_TYPE_LATEST as CONTENT_TYPE_LATEST,
)
from prometheus_client import (
    CollectorRegistry,
    generate_latest,
)
from prometheus_client.core import GaugeMetricFamily, HistogramMetricFamily

from app import API_VERSION
from app.config import settings
from app.store.db import connect

# LLM-driven task latency spans seconds to an hour, unlike subsecond HTTP-
# request histograms.
LATENCY_BUCKETS_SECONDS: tuple[float, ...] = (
    5.0,
    15.0,
    30.0,
    60.0,
    120.0,
    300.0,
    600.0,
    1800.0,
    3600.0,
)


def runs_by_status(db_path: str | None = None) -> dict[str, int]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM runs GROUP BY status"
        ).fetchall()
    return {row["status"]: int(row["n"]) for row in rows}


def tasks_by_status(db_path: str | None = None) -> dict[str, int]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM scientific_tasks GROUP BY status"
        ).fetchall()
    return {row["status"]: int(row["n"]) for row in rows}


def failed_task_exhaustion(db_path: str | None = None) -> dict[str, int]:
    query = (
        "SELECT"
        " COALESCE(SUM(attempt>=max_attempts), 0) AS exhausted,"
        " COALESCE(SUM(attempt<max_attempts), 0) AS not_exhausted"
        " FROM scientific_tasks WHERE status='failed'"
    )
    with connect(db_path) as conn:
        row = conn.execute(query).fetchone()
    return {
        "true": int(row["exhausted"]),
        "false": int(row["not_exhausted"]),
    }


@dataclasses.dataclass(frozen=True)
class TaskLatencyRow:
    """Histogram buckets are cumulative counts of durations at or below each
    bound, as Prometheus requires.
    """

    task_type: str
    count: int
    total_duration: float
    bucket_counts: tuple[int, ...]


def task_latency_by_type(db_path: str | None = None) -> list[TaskLatencyRow]:
    """SQL returns one aggregate per task type; the completed row scan still
    grows with deployment lifetime.
    """
    bucket_columns = [f"b{i}" for i in range(len(LATENCY_BUCKETS_SECONDS))]
    bucket_sql = ",".join(
        "SUM(CASE WHEN (completed_at-started_at)<=? THEN 1 ELSE 0 END)"
        f" AS {col}"
        for col in bucket_columns
    )
    query = (
        "SELECT task_type, COUNT(*) AS n,"
        " COALESCE(SUM(completed_at-started_at), 0) AS total_duration,"
        f" {bucket_sql}"
        " FROM scientific_tasks"
        " WHERE status='completed' AND started_at IS NOT NULL"
        " AND completed_at IS NOT NULL"
        " GROUP BY task_type"
    )
    with connect(db_path) as conn:
        rows = conn.execute(query, LATENCY_BUCKETS_SECONDS).fetchall()
    return [
        TaskLatencyRow(
            task_type=row["task_type"],
            count=int(row["n"]),
            total_duration=float(row["total_duration"]),
            bucket_counts=tuple(int(row[col]) for col in bucket_columns),
        )
        for row in rows
    ]


def _runs_family(db_path: str | None) -> GaugeMetricFamily:
    family = GaugeMetricFamily(
        "coscientist_runs",
        "Number of runs currently in each lifecycle status.",
        labels=["status"],
    )
    for status, count in runs_by_status(db_path).items():
        family.add_metric([status], count)
    return family


def _tasks_family(db_path: str | None) -> GaugeMetricFamily:
    family = GaugeMetricFamily(
        "coscientist_tasks",
        "Number of durable scientific tasks currently in each status.",
        labels=["status"],
    )
    for status, count in tasks_by_status(db_path).items():
        family.add_metric([status], count)
    return family


def _failed_task_exhaustion_family(db_path: str | None) -> GaugeMetricFamily:
    family = GaugeMetricFamily(
        "coscientist_failed_tasks",
        "Failed tasks, split by whether their retry budget was spent.",
        labels=["exhausted"],
    )
    for exhausted, count in failed_task_exhaustion(db_path).items():
        family.add_metric([exhausted], count)
    return family


def _task_latency_family(db_path: str | None) -> HistogramMetricFamily:
    family = HistogramMetricFamily(
        "coscientist_task_duration_seconds",
        "Durable task wall-clock duration (started_at to completed_at).",
        labels=["task_type"],
    )
    bound_labels = [f"{bound:g}" for bound in LATENCY_BUCKETS_SECONDS]
    for row in task_latency_by_type(db_path):
        buckets = list(zip(bound_labels, row.bucket_counts, strict=True))
        buckets.append(("+Inf", row.count))
        family.add_metric([row.task_type], buckets, row.total_duration)
    return family


def _build_info_family() -> GaugeMetricFamily:
    family = GaugeMetricFamily(
        "coscientist_build_info",
        "Always 1; the running build's version is the label.",
        labels=["version"],
    )
    family.add_metric([API_VERSION], 1)
    return family


class _StoreCollector:
    """Durable store snapshots survive restarts; process-local metric
    counters would lose accumulated truth.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path

    def collect(self) -> list[GaugeMetricFamily | HistogramMetricFamily]:
        return [
            _runs_family(self._db_path),
            _tasks_family(self._db_path),
            _failed_task_exhaustion_family(self._db_path),
            _task_latency_family(self._db_path),
            _build_info_family(),
        ]


def render_metrics_text(db_path: str | None = None) -> bytes:
    registry = CollectorRegistry()
    registry.register(_StoreCollector(db_path))
    return generate_latest(registry)


# A double cache miss is harmless duplicated reads; loop-bound locks would break
# across worker-cohort event loops.
_metrics_cache: tuple[float, bytes] | None = None


def clear_metrics_cache() -> None:
    global _metrics_cache
    _metrics_cache = None


def metrics_text_cached(db_path: str | None = None) -> bytes:
    global _metrics_cache
    now = time.monotonic()
    if _metrics_cache is not None and now < _metrics_cache[0]:
        return _metrics_cache[1]
    text = render_metrics_text(db_path)
    ttl = settings.metrics_cache_ttl_seconds
    _metrics_cache = (now + ttl, text)
    return text
