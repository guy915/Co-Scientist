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
from app.engine_adapter import restore_workflow_state
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
from app.store import db, interviews, runs, tasks
from app.store import runs_views as views
from app.store.models import RunRow, ScientificTask
from app.store.runs import RunCreateOptions
from tests._client import create_run as _create_run
from tests._client import make_client
from tests._engine_tasks_helpers import small_run_config as _cfg
from tests._interviews_helpers import (
    InterviewFields,
    _interview_payload,
    _patch_model_sequence,
    _response,
)
from tests._llm_fake_backend import (
    completion_response,
    install_completion_backend,
)
from tests._process_mode_helpers import FakeProcessMode
from tests._store_helpers import enqueue_task, seed_run

# Shared response caches can replay earlier-code results before the offline
# router.


def test_the_suite_resolves_its_own_cache_directory() -> None:
    # Cache placement precedes Settings import or environment bridging
    # overwrites the isolated directory.
    _, cache_dir, _ = _resolve_cache_env()
    resolved = pathlib.Path(cache_dir).resolve()

    assert resolved.is_relative_to(
        pathlib.Path(tempfile.gettempdir()).resolve()
    ), resolved
    assert not resolved.is_relative_to(pathlib.Path.cwd()), resolved


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
        "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free"
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
        "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free",
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
        "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free",
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
    assert (
        campaign["model_name"]
        == "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free"
    )
    assert (
        campaign["options"].supervisor_model_name
        == "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free"
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
        ("credential", "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free"),
        ("request", "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free"),
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
        "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free",
        "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free",
        "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free",
        "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free",
        "configured/claims",
        "configured/claims",
        "configured/claims",
        "configured/claims",
    ]


async def test_recovery_restores_saved_campaign_model_and_leaves_standard_state(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved_model = "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free"
    campaign = seed_run(
        "Campaign goal",
        config={"campaign_model_name": saved_model},
        options=RunCreateOptions(
            client_id="campaign-owner",
            execution_policy=CAMPAIGN,
            llm_backend="real",
            db_path=isolated_db,
        ),
    )
    standard = seed_run(
        "Standard goal",
        options=RunCreateOptions(
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
    run = seed_run(
        "Legacy campaign goal",
        options=RunCreateOptions(
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
        return completion_response("ok")

    return transport


async def _no_background_model(*_args: Any, **_kwargs: Any) -> None:
    return None


def _expire_claimed_task(run_id: str, db_path: str) -> str:
    task = enqueue_task(
        run_id,
        "engine.node.generate",
        f"recovered-admission:{run_id}",
        db_path=db_path,
    )
    claimed = tasks.claim_task(f"dead-{run_id}", run_id=run_id, db_path=db_path)
    assert claimed is not None
    with db.connect(db_path) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET lease_expires_at=0 WHERE id=?",
            (task.id,),
        )
    return task.id


def _dispatch_spy(outcomes: dict[str, str]) -> Any:
    async def dispatch(
        task: ScientificTask, *, db_path: str | None = None
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
    saved = tasks.get_task(task_id, db_path=db_path)
    assert saved is not None
    assert saved.status == "completed"
    assert saved.attempt == 2
    assert saved.result == {"admission": expected}


async def test_recovered_campaign_blocks_paid_transport_while_byok_runs(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    campaign_response = _create_run(
        make_client(),
        "Public campaign recovery",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert campaign_response.status_code == 200, campaign_response.text
    campaign_id = campaign_response.json()["id"]
    assert campaign_response.json()["execution_policy"] == "campaign"
    campaign_run = runs.get_run(campaign_id, db_path=isolated_db)
    assert campaign_run is not None
    assert campaign_run.config["campaign_model_name"] == (
        "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free"
    )

    ordinary_response = _create_run(
        make_client(),
        "Ordinary BYOK recovery",
        headers={
            "X-Client-ID": "ordinary-user",
            "X-LLM-Provider": "openrouter",
            "X-LLM-API-Key": _PAID_KEY,
        },
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


async def test_recovered_new_campaign_sends_zero_price_request(
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
                model: {
                    "pricing": {"prompt": "0", "completion": "0"},
                    "architecture": {
                        "input_modalities": ["text"],
                        "output_modalities": ["text"],
                    },
                }
                for model in (
                    "nvidia/nemotron-3-ultra-550b-a55b:free",
                    "dots-studio/dots-3-note-preview:free",
                    "nvidia/nemotron-3-super-120b-a12b:free",
                )
            }
        )
    )
    sent: list[dict[str, Any]] = []
    install_completion_backend(monkeypatch, _transport_spy(sent))

    token = auth.create_session_token("campaign-user")
    response = _create_run(
        make_client(),
        "Public campaign recovery",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    run_id = response.json()["id"]
    run = runs.get_run(run_id, db_path=isolated_db)
    assert run is not None
    assert run.config["campaign_model_name"] == (
        "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free"
    )
    task_id = _expire_claimed_task(run_id, isolated_db)

    async def dispatch(
        task: ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        model = effective_execution_model("configured/worker-role")
        assert model == "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free"
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
    assert (
        sent[0]["model"] == "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free"
    )
    assert sent[0]["extra_body"]["provider"]["max_price"] == {
        "prompt": 0,
        "completion": 0,
        "request": 0,
    }
    _assert_completed(task_id, "campaign recovery", isolated_db)


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


def test_campaign_interview_survives_restart_and_cannot_downgrade_linked_run(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
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

    interviews.update_interview(
        interview["id"],
        {
            **interview["fields"],
            "title": "Treatment resistance",
        },
        None,
        completed=True,
    )
    monkeypatch.setattr(settings, "campaign_researcher_ids", set())

    from app.store import db as store_db

    store_db._initialized.discard(isolated_db)
    resumed = make_client().get(
        f"/api/interviews/{interview['id']}", headers=headers
    )
    assert resumed.json()["execution_policy"] == "campaign"

    run = _create_run(
        make_client(),
        "client placeholder",
        headers=headers,
        interview_id=interview["id"],
        execution_policy="standard",
    )
    assert run.status_code == 200
    assert run.json()["execution_policy"] == "campaign"
    stored_run = runs.get_run(run.json()["id"])
    assert stored_run is not None
    assert stored_run.execution_policy == "campaign"


def test_unsigned_identity_and_body_cannot_originate_campaign(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
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

    run = _create_run(
        client,
        "Map treatment resistance",
        headers=headers,
        execution_policy="campaign",
    )
    assert run.status_code == 200
    assert run.json()["execution_policy"] == "standard"


async def test_campaign_run_rejects_byok_before_transport(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    assert interviews.list_interviews("researcher-a") == []

    response = _create_run(
        make_client(), "Map treatment resistance", headers=headers
    )

    assert response.status_code == 400
    assert "campaign" in response.json()["detail"].lower()
    assert called is False
    assert views.list_runs(client_id="researcher-a") == []


def _run(policy: str, *, owner: str = "owner") -> RunRow:
    return seed_run(
        f"{policy} research",
        options=RunCreateOptions(
            client_id=owner,
            execution_policy=policy,
            llm_backend="real",
        ),
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
    interview = interviews.create_interview(
        "owner", "Campaign interview", execution_policy="campaign"
    )
    seen: list[bool] = []

    async def advance(
        interview_id: str, _reasoning: Any = None, _prose: Any = None
    ) -> dict[str, Any]:
        seen.append(campaign_free_mode())
        saved = interviews.get_interview(interview_id)
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
    runs.delete_run(campaign.id)

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
        _run_row: RunRow, *, thinking_enabled: bool = True
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
    interview = interviews.create_interview(
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
    interviews.delete_interview(str(interview["id"]))

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
    runs.delete_run(campaign.id)

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
        _run_row: RunRow, *, thinking_enabled: bool = True
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
    runs.delete_run(campaign.id)

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
        task: ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        seen[task.run_id] = campaign_free_mode()
        return {"ok": True}

    monkeypatch.setattr(engine_tasks, "_dispatch_engine_task", dispatch)
    await engine_tasks.execute_engine_task(_route_task(campaign.id))
    await engine_tasks.execute_engine_task(_route_task(standard.id))

    assert seen == {campaign.id: True, standard.id: False}
    assert campaign_free_mode() is False


async def test_durable_dispatch_aborts_when_run_was_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    campaign = _run("campaign")
    dispatched = False

    async def dispatch(
        _task_row: ScientificTask, *, db_path: str | None = None
    ) -> dict[str, Any]:
        nonlocal dispatched
        dispatched = True
        return {"ok": True}

    monkeypatch.setattr(engine_tasks, "_dispatch_engine_task", dispatch)
    runs.delete_run(campaign.id)

    with pytest.raises(LookupError, match="run not found for task dispatch"):
        await engine_tasks.execute_engine_task(_route_task(campaign.id))

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


# Unknown model pricing silently reports zero spend and removes gateway price
# caps.


_MODEL_FIELDS = (
    "model_name",
    "supervisor_model_name",
    "chat_model_name",
    "semantic_safety_model",
)
_SYSTEM_DEFAULT_MODEL = "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free"


def _default_models() -> set[str]:
    # Inspect shipped field defaults rather than dotenv-overridden live
    # settings.
    return {
        default
        for field in _MODEL_FIELDS
        if isinstance(default := Settings.model_fields[field].default, str)
    }


def test_all_system_default_roles_select_nemotron_ultra() -> None:
    actual = {
        field: Settings.model_fields[field].default for field in _MODEL_FIELDS
    }

    assert actual == dict.fromkeys(_MODEL_FIELDS, _SYSTEM_DEFAULT_MODEL)
    assert Settings.model_fields["claim_verifier_model"].default is None


def test_every_default_model_is_priced() -> None:
    unpriced = sorted(_default_models() - set(MODEL_PRICING))

    assert not unpriced, (
        f"default models missing from MODEL_PRICING: {unpriced}"
    )


def test_every_byok_default_model_is_priced() -> None:
    unpriced = sorted(
        set(BYOK_PROVIDER_DEFAULT_MODELS.values()) - set(MODEL_PRICING)
    )

    assert not unpriced, f"BYOK models missing from MODEL_PRICING: {unpriced}"


def test_thinking_kwargs_native_deepseek() -> None:
    kwargs = deepseek_thinking_kwargs("deepseek/deepseek-v4-pro")

    assert kwargs == {
        "extra_body": {"thinking": {"type": "enabled"}},
        "reasoning_effort": "high",
    }


def test_thinking_kwargs_empty_for_other_models() -> None:
    assert deepseek_thinking_kwargs("gemini/gemini-2.5-flash") == {}


def test_non_thinking_body_native_deepseek() -> None:
    body = deepseek_non_thinking_extra_body("deepseek/deepseek-v4-flash")

    assert body == {"thinking": {"type": "disabled"}}


def test_non_thinking_body_empty_for_other_models() -> None:
    assert deepseek_non_thinking_extra_body("gpt-4o-mini") == {}


def test_thinking_floor_raises_an_answer_sized_budget() -> None:
    # Reasoning counts toward output budget; answer-only budgets can return
    # empty content at full cost.
    from app.config import THINKING_FLOOR_MAX_TOKENS, thinking_safe_max_tokens

    assert (
        thinking_safe_max_tokens("deepseek/deepseek-v4-flash", 3_000)
        == THINKING_FLOOR_MAX_TOKENS
    )


def test_thinking_floor_never_lowers_a_larger_budget() -> None:
    from app.config import THINKING_FLOOR_MAX_TOKENS, thinking_safe_max_tokens

    above = THINKING_FLOOR_MAX_TOKENS + 5_000

    assert thinking_safe_max_tokens("deepseek/deepseek-v4-pro", above) == above


def test_thinking_floor_leaves_non_deepseek_budgets_alone() -> None:
    from app.config import thinking_safe_max_tokens

    assert thinking_safe_max_tokens("gemini/gemini-2.5-flash", 3_000) == 3_000


def test_thinking_timeout_floor_raises_an_answer_sized_deadline() -> None:
    # Token floors require enough deadline for reasoning or calls merely fail
    # later in the same fallback.
    from app.config import THINKING_FLOOR_TIMEOUT_SECONDS, thinking_safe_timeout

    assert (
        thinking_safe_timeout("deepseek/deepseek-v4-flash", 20.0)
        == THINKING_FLOOR_TIMEOUT_SECONDS
    )


def test_thinking_timeout_floor_never_lowers_a_longer_deadline() -> None:
    from app.config import THINKING_FLOOR_TIMEOUT_SECONDS, thinking_safe_timeout

    above = THINKING_FLOOR_TIMEOUT_SECONDS + 120.0

    assert thinking_safe_timeout("deepseek/deepseek-v4-pro", above) == above


def test_thinking_timeout_floor_leaves_non_deepseek_deadlines_alone() -> None:
    from app.config import thinking_safe_timeout

    assert thinking_safe_timeout("gemini/gemini-2.5-flash", 20.0) == 20.0


def test_thinking_timeout_floor_admits_the_token_floor() -> None:
    # Token and time ceilings must remain compatible; tuning one can silently
    # break the other.
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
    # Thinking wire shapes depend on routes; duplicated shaping can turn a
    # requested disable into enable.
    from app.config import (
        deepseek_non_thinking_extra_body,
        deepseek_thinking_kwargs,
    )

    routed = "openrouter/deepseek/deepseek-v4-flash"
    direct = "deepseek/deepseek-v4-flash"

    # Stable provider ordering preserves prompt caches; price caps remain
    # engine-owned across differently priced hosts.
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

    # Duplicate top-level and gateway reasoning parameters can fail before
    # contextual safety runs.
    assert "reasoning_effort" not in deepseek_thinking_kwargs(routed)
    assert deepseek_thinking_kwargs(direct)["reasoning_effort"] == "high"


def test_effort_override_replaces_the_gateway_s_nested_tier() -> None:
    routed = "openrouter/deepseek/deepseek-v4-flash"

    kwargs = deepseek_thinking_kwargs(routed, effort="medium")

    assert kwargs["extra_body"]["reasoning"]["effort"] == "medium"


def test_effort_override_replaces_the_direct_route_s_top_level_tier() -> None:
    direct = "deepseek/deepseek-v4-flash"

    kwargs = deepseek_thinking_kwargs(direct, effort="medium")

    assert kwargs["reasoning_effort"] == "medium"


def test_effort_override_is_a_no_op_for_a_model_with_no_thinking_mode() -> None:
    assert (
        deepseek_thinking_kwargs("gemini/gemini-2.5-flash", effort="low") == {}
    )


def test_omitted_effort_keeps_the_engine_s_high_floor() -> None:
    direct = "deepseek/deepseek-v4-flash"

    assert (
        deepseek_thinking_kwargs(direct)["reasoning_effort"]
        == deepseek_thinking_kwargs(direct, effort=None)["reasoning_effort"]
        == "high"
    )


def test_thinking_off_kwargs_wraps_the_disable_body_for_a_completion_call() -> (
    None
):
    assert thinking_off_kwargs("deepseek/deepseek-v4-flash") == {
        "extra_body": {"thinking": {"type": "disabled"}}
    }
    assert thinking_off_kwargs("gemini/gemini-2.5-flash") == {}


def test_one_adapter_answers_every_offline_reader(
    fake_process_mode: FakeProcessMode,
) -> None:
    fake_process_mode.online()

    assert process_mode.offline_mode() is False
    assert engine_adapter.offline_mode() is False
    assert engine_adapter.resolve_offline_backend({}) is False
    assert offline_guard.remote_chat_allowed() is True

    fake_process_mode.offline = True

    assert process_mode.offline_mode() is True
    assert engine_adapter.offline_mode() is True
    assert engine_adapter.resolve_offline_backend({}) is True
    assert offline_guard.remote_chat_allowed() is False


def test_a_credential_callable_is_asked_per_model(
    fake_process_mode: FakeProcessMode,
) -> None:
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
