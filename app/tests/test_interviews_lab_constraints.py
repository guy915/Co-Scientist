"""Lab-constraints elicitation and threading (fidelity-audit K5).

The goal interview gains a ``lab_constraints`` structured field elicited
alongside the existing fields ("none" is a valid answer), persisted on the
interview, and threaded through run creation into the engine opts. The
scripted offline fallback completes without eliciting the field, and an
empty field leaves the engine prompts unchanged.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import interviews, store
from app.engine_adapter import _build_engine_opts
from app.interviews_prompts import _normalized_fields
from app.main import app

from ._interviews_helpers import InterviewFields, _interview_payload, _response

_HEADERS = {"X-Client-ID": "lab-constraints-scientist"}


def _lab_response(message: str, lab_constraints: list[str]) -> dict[str, Any]:
    """A completing model response carrying lab constraints."""
    response = _response(
        message,
        InterviewFields(
            focus=["Efflux-pump regulation"],
            preferences=["Clinical isolates"],
            completed=True,
        ),
    )
    response["lab_constraints"] = lab_constraints
    return response


def test_create_interview_seeds_empty_lab_constraints(
    isolated_db: str,
) -> None:
    """A new interview starts with the field at its "none declared" state."""
    interview = store.create_interview(
        "c1", "Study resistance", db_path=isolated_db
    )
    assert interview["fields"]["lab_constraints"] == []


def test_model_turn_persists_elicited_lab_constraints(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Constraints the model derives from the scientist are persisted."""

    async def _model(
        _interview: dict[str, Any],
        _on_reasoning: Any = None,
        _on_prose: Any = None,
    ) -> dict[str, Any]:
        return _lab_response(
            "The goal is ready for run configuration.",
            ["Zebrafish facility only", "No BSL-3 work"],
        )

    monkeypatch.setattr(interviews, "_call_interview_model", _model)
    with TestClient(app) as client:
        created = client.post(
            "/api/interviews",
            headers=_HEADERS,
            json={"research_challenge": "Restore antibiotic susceptibility"},
        )

    payload = _interview_payload(created)
    assert payload["status"] == "completed"
    assert payload["fields"]["lab_constraints"] == [
        "Zebrafish facility only",
        "No BSL-3 work",
    ]


def test_model_turn_omitting_lab_constraints_normalizes_empty(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A response without the field (an older model turn) records none."""

    async def _model(
        _interview: dict[str, Any],
        _on_reasoning: Any = None,
        _on_prose: Any = None,
    ) -> dict[str, Any]:
        return _response(
            "The goal is ready.",
            InterviewFields(
                focus=["Efflux-pump regulation"],
                preferences=["Clinical isolates"],
                completed=True,
            ),
        )

    monkeypatch.setattr(interviews, "_call_interview_model", _model)
    with TestClient(app) as client:
        created = client.post(
            "/api/interviews",
            headers=_HEADERS,
            json={"research_challenge": "A challenge"},
        )

    assert _interview_payload(created)["fields"]["lab_constraints"] == []


def test_normalized_fields_defaults_lab_constraints_to_empty() -> None:
    """Normalization treats an omitted field as the empty list."""
    fields = _normalized_fields(
        {
            "research_challenge": "a challenge",
            "focus_area": ["a focus"],
            "preferences": [],
            "title": None,
        }
    )
    assert fields["lab_constraints"] == []


def test_normalized_fields_recovers_a_bare_string_focus_area() -> None:
    """A single focus area, not wrapped in a list, is still recovered.

    The interview turn carries no schema (a plain trailing JSON block), so
    a model naming exactly one focus area can plausibly write it as a bare
    string; dropping it silently would strand the interview on a real
    answer the scientist already gave.
    """
    fields = _normalized_fields(
        {
            "research_challenge": "a challenge",
            "focus_area": "a single focus",
            "preferences": [],
            "title": None,
        }
    )
    assert fields["focus_area"] == ["a single focus"]


def test_scripted_fallback_completes_without_the_field(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The offline scripted flow finishes with lab constraints still empty.

    The deterministic recovery path asks its focus and preferences
    questions and completes; it never elicits lab constraints, and that
    must not block completion.
    """

    async def _unavailable(
        _interview: dict[str, Any],
        _on_reasoning: Any = None,
        _on_prose: Any = None,
    ) -> dict[str, Any]:
        raise HTTPException(status_code=503, detail="unavailable")

    monkeypatch.setattr(interviews, "_call_interview_model", _unavailable)
    with TestClient(app) as client:
        created = client.post(
            "/api/interviews",
            headers=_HEADERS,
            json={"research_challenge": "Study resistance"},
        )
        interview_id = _interview_payload(created)["id"]
        client.post(
            f"/api/interviews/{interview_id}/turns",
            headers=_HEADERS,
            json={"content": "Prioritize efflux-pump regulation."},
        )
        third = client.post(
            f"/api/interviews/{interview_id}/turns",
            headers=_HEADERS,
            json={"content": "Use clinical isolates only."},
        )

    payload = _interview_payload(third)
    assert payload["status"] == "completed"
    assert payload["fields"]["lab_constraints"] == []


def test_field_edits_persist_lab_constraints(
    isolated_db: str,
) -> None:
    """Scientist-authored field edits accept and clean the new field."""
    interview = store.create_interview(
        "lab-constraints-scientist", "A challenge", db_path=isolated_db
    )
    with TestClient(app) as client:
        updated = client.put(
            f"/api/interviews/{interview['id']}/fields",
            headers=_HEADERS,
            json={
                "research_challenge": "A challenge",
                "focus_area": ["a focus"],
                "preferences": ["a preference"],
                "lab_constraints": ["  Plate reader available  ", ""],
                "title": None,
            },
        )

    assert updated.status_code == 200
    fields = updated.json()["fields"]
    assert fields["lab_constraints"] == ["Plate reader available"]
    assert updated.json()["status"] == "completed"


def test_field_edits_without_lab_constraints_record_none(
    isolated_db: str,
) -> None:
    """Clients predating the field keep validating; omission records none."""
    interview = store.create_interview(
        "lab-constraints-scientist", "A challenge", db_path=isolated_db
    )
    with TestClient(app) as client:
        updated = client.put(
            f"/api/interviews/{interview['id']}/fields",
            headers=_HEADERS,
            json={
                "research_challenge": "A challenge",
                "focus_area": ["a focus"],
                "preferences": ["a preference"],
                "title": None,
            },
        )

    assert updated.status_code == 200
    assert updated.json()["fields"]["lab_constraints"] == []


def _run_from_interview(interview_id: str, isolated_db: str) -> Any:
    """Create a run whose config links it to an interview."""
    return store.create_run(
        "a goal",
        "standard",
        "engine",
        {"interview_id": interview_id},
        store.RunCreateOptions(db_path=isolated_db),
    )


def test_engine_opts_thread_interview_lab_constraints(
    isolated_db: str,
) -> None:
    """A run created from an interview carries its lab constraints as opts."""
    interview = store.create_interview("c4", "A challenge", db_path=isolated_db)
    store.update_interview(
        interview["id"],
        {
            **interview["fields"],
            "lab_constraints": ["Zebrafish facility only"],
        },
        None,
        completed=True,
        db_path=isolated_db,
    )
    run = _run_from_interview(interview["id"], isolated_db)

    opts = _build_engine_opts(run.config, run.id, isolated_db)
    assert opts.get("lab_constraints") == ["Zebrafish facility only"]


def test_engine_opts_omit_lab_constraints_when_none_declared(
    isolated_db: str,
) -> None:
    """Empty constraints produce no opt, leaving engine prompts unchanged."""
    interview = store.create_interview("c5", "A challenge", db_path=isolated_db)
    run = _run_from_interview(interview["id"], isolated_db)

    opts = _build_engine_opts(run.config, run.id, isolated_db)
    assert "lab_constraints" not in opts


def test_engine_opts_without_interview_carry_no_lab_constraints(
    isolated_db: str,
) -> None:
    """A run with no interview has no lab-constraint opt."""
    run = store.create_run(
        "a goal",
        "standard",
        "engine",
        {},
        store.RunCreateOptions(db_path=isolated_db),
    )
    opts = _build_engine_opts(run.config, run.id, isolated_db)
    assert "lab_constraints" not in opts


def test_engine_opts_survive_a_missing_interview_row(
    isolated_db: str,
) -> None:
    """A dangling interview_id degrades to no constraints, never an error."""
    run = store.create_run(
        "a goal",
        "standard",
        "engine",
        {"interview_id": "no-such-interview"},
        store.RunCreateOptions(db_path=isolated_db),
    )
    opts = _build_engine_opts(run.config, run.id, isolated_db)
    assert "lab_constraints" not in opts
