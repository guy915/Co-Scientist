"""Persisted campaign policy reaches every app-side model boundary."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from co_scientist.llm_free_policy import campaign_free_mode
from fastapi import HTTPException, Request

from app import (
    engine_tasks,
    human_input,
    interviews,
    interviews_stream,
    qa,
    run_start_announcement,
    runs_chat,
    runs_contrib,
    runs_crud,
    store,
)
from app.runs_models import HumanHypothesisRequest


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


def _task(run_id: str) -> store.ScientificTask:
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
        interviews._request_byok(_paid_request(), "campaign")
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

    monkeypatch.setattr(interviews_stream, "_advance", advance)
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

    monkeypatch.setattr(interviews_stream, "_advance", advance)
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
    await engine_tasks.execute_engine_task(_task(campaign.id))
    await engine_tasks.execute_engine_task(_task(standard.id))

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
        await engine_tasks.execute_engine_task(_task(campaign.id))

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
    request = Request(
        {"type": "http", "headers": [(b"x-client-id", b"owner")]}
    )

    response = await runs_contrib.add_human_hypothesis(
        campaign.id,
        HumanHypothesisRequest(
            statement="A benign hypothesis", author="owner"
        ),
        request,
    )

    assert response["admitted"] is True
    assert seen == [True]
    assert campaign_free_mode() is False
