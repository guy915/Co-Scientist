"""End-to-end tests for the durable, model-driven research interview."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import interviews
from app.main import app


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

    async def _model(_interview: dict[str, Any]) -> dict[str, Any]:
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
        interview_id = created.json()["id"]
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
        assert second.json()["status"] == "active"
        payload = final.json()
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
                "tier": "advanced",
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

    async def _model(_interview: dict[str, Any]) -> dict[str, Any]:
        return _response("Which mechanism should be prioritized?")

    monkeypatch.setattr(interviews, "_call_interview_model", _model)
    with TestClient(app) as client:
        created = client.post(
            "/api/interviews",
            headers={"X-Client-ID": "owner"},
            json={"research_challenge": "Study resistance"},
        )
        interview_id = created.json()["id"]
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

    async def _model(_interview: dict[str, Any]) -> dict[str, Any]:
        return _response("Clarify the focus area.")

    monkeypatch.setattr(interviews, "_call_interview_model", _model)
    headers = {"X-Client-ID": "editor"}
    with TestClient(app) as client:
        created = client.post(
            "/api/interviews",
            headers=headers,
            json={"research_challenge": "Study resistance"},
        )
        interview_id = created.json()["id"]
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


def test_interview_remains_usable_during_model_outage(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit answers populate the four fields when the model is absent."""

    async def _unavailable(_interview: dict[str, Any]) -> dict[str, Any]:
        raise HTTPException(status_code=503, detail="unavailable")

    monkeypatch.setattr(interviews, "_call_interview_model", _unavailable)
    headers = {"X-Client-ID": "offline-scientist"}
    with TestClient(app) as client:
        created = client.post(
            "/api/interviews",
            headers=headers,
            json={"research_challenge": "Test astrocyte lactate transport"},
        )
        interview_id = created.json()["id"]
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
    assert focused.json()["fields"]["focus_area"] == [
        "Prioritize MCT1 and MCT4 mechanisms."
    ]
    payload = completed.json()
    assert payload["status"] == "completed"
    assert payload["fields"] == {
        "research_challenge": "Test astrocyte lactate transport",
        "focus_area": ["Prioritize MCT1 and MCT4 mechanisms."],
        "preferences": ["Use human organoids and exclude animal work."],
        "title": None,
    }
