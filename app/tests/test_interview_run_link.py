"""The run link a reopened chat carries.

``GET /api/interviews/{id}`` reports the run this chat started, when it
started one. The workbench reads it to decide whether the plan is still
editable: without it, reopening a chat re-staged the completing turn as a
draft with Start research live, beside a card saying the run was already
under way -- one click from a second run on the same goal.

The link lives in the run's config blob rather than on the interview row,
so it is resolved per client (``store.run_id_for_interview``) and is never
visible across clients.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app

from ._interviews_helpers import (
    _antibiotic_responses,
    _patch_model_sequence,
    _run_antibiotic_interview,
)


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


def test_reopened_chat_reports_the_run_it_started(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed chat carries its run id once a run has been created."""
    _patch_model_sequence(monkeypatch, _antibiotic_responses())
    headers = {"X-Client-ID": "scientist-a"}
    with TestClient(app) as client:
        interview_id, *_ = _run_antibiotic_interview(client, headers)

        before = client.get(
            f"/api/interviews/{interview_id}", headers=headers
        ).json()
        run = _create_run_from_interview(client, headers, interview_id)
        after = client.get(
            f"/api/interviews/{interview_id}", headers=headers
        ).json()

    # A completed interview that has started nothing is still editable, so
    # the absence has to be reported as plainly as the link.
    assert before["run_id"] is None
    assert after["run_id"] == run["id"]
