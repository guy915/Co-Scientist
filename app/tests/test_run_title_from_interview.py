# A completed interview title takes precedence over a goal-derived title.

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.runs import crud as runs_crud
from tests._process_mode_helpers import FakeProcessMode

from ._interviews_helpers import (
    InterviewFields,
    _antibiotic_responses,
    _interview_payload,
    _patch_model_sequence,
    _response,
    _run_antibiotic_interview,
)


@pytest.fixture(autouse=True)
def _titling_is_reachable(fake_process_mode: FakeProcessMode) -> None:
    # Use an online fake so the offline skip cannot make this title guard pass
    # accidentally.
    fake_process_mode.online()


@pytest.fixture
def _generated_titles(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    async def _generate(goal: str) -> str | None:
        seen.append(goal)
        return "Generated Replacement Title"

    monkeypatch.setattr(runs_crud, "generate_run_title", _generate)
    return seen


def _create_run_from_interview(
    client: TestClient, headers: dict[str, str], interview_id: str
) -> dict[str, Any]:
    response = client.post(
        "/api/runs",
        headers=headers,
        json={"research_goal": "placeholder", "interview_id": interview_id},
    )
    assert response.status_code == 200
    return dict(response.json())


def test_interview_title_is_kept_and_generation_never_runs(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    _generated_titles: list[str],
) -> None:
    _patch_model_sequence(monkeypatch, _antibiotic_responses())
    headers = {"X-Client-ID": "scientist-a"}
    with TestClient(app) as client:
        interview_id, *_ = _run_antibiotic_interview(client, headers)
        run = _create_run_from_interview(client, headers, interview_id)
        settled = client.get(f"/api/runs/{run['id']}", headers=headers).json()

    assert run["title"] == "Restoring Antibiotic Susceptibility"
    assert _generated_titles == []
    assert settled["title"] == "Restoring Antibiotic Susceptibility"


def _overlong_title_responses() -> list[dict[str, Any]]:
    responses = _antibiotic_responses()
    responses[-1] = _response(
        "The goal is ready for run configuration.",
        InterviewFields(
            focus=["Efflux-pump regulation"],
            title="Restoring " + "Antibiotic Susceptibility " * 5,
            completed=True,
        ),
    )
    return responses


def test_overlong_interview_title_falls_through_to_generation(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    _generated_titles: list[str],
) -> None:
    # Accepted interview titles share the generated-title length cap.
    _patch_model_sequence(monkeypatch, _overlong_title_responses())
    headers = {"X-Client-ID": "scientist-a"}
    with TestClient(app) as client:
        interview_id, *_, final = _run_antibiotic_interview(client, headers)
        fields = _interview_payload(final)["fields"]
        run = _create_run_from_interview(client, headers, interview_id)
        settled = client.get(f"/api/runs/{run['id']}", headers=headers).json()

    assert len(fields["title"]) > 80
    assert run["title"] is None
    assert _generated_titles == [run["research_goal"]]
    assert settled["title"] == "Generated Replacement Title"
