"""API tests for the run execution-metrics sub-resource."""

from __future__ import annotations

from tests._client import make_client as _client
from tests._client import wait_for_status as _wait_status

_METRIC_FIELDS = (
    "total_time",
    "hypothesis_count",
    "reviews_count",
    "tournaments_count",
    "evolutions_count",
    "llm_calls",
    "phase_times",
)


def test_metrics_unknown_run_404s() -> None:
    res = _client().get("/api/runs/does-not-exist/metrics")
    assert res.status_code == 404


def test_metrics_null_before_finalize(isolated_db: str) -> None:
    client = _client()
    created = client.post(
        "/api/runs", json={"research_goal": "Draft metrics goal"}
    )
    run_id = created.json()["id"]

    res = client.get(f"/api/runs/{run_id}/metrics")

    assert res.status_code == 200
    assert res.json() == {"metrics": None}


def test_completed_mock_run_serves_deterministic_metrics(
    isolated_db: str,
) -> None:
    """A completed offline mock run persists engine-shaped metrics.

    The mock derives its metrics from the run's persisted artifacts plus a
    documented deterministic formula, so the values must reconcile exactly
    with the run's summary counts.
    """
    client = _client()
    created = client.post(
        "/api/runs", json={"research_goal": "Metrics for a full mock run"}
    )
    run_id = created.json()["id"]
    assert client.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
    assert _wait_status(client, run_id, "completed")

    metrics = client.get(f"/api/runs/{run_id}/metrics").json()["metrics"]

    assert metrics is not None
    for field in _METRIC_FIELDS:
        assert field in metrics
    summary = client.get(f"/api/runs/{run_id}").json()["summary"]
    assert metrics["hypothesis_count"] == summary["hypotheses"]
    assert metrics["reviews_count"] == summary["reviews"]
    assert metrics["tournaments_count"] == summary["matches"]
    assert metrics["llm_calls"] == 2 + (
        summary["hypotheses"] + summary["reviews"] + summary["matches"]
    )
    assert metrics["evolutions_count"] > 0
    assert metrics["phase_times"]
    assert metrics["total_time"] == round(
        sum(metrics["phase_times"].values()), 3
    )
