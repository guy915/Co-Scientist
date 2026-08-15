"""Revising a chat: editing a scientist prompt, retrying an Agent answer.

Both rewind the transcript rather than extending it, which is the property
these cover -- the turns downstream of the revised one were derived from a
conversation that no longer exists, so they must not survive it.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import interviews
from app.main import app

from ._interviews_helpers import (
    InterviewFields,
    _interview_payload,
    _patch_model_sequence,
    _response,
)

HEADERS = {"X-Client-ID": "revision-scientist"}


def _start(client: TestClient, challenge: str) -> dict[str, Any]:
    """Create an interview and return its first resolved state."""
    return _interview_payload(
        client.post(
            "/api/interviews",
            headers=HEADERS,
            json={"research_challenge": challenge},
        )
    )


def _texts(interview: dict[str, Any]) -> list[str]:
    """The transcript as plain strings, in order."""
    return [turn["content"] for turn in interview["turns"]]


def test_editing_a_prompt_replaces_it_and_drops_what_followed(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The correction stands where the original did, not after it."""
    _patch_model_sequence(
        monkeypatch,
        [
            _response("Which mechanism should this prioritize?"),
            _response("Which organism should this prioritize?"),
        ],
    )
    with TestClient(app) as client:
        started = _start(client, "How do bacteria regain susceptibility?")
        first_prompt = started["turns"][0]

        revised = _interview_payload(
            client.put(
                f"/api/interviews/{started['id']}/turns/{first_prompt['id']}",
                headers=HEADERS,
                json={"content": "How do fungi regain susceptibility?"},
            )
        )

    assert _texts(revised) == [
        "How do fungi regain susceptibility?",
        "Which organism should this prioritize?",
    ]


def test_a_revision_re_derives_from_what_survives(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The model answers the rewound conversation, not the withdrawn one.

    The stored five fields are a derivation of a transcript that no longer
    exists, so carrying them into the next turn would hand the model back
    exactly the conclusions the scientist just withdrew.
    """
    completed = InterviewFields(
        focus=["Efflux-pump regulation"],
        preferences=["Clinical isolates only"],
        completed=True,
    )
    _patch_model_sequence(
        monkeypatch,
        [_response("The goal is ready.", completed), _response("Next?")],
    )
    seen: list[dict[str, Any]] = []
    with TestClient(app) as client:
        started = _start(client, "How do bacteria regain susceptibility?")
        _capture_model_input(monkeypatch, seen, _response("Next?"))
        client.put(
            f"/api/interviews/{started['id']}/turns/"
            f"{started['turns'][0]['id']}",
            headers=HEADERS,
            json={"content": "How do fungi regain susceptibility?"},
        )

    assert len(seen) == 1
    assert _texts(seen[0]) == ["How do fungi regain susceptibility?"]
    assert seen[0]["fields"] == {
        "research_challenge": "How do fungi regain susceptibility?",
        "focus_area": [],
        "preferences": [],
        "lab_constraints": [],
        "title": None,
    }


def _capture_model_input(
    monkeypatch: pytest.MonkeyPatch,
    seen: list[dict[str, Any]],
    reply: dict[str, Any],
) -> None:
    """Record the interview each model call is given, and answer with it."""

    async def _model(
        interview: dict[str, Any],
        _on_reasoning: Any = None,
        _on_prose: Any = None,
    ) -> dict[str, Any]:
        seen.append(interview)
        return reply

    monkeypatch.setattr(interviews, "_call_interview_model", _model)


def test_retrying_an_answer_discards_it_before_asking_again(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retry replaces the rejected answer rather than appending to it."""
    _patch_model_sequence(
        monkeypatch,
        [
            _response("A vague first question."),
            _response("A sharper second question."),
        ],
    )
    with TestClient(app) as client:
        started = _start(client, "How do bacteria regain susceptibility?")
        answer = started["turns"][-1]
        assert answer["role"] == "agent"

        retried = _interview_payload(
            client.post(
                f"/api/interviews/{started['id']}/turns/{answer['id']}/retry",
                headers=HEADERS,
            )
        )

    assert _texts(retried) == [
        "How do bacteria regain susceptibility?",
        "A sharper second question.",
    ]


def test_revising_a_completed_interview_reopens_it(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A finished plan can be sent back for another answer."""
    completed = InterviewFields(
        focus=["Efflux-pump regulation"],
        preferences=["Clinical isolates only"],
        title="Restoring susceptibility",
        completed=True,
    )
    _patch_model_sequence(
        monkeypatch,
        [
            _response("The goal is ready.", completed),
            _response("One more question first."),
        ],
    )
    with TestClient(app) as client:
        started = _start(client, "How do bacteria regain susceptibility?")
        assert started["status"] == "completed"

        retried = _interview_payload(
            client.post(
                f"/api/interviews/{started['id']}/turns/"
                f"{started['turns'][-1]['id']}/retry",
                headers=HEADERS,
            )
        )

    assert retried["status"] == "active"
    assert retried["completed_at"] is None
    # The plan the withdrawn turn derived does not outlive it.
    assert retried["fields"]["focus_area"] == []
    assert retried["fields"]["preferences"] == []


def test_a_revision_refuses_the_wrong_kind_of_turn(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Editing addresses a prompt and retrying an answer; not vice versa."""
    _patch_model_sequence(monkeypatch, [_response("A first question.")])
    with TestClient(app) as client:
        started = _start(client, "How do bacteria regain susceptibility?")
        prompt, answer = started["turns"][0], started["turns"][-1]

        assert (
            client.put(
                f"/api/interviews/{started['id']}/turns/{answer['id']}",
                headers=HEADERS,
                json={"content": "Not a scientist turn."},
            ).status_code
            == 409
        )
        assert (
            client.post(
                f"/api/interviews/{started['id']}/turns/{prompt['id']}/retry",
                headers=HEADERS,
            ).status_code
            == 409
        )
        assert (
            client.post(
                f"/api/interviews/{started['id']}/turns/99999/retry",
                headers=HEADERS,
            ).status_code
            == 404
        )


def test_a_revision_is_owner_scoped(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another client cannot rewind a chat it does not own."""
    _patch_model_sequence(monkeypatch, [_response("A first question.")])
    with TestClient(app) as client:
        started = _start(client, "How do bacteria regain susceptibility?")

        assert (
            client.post(
                f"/api/interviews/{started['id']}/turns/"
                f"{started['turns'][-1]['id']}/retry",
                headers={"X-Client-ID": "someone-else"},
            ).status_code
            == 404
        )

        # And the transcript is untouched by the attempt.
        assert (
            len(
                client.get(
                    f"/api/interviews/{started['id']}", headers=HEADERS
                ).json()["turns"]
            )
            == 2
        )
