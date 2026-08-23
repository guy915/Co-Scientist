"""``/metrics``: the Prometheus exposition-format ops surface.

Covers the whole chain: the endpoint's format/content-type/auth gating,
each metric family's derivation from ``runs``/``scientific_tasks``, the
short-TTL cache, and -- the hard constraint -- that a scrape issues no
write (see AGENTS.md on never writing on a poll tick).
"""

from __future__ import annotations

from typing import Any

import pytest
from prometheus_client.parser import text_string_to_metric_families

from app import ops_metrics, store
from app.store.db import connect
from tests._client import make_client as _client
from tests._client import make_operator_client as _operator_client

pytestmark = pytest.mark.usefixtures("isolated_db")


@pytest.fixture(autouse=True)
def _clear_metrics_cache() -> None:
    """Every test gets its own isolated DB; the cache must not straddle it."""
    ops_metrics.clear_metrics_cache()


def _families(text: str) -> dict[str, Any]:
    """Parse exposition text into {metric name: family}."""
    return {
        family.name: family for family in text_string_to_metric_families(text)
    }


def _sample_value(family: Any, **labels: str) -> float | None:
    for sample in family.samples:
        if all(sample.labels.get(k) == v for k, v in labels.items()):
            return sample.value
    return None


def _make_run(
    db_path: str, status: store.RunStatus = store.RunStatus.COMPLETED
) -> str:
    run = store.create_run(
        "metrics goal",
        "standard",
        "engine",
        {},
        options=store.RunCreateOptions(db_path=db_path),
    )
    store.update_run_status(run.id, status, db_path=db_path)
    return run.id


def _enqueue(
    run_id: str, key: str, db_path: str, task_type: str = "engine.node.x"
) -> str:
    task = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=task_type,
            inputs={},
            idempotency_key=key,
        ),
        db_path=db_path,
    )
    return task.id


def _set_task_row(task_id: str, db_path: str, **fields: Any) -> None:
    """Directly overwrite columns on a task row (test seeding only)."""
    assignments = ",".join(f"{col}=?" for col in fields)
    with connect(db_path) as conn:
        conn.execute(
            f"UPDATE scientific_tasks SET {assignments} WHERE id=?",
            (*fields.values(), task_id),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Endpoint shape: format, content type, auth gating
# ---------------------------------------------------------------------------


def test_metrics_requires_operator_access() -> None:
    res = _client().get("/metrics")
    assert res.status_code == 404


def test_metrics_returns_valid_exposition_format() -> None:
    res = _operator_client().get("/metrics")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/plain")
    families = _families(res.text)
    assert "coscientist_runs" in families
    assert "coscientist_tasks" in families
    assert "coscientist_failed_tasks" in families
    assert "coscientist_task_duration_seconds" in families
    assert "coscientist_build_info" in families


# ---------------------------------------------------------------------------
# Runs by status
# ---------------------------------------------------------------------------


def test_metrics_counts_runs_per_status(isolated_db: str) -> None:
    _make_run(isolated_db, store.RunStatus.COMPLETED)
    _make_run(isolated_db, store.RunStatus.COMPLETED)
    _make_run(isolated_db, store.RunStatus.FAILED)
    _make_run(isolated_db, store.RunStatus.RUNNING)

    res = _operator_client().get("/metrics")
    family = _families(res.text)["coscientist_runs"]

    assert _sample_value(family, status="completed") == 2
    assert _sample_value(family, status="failed") == 1
    assert _sample_value(family, status="running") == 1


# ---------------------------------------------------------------------------
# Tasks by status
# ---------------------------------------------------------------------------


def test_metrics_counts_tasks_per_status(isolated_db: str) -> None:
    run_id = _make_run(isolated_db, store.RunStatus.RUNNING)
    _enqueue(run_id, "k1", isolated_db)
    t2 = _enqueue(run_id, "k2", isolated_db)
    _set_task_row(t2, isolated_db, status="completed")

    res = _operator_client().get("/metrics")
    family = _families(res.text)["coscientist_tasks"]

    assert _sample_value(family, status="queued") == 1
    assert _sample_value(family, status="completed") == 1


# ---------------------------------------------------------------------------
# Failed-task retry-budget exhaustion
# ---------------------------------------------------------------------------


def test_metrics_splits_failed_tasks_by_exhaustion(isolated_db: str) -> None:
    run_id = _make_run(isolated_db, store.RunStatus.FAILED)
    exhausted = _enqueue(run_id, "k1", isolated_db)
    _set_task_row(
        exhausted, isolated_db, status="failed", attempt=3, max_attempts=3
    )
    not_exhausted = _enqueue(run_id, "k2", isolated_db)
    _set_task_row(
        not_exhausted,
        isolated_db,
        status="failed",
        attempt=1,
        max_attempts=3,
    )

    res = _operator_client().get("/metrics")
    family = _families(res.text)["coscientist_failed_tasks"]

    assert _sample_value(family, exhausted="true") == 1
    assert _sample_value(family, exhausted="false") == 1


# ---------------------------------------------------------------------------
# Latency histogram
# ---------------------------------------------------------------------------


def test_metrics_latency_reflects_started_completed_timestamps(
    isolated_db: str,
) -> None:
    run_id = _make_run(isolated_db, store.RunStatus.COMPLETED)
    task_id = _enqueue(
        run_id, "k1", isolated_db, task_type="engine.node.ranking"
    )
    # A 20s-duration task falls into the 30s bucket and every bucket above
    # it, but not the 5s or 15s buckets below it.
    _set_task_row(
        task_id,
        isolated_db,
        status="completed",
        started_at=1000.0,
        completed_at=1020.0,
    )

    res = _operator_client().get("/metrics")
    family = _families(res.text)["coscientist_task_duration_seconds"]

    bucket_samples = {
        s.labels["le"]: s.value
        for s in family.samples
        if s.name.endswith("_bucket")
        and s.labels.get("task_type") == "engine.node.ranking"
    }
    assert bucket_samples["15"] == 0
    assert bucket_samples["30"] == 1
    assert bucket_samples["+Inf"] == 1
    sum_sample = next(
        s
        for s in family.samples
        if s.name.endswith("_sum")
        and s.labels.get("task_type") == "engine.node.ranking"
    )
    assert sum_sample.value == 20.0


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def test_metrics_cache_avoids_requerying_within_ttl(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}
    real_runs_by_status = ops_metrics.runs_by_status

    def _counting_runs_by_status(db_path: str | None = None) -> Any:
        calls["n"] += 1
        return real_runs_by_status(db_path)

    monkeypatch.setattr(ops_metrics, "runs_by_status", _counting_runs_by_status)

    first = ops_metrics.metrics_text_cached(db_path=isolated_db)
    second = ops_metrics.metrics_text_cached(db_path=isolated_db)

    assert calls["n"] == 1
    assert first == second


# ---------------------------------------------------------------------------
# No write on a scrape
# ---------------------------------------------------------------------------


def test_metrics_endpoint_issues_no_write(isolated_db: str) -> None:
    _make_run(isolated_db, store.RunStatus.COMPLETED)
    run_id = _make_run(isolated_db, store.RunStatus.RUNNING)
    task_id = _enqueue(run_id, "k1", isolated_db)
    _set_task_row(
        task_id,
        isolated_db,
        status="completed",
        started_at=1.0,
        completed_at=2.0,
    )

    with connect(isolated_db) as probe:
        before = probe.execute("PRAGMA data_version").fetchone()[0]

    res = _operator_client().get("/metrics")
    assert res.status_code == 200

    with connect(isolated_db) as probe:
        after = probe.execute("PRAGMA data_version").fetchone()[0]

    assert after == before
