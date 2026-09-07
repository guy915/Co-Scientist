"""Structured multiple-choice questions carried by one interview turn.

An Agent turn may offer the scientist a small set of answers to click
instead of typing. The options ride in the same trailing spec block the
turn's five fields already use, are persisted per turn so a reopened chat
still shows them, and are answered by an ordinary scientist turn.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import interviews, store
from app.interviews_questions import normalized_questions
from app.main import app

from ._interviews_helpers import (
    InterviewFields,
    _fake_stream,
    _interview_payload,
    _response,
    _wire_turn,
)

_QUESTIONS = [
    {
        "header": "Model system",
        "question": "Which model system should the ideas be built around?",
        "multi_select": False,
        "options": [
            {"label": "Primary human cells", "description": "Closest to"},
            {"label": "iPSC-derived line", "description": "Renewable"},
        ],
    }
]


def test_agent_turn_round_trips_its_questions(isolated_db: str) -> None:
    interview = store.create_interview("client-1", "Reverse cardiac fibrosis")
    store.append_interview_turn(
        interview["id"],
        store.NewInterviewTurn(
            "agent", "Which model system?", questions=_QUESTIONS
        ),
    )
    reloaded = store.get_interview(interview["id"])
    assert reloaded is not None
    assert reloaded["turns"][-1]["questions"] == _QUESTIONS


def test_a_turn_without_questions_reads_as_an_empty_list(
    isolated_db: str,
) -> None:
    """Absent options are the empty list, never None.

    The frontend maps straight over this, so one shape for "no options"
    keeps every read site free of a null branch.
    """
    interview = store.create_interview("client-1", "Reverse cardiac fibrosis")
    reloaded = store.get_interview(interview["id"])
    assert reloaded is not None
    assert reloaded["turns"][0]["questions"] == []


def test_a_well_formed_question_survives_normalization() -> None:
    assert normalized_questions(_QUESTIONS) == _QUESTIONS


def test_options_default_their_optional_parts() -> None:
    """Only ``question`` and two ``label``s are required of the model.

    Everything else has a defensible default, and production runs
    ``json_object`` mode, which enforces no schema at all -- so a turn that
    omits the optional parts must still offer its choice rather than
    silently losing it.
    """
    assert normalized_questions(
        [
            {
                "question": "Which readout?",
                "options": [{"label": "A"}, {"label": "B"}],
            }
        ]
    ) == [
        {
            "header": "",
            "question": "Which readout?",
            "multi_select": False,
            "options": [
                {"label": "A", "description": ""},
                {"label": "B", "description": ""},
            ],
        }
    ]


def test_a_question_offering_fewer_than_two_options_is_dropped() -> None:
    """One option is not a choice; it is a sentence with a button on it."""
    assert (
        normalized_questions(
            [{"question": "Proceed?", "options": [{"label": "Yes"}]}]
        )
        == []
    )


def test_malformed_questions_are_dropped_rather_than_failing_the_turn() -> None:
    """The prose is the turn; the options are an affordance on top of it.

    Losing the affordance costs the scientist a click. Failing the turn
    costs them the answer, so nothing here raises.
    """
    assert normalized_questions("not a list") == []
    assert (
        normalized_questions([{"options": [{"label": "A"}, {"label": "B"}]}])
        == []
    )
    assert (
        normalized_questions([{"question": "Which?", "options": "nope"}]) == []
    )
    assert normalized_questions(None) == []


def _turn_offering(questions: Any) -> str:
    """One streamed turn whose spec block offers ``questions``."""
    response = _response("Which model system should we build around?")
    return _wire_turn({**response, "questions": questions})


def _patch_stream(monkeypatch: pytest.MonkeyPatch, turn: str) -> None:
    """Answer the next model call with ``turn`` over the real wire."""
    import litellm

    async def _fake_acompletion(**_kwargs: Any) -> Any:
        return _fake_stream(turn)

    monkeypatch.setattr(litellm, "acompletion", _fake_acompletion)


def _created_turn(monkeypatch: pytest.MonkeyPatch, turn: str) -> dict[str, Any]:
    """Create an interview from ``turn`` and return the Agent turn it wrote."""
    _patch_stream(monkeypatch, turn)
    with TestClient(app) as client:
        created = client.post(
            "/api/interviews",
            headers={"X-Client-ID": "scientist-a"},
            json={"research_challenge": "Reverse cardiac fibrosis"},
        )
    agent_turn: dict[str, Any] = _interview_payload(created)["turns"][-1]
    return agent_turn


def test_a_streamed_turn_carries_its_questions_to_the_scientist(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    """The whole path: spec block -> parsed turn -> persisted -> streamed."""
    turn = _created_turn(monkeypatch, _turn_offering(_QUESTIONS))
    assert turn["questions"] == _QUESTIONS


def test_the_options_never_leak_into_the_prose_the_scientist_reads(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    """The block is machine-read; only the prose above it is the message."""
    turn = _created_turn(monkeypatch, _turn_offering(_QUESTIONS))
    assert turn["content"] == "Which model system should we build around?"


def _patch_repair(
    monkeypatch: pytest.MonkeyPatch, questions: list[dict[str, Any]]
) -> list[str]:
    """Answer the repair call with ``questions``; return the messages it saw."""
    seen: list[str] = []

    async def _fake_repair(message: str) -> list[dict[str, Any]]:
        seen.append(message)
        return questions

    monkeypatch.setattr(interviews, "repair_questions", _fake_repair)
    return seen


def test_a_turn_offering_no_questions_persists_none(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    """Questions are per turn, never cumulative: an omission means none.

    And a repair that finds nothing to offer -- the model could not be
    reached, or the prose asks nothing -- leaves the turn exactly as it
    was rather than failing it.
    """
    seen = _patch_repair(monkeypatch, [])
    turn = _created_turn(monkeypatch, _wire_turn(_response("Which one?")))
    assert turn["questions"] == []
    assert seen == ["Which one?"]


def test_a_question_asked_in_prose_alone_gets_its_options_back(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    """The block is last in the reply, so it is what a short turn loses.

    The prose asked correctly either way, so the question is read back out
    of it rather than the whole turn being re-derived.
    """
    seen = _patch_repair(monkeypatch, _QUESTIONS)

    turn = _created_turn(monkeypatch, _wire_turn(_response("Which one?")))

    assert turn["questions"] == _QUESTIONS
    assert seen == ["Which one?"]


def test_a_turn_that_offered_its_own_questions_is_not_repaired(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    seen = _patch_repair(monkeypatch, [])

    turn = _created_turn(monkeypatch, _turn_offering(_QUESTIONS))

    assert turn["questions"] == _QUESTIONS
    assert seen == []


def test_the_completing_turn_is_never_repaired(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    """It asks nothing by contract, so there is nothing to offer."""
    seen = _patch_repair(monkeypatch, _QUESTIONS)
    completing = _response(
        "That is enough to start.",
        InterviewFields(
            focus=["Efflux pumps"],
            preferences=["Mechanistic novelty"],
            completed=True,
        ),
    )

    turn = _created_turn(monkeypatch, _wire_turn(completing))

    assert turn["questions"] == []
    assert seen == []
