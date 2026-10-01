"""The title a completed interview hands the run it seeds.

Two paths meet on ``runs.title``: the interview names the session from the
whole conversation, and ``title_gen`` names it from the goal alone. The
interview's name wins where it has one, so these cases pin which path runs
-- generation used to fire unconditionally and overwrite the better title
with the worse one.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import runs_crud
from app.main import app
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
    """Report a keyed deployment so the scheduling guard is the only gate.

    Offline runs skip titling wholesale, which would make every assertion
    here pass for the wrong reason.
    """
    fake_process_mode.online()


@pytest.fixture
def _generated_titles(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every goal that reaches title generation."""
    seen: list[str] = []

    async def _generate(goal: str) -> str | None:
        seen.append(goal)
        return "Generated Replacement Title"

    monkeypatch.setattr(runs_crud, "generate_run_title", _generate)
    return seen


def _create_run_from_interview(
    client: TestClient, headers: dict[str, str], interview_id: str
) -> dict[str, Any]:
    """Create a run seeded by ``interview_id`` and return its payload."""
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
    """A named interview settles the title; nothing regenerates over it."""
    _patch_model_sequence(monkeypatch, _antibiotic_responses())
    headers = {"X-Client-ID": "scientist-a"}
    with TestClient(app) as client:
        interview_id, *_ = _run_antibiotic_interview(client, headers)
        run = _create_run_from_interview(client, headers, interview_id)
        settled = client.get(f"/api/runs/{run['id']}", headers=headers).json()

    assert run["title"] == "Restoring Antibiotic Susceptibility"
    # The background task is the thing under test: it must never have run.
    assert _generated_titles == []
    assert settled["title"] == "Restoring Antibiotic Susceptibility"


def _overlong_title_responses() -> list[dict[str, Any]]:
    """Interview turns whose final title busts the title-length ceiling."""
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
    """A title too long for the surfaces is rejected, not stored.

    Keeping the interview's title means it is no longer overwritten by a
    bounded generated one, so it has to clear the same ceiling every other
    title path clears; rejected, it leaves the run unnamed and generation
    supplies the name as it always did.
    """
    _patch_model_sequence(monkeypatch, _overlong_title_responses())
    headers = {"X-Client-ID": "scientist-a"}
    with TestClient(app) as client:
        interview_id, *_, final = _run_antibiotic_interview(client, headers)
        fields = _interview_payload(final)["fields"]
        run = _create_run_from_interview(client, headers, interview_id)
        settled = client.get(f"/api/runs/{run['id']}", headers=headers).json()

    # The interview itself still carries what the model wrote.
    assert len(fields["title"]) > 80
    assert run["title"] is None
    assert _generated_titles == [run["research_goal"]]
    assert settled["title"] == "Generated Replacement Title"
