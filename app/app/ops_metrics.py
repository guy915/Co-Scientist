"""Prometheus ``/metrics`` derivation: read-only aggregates over the store.

Every number here is computed fresh from ``runs``/``scientific_tasks`` on
each call rather than accumulated in an in-process counter -- a counter
would read zero after every restart and, on the single serving replica
this API runs at, is strictly worse than a query against the table that
is already the source of truth (see AGENTS.md). Each query is scoped to
an indexed column (``runs.status`` via ``idx_runs_status``,
``scientific_tasks.status`` via ``idx_tasks_ready``) and issues no write,
so it is safe to run on every Prometheus scrape; :func:`metrics_text_cached`
adds a short TTL cache on top so an accidental scrape storm costs one
query pass, not one per request.
"""

from __future__ import annotations

import dataclasses
import time

# CONTENT_TYPE_LATEST (the text/plain exposition content type) is imported
# here to be re-exported, so the endpoint handler does not need its own
# import of the library's constant name.
from prometheus_client import (
    CONTENT_TYPE_LATEST as CONTENT_TYPE_LATEST,
)
from prometheus_client import (
    CollectorRegistry,
    generate_latest,
)
from prometheus_client.core import GaugeMetricFamily, HistogramMetricFamily

from app.config import settings
from app.store.db import connect
from app.version import API_VERSION

# Latency histogram bucket upper bounds, in seconds. A durable task is an
# LLM-driven engine node, so the range runs from a few seconds to an hour
# rather than the sub-second buckets a web-request histogram would use.
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
    """Return the count of runs in each lifecycle status.

    One aggregate query over ``idx_runs_status``.

    Args:
        db_path: Optional override for the SQLite database path.

    Returns:
        Mapping of run status to row count.
    """
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM runs GROUP BY status"
        ).fetchall()
    return {row["status"]: int(row["n"]) for row in rows}


def tasks_by_status(db_path: str | None = None) -> dict[str, int]:
    """Return the count of scientific tasks in each queue status.

    One aggregate query over ``idx_tasks_ready``'s leading ``status``
    column.

    Args:
        db_path: Optional override for the SQLite database path.

    Returns:
        Mapping of task status to row count.
    """
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM scientific_tasks GROUP BY status"
        ).fetchall()
    return {row["status"]: int(row["n"]) for row in rows}


def failed_task_exhaustion(db_path: str | None = None) -> dict[str, int]:
    """Return failed-task counts split by retry-budget exhaustion.

    Scoped to ``status='failed'``, which ``idx_tasks_ready`` covers, so
    this never scans queued/leased/completed rows.

    Args:
        db_path: Optional override for the SQLite database path.

    Returns:
        ``{"true": <exhausted count>, "false": <not-exhausted count>}``.
    """
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
    """One task type's latency histogram data, over completed tasks.

    Attributes:
        task_type: The task type this row summarizes.
        count: Number of completed tasks of this type with both
            timestamps set.
        total_duration: Sum of ``completed_at - started_at`` in seconds.
        bucket_counts: Cumulative count per bound in
            :data:`LATENCY_BUCKETS_SECONDS`, same order (Prometheus
            histogram bucket semantics: count of durations <= bound).
    """

    task_type: str
    count: int
    total_duration: float
    bucket_counts: tuple[int, ...]


def task_latency_by_type(db_path: str | None = None) -> list[TaskLatencyRow]:
    """Return per-task-type latency histogram data for completed tasks.

    One aggregate query, scoped to ``status='completed'`` (an
    ``idx_tasks_ready`` range scan) with the per-bucket cumulative counts
    computed in SQL so only ``O(task types)`` rows -- not one row per
    task -- ever cross into Python. The matched row set still grows with
    the deployment's lifetime completed-task count, since neither
    ``started_at`` nor ``completed_at`` is independently indexed; see the
    module docstring and the shipping report for that caveat.

    Args:
        db_path: Optional override for the SQLite database path.

    Returns:
        One :class:`TaskLatencyRow` per task type with at least one
        completed, timestamped task.
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
    """Collector whose families are recomputed on every ``collect()``.

    The custom-collector pattern (rather than module-level ``Gauge``s
    mutated by callers) is what lets every value here be a fresh,
    read-only snapshot of the store instead of an in-process counter --
    see the module docstring for why that distinction matters on a
    single-replica, restart-prone deployment.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path

    def collect(self) -> list[GaugeMetricFamily | HistogramMetricFamily]:
        """Return every metric family, each backed by one store query."""
        return [
            _runs_family(self._db_path),
            _tasks_family(self._db_path),
            _failed_task_exhaustion_family(self._db_path),
            _task_latency_family(self._db_path),
            _build_info_family(),
        ]


def render_metrics_text(db_path: str | None = None) -> bytes:
    """Render the full Prometheus exposition-format text, uncached.

    Args:
        db_path: Optional override for the SQLite database path.

    Returns:
        The exposition text as UTF-8 bytes.
    """
    registry = CollectorRegistry()
    registry.register(_StoreCollector(db_path))
    return generate_latest(registry)


# Module-level (monotonic deadline, rendered text) cache. A bare tuple
# assignment, no lock: mirrors app.diagnostics's health-check and probe
# caches. A race between two callers both missing the cache just runs the
# query pass twice, which is what would happen without a cache at all --
# the cache's job is to make the *steady-state* repeated-scrape case
# cheap, not to guarantee a single query per TTL window. A
# threading.Lock would only serialize that harmless race; an asyncio
# primitive would be actively wrong here (see AGENTS.md: each durable
# run's worker cohort runs its own event loop, so a lock created on one
# loop raises when awaited from another -- this endpoint is reachable
# from any of them).
_metrics_cache: tuple[float, bytes] | None = None


def clear_metrics_cache() -> None:
    """Drop the cached exposition text (used by tests and reconfig)."""
    global _metrics_cache
    _metrics_cache = None


def metrics_text_cached(db_path: str | None = None) -> bytes:
    """Return exposition text, reusing a short-TTL cache.

    Args:
        db_path: Optional override for the SQLite database path.

    Returns:
        The cached or freshly rendered exposition text, at most
        ``settings.metrics_cache_ttl_seconds`` old.
    """
    global _metrics_cache
    now = time.monotonic()
    if _metrics_cache is not None and now < _metrics_cache[0]:
        return _metrics_cache[1]
    text = render_metrics_text(db_path)
    ttl = settings.metrics_cache_ttl_seconds
    _metrics_cache = (now + ttl, text)
    return text
