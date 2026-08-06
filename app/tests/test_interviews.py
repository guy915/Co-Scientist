"""End-to-end tests for the durable, model-driven research interview.

The two mutating endpoints stream Server-Sent Events so the scientist sees the
model's real chain of thought as it is produced, so these tests read the
terminal ``interview`` frame via :func:`_interview_payload` rather than
``response.json()``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import interviews
from app.config import settings
from app.main import app

from ._interviews_helpers import (
    InterviewFields,
    _fake_stream,
    _interview_payload,
    _patch_model_sequence,
    _response,
)


def _stream_frames(response: Any) -> list[dict[str, Any]]:
    """Return every SSE frame from a streamed turn, in order."""
    return [
        json.loads(line[len("data: ") :])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def _patch_model_raising(
    monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> None:
    """Patch the interview model to raise ``exc`` on every call."""

    async def _unavailable(
        _interview: dict[str, Any], _on_reasoning: Any = None
    ) -> dict[str, Any]:
        raise exc

    monkeypatch.setattr(interviews, "_call_interview_model", _unavailable)


def _patch_streaming_litellm(
    monkeypatch: pytest.MonkeyPatch,
    response: dict[str, Any],
    *,
    reasoning: str,
) -> None:
    """Swap ``litellm.acompletion`` for a fake DeepSeek-shaped stream."""
    import litellm

    async def _fake_acompletion(**_kwargs: Any) -> Any:
        return _fake_stream(json.dumps(response), reasoning=reasoning)

    monkeypatch.setattr(litellm, "acompletion", _fake_acompletion)
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-v4-pro")


def _antibiotic_responses() -> list[dict[str, Any]]:
    """Return the three model turns of the antibiotic-resistance interview."""
    return [
        _response("Which resistance mechanism should the study prioritize?"),
        _response(
            "What models, constraints, or exclusions should guide it?",
            InterviewFields(focus=["Efflux-pump regulation"]),
        ),
        _response(
            "The goal is ready for run configuration.",
            InterviewFields(
                focus=["Efflux-pump regulation"],
                preferences=[
                    "Use clinical Gram-negative isolates",
                    "Exclude new antibiotic discovery",
                ],
                title="Restoring Antibiotic Susceptibility",
                completed=True,
            ),
        ),
    ]


def _run_antibiotic_interview(
    client: TestClient, headers: dict[str, str]
) -> tuple[str, Any, Any, Any]:
    """Drive the three-turn antibiotic interview; return id and responses."""
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
    return interview_id, created, second, final


def test_interview_persists_turns_progress_and_final_plan(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Contextual Agent turns produce and persist exactly four plan fields."""
    _patch_model_sequence(monkeypatch, _antibiotic_responses())
    headers = {"X-Client-ID": "scientist-a"}
    with TestClient(app) as client:
        interview_id, created, second, final = _run_antibiotic_interview(
            client, headers
        )

        assert created.status_code == 200
        assert _interview_payload(second)["status"] == "active"
        payload = _interview_payload(final)
        assert payload["status"] == "completed"
        assert set(payload["fields"]) == {
            "research_challenge",
            "focus_area",
            "preferences",
            "lab_constraints",
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


def test_completed_interview_authoritatively_seeds_run_creation(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The interview's saved plan, not the client body, drives the run."""
    _patch_model_sequence(monkeypatch, _antibiotic_responses())
    headers = {"X-Client-ID": "scientist-a"}
    with TestClient(app) as client:
        interview_id, _created, _second, final = _run_antibiotic_interview(
            client, headers
        )
        fields = _interview_payload(final)["fields"]

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
    assert run_payload["research_goal"] == fields["research_challenge"]
    assert run_payload["title"] == "Restoring Antibiotic Susceptibility"
    assert run_payload["config"]["interview_id"] == interview_id


def test_chat_list_is_owner_scoped_and_links_its_run(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sidebar's chat list carries each chat's run and nobody else's.

    The listing is what makes a chat resumable at all, so it has to appear
    the moment the first turn lands -- before any run exists -- and then
    pick up the run id once one is started.
    """
    _patch_model_sequence(monkeypatch, _antibiotic_responses())
    headers = {"X-Client-ID": "scientist-a"}
    with TestClient(app) as client:
        interview_id, created, _second, _final = _run_antibiotic_interview(
            client, headers
        )
        assert created.status_code == 200
        before = client.get("/api/interviews", headers=headers).json()
        run = client.post(
            "/api/runs",
            headers=headers,
            json={
                "research_goal": "placeholder",
                "interview_id": interview_id,
            },
        )
        after = client.get("/api/interviews", headers=headers).json()
        other = client.get(
            "/api/interviews", headers={"X-Client-ID": "scientist-b"}
        ).json()

    assert [chat["id"] for chat in before] == [interview_id]
    assert before[0]["run_id"] is None
    assert before[0]["title"] == "Restoring Antibiotic Susceptibility"
    assert after[0]["run_id"] == run.json()["id"]
    assert other == []


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


def test_turn_streams_real_reasoning_before_resolving(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The thinking shown to the scientist is the model's own reasoning.

    The indicator is only honest if its frames carry the ``reasoning_content``
    the provider actually produced and arrive before the turn resolves, rather
    than a placeholder spun while a request is in flight. The reasoning is
    persisted on its own column rather than folded into the message, so a
    resumed chat can show the thinking without it ever reading as the Agent's
    answer.
    """
    _patch_streaming_litellm(
        monkeypatch,
        _response("Which mechanism should we prioritize?"),
        reasoning="No mechanism named yet, so ask for one.",
    )

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
    agent_turns = [
        turn for turn in interview["turns"] if turn["role"] == "agent"
    ]
    assert [turn["content"] for turn in agent_turns] == [
        "Which mechanism should we prioritize?"
    ]
    # Kept beside the answer, never inside it.
    assert [turn["reasoning"] for turn in agent_turns] == [
        "No mechanism named yet, so ask for one."
    ]


def test_persisted_reasoning_returns_to_the_model_next_turn(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A chat's own thinking stays in the context its next turn builds on.

    Chats are short, so dropping the chain of thought after each answer
    would ask the Agent to continue from less than the scientist can see on
    screen. The prompt is asserted directly because nothing else observes
    what the model was actually handed.
    """
    _patch_streaming_litellm(
        monkeypatch,
        _response("Which mechanism should we prioritize?"),
        reasoning="No mechanism named yet, so ask for one.",
    )
    headers = {"X-Client-ID": "thinker"}

    with TestClient(app) as client:
        created = client.post(
            "/api/interviews",
            headers=headers,
            json={"research_challenge": "Study resistance"},
        )
        interview_id = _interview_payload(created)["id"]
        interview = client.get(
            f"/api/interviews/{interview_id}", headers=headers
        ).json()

    prompt = json.loads(interviews._prompt(interview))
    reasoning = [turn.get("reasoning") for turn in prompt["transcript"]]
    assert "No mechanism named yet, so ask for one." in reasoning


def test_interview_completes_when_model_reports_no_preferences(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A model-confirmed completion with empty preferences must finalize.

    The interview contract treats an explicit "no constraints" as a valid
    terminal state, so an empty preferences list must not deadlock the
    interview in 'active' (which would leave the run un-creatable).
    """
    _patch_model_sequence(
        monkeypatch,
        [
            _response("Which pathways should this research prioritize?"),
            _response(
                "The goal is finalized. Proceeding with the analysis.",
                InterviewFields(
                    focus=["PI3K/AKT/mTOR pathway"],
                    # scientist stated there are no constraints
                    preferences=[],
                    completed=True,
                ),
            ),
        ],
    )
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
    """Explicit answers populate the fields when the model is absent.

    The scripted flow completes without eliciting lab constraints (K5):
    the field records its empty "none declared" state.
    """
    _patch_model_raising(
        monkeypatch, HTTPException(status_code=503, detail="unavailable")
    )
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
        "lab_constraints": [],
        "title": None,
    }
