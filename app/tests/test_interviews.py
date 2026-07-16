"""End-to-end tests for the durable, model-driven research interview.

The two mutating endpoints stream Server-Sent Events so the scientist sees the
model's real chain of thought as it is produced, so these tests read the
terminal ``interview`` frame via :func:`_interview_payload` rather than
``response.json()``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import interviews
from app.config import settings
from app.main import app


def _interview_payload(response: Any) -> dict[str, Any]:
    """Return the interview carried by a streamed turn's terminal frame.

    Args:
        response: The TestClient response for a streamed interview endpoint.

    Returns:
        The interview row from the closing ``interview`` frame.

    Raises:
        AssertionError: If the stream carried no ``interview`` frame, which
            means the turn errored instead of resolving.
    """
    for line in response.text.splitlines():
        if not line.startswith("data: "):
            continue
        event = json.loads(line[len("data: ") :])
        if event["type"] == "interview":
            return cast(dict[str, Any], event["interview"])
    raise AssertionError(f"no interview frame in stream: {response.text!r}")


def _stream_frames(response: Any) -> list[dict[str, Any]]:
    """Return every SSE frame from a streamed turn, in order."""
    return [
        json.loads(line[len("data: ") :])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def _response(
    message: str,
    *,
    challenge: str = "How can resistant bacteria regain drug susceptibility?",
    focus: list[str] | None = None,
    preferences: list[str] | None = None,
    title: str | None = None,
    completed: bool = False,
) -> dict[str, Any]:
    return {
        "assistant_message": message,
        "research_challenge": challenge,
        "focus_area": focus or [],
        "preferences": preferences or [],
        "title": title,
        "completed": completed,
    }


def test_interview_persists_turns_progress_and_final_plan(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Contextual Agent turns produce and persist exactly four plan fields."""
    responses = iter(
        [
            _response(
                "Which resistance mechanism should the study prioritize?"
            ),
            _response(
                "What models, constraints, or exclusions should guide it?",
                focus=["Efflux-pump regulation"],
            ),
            _response(
                "The goal is ready for run configuration.",
                focus=["Efflux-pump regulation"],
                preferences=[
                    "Use clinical Gram-negative isolates",
                    "Exclude new antibiotic discovery",
                ],
                title="Restoring Antibiotic Susceptibility",
                completed=True,
            ),
        ]
    )

    async def _model(
        _interview: dict[str, Any], _on_reasoning: Any = None
    ) -> dict[str, Any]:
        return next(responses)

    monkeypatch.setattr(interviews, "_call_interview_model", _model)
    headers = {"X-Client-ID": "scientist-a"}
    with TestClient(app) as client:
        created = client.post(
            "/api/interviews",
            headers=headers,
            json={
                "research_challenge": (
                    "How can resistant bacteria regain drug susceptibility?"
                )
            },
        )
        interview_id = _interview_payload(created)["id"]
        second = client.post(
            f"/api/interviews/{interview_id}/turns",
            headers=headers,
            json={"content": "Prioritize efflux-pump regulation."},
        )
        final = client.post(
            f"/api/interviews/{interview_id}/turns",
            headers=headers,
            json={
                "content": (
                    "Use clinical Gram-negative isolates and exclude new "
                    "antibiotic discovery."
                )
            },
        )

        assert created.status_code == 200
        assert _interview_payload(second)["status"] == "active"
        payload = _interview_payload(final)
        assert payload["status"] == "completed"
        assert set(payload["fields"]) == {
            "research_challenge",
            "focus_area",
            "preferences",
            "title",
        }
        assert [turn["role"] for turn in payload["turns"]] == [
            "user",
            "agent",
            "user",
            "agent",
            "user",
            "agent",
        ]

        resumed = client.get(f"/api/interviews/{interview_id}", headers=headers)
        assert resumed.json()["fields"] == payload["fields"]

        run = client.post(
            "/api/runs",
            headers=headers,
            json={
                "research_goal": "client placeholder is not authoritative",
                "interview_id": interview_id,
                "tier": "ultra",
            },
        )
        assert run.status_code == 200
        run_payload = run.json()
        assert (
            run_payload["research_goal"]
            == payload["fields"]["research_challenge"]
        )
        assert run_payload["title"] == "Restoring Antibiotic Susceptibility"
        assert run_payload["config"]["interview_id"] == interview_id


def test_interview_is_owner_scoped_and_requires_completion(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Private interview state cannot be read or used by another client."""

    async def _model(
        _interview: dict[str, Any], _on_reasoning: Any = None
    ) -> dict[str, Any]:
        return _response("Which mechanism should be prioritized?")

    monkeypatch.setattr(interviews, "_call_interview_model", _model)
    with TestClient(app) as client:
        created = client.post(
            "/api/interviews",
            headers={"X-Client-ID": "owner"},
            json={"research_challenge": "Study resistance"},
        )
        interview_id = _interview_payload(created)["id"]
        denied = client.get(
            f"/api/interviews/{interview_id}",
            headers={"X-Client-ID": "other"},
        )
        premature = client.post(
            "/api/runs",
            headers={"X-Client-ID": "owner"},
            json={
                "research_goal": "Study resistance",
                "interview_id": interview_id,
            },
        )
    assert denied.status_code == 404
    assert premature.status_code == 409


def test_scientist_can_edit_and_finalize_fields(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit edits persist and complete once all required fields exist."""

    async def _model(
        _interview: dict[str, Any], _on_reasoning: Any = None
    ) -> dict[str, Any]:
        return _response("Clarify the focus area.")

    monkeypatch.setattr(interviews, "_call_interview_model", _model)
    headers = {"X-Client-ID": "editor"}
    with TestClient(app) as client:
        created = client.post(
            "/api/interviews",
            headers=headers,
            json={"research_challenge": "Study resistance"},
        )
        interview_id = _interview_payload(created)["id"]
        edited = client.put(
            f"/api/interviews/{interview_id}/fields",
            headers=headers,
            json={
                "research_challenge": "Test efflux-pump suppression",
                "focus_area": ["AcrAB-TolC"],
                "preferences": ["Use isogenic controls"],
                "title": None,
            },
        )
    assert edited.status_code == 200
    assert edited.json()["status"] == "completed"


def _fake_stream(content: str, reasoning: str = "") -> Any:
    """Build a litellm-style streaming completion.

    Mirrors the real DeepSeek delta order verified against the live API: the
    whole chain of thought arrives as ``reasoning_content`` deltas before the
    first ``content`` delta.

    Args:
        content: The answer text, delivered as a single content delta.
        reasoning: Optional chain of thought delivered before the answer.

    Returns:
        An async iterator of litellm-shaped streaming chunks.
    """

    def _chunk(
        *, reasoning_content: str | None = None, content: str | None = None
    ) -> SimpleNamespace:
        delta = SimpleNamespace(
            reasoning_content=reasoning_content, content=content
        )
        return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])

    async def _chunks() -> Any:
        if reasoning:
            yield _chunk(reasoning_content=reasoning)
        yield _chunk(content=content)

    return _chunks()


async def test_interview_downgrades_response_format_for_deepseek(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DeepSeek rejects json_schema, so the interview must use json_object.

    The engine already downgrades DeepSeek to json_object + schema-in-prompt;
    the interview call must defer to the same provider-capability check rather
    than hardcoding json_schema (which DeepSeek returns a BadRequest for).
    """
    import json

    import litellm

    captured: dict[str, Any] = {}

    async def _fake_acompletion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _fake_stream(json.dumps(_response("Which mechanism?")))

    monkeypatch.setattr(litellm, "acompletion", _fake_acompletion)
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-chat")

    interview = {
        "turns": [{"role": "user", "content": "restore susceptibility"}],
        "fields": {},
    }
    result = await interviews._call_interview_model(interview)

    assert captured["response_format"] == {"type": "json_object"}
    # The schema is restated in the prompt so structure survives the downgrade.
    prompt_text = " ".join(m["content"] for m in captured["messages"])
    assert "assistant_message" in prompt_text
    assert result["assistant_message"] == "Which mechanism?"


async def test_interview_keeps_json_schema_for_supporting_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model that supports json_schema still gets the native schema format."""
    import json

    import litellm

    captured: dict[str, Any] = {}

    async def _fake_acompletion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _fake_stream(json.dumps(_response("ok")))

    monkeypatch.setattr(litellm, "acompletion", _fake_acompletion)
    monkeypatch.setattr(settings, "chat_model_name", "openai/gpt-4o")

    interview = {
        "turns": [{"role": "user", "content": "test"}],
        "fields": {},
    }
    await interviews._call_interview_model(interview)

    assert captured["response_format"]["type"] == "json_schema"


def test_turn_streams_real_reasoning_before_resolving(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The thinking shown to the scientist is the model's own reasoning.

    The indicator is only honest if its frames carry the ``reasoning_content``
    the provider actually produced and arrive before the turn resolves, rather
    than a placeholder spun while a request is in flight. The reasoning must
    also stay out of the persisted transcript, so a resumed interview does not
    replay stale thinking as if it were the Agent's message.
    """
    import litellm

    async def _fake_acompletion(**_kwargs: Any) -> Any:
        return _fake_stream(
            json.dumps(_response("Which mechanism should we prioritize?")),
            reasoning="No mechanism named yet, so ask for one.",
        )

    monkeypatch.setattr(litellm, "acompletion", _fake_acompletion)
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-v4-pro")

    with TestClient(app) as client:
        created = client.post(
            "/api/interviews",
            headers={"X-Client-ID": "thinker"},
            json={"research_challenge": "Study resistance"},
        )

    frames = _stream_frames(created)
    assert [frame["type"] for frame in frames] == ["reasoning", "interview"]
    assert frames[0]["content"] == "No mechanism named yet, so ask for one."

    interview = frames[1]["interview"]
    assert interview["status"] == "active"
    # Only the answer is persisted; the chain of thought is display-only.
    assert [
        turn["content"]
        for turn in interview["turns"]
        if turn["role"] == "agent"
    ] == ["Which mechanism should we prioritize?"]


def test_interview_completes_when_model_reports_no_preferences(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A model-confirmed completion with empty preferences must finalize.

    The interview contract treats an explicit "no constraints" as a valid
    terminal state, so an empty preferences list must not deadlock the
    interview in 'active' (which would leave the run un-creatable).
    """
    responses = iter(
        [
            _response("Which pathways should this research prioritize?"),
            _response(
                "The goal is finalized. Proceeding with the analysis.",
                focus=["PI3K/AKT/mTOR pathway"],
                preferences=[],  # scientist stated there are no constraints
                completed=True,
            ),
        ]
    )

    async def _model(
        _interview: dict[str, Any], _on_reasoning: Any = None
    ) -> dict[str, Any]:
        return next(responses)

    monkeypatch.setattr(interviews, "_call_interview_model", _model)
    headers = {"X-Client-ID": "no-prefs-scientist"}
    with TestClient(app) as client:
        created = client.post(
            "/api/interviews",
            headers=headers,
            json={"research_challenge": "Repurpose a drug for glioblastoma"},
        )
        interview_id = _interview_payload(created)["id"]
        assert _interview_payload(created)["status"] == "active"
        done = client.post(
            f"/api/interviews/{interview_id}/turns",
            headers=headers,
            json={"content": "PI3K/AKT/mTOR; no other constraints, proceed."},
        )

    payload = _interview_payload(done)
    assert payload["status"] == "completed"
    assert payload["fields"]["preferences"] == []


def test_interview_remains_usable_during_model_outage(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit answers populate the four fields when the model is absent."""

    async def _unavailable(
        _interview: dict[str, Any], _on_reasoning: Any = None
    ) -> dict[str, Any]:
        raise HTTPException(status_code=503, detail="unavailable")

    monkeypatch.setattr(interviews, "_call_interview_model", _unavailable)
    headers = {"X-Client-ID": "offline-scientist"}
    with TestClient(app) as client:
        created = client.post(
            "/api/interviews",
            headers=headers,
            json={"research_challenge": "Test astrocyte lactate transport"},
        )
        interview_id = _interview_payload(created)["id"]
        focused = client.post(
            f"/api/interviews/{interview_id}/turns",
            headers=headers,
            json={"content": "Prioritize MCT1 and MCT4 mechanisms."},
        )
        completed = client.post(
            f"/api/interviews/{interview_id}/turns",
            headers=headers,
            json={"content": "Use human organoids and exclude animal work."},
        )

    assert created.status_code == 200
    assert _interview_payload(focused)["fields"]["focus_area"] == [
        "Prioritize MCT1 and MCT4 mechanisms."
    ]
    payload = _interview_payload(completed)
    assert payload["status"] == "completed"
    assert payload["fields"] == {
        "research_challenge": "Test astrocyte lactate transport",
        "focus_area": ["Prioritize MCT1 and MCT4 mechanisms."],
        "preferences": ["Use human organoids and exclude animal work."],
        "title": None,
    }
