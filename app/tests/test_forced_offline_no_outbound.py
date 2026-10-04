# The engine offline router does not intercept forced-offline chat transport.

from __future__ import annotations

import sys
from typing import Any

import pytest

from app import credentials, goal_text, qa, run_start_announcement
from app.store import messages as store
from app.store import runs
from tests._client import make_client

from ._interviews_helpers import _interview_payload


@pytest.fixture(autouse=True)
def _forced_offline_with_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COSCIENTIST_FORCE_OFFLINE", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-present-but-must-be-unused")


@pytest.fixture
def attempts(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    # Only non-offline models count as outbound attempts.
    import litellm
    from co_scientist.offline.llm import is_offline_model

    original = litellm.acompletion
    recorded: list[dict[str, Any]] = []

    async def _guard(**kwargs: Any) -> Any:
        if is_offline_model(str(kwargs.get("model") or "")):
            return await original(**kwargs)
        recorded.append(kwargs)
        raise AssertionError(
            "outbound completion attempted under COSCIENTIST_FORCE_OFFLINE=1"
        )

    monkeypatch.setattr(litellm, "acompletion", _guard)
    return recorded


_GOAL = "How can resistant bacteria regain drug susceptibility?"


def test_interview_turn_makes_no_outbound_request(
    attempts: list[dict[str, Any]],
) -> None:
    with make_client() as client:
        response = client.post(
            "/api/interviews", json={"research_challenge": _GOAL}
        )
    assert response.status_code == 200
    interview = _interview_payload(response)
    assert interview["turns"], "the turn resolved to nothing at all"
    assert attempts == []


def test_qa_answer_makes_no_outbound_request(
    attempts: list[dict[str, Any]],
) -> None:
    with make_client() as client:
        created = client.post("/api/runs", json={"research_goal": _GOAL})
        assert created.status_code == 200
        run_id = created.json()["id"]
        answered = client.post(
            f"/api/runs/{run_id}/messages/ask",
            json={"question": "Which idea ranked first?"},
        )
    assert answered.status_code == 200
    assert "data:" in answered.text
    assert attempts == []


@pytest.mark.asyncio
async def test_run_titling_makes_no_outbound_request(
    attempts: list[dict[str, Any]],
) -> None:
    assert await goal_text.generate_run_title(_GOAL) is None
    assert attempts == []


@pytest.mark.asyncio
async def test_byok_still_reaches_its_own_key(
    attempts: list[dict[str, Any]],
) -> None:
    # Explicit owner credentials exempt BYOK from the deployment-key offline
    # guard.
    credential = credentials.ByokCredential(
        provider="deepseek", api_key="sk-scientist-own", model="deepseek/chat"
    )
    with (
        credentials.scoped_byok(credential),
        pytest.raises(AssertionError),
    ):
        await goal_text._request_completion(_GOAL, goal_text._TITLE)
    assert len(attempts) == 1
    assert attempts[0]["api_key"] == "sk-scientist-own"


def test_qa_dispatch_stays_on_the_offline_answer(
    attempts: list[dict[str, Any]],
) -> None:
    with make_client() as client:
        created = client.post("/api/runs", json={"research_goal": _GOAL})
        run_id = created.json()["id"]
        answered = client.post(
            f"/api/runs/{run_id}/messages/ask",
            json={"question": "Which idea ranked first?"},
        )
    assert "offline mode" in answered.text
    assert attempts == []
    assert store.list_messages(run_id)
    # Read the installed module through sys.modules rather than a private
    # package attribute.
    assert sys.modules["app.runs.chat"].qa is qa


@pytest.mark.asyncio
async def test_restatement_makes_no_outbound_request(
    attempts: list[dict[str, Any]],
) -> None:
    assert await goal_text.generate_goal_restatement(_GOAL) is None
    assert attempts == []


@pytest.mark.asyncio
async def test_announcement_makes_no_outbound_request(
    attempts: list[dict[str, Any]],
) -> None:
    from app.offline_guard import OfflineModeError

    with pytest.raises(OfflineModeError):
        async for _ in run_start_announcement._stream_model_fragments(
            runs.create_run(_GOAL, "express", "engine", {})
        ):
            pass
    assert attempts == []


async def test_question_repair_makes_no_outbound_request(
    attempts: list[dict[str, Any]],
) -> None:
    from app.interviews.questions import repair_questions

    assert await repair_questions("Private scientific question?") == []
    assert attempts == []
