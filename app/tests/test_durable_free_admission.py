"""Durable workers reload credentials and preserve campaign admission."""

import asyncio
from functools import partial
from typing import Any

import pytest
from co_scientist.exceptions import FreeModelEligibilityError
from co_scientist.llm import current_api_key

from app import async_bridge, credentials, engine_tasks, store, task_worker
from app.config import settings

from ._llm_fake_backend import install_completion_backend


@pytest.mark.parametrize("mode", ["blocked_paid", "campaign_free", "user_byok"])
@pytest.mark.parametrize("recovered", [False, True])
@pytest.mark.parametrize("auxiliary", ["claim", "batch", "safety"])
async def test_durable_auxiliary_admission_with_stored_credential(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    recovered: bool,
    auxiliary: str,
    mode: str,
) -> None:
    from co_scientist.llm.admission import free_catalog

    from app import safety_semantic
    from app.claims import verifier as claim_verifier
    from app.claims import verifier_batch as claim_verifier_batch

    monkeypatch.setattr(settings, "byok_encryption_key", "campaign-test-secret")
    monkeypatch.delenv("COSCIENTIST_REQUIRE_FREE_MODELS", raising=False)
    monkeypatch.setattr(free_catalog, "_snapshot", None)
    monkeypatch.setattr(
        free_catalog,
        "_fetch_catalog",
        lambda: {
            "campaign/free:free": {
                "pricing": {"prompt": "0", "completion": "0"},
                "architecture": {
                    "input_modalities": ["text"],
                    "output_modalities": ["text"],
                },
            }
        },
    )
    run = store.create_run(
        "public research",
        "standard",
        "engine",
        {},
        store.RunCreateOptions(
            execution_policy=("standard" if mode == "user_byok" else "campaign")
        ),
    )
    credential = credentials.ByokCredential(
        "openrouter",
        "stored-test-key",
        "openrouter/campaign/free:free"
        if mode == "campaign_free"
        else "openrouter/campaign/paid",
    )
    credentials.store_run_credential(
        run.id, "test-owner", credential, isolated_db
    )
    task = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type="engine.node.generate",
            inputs={},
            idempotency_key="campaign-check",
        ),
        db_path=isolated_db,
    )
    if recovered:
        claimed = store.claim_task(
            "lost-worker", run_id=run.id, db_path=isolated_db
        )
        assert claimed is not None
        with store.connect(isolated_db) as conn:
            conn.execute(
                "UPDATE scientific_tasks SET lease_expires_at=0 WHERE id=?",
                (task.id,),
            )

    sent: list[dict[str, Any]] = []

    async def transport(**kwargs: Any) -> Any:
        sent.append(kwargs)
        raise FreeModelEligibilityError("test transport reached")

    install_completion_backend(monkeypatch, transport)

    calls = {
        "claim": partial(
            claim_verifier._call_llm_entailment_async, "deployment", "claim", []
        ),
        "batch": partial(
            claim_verifier_batch._call_llm_batch_entailment_async,
            "deployment",
            ["claim"],
            [],
        ),
        "safety": partial(
            safety_semantic._call_semantic_safety_model,
            "public goal",
            "intake",
            "deployment",
        ),
    }

    async def assess() -> None:
        assert current_api_key() == credential.api_key
        assert credentials.current_byok() == credential
        with pytest.raises(FreeModelEligibilityError):
            await calls[auxiliary]()

    async def dispatch(
        task: store.ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        await asyncio.create_task(assess())
        await async_bridge.run_off_loop(
            lambda: async_bridge.run_coroutine_sync(assess)
        )
        return {"checked": auxiliary}

    monkeypatch.setattr(engine_tasks, "_dispatch_engine_task", dispatch)
    assert credentials.current_byok() is None
    assert current_api_key() is None
    assert await task_worker.run_once(
        "fresh-worker", run_id=run.id, db_path=isolated_db
    )
    saved = store.get_task(task.id, db_path=isolated_db)
    assert saved is not None and saved.status == "completed"
    assert saved.result == {"checked": auxiliary}
    assert saved.attempt == (2 if recovered else 1)
    assert len(sent) == (0 if mode == "blocked_paid" else 2)
    _assert_requests(sent, credential, mode)
    assert credentials.current_byok() is None
    assert current_api_key() is None


def _assert_requests(
    sent: list[dict[str, Any]],
    credential: credentials.ByokCredential,
    mode: str,
) -> None:
    for request in sent:
        assert request["api_key"] == credential.api_key
        assert request["model"] == credential.model
        if mode == "campaign_free":
            assert request["extra_body"]["provider"]["max_price"] == {
                "prompt": 0,
                "completion": 0,
                "request": 0,
            }
        else:
            assert request.get("extra_body", {}).get("provider", {}).get(
                "max_price"
            ) != {"prompt": 0, "completion": 0, "request": 0}
