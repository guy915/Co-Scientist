"""Forced offline must reach no provider from the app's own chat calls.

The engine's offline router only intercepts ``offline/``-prefixed models, so
it never covers the three call sites that talk to litellm directly -- the
goal interview, run Q&A, and run titling. Each of those carries the
scientist's research goal verbatim, so a deployment that sets
``COSCIENTIST_FORCE_OFFLINE=1`` while a provider key happens to be present
in the environment must still send nothing: the point of the switch is that
the goal text does not leave the process.

Every case here asserts at the transport, not at the answer. A deterministic
fallback answer is indistinguishable from a real one that failed, so the
probe replaces ``litellm.acompletion`` with a function that records the
attempt and raises; "no outbound request" means that recorder stayed empty.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import credentials, qa, runs_chat, store, title_gen
from app.main import app

from ._interviews_helpers import _interview_payload


@pytest.fixture(autouse=True)
def _forced_offline_with_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the exact posture N9 describes: forced offline, key reachable."""
    monkeypatch.setenv("COSCIENTIST_FORCE_OFFLINE", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-present-but-must-be-unused")


@pytest.fixture
def attempts(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace litellm.acompletion with a recorder that refuses to call out.

    Returns:
        The list every attempted completion is appended to; it must stay
        empty for the whole forced-offline posture.
    """
    import litellm

    recorded: list[dict[str, Any]] = []

    async def _refuse(**kwargs: Any) -> Any:
        recorded.append(kwargs)
        raise AssertionError(
            "outbound completion attempted under COSCIENTIST_FORCE_OFFLINE=1"
        )

    monkeypatch.setattr(litellm, "acompletion", _refuse)
    return recorded


_GOAL = "How can resistant bacteria regain drug susceptibility?"


def test_interview_turn_makes_no_outbound_request(
    attempts: list[dict[str, Any]],
) -> None:
    """The opening interview turn must not reach the configured model."""
    with TestClient(app) as client:
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
    with TestClient(app) as client:
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
    with TestClient(app) as client:
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
    # router still dispatches into the module the guard lives in.
    assert getattr(runs_chat, "qa") is qa
