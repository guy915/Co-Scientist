"""Campaign model selection survives Robin's durable refinement boundary."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from co_scientist.agents import evolution
from co_scientist.models import Hypothesis, HypothesisOrigin

from app import store, task_worker
from app.config import settings
from app.store import RunStatus
from tests._client import make_client
from tests._outcome_refinement_api_support import (
    MESELSON_STAHL_PARENT_TEXT,
    _add_meselson_stahl_fixture,
    _new_run,
    _save_engine_checkpoint,
    _signed_headers,
)


@pytest.fixture(autouse=True)
def _disable_embedded_provider_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_mode", "compatibility")
    monkeypatch.setattr(settings, "auth_secret", "outcome-executor-test")
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)


def _campaign_refinement_task(db_path: str) -> tuple[Any, store.ScientificTask]:
    owner = "refinement-owner"
    client = make_client()
    run_id = _new_run(client, owner)
    parent_id, outcome_fields, _source_ids = _add_meselson_stahl_fixture(
        run_id, db_path
    )
    parent = Hypothesis(
        id=parent_id,
        text=MESELSON_STAHL_PARENT_TEXT,
        title="Semiconservative DNA replication in E. coli",
        origin=HypothesisOrigin.GENERATION,
    )
    _save_engine_checkpoint(run_id, parent, db_path)
    store.update_run_status(run_id, RunStatus.COMPLETED, db_path=db_path)
    headers = {
        **_signed_headers(owner),
        "Idempotency-Key": "campaign-robin",
    }
    recorded = client.post(
        f"/api/runs/{run_id}/hypotheses/{parent_id}/outcomes",
        headers=headers,
        json=outcome_fields,
    )
    assert recorded.status_code == 201
    response = client.post(
        f"/api/runs/{run_id}/hypotheses/{parent_id}/outcomes/"
        f"{recorded.json()['id']}/refine",
        headers=headers,
    )
    assert response.status_code == 202

    task = store.claim_task("campaign-robin", run_id=run_id, db_path=db_path)
    assert task is not None
    assert task.task_type == "engine.outcome.refinement"
    return client, task


def test_campaign_robin_refinement_uses_persisted_model(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        settings, "campaign_researcher_ids", {"refinement-owner"}
    )
    client, task = _campaign_refinement_task(isolated_db)
    run = store.get_run(task.run_id, db_path=isolated_db)
    assert run is not None
    assert run.execution_policy == "campaign"
    assert run.config["campaign_model_name"] == (
        "openrouter/stealth/space-bunny-alpha"
    )
    seen: list[str] = []

    async def evolve_stub(
        parent: Hypothesis,
        context: Any,
        outcome_context: str,
        validation_hypotheses: list[Hypothesis],
    ) -> tuple[None, None]:
        seen.append(context.model_name)
        return None, None

    monkeypatch.setattr(
        evolution,
        "evolve_single_hypothesis_from_outcome",
        evolve_stub,
    )
    result = asyncio.run(
        task_worker._execute_task_payload(task, db_path=isolated_db)
    )

    assert result["status"] == "no_child"
    assert seen == ["openrouter/stealth/space-bunny-alpha"]
    client.close()
