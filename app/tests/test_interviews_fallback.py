"""Per-turn provenance for fallback-authored interview turns (A16).

When no model credential is reachable the interview degrades to the
deterministic scripted question flow. The turns that flow produces must be
durably marked so the UI can signal the fallback instead of silently serving
canned questions; turns a real model produced (deployment key or a
bring-your-own-key credential) must carry no marker. Marking is per turn:
an interview may mix the two when the model becomes reachable (or
unreachable) mid-session.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import interviews
from app.main import app

from ._interviews_helpers import (
    InterviewFields,
    _interview_payload,
    _response,
)

_KEY = "sk-fallback-probe-123"
_BYOK_HEADERS = {
    "X-LLM-API-Key": _KEY,
    "X-LLM-Provider": "deepseek",
    "X-Client-ID": "byok-fallback-scientist",
}


def _flags(interview: dict[str, Any], role: str) -> list[bool]:
    """Return each turn's fallback flag for one role, in transcript order."""
    return [
        bool(turn["fallback"])
        for turn in interview["turns"]
        if turn["role"] == role
    ]


def _patch_model_failing_after(
    monkeypatch: pytest.MonkeyPatch, responses: list[dict[str, Any]]
) -> None:
    """Answer the first calls, then fail every later one with a 503.

    Simulates a model that is reachable for the opening turn(s) and drops
    out mid-session -- the mixed case the per-turn marker exists for.
    """
    replies: Iterator[dict[str, Any]] = iter(responses)

    async def _model(
        _interview: dict[str, Any],
        _on_reasoning: Any = None,
        _on_prose: Any = None,
    ) -> dict[str, Any]:
        try:
            return next(replies)
        except StopIteration:
            raise HTTPException(status_code=503, detail="unavailable") from None

    monkeypatch.setattr(interviews, "_call_interview_model", _model)


def test_keyless_fallback_turns_are_marked(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every turn the scripted recovery authors is marked, durably."""

    async def _unavailable(
        _interview: dict[str, Any],
        _on_reasoning: Any = None,
        _on_prose: Any = None,
    ) -> dict[str, Any]:
        raise HTTPException(status_code=503, detail="unavailable")

    monkeypatch.setattr(interviews, "_call_interview_model", _unavailable)
    headers = {"X-Client-ID": "keyless-scientist"}
    with TestClient(app) as client:
        created = client.post(
            "/api/interviews",
            headers=headers,
            json={"research_challenge": "Test astrocyte lactate transport"},
        )
        interview_id = _interview_payload(created)["id"]
        second = client.post(
            f"/api/interviews/{interview_id}/turns",
            headers=headers,
            json={"content": "Prioritize MCT1 and MCT4 mechanisms."},
        )

    assert created.status_code == 200
    assert _flags(_interview_payload(created), "agent") == [True]
    assert _flags(_interview_payload(second), "agent") == [True, True]
    # User turns are the scientist's own; the marker never touches them.
    assert _flags(_interview_payload(second), "user") == [False, False]


def test_credentialed_turns_are_not_marked(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Turns a reachable model authors carry no fallback marker."""
    first = _response("Which resistance mechanisms matter most?")
    second = _response(
        "The goal is ready for run configuration.",
        InterviewFields(
            focus=["Efflux-pump regulation"],
            preferences=["Use clinical isolates"],
            completed=True,
        ),
    )
    replies = iter([first, second])

    async def _model(
        _interview: dict[str, Any],
        _on_reasoning: Any = None,
        _on_prose: Any = None,
    ) -> dict[str, Any]:
        return next(replies)

    monkeypatch.setattr(interviews, "_call_interview_model", _model)
    headers = {"X-Client-ID": "keyed-scientist"}
    with TestClient(app) as client:
        created = client.post(
            "/api/interviews",
            headers=headers,
            json={"research_challenge": "Restore antibiotic susceptibility"},
        )
        interview_id = _interview_payload(created)["id"]
        final = client.post(
            f"/api/interviews/{interview_id}/turns",
            headers=headers,
            json={"content": "Efflux-pump regulation; clinical isolates."},
        )

    assert _flags(_interview_payload(created), "agent") == [False]
    assert _flags(_interview_payload(final), "agent") == [False, False]


def test_mixed_interview_marks_only_its_fallback_turns(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A model outage mid-session marks only the turns it authors."""
    _patch_model_failing_after(
        monkeypatch, [_response("Which mechanisms should we prioritize?")]
    )
    headers = {"X-Client-ID": "mixed-scientist"}
    with TestClient(app) as client:
        created = client.post(
            "/api/interviews",
            headers=headers,
            json={"research_challenge": "Study resistance"},
        )
        interview_id = _interview_payload(created)["id"]
        second = client.post(
            f"/api/interviews/{interview_id}/turns",
            headers=headers,
            json={"content": "Prioritize efflux-pump regulation."},
        )
        payload = _interview_payload(second)
        # The marker is persisted on the turn row, so a fresh read -- the
        # rehydrate path the chat workspace uses -- carries it too.
        resumed = client.get(
            f"/api/interviews/{interview_id}", headers=headers
        ).json()

    assert _flags(payload, "agent") == [False, True]
    assert _flags(resumed, "agent") == [False, True]


def test_byok_turn_is_not_marked(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bring-your-own-key interview turn is model-driven and unmarked.

    The BYOK header credential makes the turn's provider call the
    scientist's own; when it answers, the turn must read exactly like one
    the deployment key produced.
    """

    async def fake_stream(
        interview: dict[str, Any], sinks: Any
    ) -> tuple[str, dict[str, Any]]:
        return "Which focus area matters most?", {
            "research_challenge": "challenge",
            "focus_area": [],
            "preferences": [],
            "completed": False,
            "questions": [
                {
                    "header": "Focus",
                    "question": "Which focus area matters most?",
                    "multi_select": False,
                    "options": [
                        {
                            "label": "Mechanisms",
                            "description": "Find mechanisms",
                        },
                        {"label": "Evidence", "description": "Review evidence"},
                    ],
                }
            ],
        }

    monkeypatch.setattr(
        "app.interviews.model._stream_interview_content", fake_stream
    )
    with TestClient(app) as client:
        created = client.post(
            "/api/interviews",
            headers=_BYOK_HEADERS,
            json={"research_challenge": "challenge"},
        )

    assert created.status_code == 200, created.text
    assert _flags(_interview_payload(created), "agent") == [False]
