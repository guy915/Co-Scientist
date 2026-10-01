"""Forced offline must reach no provider from the app's own chat calls.

The engine's offline router only intercepts ``offline/``-prefixed models, so
it does not cover app chat calls: interview, Q&A, announcements, titles
and goal restatements. Each of those carries the
scientist's research goal verbatim, so a deployment that sets
``COSCIENTIST_FORCE_OFFLINE=1`` while a provider key happens to be present
in the environment must still send nothing: the point of the switch is that
the goal text does not leave the process.

Every case here asserts at the transport, not at the answer. A deterministic
fallback answer is indistinguishable from a real one that failed, so the
probe replaces ``litellm.acompletion`` with a function that records the
attempt and raises; "no outbound request" means that recorder stayed empty.
An ``offline/``-prefixed call (e.g. ``make_client()``'s startup demo
seeding, which synthesizes each curated demo's R14-3 goal restatement) is
not such an attempt -- the offline router answers it locally, so it is
passed through to the real (router-installed) ``acompletion`` rather than
counted as a leak.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest

from app import (
    credentials,
    goal_restatement,
    qa,
    run_start_announcement,
    store,
    title_gen,
)
from tests._client import make_client

from ._interviews_helpers import _interview_payload


@pytest.fixture(autouse=True)
def _forced_offline_with_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the exact posture N9 describes: forced offline, key reachable."""
    monkeypatch.setenv("COSCIENTIST_FORCE_OFFLINE", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-present-but-must-be-unused")


@pytest.fixture
def attempts(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace litellm.acompletion with a recorder that refuses real calls.

    An ``offline/``-prefixed model is not a real outbound attempt -- it is
    passed through to the actual (router-installed) ``acompletion``, which
    answers it locally -- so only a non-offline model is recorded and
    refused.

    Returns:
        The list every attempted *real* completion is appended to; it must
        stay empty for the whole forced-offline posture.
    """
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
    """The opening interview turn must not reach the configured model."""
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
    """A run Q&A answer must not reach the configured chat model."""
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
    """Titling condenses the goal, so it must not send it either."""
    assert await title_gen.generate_run_title(_GOAL) is None
    assert attempts == []


@pytest.mark.asyncio
async def test_byok_still_reaches_its_own_key(
    attempts: list[dict[str, Any]],
) -> None:
    """A scientist's own validated key is not shadowed by forced offline.

    Forced offline withholds the *deployment's* credential. A scoped
    bring-your-own-key credential is the scientist's explicit instruction to
    bill their own provider, and ``resolve_offline_backend`` already exempts
    it for engine runs; the chat paths must agree rather than silently
    dropping to a scripted answer.
    """
    credential = credentials.ByokCredential(
        provider="deepseek", api_key="sk-scientist-own", model="deepseek/chat"
    )
    with (
        credentials.scoped_byok(credential),
        pytest.raises(AssertionError),
    ):
        await title_gen._request_title_completion(_GOAL)
    assert len(attempts) == 1
    assert attempts[0]["api_key"] == "sk-scientist-own"


def test_qa_dispatch_stays_on_the_offline_answer(
    attempts: list[dict[str, Any]],
) -> None:
    """The offline Q&A answer is still grounded in the run's own artifacts."""
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
    # The refusal has to come from the answer path itself, so pin that the
    # router still dispatches into the module the guard lives in. Read
    # through sys.modules: app.runs.chat imports qa for its own use and does
    # not re-export it, so reaching for the attribute directly is a private
    # access the typechecker is right to reject.
    assert sys.modules["app.runs.chat"].qa is qa


@pytest.mark.asyncio
async def test_restatement_makes_no_outbound_request(
    attempts: list[dict[str, Any]],
) -> None:
    assert await goal_restatement.generate_goal_restatement(_GOAL) is None
    assert attempts == []


@pytest.mark.asyncio
async def test_announcement_makes_no_outbound_request(
    attempts: list[dict[str, Any]],
) -> None:
    from app.offline_guard import OfflineModeError

    with pytest.raises(OfflineModeError):
        async for _ in run_start_announcement._stream_model_fragments(
            store.create_run(_GOAL, "express", "engine", {})
        ):
            pass
    assert attempts == []


async def test_question_repair_makes_no_outbound_request(
    attempts: list[dict[str, Any]],
) -> None:
    from app.interviews.question_repair import repair_questions

    assert await repair_questions("Private scientific question?") == []
    assert attempts == []
