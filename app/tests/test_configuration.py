from __future__ import annotations

import pathlib
import tempfile
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from co_scientist.cache import _resolve_cache_env
from co_scientist.constants import MODEL_PRICING
from co_scientist.exceptions import FreeModelEligibilityError
from co_scientist.llm import campaign_free_mode, current_api_key
from fastapi import Request
from pydantic import ValidationError

import app.qa as qa_stream
from app import (
    auth,
    credentials,
    engine_adapter,
    engine_tasks,
    human_input,
    llm_request,
    offline_guard,
    process_mode,
    qa,
    safety,
    task_worker,
)
from app.config import (
    BYOK_PROVIDER_DEFAULT_MODELS,
    THINKING_FLOOR_MAX_TOKENS,
    THINKING_FLOOR_TIMEOUT_SECONDS,
    Settings,
    deepseek_non_thinking_extra_body,
    deepseek_thinking_kwargs,
    settings,
    thinking_off_kwargs,
    thinking_safe_max_tokens,
    thinking_safe_timeout,
)
from app.engine_adapter.opts import build_generator
from app.execution_policy import (
    CAMPAIGN,
    CAMPAIGN_MODEL_NAME,
    STANDARD,
    scoped_execution_policy,
)
from app.interviews import model as interviews_model
from app.interviews import stream as interviews_stream
from app.interviews import turns as interview_turns
from app.runs import contrib as runs_contrib
from app.runs import crud as runs_crud
from app.runs.models import HumanHypothesisRequest
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


def _default_models() -> set[str]:
    # Inspect shipped field defaults rather than dotenv-overridden live
    # settings.
    return {
        default
        for field in _MODEL_FIELDS
        if isinstance(default := Settings.model_fields[field].default, str)
    }


def test_every_default_and_byok_model_is_priced() -> None:
    unpriced = sorted(
        (_default_models() | set(BYOK_PROVIDER_DEFAULT_MODELS.values()))
        - set(MODEL_PRICING)
    )

    assert not unpriced, f"models missing from MODEL_PRICING: {unpriced}"


@pytest.mark.parametrize(
    ("model", "budget", "expected"),
    [
        ("deepseek/deepseek-v4-flash", 3_000, THINKING_FLOOR_MAX_TOKENS),
        (
            "deepseek/deepseek-v4-pro",
            THINKING_FLOOR_MAX_TOKENS + 5_000,
            THINKING_FLOOR_MAX_TOKENS + 5_000,
        ),
        ("gemini/gemini-2.5-flash", 3_000, 3_000),
    ],
)
def test_thinking_floor_raises_only_small_deepseek_token_budgets(
    model: str, budget: int, expected: int
) -> None:
    assert thinking_safe_max_tokens(model, budget) == expected


@pytest.mark.parametrize(
    ("model", "deadline", "expected"),
    [
        ("deepseek/deepseek-v4-flash", 20.0, THINKING_FLOOR_TIMEOUT_SECONDS),
        (
            "deepseek/deepseek-v4-pro",
            THINKING_FLOOR_TIMEOUT_SECONDS + 120.0,
            THINKING_FLOOR_TIMEOUT_SECONDS + 120.0,
        ),
        ("gemini/gemini-2.5-flash", 20.0, 20.0),
    ],
)
def test_thinking_floor_raises_only_short_deepseek_deadlines(
    model: str, deadline: float, expected: float
) -> None:
    assert thinking_safe_timeout(model, deadline) == expected


def test_thinking_timeout_floor_admits_the_token_floor() -> None:
    # Token and time ceilings must remain compatible; tuning one can silently
    # break the other.
    pessimistic_tokens_per_second = 75.0

    assert (
        THINKING_FLOOR_MAX_TOKENS / pessimistic_tokens_per_second
        <= THINKING_FLOOR_TIMEOUT_SECONDS
    )


def test_the_thinking_knob_is_the_engine_s_to_choose() -> None:
    # Thinking wire shapes depend on routes; duplicated shaping can turn a
    # requested disable into enable.
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
    assert thinking_off_kwargs(direct) == {
        "extra_body": {"thinking": {"type": "disabled"}}
    }
    assert deepseek_thinking_kwargs(routed)["extra_body"] == {
        "reasoning": {"enabled": True, "effort": "high"},
        "provider": gateway,
    }
    assert deepseek_thinking_kwargs(direct) == {
        "extra_body": {"thinking": {"type": "enabled"}},
        "reasoning_effort": "high",
    }
    for other in (
        deepseek_non_thinking_extra_body,
        deepseek_thinking_kwargs,
        thinking_off_kwargs,
    ):
        assert other("gemini/gemini-2.5-flash") == {}

    # Duplicate top-level and gateway reasoning parameters can fail before
    # contextual safety runs.
    assert "reasoning_effort" not in deepseek_thinking_kwargs(routed)


def test_effort_override_replaces_the_route_s_reasoning_tier() -> None:
    routed = deepseek_thinking_kwargs(
        "openrouter/deepseek/deepseek-v4-flash", effort="medium"
    )
    direct = deepseek_thinking_kwargs(
        "deepseek/deepseek-v4-flash", effort="medium"
    )

    assert routed["extra_body"]["reasoning"]["effort"] == "medium"
    assert direct["reasoning_effort"] == "medium"
    assert (
        deepseek_thinking_kwargs("gemini/gemini-2.5-flash", effort="low") == {}
    )


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


def test_the_free_default_route_keeps_its_highest_effort_in_chat() -> None:
    from app.config import CONVERSATIONAL_REASONING_EFFORT, DEFAULT_MODEL

    kwargs = deepseek_thinking_kwargs(
        DEFAULT_MODEL, effort=CONVERSATIONAL_REASONING_EFFORT
    )

    assert kwargs["extra_body"]["reasoning"]["effort"] == "high"
