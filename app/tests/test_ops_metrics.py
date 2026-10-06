from __future__ import annotations

from typing import Any

import pytest
from prometheus_client.parser import text_string_to_metric_families

from app import ops_metrics
from app.store import runs
from app.store.db import connect
from app.store.models import RunStatus
from tests._client import make_client as _client
from tests._client import make_operator_client as _operator_client
from tests._store_helpers import enqueue_task, seed_run

pytestmark = pytest.mark.usefixtures("isolated_db")


@pytest.fixture(autouse=True)
def _clear_metrics_cache() -> None:
    # Metric caches must not cross isolated databases.
    ops_metrics.clear_metrics_cache()


def _families(text: str) -> dict[str, Any]:
    return {
        family.name: family for family in text_string_to_metric_families(text)
    }


def _sample_value(family: Any, **labels: str) -> float | None:
    for sample in family.samples:
        if all(sample.labels.get(k) == v for k, v in labels.items()):
            return float(sample.value)
    return None


def _make_run(db_path: str, status: RunStatus = RunStatus.COMPLETED) -> str:
    run = seed_run("metrics goal", db_path=db_path)
    runs.update_run_status(run.id, status, db_path=db_path)
    return run.id


def _enqueue(
    run_id: str, key: str, db_path: str, task_type: str = "engine.node.x"
) -> str:
    task = enqueue_task(run_id, task_type, key, db_path=db_path)
    return task.id


def _set_task_row(task_id: str, db_path: str, **fields: Any) -> None:
    assignments = ",".join(f"{col}=?" for col in fields)
    with connect(db_path) as conn:
        conn.execute(
            f"UPDATE scientific_tasks SET {assignments} WHERE id=?",
            (*fields.values(), task_id),
        )
        conn.commit()


def test_metrics_are_operator_only_and_in_exposition_format() -> None:
    assert _client().get("/metrics").status_code == 404

    res = _operator_client().get("/metrics")

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/plain")
    assert {
        "coscientist_runs",
        "coscientist_tasks",
        "coscientist_failed_tasks",
        "coscientist_task_duration_seconds",
        "coscientist_build_info",
    } <= set(_families(res.text))


def test_metrics_count_runs_tasks_and_failed_tasks_by_status(
    isolated_db: str,
) -> None:
    for status in (
        RunStatus.COMPLETED,
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.RUNNING,
    ):
        _make_run(isolated_db, status)
    run_id = _make_run(isolated_db, RunStatus.RUNNING)
    _enqueue(run_id, "k1", isolated_db)
    _set_task_row(
        _enqueue(run_id, "k2", isolated_db), isolated_db, status="completed"
    )
    _set_task_row(
        _enqueue(run_id, "k3", isolated_db),
        isolated_db,
        status="failed",
        attempt=3,
        max_attempts=3,
    )
    _set_task_row(
        _enqueue(run_id, "k4", isolated_db),
        isolated_db,
        status="failed",
        attempt=1,
        max_attempts=3,
    )

    families = _families(_operator_client().get("/metrics").text)

    runs_family = families["coscientist_runs"]
    assert _sample_value(runs_family, status="completed") == 2
    assert _sample_value(runs_family, status="failed") == 1
    assert _sample_value(runs_family, status="running") == 2
    tasks_family = families["coscientist_tasks"]
    assert _sample_value(tasks_family, status="queued") == 1
    assert _sample_value(tasks_family, status="completed") == 1
    failed = families["coscientist_failed_tasks"]
    assert _sample_value(failed, exhausted="true") == 1
    assert _sample_value(failed, exhausted="false") == 1


def test_metrics_endpoint_issues_no_write(isolated_db: str) -> None:
    _make_run(isolated_db, RunStatus.COMPLETED)
    run_id = _make_run(isolated_db, RunStatus.RUNNING)
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
