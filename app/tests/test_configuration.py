"""Tests for configuration."""

from __future__ import annotations

import pathlib
import tempfile
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any, ClassVar, cast

import pytest
from co_scientist.cache import _resolve_cache_env
from co_scientist.checkpoint import serialize_workflow_state
from co_scientist.constants import MODEL_PRICING
from co_scientist.exceptions import FreeModelEligibilityError
from co_scientist.llm import campaign_free_mode, current_api_key
from fastapi import HTTPException, Request
from pydantic import ValidationError

import app.engine_adapter.drain.final_state as drain_claim_grounding
import app.interviews.turns as interview_support
import app.qa as qa_stream
import app.runs.crud as runs_crud_create
from app import (
    auth,
    credentials,
    engine_adapter,
    engine_tasks,
    execution_policy,
    human_input,
    llm_request,
    offline_guard,
    process_mode,
    qa,
    run_start_announcement,
    safety,
    store,
    task_worker,
)
from app.claims import grounding as claim_grounding
from app.config import (
    BYOK_PROVIDER_DEFAULT_MODELS,
    Settings,
    deepseek_non_thinking_extra_body,
    deepseek_thinking_kwargs,
    settings,
    thinking_off_kwargs,
)
from app.engine_adapter import provider, restore_workflow_state
from app.engine_adapter.opts import build_generator
from app.engine_tasks import gate as engine_tasks_gate
from app.execution_policy import (
    CAMPAIGN,
    CAMPAIGN_MODEL_NAME,
    STANDARD,
    scoped_execution_policy,
)
from app.interviews import model as interviews_model
from app.interviews import stream as interviews_stream
from app.interviews import turns as interview_turns
from app.runs import chat as runs_chat
from app.runs import contrib as runs_contrib
from app.runs import crud as runs_crud
from app.runs.crud import _ResolvedRunSettings
from app.runs.models import CreateRunRequest, HumanHypothesisRequest
from app.store import RunCreateOptions, ScientificTask
from tests._client import make_client
from tests._interviews_helpers import (
    InterviewFields,
    _interview_payload,
    _patch_model_sequence,
    _response,
)
from tests._llm_fake_backend import install_completion_backend
from tests._process_mode_helpers import FakeProcessMode

# The suite must not share the working directory's LLM cache.
#
# Caching is on by default and its directory resolves relative to the working
# directory, so a suite run from ``app/`` would write into ``app/cache`` --
# shared with every previous run, with local development, and gitignored, so
# nothing surfaces it. The engine consults that cache *before* the offline
# router, which makes it a correctness problem: a test can be served a
# response another run recorded under different code.


def test_the_suite_resolves_its_own_cache_directory() -> None:
    """The resolved cache directory is a throwaway, not the repo's own.

    Pins the placement as much as the value: the assignment has to happen
    before ``app.config`` is imported, because ``Settings()`` reads the
    environment at that module's import time and ``app.main`` bridges what
    it captured back. Moving the two lines below the import leaves the
    default in place and fails here.
    """
    _, cache_dir, _ = _resolve_cache_env()
    resolved = pathlib.Path(cache_dir).resolve()

    assert resolved.is_relative_to(
        pathlib.Path(tempfile.gettempdir()).resolve()
    ), resolved
    assert not resolved.is_relative_to(pathlib.Path.cwd()), resolved


# Campaign model selection stays scoped to persisted campaign work.


def _cfg() -> dict[str, Any]:
    return {
        "max_iterations": 1,
        "initial_hypotheses_count": 4,
        "evolution_max_count": 4,
        "tournament_pairs": 6,
        "evidence_count": 4,
        "k_factor": 36,
        "max_llm_calls": 100,
        "max_ideas": 12,
        "max_matches_per_idea": 4,
    }


class _Generator:
    last_kwargs: ClassVar[dict[str, Any]] = {}

    def __init__(self, **kwargs: Any) -> None:
        _Generator.last_kwargs = kwargs


def _route_task(run_id: str) -> ScientificTask:
    return ScientificTask(
        id=f"task-{run_id}",
        run_id=run_id,
        task_type="engine.node.generate",
        status="leased",
        priority=90,
        inputs={},
        dependencies=(),
        provenance={},
        idempotency_key=f"generate:{run_id}",
        budget={},
        attempt=1,
        max_attempts=3,
        lease_owner="test",
        lease_expires_at=None,
        result=None,
        error=None,
        created_at=0.0,
        updated_at=0.0,
        started_at=None,
        completed_at=None,
    )


def _request() -> Request:
    return Request({"type": "http", "headers": [(b"x-client-id", b"owner")]})


def _callbacks(policy: str) -> runs_crud_create.RunCreationCallbacks:
    async def no_byok(*_args: Any) -> None:
        return None

    def resolve_settings(*_args: Any) -> _ResolvedRunSettings:
        return _ResolvedRunSettings(
            config={"setup": {"goal": "study"}},
            # Express: a keyless real run outside it is refused as free
            # usage before the campaign route is reached.
            run_mode="express",
            provider="engine",
            focus="balance",
            llm_backend="real",
        )

    return cast(
        runs_crud_create.RunCreationCallbacks,
        SimpleNamespace(
            resolve_run_interview=lambda *_args: (None, _args[0]),
            resolve_execution_policy=lambda *_args: policy,
            scoped_execution_policy=scoped_execution_policy,
            resolve_byok=no_byok,
            run_setup_documents=lambda *_args: [],
            resolve_run_settings=resolve_settings,
        ),
    )


async def test_campaign_run_saves_route_and_standard_does_not() -> None:
    request = _request()
    campaign = await runs_crud_create._resolve_setup(
        CreateRunRequest(research_goal="study"),
        request,
        "owner",
        _callbacks(CAMPAIGN),
    )
    standard = await runs_crud_create._resolve_setup(
        CreateRunRequest(research_goal="study"),
        request,
        "owner",
        _callbacks(STANDARD),
    )

    assert campaign.settings.config["campaign_model_name"] == (
        "openrouter/stealth/space-bunny-alpha"
    )
    assert "campaign_model_name" not in standard.settings.config


def _install_stream_capture(
    monkeypatch: pytest.MonkeyPatch, models: list[str]
) -> None:
    async def request(**kwargs: Any) -> object:
        models.append(kwargs["model"])
        return object()

    async def chunks(*_args: Any, **_kwargs: Any) -> Any:
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content="A response.", reasoning_content=""
                    )
                )
            ]
        )

    monkeypatch.setattr(
        interviews_model,
        "_interview_request",
        lambda _: ("configured-chat-role", []),
    )
    monkeypatch.setattr(interviews_model, "stream_chunks", chunks)
    monkeypatch.setattr(offline_guard, "require_remote_chat", lambda *_: None)
    monkeypatch.setattr(qa_stream, "stream_chunks", chunks)
    monkeypatch.setattr(llm_request, "acompletion", request)


async def test_campaign_interview_request_uses_selected_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models: list[str] = []
    _install_stream_capture(monkeypatch, models)

    async def turn() -> None:
        await interviews_model._stream_interview_content(
            {"fields": {}, "turns": []}, interviews_model.TurnSinks()
        )

    with scoped_execution_policy(
        CAMPAIGN, campaign_model_name=CAMPAIGN_MODEL_NAME
    ):
        await turn()
    with scoped_execution_policy(STANDARD):
        await turn()

    assert models == [
        "openrouter/stealth/space-bunny-alpha",
        "configured-chat-role",
    ]


async def test_campaign_chat_request_uses_selected_model_and_keeps_standard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models: list[str] = []
    _install_stream_capture(monkeypatch, models)

    with scoped_execution_policy(
        CAMPAIGN, campaign_model_name=CAMPAIGN_MODEL_NAME
    ):
        async for _ in qa_stream.stream_llm_deltas(
            "configured-chat-role", "system", "question", []
        ):
            pass
    with scoped_execution_policy(STANDARD):
        async for _ in qa_stream.stream_llm_deltas(
            "configured-chat-role", "system", "question", []
        ):
            pass

    assert models == [
        "openrouter/stealth/space-bunny-alpha",
        "configured-chat-role",
    ]


def test_generator_uses_campaign_worker_and_supervisor_and_isolates_standard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = "configured/worker-role"
    supervisor = "configured/supervisor-role"
    monkeypatch.setattr(settings, "model_name", worker)
    monkeypatch.setattr(settings, "supervisor_model_name", supervisor)

    with scoped_execution_policy(
        CAMPAIGN, campaign_model_name=CAMPAIGN_MODEL_NAME
    ):
        build_generator(_Generator, _cfg())
    campaign = _Generator.last_kwargs
    assert campaign["model_name"] == "openrouter/stealth/space-bunny-alpha"
    assert (
        campaign["options"].supervisor_model_name
        == "openrouter/stealth/space-bunny-alpha"
    )

    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    with scoped_execution_policy(STANDARD):
        build_generator(_Generator, _cfg())
    standard = _Generator.last_kwargs
    assert standard["model_name"] == worker
    assert standard["options"].supervisor_model_name == supervisor


async def test_semantic_safety_selects_campaign_before_credential_check(
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    models: list[tuple[str, str]] = []
    monkeypatch.setattr(settings, "semantic_safety_enabled", True)
    monkeypatch.setattr(settings, "semantic_safety_model", "configured/safety")
    monkeypatch.setattr(
        settings, "supervisor_model_name", "configured/supervisor"
    )
    monkeypatch.setattr(settings, "model_name", "configured/worker")

    def credential_available(model: str) -> bool:
        models.append(("credential", model))
        return True

    async def assess(text: str, stage: str, model: str) -> Any:
        models.append(("request", model))
        return safety.screen_intake(text)

    fake_process_mode.online(credential=credential_available)
    monkeypatch.setattr(safety, "run_semantic_safety_model", assess)

    with scoped_execution_policy(
        CAMPAIGN, campaign_model_name=CAMPAIGN_MODEL_NAME
    ):
        await safety.screen_contextual("A benign research goal.", "intake")
    with scoped_execution_policy(STANDARD):
        await safety.screen_contextual("A benign research goal.", "intake")

    assert models == [
        ("credential", "openrouter/stealth/space-bunny-alpha"),
        ("request", "openrouter/stealth/space-bunny-alpha"),
        ("credential", "configured/safety"),
        ("request", "configured/safety"),
    ]


async def test_claim_gate_and_finalize_grounding_use_campaign_assessor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models: list[str] = []
    monkeypatch.setattr(settings, "claim_assessor", "llm")
    monkeypatch.setattr(settings, "claim_verifier_model", "configured/claims")

    def build(_mode: str, model: str) -> tuple[Any, str]:
        models.append(model)
        return object(), f"llm:{model}"

    def build_batch(_mode: str, model: str, **_kwargs: Any) -> Any:
        models.append(model)
        return object()

    async def no_gate_assessment(*_args: Any) -> list[list[Any]]:
        return []

    def no_grounding_assessment(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(claim_grounding, "build_assessor", build)
    monkeypatch.setattr(claim_grounding, "build_batch_assessor", build_batch)
    monkeypatch.setattr(
        engine_tasks_gate, "_build_evidence_passages", lambda _: []
    )
    monkeypatch.setattr(
        engine_tasks_gate, "_assess_gate_claims", no_gate_assessment
    )
    monkeypatch.setattr(drain_claim_grounding, "build_assessor", build)
    monkeypatch.setattr(
        drain_claim_grounding, "build_batch_assessor", build_batch
    )
    monkeypatch.setattr(
        drain_claim_grounding,
        "assess_hypothesis_claims",
        no_grounding_assessment,
    )

    with scoped_execution_policy(
        CAMPAIGN, campaign_model_name=CAMPAIGN_MODEL_NAME
    ):
        await engine_tasks_gate._apply_pre_ranking_evidence_gate(
            {"hypotheses": []}
        )
        await drain_claim_grounding._assess_claims([], [])
    with scoped_execution_policy(STANDARD):
        await engine_tasks_gate._apply_pre_ranking_evidence_gate(
            {"hypotheses": []}
        )
        await drain_claim_grounding._assess_claims([], [])

    assert models == [
        "openrouter/stealth/space-bunny-alpha",
        "openrouter/stealth/space-bunny-alpha",
        "openrouter/stealth/space-bunny-alpha",
        "openrouter/stealth/space-bunny-alpha",
        "configured/claims",
        "configured/claims",
        "configured/claims",
        "configured/claims",
    ]


async def test_recovery_restores_saved_campaign_model_and_leaves_standard_state(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved_model = "openrouter/stealth/space-bunny-alpha"
    campaign = store.create_run(
        "Campaign goal",
        "standard",
        "engine",
        {"campaign_model_name": saved_model},
        RunCreateOptions(
            client_id="campaign-owner",
            execution_policy=CAMPAIGN,
            llm_backend="real",
            db_path=isolated_db,
        ),
    )
    standard = store.create_run(
        "Standard goal",
        "standard",
        "engine",
        {},
        RunCreateOptions(
            client_id="standard-owner",
            execution_policy=STANDARD,
            llm_backend="real",
            db_path=isolated_db,
        ),
    )
    monkeypatch.setattr(
        execution_policy, "CAMPAIGN_MODEL_NAME", "openrouter/stealth/next"
    )
    checkpoint = serialize_workflow_state(
        {
            "hypotheses": [],
            "model_name": "stale/checkpoint-model",
            "supervisor_model_name": "stale/checkpoint-supervisor",
        },
        last_event_seq=0,
    )
    restored: dict[str, tuple[str, str]] = {}

    async def dispatch(
        task: ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        state = restore_workflow_state(checkpoint)
        restored[task.run_id] = (
            state["model_name"],
            state["supervisor_model_name"],
        )
        return {"ok": True}

    monkeypatch.setattr(engine_tasks, "_dispatch_engine_task", dispatch)
    await engine_tasks.execute_engine_task(
        _route_task(campaign.id), db_path=isolated_db
    )
    await engine_tasks.execute_engine_task(
        _route_task(standard.id), db_path=isolated_db
    )

    assert restored == {
        campaign.id: (saved_model, saved_model),
        standard.id: (
            "stale/checkpoint-model",
            "stale/checkpoint-supervisor",
        ),
    }


async def test_legacy_campaign_recovery_keeps_checkpoint_route_and_byok(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "byok_encryption_key", "test-encryption-key")
    run = store.create_run(
        "Legacy campaign goal",
        "standard",
        "engine",
        {},
        RunCreateOptions(
            client_id="legacy-campaign-owner",
            execution_policy=CAMPAIGN,
            llm_backend="real",
            db_path=isolated_db,
        ),
    )
    byok = credentials.ByokCredential(
        "openrouter", "legacy-key", "openrouter/campaign/legacy-free"
    )
    credentials.store_run_credential(
        run.id, "legacy-campaign-owner", byok, isolated_db
    )
    checkpoint = serialize_workflow_state(
        {
            "hypotheses": [],
            "model_name": "legacy/checkpoint-model",
            "supervisor_model_name": "legacy/checkpoint-supervisor",
        },
        last_event_seq=0,
    )
    seen: dict[str, Any] = {}

    async def dispatch(
        task: ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        seen["credential"] = credentials.current_byok()
        seen["api_key"] = current_api_key()
        state = restore_workflow_state(checkpoint)
        seen["models"] = (
            state["model_name"],
            state["supervisor_model_name"],
        )
        return {"ok": True}

    monkeypatch.setattr(engine_tasks, "_dispatch_engine_task", dispatch)
    await engine_tasks.execute_engine_task(
        _route_task(run.id), db_path=isolated_db
    )

    assert seen == {
        "credential": byok,
        "api_key": byok.api_key,
        "models": (
            "legacy/checkpoint-model",
            "legacy/checkpoint-supervisor",
        ),
    }


# Campaign policy survives public creation and durable task recovery.


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
    from co_scientist.llm.admission import free_policy as free_catalog

    monkeypatch.setattr(settings, "auth_secret", "campaign-test-secret")
    monkeypatch.setattr(settings, "campaign_researcher_ids", {"campaign-user"})
    monkeypatch.setattr(settings, "byok_encryption_key", "encrypt-test-secret")
    monkeypatch.setitem(BYOK_PROVIDER_DEFAULT_MODELS, "openrouter", _PAID_MODEL)
    free_catalog.install_catalog_reader(
        free_catalog.CatalogReader(_paid_catalog)
    )
    sent: list[dict[str, Any]] = []
    install_completion_backend(monkeypatch, _transport_spy(sent))
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
    from co_scientist.llm import CompletionSpec, LLMCallOptions, call_llm
    from co_scientist.llm.admission import free_policy as free_catalog

    from app.execution_policy import effective_execution_model

    monkeypatch.setattr(settings, "auth_secret", "campaign-test-secret")
    monkeypatch.setattr(settings, "campaign_researcher_ids", {"campaign-user"})
    monkeypatch.setattr(runs_crud, "_populate_run_title", _no_background_model)
    monkeypatch.setattr(
        runs_crud, "_populate_goal_restatement", _no_background_model
    )
    free_catalog.install_catalog_reader(
        free_catalog.CatalogReader(
            lambda: {
                "stealth/space-bunny-alpha": {
                    "pricing": {"prompt": "0", "completion": "0"},
                    "architecture": {
                        "input_modalities": ["text"],
                        "output_modalities": ["text"],
                    },
                }
            }
        )
    )
    sent: list[dict[str, Any]] = []
    install_completion_backend(monkeypatch, _transport_spy(sent))

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


# Server-derived campaign policy persistence for interviews and runs.


def _campaign_headers(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setattr(settings, "auth_secret", "campaign-test-secret")
    monkeypatch.setattr(settings, "campaign_researcher_ids", {"researcher-a"})
    token = auth.create_session_token("researcher-a")
    return {"Authorization": f"Bearer {token}"}


def test_campaign_researcher_setting_normalizes_and_rejects_empty_ids() -> None:
    configured = Settings(
        _env_file=None,
        campaign_researcher_ids={" researcher-a ", "researcher-b"},
    )
    assert configured.campaign_researcher_ids == {
        "researcher-a",
        "researcher-b",
    }

    with pytest.raises(ValidationError):
        Settings(_env_file=None, campaign_researcher_ids={"researcher-a", " "})


def test_legacy_rows_migrate_to_standard_policy(isolated_db: str) -> None:
    """Rows created before the policy columns retain ordinary behavior."""
    run = store.create_run(
        "Legacy run",
        "standard",
        "mock",
        {},
        store.RunCreateOptions(client_id="legacy", db_path=isolated_db),
    )
    interview = store.create_interview(
        "legacy", "Legacy interview", db_path=isolated_db
    )

    from app.store.db import _run_migrations

    with store.connect(isolated_db) as conn:
        conn.execute("ALTER TABLE runs DROP COLUMN execution_policy")
        conn.execute("ALTER TABLE interviews DROP COLUMN execution_policy")
        _run_migrations(conn)

    migrated_run = store.get_run(run.id, db_path=isolated_db)
    migrated_interview = store.get_interview(
        interview["id"], db_path=isolated_db
    )
    assert migrated_run is not None
    assert migrated_run.execution_policy == "standard"
    assert migrated_interview is not None
    assert migrated_interview["execution_policy"] == "standard"


def test_campaign_interview_survives_restart_and_cannot_downgrade_linked_run(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The campaign marker survives allowlist removal and a fresh connection."""
    headers = _campaign_headers(monkeypatch)
    _patch_model_sequence(
        monkeypatch,
        [_response("What should the study prioritize?")],
    )
    client = make_client()

    created = client.post(
        "/api/interviews",
        headers=headers,
        json={"research_challenge": "Map treatment resistance"},
    )
    interview = _interview_payload(created)
    assert interview["execution_policy"] == "campaign"

    store.update_interview(
        interview["id"],
        {
            **interview["fields"],
            "title": "Treatment resistance",
        },
        None,
        completed=True,
    )
    monkeypatch.setattr(settings, "campaign_researcher_ids", set())

    # A fresh connection/process initialization must read the durable marker,
    # not re-derive it from the now-changed deployment allowlist.
    from app.store import db as store_db

    store_db._initialized.discard(isolated_db)
    resumed = make_client().get(
        f"/api/interviews/{interview['id']}", headers=headers
    )
    assert resumed.json()["execution_policy"] == "campaign"

    run = make_client().post(
        "/api/runs",
        headers=headers,
        json={
            "research_goal": "client placeholder",
            "interview_id": interview["id"],
            "execution_policy": "standard",
        },
    )
    assert run.status_code == 200
    assert run.json()["execution_policy"] == "campaign"
    stored_run = store.get_run(run.json()["id"])
    assert stored_run is not None
    assert stored_run.execution_policy == "campaign"


def test_unsigned_identity_and_body_cannot_originate_campaign(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Compatibility identity and body policy fields remain standard."""
    monkeypatch.setattr(settings, "campaign_researcher_ids", {"researcher-a"})
    _patch_model_sequence(
        monkeypatch,
        [_response("What should the study prioritize?", InterviewFields())],
    )
    headers = {"X-Client-ID": "researcher-a"}
    client = make_client()

    interview_response = client.post(
        "/api/interviews",
        headers=headers,
        json={
            "research_challenge": "Map treatment resistance",
            "execution_policy": "campaign",
        },
    )
    interview = _interview_payload(interview_response)
    assert interview["execution_policy"] == "standard"

    run = client.post(
        "/api/runs",
        headers=headers,
        json={
            "research_goal": "Map treatment resistance",
            "execution_policy": "campaign",
        },
    )
    assert run.status_code == 200
    assert run.json()["execution_policy"] == "standard"


async def test_campaign_run_rejects_byok_before_transport(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A campaign request never probes a caller-supplied paid credential."""
    headers = {
        **_campaign_headers(monkeypatch),
        "X-LLM-Provider": "openai",
        "X-LLM-API-Key": "paid-key",
    }
    monkeypatch.setattr(settings, "byok_encryption_key", "encrypt-test")
    called = False

    async def _unexpected_validation(
        _credential: credentials.ByokCredential,
    ) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(
        credentials, "validate_byok_credential", _unexpected_validation
    )

    interview_response = make_client().post(
        "/api/interviews",
        headers=headers,
        json={"research_challenge": "Map treatment resistance"},
    )
    assert interview_response.status_code == 400
    assert "campaign" in interview_response.json()["detail"].lower()
    assert store.list_interviews("researcher-a") == []

    response = make_client().post(
        "/api/runs",
        headers=headers,
        json={"research_goal": "Map treatment resistance"},
    )

    assert response.status_code == 400
    assert "campaign" in response.json()["detail"].lower()
    assert called is False
    assert store.list_runs(client_id="researcher-a") == []


# Persisted campaign policy reaches every app-side model boundary.


def _run(policy: str, *, owner: str = "owner") -> store.RunRow:
    return store.create_run(
        f"{policy} research",
        "standard",
        "engine",
        {},
        store.RunCreateOptions(
            client_id=owner,
            execution_policy=policy,
            llm_backend="real",
        ),
    )


def _scope_task(run_id: str) -> store.ScientificTask:
    return store.ScientificTask(
        id=f"task-{run_id}",
        run_id=run_id,
        task_type="engine.node.generate",
        status="leased",
        priority=90,
        inputs={},
        dependencies=(),
        provenance={},
        idempotency_key=f"generate:{run_id}",
        budget={},
        attempt=1,
        max_attempts=3,
        lease_owner="test",
        lease_expires_at=None,
        result=None,
        error=None,
        created_at=0.0,
        updated_at=0.0,
        started_at=None,
        completed_at=None,
    )


def _paid_request() -> Request:
    return Request(
        {
            "type": "http",
            "headers": [
                (b"x-client-id", b"owner"),
                (b"x-llm-provider", b"openai"),
                (b"x-llm-api-key", b"paid-key"),
            ],
        }
    )


def test_persisted_campaign_rejects_late_byok_before_streaming() -> None:
    campaign = _run("campaign")

    with pytest.raises(HTTPException, match="campaign"):
        interview_support.request_byok(_paid_request(), "campaign")
    with pytest.raises(HTTPException, match="campaign"):
        runs_chat._resolve_qa_byok(campaign, _paid_request())

    standard = _run("standard")
    credential = runs_chat._resolve_qa_byok(standard, _paid_request())
    assert credential is not None
    assert credential.api_key == "paid-key"


async def test_interview_stream_loads_its_persisted_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    interview = store.create_interview(
        "owner", "Campaign interview", execution_policy="campaign"
    )
    seen: list[bool] = []

    async def advance(
        interview_id: str, _reasoning: Any = None, _prose: Any = None
    ) -> dict[str, Any]:
        seen.append(campaign_free_mode())
        saved = store.get_interview(interview_id)
        assert saved is not None
        return saved

    monkeypatch.setattr(interview_turns, "advance_turn", advance)
    list_items = [
        frame
        async for frame in interviews_stream._advance_stream(interview["id"])
    ]

    assert list_items
    assert seen == [True]
    assert campaign_free_mode() is False


async def test_detached_run_generators_reload_policy_and_stay_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    campaign = _run("campaign")
    standard = _run("standard")
    seen: dict[str, bool] = {}

    async def title(goal: str) -> str:
        seen[goal] = campaign_free_mode()
        return goal

    async def restatement(goal: str) -> str:
        seen[f"restatement:{goal}"] = campaign_free_mode()
        return goal

    monkeypatch.setattr(runs_crud, "generate_run_title", title)
    monkeypatch.setattr(runs_crud, "generate_goal_restatement", restatement)

    await runs_crud._populate_run_title(
        campaign.id,
        campaign.research_goal,
        execution_policy=campaign.execution_policy,
    )
    await runs_crud._populate_goal_restatement(
        standard.id,
        standard.research_goal,
        execution_policy=standard.execution_policy,
    )

    assert seen[campaign.research_goal] is True
    assert seen[f"restatement:{standard.research_goal}"] is False
    assert campaign_free_mode() is False


async def test_detached_run_generators_keep_trusted_policy_after_deletion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    campaign = _run("campaign")
    seen: list[tuple[str, bool]] = []

    async def title(_goal: str) -> str:
        seen.append(("title", campaign_free_mode()))
        return "title"

    async def restatement(_goal: str) -> str:
        seen.append(("restatement", campaign_free_mode()))
        return "restatement"

    monkeypatch.setattr(runs_crud, "generate_run_title", title)
    monkeypatch.setattr(runs_crud, "generate_goal_restatement", restatement)
    store.delete_run(campaign.id)

    await runs_crud._populate_run_title(
        campaign.id,
        campaign.research_goal,
        execution_policy=campaign.execution_policy,
    )
    await runs_crud._populate_goal_restatement(
        campaign.id,
        campaign.research_goal,
        execution_policy=campaign.execution_policy,
    )

    assert seen == [("title", True), ("restatement", True)]
    assert campaign_free_mode() is False


async def test_run_streams_use_policy_captured_at_response_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    campaign = _run("campaign")
    seen: list[tuple[str, bool]] = []

    async def deltas(*_args: Any, **_kwargs: Any) -> AsyncIterator[Any]:
        seen.append(("qa", campaign_free_mode()))
        yield ("chunk", "answer")

    async def fragments(
        _run_row: store.RunRow, *, thinking_enabled: bool = True
    ) -> AsyncIterator[tuple[str, str]]:
        seen.append(("announcement", campaign_free_mode()))
        yield ("chunk", "started")

    monkeypatch.setattr(qa, "stream_llm_deltas", deltas)
    monkeypatch.setattr(qa, "_persist_qa_answer", lambda *_args: None)
    monkeypatch.setattr(
        run_start_announcement, "_stream_model_fragments", fragments
    )
    monkeypatch.setattr(
        run_start_announcement,
        "_persist_announcement",
        lambda *_args: None,
    )

    answer = qa.stream_answer(
        campaign.id,
        qa.QaQuestion(text="question", message_id=1),
        qa.QaAnswerInputs("system", []),
    )
    async for _ in answer:
        pass
    announcement = run_start_announcement.stream_announcement(campaign, 1)
    async for _ in announcement:
        pass

    assert seen == [("qa", True), ("announcement", True)]
    assert campaign_free_mode() is False


async def test_interview_stream_keeps_trusted_policy_after_deletion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    interview = store.create_interview(
        "owner", "Campaign interview", execution_policy="campaign"
    )
    seen: list[bool] = []

    async def advance(
        _interview_id: str, _reasoning: Any = None, _prose: Any = None
    ) -> dict[str, Any]:
        seen.append(campaign_free_mode())
        return interview

    monkeypatch.setattr(interview_turns, "advance_turn", advance)
    interview_stream = interviews_stream._advance_stream(
        str(interview["id"]), execution_policy="campaign"
    )
    store.delete_interview(str(interview["id"]))

    async for _ in interview_stream:
        pass

    assert seen == [True]
    assert campaign_free_mode() is False


async def test_qa_stream_keeps_trusted_policy_after_deletion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    campaign = _run("campaign")
    seen: list[bool] = []

    async def deltas(*_args: Any, **_kwargs: Any) -> AsyncIterator[Any]:
        seen.append(campaign_free_mode())
        yield ("chunk", "answer")

    monkeypatch.setattr(qa, "stream_llm_deltas", deltas)
    monkeypatch.setattr(qa, "_persist_qa_answer", lambda *_args: None)
    answer_stream = qa.stream_answer(
        campaign.id,
        qa.QaQuestion(text="question", message_id=1),
        qa.QaAnswerInputs("system", []),
        execution_policy=campaign.execution_policy,
    )
    store.delete_run(campaign.id)

    async for _ in answer_stream:
        pass

    assert seen == [True]
    assert campaign_free_mode() is False


async def test_announcement_keeps_trusted_policy_after_deletion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    campaign = _run("campaign")
    seen: list[bool] = []

    async def fragments(
        _run_row: store.RunRow, *, thinking_enabled: bool = True
    ) -> AsyncIterator[tuple[str, str]]:
        seen.append(campaign_free_mode())
        yield ("chunk", "started")

    monkeypatch.setattr(
        run_start_announcement, "_stream_model_fragments", fragments
    )
    monkeypatch.setattr(
        run_start_announcement,
        "_persist_announcement",
        lambda *_args: None,
    )
    announcement_stream = run_start_announcement.stream_announcement(
        campaign, 1
    )
    store.delete_run(campaign.id)

    async for _ in announcement_stream:
        pass

    assert seen == [True]
    assert campaign_free_mode() is False


async def test_durable_dispatch_reloads_policy_for_recovery_and_resets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    campaign = _run("campaign")
    standard = _run("standard")
    seen: dict[str, bool] = {}

    async def dispatch(
        task: store.ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        seen[task.run_id] = campaign_free_mode()
        return {"ok": True}

    monkeypatch.setattr(engine_tasks, "_dispatch_engine_task", dispatch)
    await engine_tasks.execute_engine_task(_scope_task(campaign.id))
    await engine_tasks.execute_engine_task(_scope_task(standard.id))

    assert seen == {campaign.id: True, standard.id: False}
    assert campaign_free_mode() is False


async def test_durable_dispatch_aborts_when_run_was_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    campaign = _run("campaign")
    dispatched = False

    async def dispatch(
        _task_row: store.ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        nonlocal dispatched
        dispatched = True
        return {"ok": True}

    monkeypatch.setattr(engine_tasks, "_dispatch_engine_task", dispatch)
    store.delete_run(campaign.id)

    with pytest.raises(LookupError, match="run not found for task dispatch"):
        await engine_tasks.execute_engine_task(_scope_task(campaign.id))

    assert dispatched is False


async def test_contribution_safety_uses_persisted_run_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    campaign = _run("campaign")
    seen: list[bool] = []

    async def admit(**kwargs: Any) -> human_input.HumanHypothesisAdmission:
        seen.append(campaign_free_mode())
        return human_input.admit_human_hypothesis(
            text=kwargs["text"],
            author=kwargs["author"],
            title=kwargs.get("title", ""),
        )

    monkeypatch.setattr(
        human_input, "admit_human_hypothesis_with_escalation", admit
    )
    request = Request({"type": "http", "headers": [(b"x-client-id", b"owner")]})

    response = await runs_contrib.add_human_hypothesis(
        campaign.id,
        HumanHypothesisRequest(statement="A benign hypothesis", author="owner"),
        request,
    )

    assert response["admitted"] is True
    assert seen == [True]
    assert campaign_free_mode() is False


# The models this deployment defaults to must be ones the engine prices.
#
# An unpriced model is not a cosmetic gap. ``estimate_cost_usd`` returns 0.0
# for a model absent from ``MODEL_PRICING``, so every run reports a cost of
# zero -- and, on an OpenRouter route,
# ``llm.request.thinking._gateway_provider``
# derives its ``max_price`` ceiling from the same table and simply omits the
# cap when there is no entry, which lets a call land on the most expensive
# host serving that model. Both failures are silent, which is why the
# pairing is asserted rather than left to the pricing table's comment.


_MODEL_FIELDS = (
    "model_name",
    "supervisor_model_name",
    "chat_model_name",
    "semantic_safety_model",
)
_SYSTEM_DEFAULT_MODEL = "openrouter/stealth/space-bunny-alpha"


def _default_models() -> set[str]:
    """Every model name this deployment ships as a tier's default.

    Read off the field declarations rather than the live ``settings``
    object: a developer's own ``.env`` overrides those at import time, and
    a check that passes only because the local environment names a priced
    model is not checking the shipped default at all.
    """
    return {
        default
        for field in _MODEL_FIELDS
        if isinstance(default := Settings.model_fields[field].default, str)
    }


def test_all_system_default_roles_select_space_bunny() -> None:
    """Worker, supervisor, chat and semantic safety share the selected model."""
    actual = {
        field: Settings.model_fields[field].default for field in _MODEL_FIELDS
    }

    assert actual == dict.fromkeys(_MODEL_FIELDS, _SYSTEM_DEFAULT_MODEL)
    assert Settings.model_fields["claim_verifier_model"].default is None


def test_every_default_model_is_priced() -> None:
    """Each tier's default model carries a rate in the engine's table."""
    unpriced = sorted(_default_models() - set(MODEL_PRICING))

    assert not unpriced, (
        f"default models missing from MODEL_PRICING: {unpriced}"
    )


def test_every_byok_default_model_is_priced() -> None:
    """A bring-your-own-key run is priced the same way a house run is."""
    unpriced = sorted(
        set(BYOK_PROVIDER_DEFAULT_MODELS.values()) - set(MODEL_PRICING)
    )

    assert not unpriced, f"BYOK models missing from MODEL_PRICING: {unpriced}"


# Tests for the DeepSeek thinking-mode helpers in ``app.config``.
#
# The two helpers translate the thinking toggle into DeepSeek's request
# params: a ``thinking`` object plus ``reasoning_effort``. Getting the
# format wrong is silent rather than an error, so the shape is pinned here.
# Every app call site thinks now, titling included; the opt-out
# (``deepseek_non_thinking_extra_body``) has no live caller but stays
# covered here as a tested seam -- see its docstring.


def test_thinking_kwargs_native_deepseek() -> None:
    """Native DeepSeek gets the thinking object at low reasoning effort."""
    kwargs = deepseek_thinking_kwargs("deepseek/deepseek-v4-pro")

    assert kwargs == {
        "extra_body": {"thinking": {"type": "enabled"}},
        "reasoning_effort": "high",
    }


def test_thinking_kwargs_empty_for_other_models() -> None:
    """Non-DeepSeek models carry no thinking params at all."""
    assert deepseek_thinking_kwargs("gemini/gemini-2.5-flash") == {}


def test_non_thinking_body_native_deepseek() -> None:
    """The opt-out disables thinking explicitly on the native API."""
    body = deepseek_non_thinking_extra_body("deepseek/deepseek-v4-flash")

    assert body == {"thinking": {"type": "disabled"}}


def test_non_thinking_body_empty_for_other_models() -> None:
    """Non-DeepSeek models carry no thinking params at all."""
    assert deepseek_non_thinking_extra_body("gpt-4o-mini") == {}


# --- thinking token floor ----------------------------------------------------


def test_thinking_floor_raises_an_answer_sized_budget() -> None:
    """A DeepSeek budget sized for the answer alone is lifted to the floor.

    The provider counts reasoning against ``max_tokens``, so an answer-sized
    budget lets a long chain of thought return empty content -- billed in
    full, and for the claim verifier indistinguishable from "the LLM
    assessor never wins".
    """
    from app.config import THINKING_FLOOR_MAX_TOKENS, thinking_safe_max_tokens

    assert (
        thinking_safe_max_tokens("deepseek/deepseek-v4-flash", 3_000)
        == THINKING_FLOOR_MAX_TOKENS
    )


def test_thinking_floor_never_lowers_a_larger_budget() -> None:
    """The floor only raises; a call site asking for more keeps its number."""
    from app.config import THINKING_FLOOR_MAX_TOKENS, thinking_safe_max_tokens

    above = THINKING_FLOOR_MAX_TOKENS + 5_000

    assert thinking_safe_max_tokens("deepseek/deepseek-v4-pro", above) == above


def test_thinking_floor_leaves_non_deepseek_budgets_alone() -> None:
    """Models without a thinking mode spend the whole budget on the answer."""
    from app.config import thinking_safe_max_tokens

    assert thinking_safe_max_tokens("gemini/gemini-2.5-flash", 3_000) == 3_000


# --- thinking timeout floor --------------------------------------------------


def test_thinking_timeout_floor_raises_an_answer_sized_deadline() -> None:
    """A deadline sized for the answer alone is lifted to the floor.

    Funding the chain of thought without extending the clock only moves the
    failure: the call is cut off mid-reasoning instead of returning empty,
    and both land in the same silent fallback.
    """
    from app.config import THINKING_FLOOR_TIMEOUT_SECONDS, thinking_safe_timeout

    assert (
        thinking_safe_timeout("deepseek/deepseek-v4-flash", 20.0)
        == THINKING_FLOOR_TIMEOUT_SECONDS
    )


def test_thinking_timeout_floor_never_lowers_a_longer_deadline() -> None:
    """The floor only raises; a call site allowing more keeps its number."""
    from app.config import THINKING_FLOOR_TIMEOUT_SECONDS, thinking_safe_timeout

    above = THINKING_FLOOR_TIMEOUT_SECONDS + 120.0

    assert thinking_safe_timeout("deepseek/deepseek-v4-pro", above) == above


def test_thinking_timeout_floor_leaves_non_deepseek_deadlines_alone() -> None:
    """Models without a thinking mode keep their own, tighter deadline."""
    from app.config import thinking_safe_timeout

    assert thinking_safe_timeout("gemini/gemini-2.5-flash", 20.0) == 20.0


def test_thinking_timeout_floor_admits_the_token_floor() -> None:
    """The clock must allow the token budget it is paired with to arrive.

    The two ceilings are one setting in two places. Pinning the relationship
    here is what stops a later tightening of the deadline from silently
    re-breaking every call the token floor was raised to fix.
    """
    from app.config import (
        THINKING_FLOOR_MAX_TOKENS,
        THINKING_FLOOR_TIMEOUT_SECONDS,
    )

    pessimistic_tokens_per_second = 75.0

    assert (
        THINKING_FLOOR_MAX_TOKENS / pessimistic_tokens_per_second
        <= THINKING_FLOOR_TIMEOUT_SECONDS
    )


def test_the_thinking_knob_is_the_engine_s_to_choose() -> None:
    """One place decides how a route expresses thinking, not two.

    The app and the engine both send thinking parameters, and the shape
    depends on the route rather than on the model: a gateway normalizes
    reasoning into its own parameter and ignores DeepSeek's. Two copies
    of that rule is one more thing to keep in step, and the copy that
    gets forgotten sends a disable that reads as an enable -- which
    costs a whole token budget and returns nothing.
    """
    from app.config import (
        deepseek_non_thinking_extra_body,
        deepseek_thinking_kwargs,
    )

    routed = "openrouter/deepseek/deepseek-v4-flash"
    direct = "deepseek/deepseek-v4-flash"

    # The price ceiling is the engine's too: a gateway spreads one model
    # over hosts differing 6.5x in price, and neither the host ordering
    # nor the throughput floor considers price at all. Restating any of
    # it here would be the second copy this test exists to prevent.
    #
    # `order` replaced `sort: throughput` after the latter was measured
    # scattering consecutive calls across upstreams and collapsing the
    # prompt-cache hit rate to 6.9% (against 33.7% for the month) on the
    # run of 2026-09-04; `preferred_min_throughput` keeps the slow-host
    # protection `sort` used to provide. Full rationale lives with the
    # engine's own copy in test_llm_wrappers_thinking.py.
    gateway = {
        "require_parameters": True,
        "allow_fallbacks": True,
        "preferred_min_throughput": 25,
        "order": ["z-ai", "deepinfra", "novita", "gmicloud"],
        "max_price": {"prompt": 0.083 * 1.05, "completion": 0.165 * 1.05},
    }

    assert deepseek_non_thinking_extra_body(routed) == {
        "reasoning": {"enabled": False},
        "provider": gateway,
    }
    assert deepseek_non_thinking_extra_body(direct) == {
        "thinking": {"type": "disabled"}
    }
    assert deepseek_thinking_kwargs(routed)["extra_body"] == {
        "reasoning": {"enabled": True, "effort": "high"},
        "provider": gateway,
    }
    assert deepseek_non_thinking_extra_body("gemini/gemini-2.5-flash") == {}
    assert deepseek_thinking_kwargs("gemini/gemini-2.5-flash") == {}

    # The tier is stated once, in the shape the route understands. A
    # top-level ``reasoning_effort`` beside the gateway's own ``reasoning``
    # object is the copy litellm refuses (``UnsupportedParamsError``) for a
    # model its OpenRouter support map does not list -- and these app call
    # sites reach litellm directly, without the ``drop_params`` every engine
    # call carries. It parked runs at the contextual safety screen.
    assert "reasoning_effort" not in deepseek_thinking_kwargs(routed)
    assert deepseek_thinking_kwargs(direct)["reasoning_effort"] == "high"


# --- per-surface effort override, and the thinking-off retry rung -----------


def test_effort_override_replaces_the_gateway_s_nested_tier() -> None:
    """A gateway route carries the tier nested in ``extra_body["reasoning"]``.

    The interview and chat turns pass a lower tier for exactly this route
    shape (see ``app.config.CONVERSATIONAL_REASONING_EFFORT``).
    """
    routed = "openrouter/deepseek/deepseek-v4-flash"

    kwargs = deepseek_thinking_kwargs(routed, effort="medium")

    assert kwargs["extra_body"]["reasoning"]["effort"] == "medium"


def test_effort_override_replaces_the_direct_route_s_top_level_tier() -> None:
    """A direct, non-gateway route carries the tier as a top-level kwarg."""
    direct = "deepseek/deepseek-v4-flash"

    kwargs = deepseek_thinking_kwargs(direct, effort="medium")

    assert kwargs["reasoning_effort"] == "medium"


def test_effort_override_is_a_no_op_for_a_model_with_no_thinking_mode() -> None:
    """Nothing to override on a model that carries no thinking params."""
    assert (
        deepseek_thinking_kwargs("gemini/gemini-2.5-flash", effort="low") == {}
    )


def test_omitted_effort_keeps_the_engine_s_high_floor() -> None:
    """No override argument means no change to the existing behavior."""
    direct = "deepseek/deepseek-v4-flash"

    assert (
        deepseek_thinking_kwargs(direct)["reasoning_effort"]
        == deepseek_thinking_kwargs(direct, effort=None)["reasoning_effort"]
        == "high"
    )


def test_thinking_off_kwargs_wraps_the_disable_body_for_a_completion_call() -> (
    None
):
    """The rung a thinking-only stream is retried at.

    ``deepseek_non_thinking_extra_body`` returns the bare disable knob;
    this wraps it the way every call site actually spreads kwargs, so a
    caller cannot forget the ``extra_body`` wrapper one of the two shapes
    needs.
    """
    assert thinking_off_kwargs("deepseek/deepseek-v4-flash") == {
        "extra_body": {"thinking": {"type": "disabled"}}
    }
    assert thinking_off_kwargs("gemini/gemini-2.5-flash") == {}


# The process-mode seam: one installed adapter answers every reader.
#
# The behaviour the adapters implement is pinned elsewhere, through the
# environment (``test_provider_selection.py`` for the offline truth table,
# ``test_safety_process_modes.py`` for the fail-closed screen). These cases pin
# the seam itself: that installing an adapter reaches every consumer, which is
# what lets a test state a process fact once instead of patching each module
# that happens to read it.


def test_one_adapter_answers_every_offline_reader(
    fake_process_mode: FakeProcessMode,
) -> None:
    """Online reaches the re-exports, the run-backend rule, the chat guard."""
    fake_process_mode.online()

    assert process_mode.offline_mode() is False
    assert engine_adapter.offline_mode() is False
    assert provider.offline_mode() is False
    assert provider.resolve_offline_backend({}) is False
    assert offline_guard.remote_chat_allowed() is True

    fake_process_mode.offline = True

    assert process_mode.offline_mode() is True
    assert engine_adapter.offline_mode() is True
    assert provider.offline_mode() is True
    assert provider.resolve_offline_backend({}) is True
    assert offline_guard.remote_chat_allowed() is False


def test_a_credential_callable_is_asked_per_model(
    fake_process_mode: FakeProcessMode,
) -> None:
    """A test can vary the answer by model, and see which models were asked."""
    asked: list[str] = []

    def credentialed(model: str) -> bool:
        asked.append(model)
        return model.startswith("openrouter/")

    fake_process_mode.online(credential=credentialed)

    assert process_mode.credential_available("openrouter/x") is True
    assert process_mode.credential_available("anthropic/y") is False
    assert asked == ["openrouter/x", "anthropic/y"]


def test_install_returns_the_replaced_adapter_so_it_can_be_restored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Restoring what ``install`` returned puts the env-derived answer back."""
    monkeypatch.setenv("COSCIENTIST_FORCE_OFFLINE", "1")
    fake = FakeProcessMode()
    fake.online()

    previous = process_mode.install(fake)
    try:
        assert isinstance(previous, process_mode.EnvProcessMode)
        assert process_mode.offline_mode() is False
    finally:
        process_mode.install(previous)

    assert process_mode.offline_mode() is True
