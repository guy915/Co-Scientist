"""A targeted outcome task retains its model call in run metrics."""

import asyncio
from typing import Any

import pytest
from co_scientist.agents.evolution import evolve as evolution
from co_scientist.llm_telemetry import ModelCallStats, record_call
from co_scientist.models import Hypothesis
from co_scientist.models_metrics import ExecutionMetrics

from app import store, task_worker
from app.config import settings
from tests._client import make_client
from tests.test_outcome_refinement_executor import (
    _claim_action,
    _headers,
    _setup_action,
)


def test_completed_refinement_retains_served_model_and_cost(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "auth_mode", "compatibility")
    monkeypatch.setattr(settings, "auth_secret", "outcome-executor-test")
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = make_client()
    run_id, _, _, _ = _setup_action(client, isolated_db)
    task = _claim_action(run_id, "metrics-worker", isolated_db)

    async def evolve_stub(*args: Any, **kwargs: Any) -> tuple[None, None]:
        record_call(
            "openrouter/stealth/space-bunny-alpha",
            ModelCallStats(
                calls=1,
                observed_model_calls=1,
                reported_usage_calls=1,
                priced_usage_calls=1,
                prompt_tokens=12,
                completion_tokens=9,
                cost_usd=0.0,
            ),
        )
        return None, None

    monkeypatch.setattr(
        evolution, "evolve_single_hypothesis_from_outcome", evolve_stub
    )
    result = asyncio.run(
        task_worker._execute_task_payload(task, db_path=isolated_db)
    )
    task_worker._record_success(task, "metrics-worker", result, isolated_db)

    response = client.get(
        f"/api/runs/{run_id}/metrics", headers=_headers("refinement-owner")
    )
    assert response.status_code == 200
    metrics = response.json()["metrics"]
    usage = metrics["model_usage"][
        "outcome_refinement::openrouter/stealth/space-bunny-alpha"
    ]
    assert usage["calls"] == usage["observed_model_calls"] == 1
    assert usage["prompt_tokens"] == 12
    assert usage["completion_tokens"] == 9
    assert usage["cost_usd"] == 0.0
    assert store.get_run_metrics(run_id, db_path=isolated_db) == metrics
    replay = asyncio.run(
        task_worker._execute_task_payload(task, db_path=isolated_db)
    )
    assert replay["replayed"] is True
    assert (
        client.get(
            f"/api/runs/{run_id}/metrics", headers=_headers("refinement-owner")
        ).json()["metrics"]
        == metrics
    )
    client.close()


def test_child_checkpoint_retains_refinement_model_usage(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "auth_mode", "compatibility")
    monkeypatch.setattr(settings, "auth_secret", "outcome-executor-test")
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = make_client()
    run_id, _, _, _ = _setup_action(client, isolated_db)
    store.save_run_metrics(
        run_id,
        ExecutionMetrics(
            llm_calls=5,
            model_usage={"prior::model": ModelCallStats(calls=5).as_dict()},
        ).to_dict(),
        db_path=isolated_db,
    )
    task = _claim_action(run_id, "child-metrics-worker", isolated_db)
    model = "openrouter/stealth/space-bunny-alpha"

    async def evolved_child(
        parent: Hypothesis, *args: Any, **kwargs: Any
    ) -> tuple[Hypothesis, dict[str, Any]]:
        record_call(model, ModelCallStats(calls=1, observed_model_calls=1))
        return Hypothesis(
            text="SOS2-dependent HGF bypass",
            parent_id=parent.id,
            parent_ids=[parent.id],
        ), {}

    monkeypatch.setattr(
        evolution, "evolve_single_hypothesis_from_outcome", evolved_child
    )
    result = asyncio.run(
        task_worker._execute_task_payload(task, db_path=isolated_db)
    )
    assert result["child_hypothesis_id"] is not None
    checkpoint = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert checkpoint is not None
    checkpoint_metrics = checkpoint["state"]["state"]["metrics"]
    usage = checkpoint_metrics["model_usage"]
    assert usage[f"outcome_refinement::{model}"]["calls"] == 1
    assert usage["prior::model"]["calls"] == 5
    assert checkpoint_metrics["llm_calls"] == 6
    task_worker._record_success(
        task, "child-metrics-worker", result, isolated_db
    )
    review_task = store.claim_task(
        "review-worker", run_id=run_id, db_path=isolated_db
    )
    assert review_task is not None
    assert review_task.task_type == "engine.node.review"
    review_result = asyncio.run(
        task_worker._execute_task_payload(review_task, db_path=isolated_db)
    )
    task_worker._record_success(
        review_task, "review-worker", review_result, isolated_db
    )
    response = client.get(
        f"/api/runs/{run_id}/metrics", headers=_headers("refinement-owner")
    )
    assert response.status_code == 200
    reported = response.json()["metrics"]
    assert reported["model_usage"][f"outcome_refinement::{model}"]["calls"] == 1
    assert reported["model_usage"]["prior::model"]["calls"] == 5
    client.close()


def test_failed_refinement_usage_survives_retry(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "auth_mode", "compatibility")
    monkeypatch.setattr(settings, "auth_secret", "outcome-executor-test")
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = make_client()
    run_id, parent_id, _, action_id = _setup_action(client, isolated_db)
    task = _claim_action(run_id, "first-worker", isolated_db)
    model = "openrouter/stealth/space-bunny-alpha"

    async def failed_evolve(*args: Any, **kwargs: Any) -> tuple[None, None]:
        record_call(model, ModelCallStats(calls=1, errors={"APIError": 1}))
        raise RuntimeError("temporary provider failure")

    monkeypatch.setattr(
        evolution, "evolve_single_hypothesis_from_outcome", failed_evolve
    )
    with pytest.raises(RuntimeError, match="temporary provider failure"):
        asyncio.run(
            task_worker._execute_task_payload(task, db_path=isolated_db)
        )
    metrics = store.get_run_metrics(run_id, db_path=isolated_db)
    assert metrics is not None
    assert metrics["model_usage"][f"outcome_refinement::{model}"]["calls"] == 1

    assert store.fail_task(
        task.id,
        "first-worker",
        "temporary",
        retryable=False,
        db_path=isolated_db,
    )
    action = store.get_outcome_refinement_action(
        run_id, action_id, db_path=isolated_db
    )
    assert action is not None
    replay = client.post(
        f"/api/runs/{run_id}/hypotheses/{parent_id}/outcomes/{action['outcome_id']}/refine",
        headers=_headers("refinement-owner"),
    )
    assert replay.status_code == 202
    retried = _claim_action(run_id, "second-worker", isolated_db)

    async def recovered_evolve(*args: Any, **kwargs: Any) -> tuple[None, None]:
        record_call(
            model, ModelCallStats(calls=1, observed_model_calls=1, cost_usd=0.0)
        )
        return None, None

    monkeypatch.setattr(
        evolution, "evolve_single_hypothesis_from_outcome", recovered_evolve
    )
    result = asyncio.run(
        task_worker._execute_task_payload(retried, db_path=isolated_db)
    )
    task_worker._record_success(retried, "second-worker", result, isolated_db)
    usage = client.get(
        f"/api/runs/{run_id}/metrics", headers=_headers("refinement-owner")
    ).json()["metrics"]["model_usage"][f"outcome_refinement::{model}"]
    assert usage["calls"] == 2
    assert usage["observed_model_calls"] == 1
    assert usage["errors"] == {"APIError": 1}
    client.close()


def test_invalid_child_still_records_completed_provider_call(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "auth_mode", "compatibility")
    monkeypatch.setattr(settings, "auth_secret", "outcome-executor-test")
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = make_client()
    run_id, _, _, _ = _setup_action(client, isolated_db)
    task = _claim_action(run_id, "invalid-child-worker", isolated_db)
    model = "openrouter/stealth/space-bunny-alpha"

    async def invalid_child(
        *args: Any, **kwargs: Any
    ) -> tuple[Hypothesis, dict[str, Any]]:
        record_call(model, ModelCallStats(calls=1, observed_model_calls=1))
        return Hypothesis(
            text="Invalid child", parent_id="wrong", parent_ids=["wrong"]
        ), {}

    monkeypatch.setattr(
        evolution, "evolve_single_hypothesis_from_outcome", invalid_child
    )
    with pytest.raises(
        ValueError, match="targeted outcome evolution must return one parent"
    ):
        asyncio.run(
            task_worker._execute_task_payload(task, db_path=isolated_db)
        )
    metrics = store.get_run_metrics(run_id, db_path=isolated_db)
    assert metrics is not None
    assert metrics["model_usage"][f"outcome_refinement::{model}"]["calls"] == 1
    client.close()
