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


def test_completed_run_serves_engine_metrics(
    isolated_db: str,
) -> None:
    """A completed offline engine run persists real execution metrics.

    The engine records metrics from its own instrumentation (LLM calls, phase
    timings, node counts) rather than a mock formula, so the assertions here
    are on the metrics being present, well-formed, and internally consistent
    with the run having done real work -- not on a reconstructed identity with
    the store's summary counts.
    """
    client = _client()
    created = client.post(
        "/api/runs",
        json={"research_goal": "Metrics for a full run", "tier": "express"},
    )
    run_id = created.json()["id"]
    assert client.post(f"/api/runs/{run_id}/start", json={}).status_code == 200
    assert _wait_status(client, run_id, "completed", timeout=30.0)

    metrics = client.get(f"/api/runs/{run_id}/metrics").json()["metrics"]

    assert metrics is not None
    for field in _METRIC_FIELDS:
        assert field in metrics
    # A real engine run generated hypotheses, ran the tournament, evolved, and
    # made LLM calls; the recorded counts must all reflect that work.
    assert metrics["hypothesis_count"] >= 1
    assert metrics["tournaments_count"] >= 1
    assert metrics["evolutions_count"] > 0
    assert metrics["llm_calls"] > 0
    assert isinstance(metrics["phase_times"], dict)
    assert metrics["total_time"] >= 0.0
