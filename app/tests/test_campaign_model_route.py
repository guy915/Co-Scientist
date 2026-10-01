"""Campaign model selection stays scoped to persisted campaign work."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, ClassVar, cast

import pytest
from co_scientist.checkpoint import serialize_workflow_state
from co_scientist.llm import current_api_key
from fastapi import Request

from app import (
    credentials,
    engine_tasks,
    execution_policy,
    llm_request,
    offline_guard,
    safety,
    store,
)
from app.claims import grounding as claim_grounding
from app.config import settings
from app.engine_adapter.checkpoints import restore_workflow_state
from app.engine_adapter.drain import claim_grounding as drain_claim_grounding
from app.engine_adapter.opts import build_generator
from app.engine_tasks import gate as engine_tasks_gate
from app.execution_policy import (
    CAMPAIGN,
    CAMPAIGN_MODEL_NAME,
    STANDARD,
    scoped_execution_policy,
)
from app.interviews import model as interviews_model
from app.qa import stream as qa_stream
from app.runs import crud_create as runs_crud_create
from app.runs.crud_resolve import _ResolvedRunSettings
from app.runs.models import CreateRunRequest
from app.store import RunCreateOptions, ScientificTask
from tests._process_mode_helpers import FakeProcessMode


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


def _task(run_id: str) -> ScientificTask:
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
        _task(campaign.id), db_path=isolated_db
    )
    await engine_tasks.execute_engine_task(
        _task(standard.id), db_path=isolated_db
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
    await engine_tasks.execute_engine_task(_task(run.id), db_path=isolated_db)

    assert seen == {
        "credential": byok,
        "api_key": byok.api_key,
        "models": (
            "legacy/checkpoint-model",
            "legacy/checkpoint-supervisor",
        ),
    }
