"""Campaign policy survives public creation and durable task recovery."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from co_scientist.exceptions import FreeModelEligibilityError
from co_scientist.llm_credentials import current_api_key

from app import (
    auth,
    credentials,
    engine_tasks,
    llm_request,
    runs_crud,
    store,
    task_worker,
)
from app.config import BYOK_PROVIDER_DEFAULT_MODELS, settings
from tests._client import make_client

_PAID_MODEL = "openrouter/campaign/paid"
_PAID_KEY = "paid-test-key"


def _paid_catalog() -> dict[str, Any]:
    return {
        "campaign/paid": {
            "pricing": {
                "prompt": "0.01",
                "completion": "0.02",
                "request": "0.03",
                "internal_reasoning": "0.04",
                "input_cache_read": "0.05",
                "input_cache_write": "0.06",
            },
            "architecture": {
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
        }
    }


def _transport_spy(sent: list[dict[str, Any]]) -> Any:
    async def transport(**kwargs: Any) -> Any:
        sent.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
        )

    return transport


async def _no_background_model(*_args: Any, **_kwargs: Any) -> None:
    return None


def _expire_claimed_task(run_id: str, db_path: str) -> str:
    task = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type="engine.node.generate",
            inputs={},
            idempotency_key=f"recovered-admission:{run_id}",
        ),
        db_path=db_path,
    )
    claimed = store.claim_task(f"dead-{run_id}", run_id=run_id, db_path=db_path)
    assert claimed is not None
    with store.connect(db_path) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET lease_expires_at=0 WHERE id=?",
            (task.id,),
        )
    return task.id


def _dispatch_spy(outcomes: dict[str, str]) -> Any:
    async def dispatch(
        task: store.ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        credential = credentials.current_byok()
        if credential is None:
            assert current_api_key() is None
            outcomes[task.run_id] = "blocked"
            return {"admission": "blocked"}
        assert credential is not None
        assert current_api_key() == credential.api_key
        try:
            await llm_request.acompletion(
                model=credential.model,
                api_key=credential.api_key,
                messages=[{"role": "user", "content": "recover"}],
                max_tokens=1,
            )
        except FreeModelEligibilityError as exc:
            assert "zero-cost route has paid or invalid pricing" in str(exc)
            outcomes[task.run_id] = "blocked"
        else:
            outcomes[task.run_id] = "sent"
        return {"admission": outcomes[task.run_id]}

    return dispatch


def _assert_completed(task_id: str, expected: str, db_path: str) -> None:
    saved = store.get_task(task_id, db_path=db_path)
    assert saved is not None
    assert saved.status == "completed"
    assert saved.attempt == 2
    assert saved.result == {"admission": expected}


async def test_recovered_campaign_blocks_paid_transport_while_byok_runs(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Persisted policy, not current identity config, controls recovery."""
    import litellm
    from co_scientist import llm_free_catalog

    monkeypatch.setattr(settings, "auth_secret", "campaign-test-secret")
    monkeypatch.setattr(settings, "campaign_researcher_ids", {"campaign-user"})
    monkeypatch.setattr(settings, "byok_encryption_key", "encrypt-test-secret")
    monkeypatch.setitem(BYOK_PROVIDER_DEFAULT_MODELS, "openrouter", _PAID_MODEL)
    monkeypatch.setattr(llm_free_catalog, "_snapshot", None)
    monkeypatch.setattr(
        llm_free_catalog,
        "_fetch_catalog",
        _paid_catalog,
    )
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(litellm, "acompletion", _transport_spy(sent))
    monkeypatch.setattr(runs_crud, "_populate_run_title", _no_background_model)
    monkeypatch.setattr(
        runs_crud, "_populate_goal_restatement", _no_background_model
    )

    token = auth.create_session_token("campaign-user")
    campaign_response = make_client().post(
        "/api/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"research_goal": "Public campaign recovery"},
    )
    assert campaign_response.status_code == 200, campaign_response.text
    campaign_id = campaign_response.json()["id"]
    assert campaign_response.json()["execution_policy"] == "campaign"
    campaign_run = store.get_run(campaign_id, db_path=isolated_db)
    assert campaign_run is not None
    assert campaign_run.config["campaign_model_name"] == (
        "openrouter/stealth/space-bunny-alpha"
    )

    ordinary_response = make_client().post(
        "/api/runs",
        headers={
            "X-Client-ID": "ordinary-user",
            "X-LLM-Provider": "openrouter",
            "X-LLM-API-Key": _PAID_KEY,
        },
        json={"research_goal": "Ordinary BYOK recovery"},
    )
    assert ordinary_response.status_code == 200, ordinary_response.text
    ordinary_id = ordinary_response.json()["id"]
    assert ordinary_response.json()["execution_policy"] == "standard"
    assert [call["api_key"] for call in sent] == [_PAID_KEY]
    sent.clear()

    stale_paid = credentials.ByokCredential(
        "openrouter", _PAID_KEY, _PAID_MODEL
    )
    credentials.store_run_credential(
        campaign_id, "campaign-user", stale_paid, isolated_db
    )

    campaign_task = _expire_claimed_task(campaign_id, isolated_db)
    ordinary_task = _expire_claimed_task(ordinary_id, isolated_db)

    # Recovery must trust the stored marker after identity configuration and
    # process-local database initialization have both changed.
    monkeypatch.setattr(settings, "campaign_researcher_ids", set())
    from app.store import db as store_db

    store_db._initialized.discard(isolated_db)
    outcomes: dict[str, str] = {}
    monkeypatch.setattr(
        engine_tasks, "_dispatch_engine_task", _dispatch_spy(outcomes)
    )

    assert await task_worker.run_once(
        "recovery-campaign", run_id=campaign_id, db_path=isolated_db
    )
    assert sent == []
    assert await task_worker.run_once(
        "recovery-ordinary", run_id=ordinary_id, db_path=isolated_db
    )

    assert outcomes == {campaign_id: "blocked", ordinary_id: "sent"}
    assert len(sent) == 1
    assert sent[0]["model"] == _PAID_MODEL
    assert sent[0]["api_key"] == _PAID_KEY
    _assert_completed(campaign_task, "blocked", isolated_db)
    _assert_completed(ordinary_task, "sent", isolated_db)
    assert credentials.current_byok() is None
    assert current_api_key() is None


async def test_recovered_new_campaign_sends_zero_price_stealth_request(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import litellm
    from co_scientist import llm_free_catalog
    from co_scientist.llm import CompletionSpec, LLMCallOptions, call_llm

    from app.execution_policy import effective_execution_model

    monkeypatch.setattr(settings, "auth_secret", "campaign-test-secret")
    monkeypatch.setattr(settings, "campaign_researcher_ids", {"campaign-user"})
    monkeypatch.setattr(runs_crud, "_populate_run_title", _no_background_model)
    monkeypatch.setattr(
        runs_crud, "_populate_goal_restatement", _no_background_model
    )
    monkeypatch.setattr(llm_free_catalog, "_snapshot", None)
    monkeypatch.setattr(
        llm_free_catalog,
        "_fetch_catalog",
        lambda: {
            "stealth/space-bunny-alpha": {
                "pricing": {"prompt": "0", "completion": "0"},
                "architecture": {
                    "input_modalities": ["text"],
                    "output_modalities": ["text"],
                },
            }
        },
    )
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(litellm, "acompletion", _transport_spy(sent))

    token = auth.create_session_token("campaign-user")
    response = make_client().post(
        "/api/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"research_goal": "Public campaign recovery"},
    )
    assert response.status_code == 200, response.text
    run_id = response.json()["id"]
    run = store.get_run(run_id, db_path=isolated_db)
    assert run is not None
    assert run.config["campaign_model_name"] == (
        "openrouter/stealth/space-bunny-alpha"
    )
    task_id = _expire_claimed_task(run_id, isolated_db)

    async def dispatch(
        task: store.ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        model = effective_execution_model("configured/worker-role")
        assert model == "openrouter/stealth/space-bunny-alpha"
        await call_llm(
            "Return a brief readiness acknowledgement.",
            CompletionSpec(model_name=model, max_tokens=1),
            options=LLMCallOptions(use_cache=False, enable_thinking=False),
        )
        return {"admission": "campaign recovery"}

    monkeypatch.setattr(engine_tasks, "_dispatch_engine_task", dispatch)
    monkeypatch.setattr(settings, "campaign_researcher_ids", set())
    assert await task_worker.run_once(
        "campaign-recovery", run_id=run_id, db_path=isolated_db
    )

    assert len(sent) == 1
    assert sent[0]["model"] == "openrouter/stealth/space-bunny-alpha"
    assert sent[0]["extra_body"]["provider"]["max_price"] == {
        "prompt": 0,
        "completion": 0,
        "request": 0,
    }
    assert sent[0]["extra_body"]["provider"]["only"] == ["Stealth"]
    assert sent[0]["extra_body"]["provider"]["allow_fallbacks"] is False
    _assert_completed(task_id, "campaign recovery", isolated_db)
