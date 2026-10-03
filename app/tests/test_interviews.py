"""Tests for interviews 1."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.interviews.model as interviews_prompts
import app.interviews.questions as question_repair
import app.interviews.questions as repair
from app import store
from app.config import settings
from app.engine_adapter.opts import build_engine_opts
from app.interviews import model as interviews_model
from app.interviews.model import CLOSE_MARKER, OPEN_MARKER, _normalized_fields
from app.interviews.questions import normalized_questions
from app.main import app
from tests._llm_fake_backend import install_completion_backend

from ._client import make_client
from ._interviews_helpers import (
    InterviewFields,
    _antibiotic_responses,
    _fake_stream,
    _interview_payload,
    _patch_model_sequence,
    _response,
    _run_antibiotic_interview,
    _wire_turn,
)

# Tests for permanent chat deletion: DELETE /api/interviews/{id}.


_OWNER = {"X-Client-ID": "chat-owner"}
_OTHER = {"X-Client-ID": "someone-else"}


def _make_chat(owner: str = "chat-owner", turns: int = 2) -> str:
    """Create an interview with a short transcript and return its id."""
    interview = store.create_interview(owner, "Why do biofilms resist drugs?")
    interview_id: str = str(interview["id"])
    for index in range(turns):
        store.append_interview_turn(
            interview_id, store.NewInterviewTurn("user", f"answer {index}")
        )
    return interview_id


def test_deletes_the_chat_and_its_transcript() -> None:
    client: TestClient = make_client()
    chat_id = _make_chat()

    response = client.delete(f"/api/interviews/{chat_id}", headers=_OWNER)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deleted"] is True
    assert body["counts"]["interviews"] == 1
    # The opening turn is seeded at creation, so the transcript is longer
    # than the answers appended above.
    assert body["counts"]["interview_turns"] >= 2
    assert store.get_interview(chat_id) is None


def test_the_chat_is_gone_from_the_owner_list() -> None:
    client: TestClient = make_client()
    kept, removed = _make_chat(), _make_chat()

    deleted = client.delete(f"/api/interviews/{removed}", headers=_OWNER)
    assert deleted.status_code == 200, deleted.text

    listed = client.get("/api/interviews", headers=_OWNER).json()
    ids = {chat["id"] for chat in listed}
    assert kept in ids
    assert removed not in ids


def test_another_client_cannot_delete_it() -> None:
    client: TestClient = make_client()
    chat_id = _make_chat()

    response = client.delete(f"/api/interviews/{chat_id}", headers=_OTHER)

    # 404, not 403: a non-owner must not learn the chat exists at all.
    assert response.status_code == 404
    assert store.get_interview(chat_id) is not None


def test_an_identity_less_caller_cannot_delete_it() -> None:
    client: TestClient = make_client()
    chat_id = _make_chat(owner="")

    response = client.delete(
        f"/api/interviews/{chat_id}", headers={"X-Client-ID": ""}
    )

    # An empty subject owns nothing, even a row whose own client_id is
    # empty too -- the rule _owned_interview enforces on every read.
    assert response.status_code == 404
    assert store.get_interview(chat_id) is not None


def test_deleting_an_unknown_chat_is_a_404() -> None:
    client: TestClient = make_client()

    response = client.delete("/api/interviews/no-such-chat", headers=_OWNER)

    assert response.status_code == 404


def test_a_deleted_chat_leaves_its_staged_document_behind() -> None:
    client: TestClient = make_client()
    chat_id = _make_chat()
    document_id = store.add_staged_document(
        store.NewStagedDocument(
            client_id="chat-owner",
            title="notes.txt",
            text="cryoprotectant toxicity notes",
            mime_type="text/plain",
            sha256="0" * 64,
            byte_size=29,
            extraction_tool="test",
        )
    )
    store.attach_documents_to_interview(chat_id, [document_id], "chat-owner")

    body = client.delete(f"/api/interviews/{chat_id}", headers=_OWNER).json()

    assert body["counts"]["staged_documents_detached"] == 1
    # The document survives: it may be the caller's only copy.
    assert store.get_staged_documents([document_id], "chat-owner")


# Recovering an interview turn's clickable answers from its own prose.
#
# The turn's trailing spec block is where a question's options ride, and it
# is last in the reply -- so a truncated turn, or one whose model ignored the
# instruction, asks in prose with no buttons under it. These cover the small
# repair call that reads the question back out of the prose, and the rule
# that it must never cost the scientist the turn.


_ANSWER = {
    "header": "Model system",
    "question": "Which model system should the ideas be built around?",
    "multi_select": False,
    "options": [
        {"label": "Primary human cells", "description": "Closest to biology"},
        {"label": "iPSC-derived line", "description": "Renewable"},
    ],
}


def _patch_call(
    monkeypatch: pytest.MonkeyPatch, result: Any
) -> list[tuple[str, Any]]:
    """Answer the repair's model call with ``result`` (or raise it)."""
    calls: list[tuple[str, Any]] = []

    async def _fake_call(prompt: str, spec: Any, **kwargs: Any) -> Any:
        calls.append((prompt, spec))
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(repair, "call_llm_json", _fake_call)
    monkeypatch.setattr("app.offline_guard.remote_chat_allowed", lambda: True)
    return calls


async def test_the_question_the_prose_asked_comes_back_as_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_call(monkeypatch, _ANSWER)

    questions = await repair.repair_questions("Which model system?")

    assert questions == [_ANSWER]
    assert "Which model system?" in calls[0][0]


async def test_a_turn_that_asks_nothing_gets_no_invented_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The completing turn's shape, and any reply that closes on a statement.

    The repair reads a question out of prose; it does not write one, so an
    empty answer stays empty rather than becoming a question the scientist
    was never asked.
    """
    _patch_call(monkeypatch, {**_ANSWER, "question": "", "options": []})

    assert await repair.repair_questions("Understood -- noted.") == []


async def test_a_failed_repair_costs_the_turn_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A turn without buttons is answerable by typing; a failed turn is not."""
    _patch_call(monkeypatch, RuntimeError("provider down"))

    assert await repair.repair_questions("Which model system?") == []


async def test_a_single_option_is_not_a_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normalization is shared with the block's own path, not re-implemented."""
    _patch_call(monkeypatch, {**_ANSWER, "options": [{"label": "Yes"}]})

    assert await repair.repair_questions("Proceed?") == []


async def test_an_empty_message_never_reaches_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_call(monkeypatch, _ANSWER)

    assert await repair.repair_questions("   ") == []
    assert calls == []


# Structured multiple-choice questions carried by one interview turn.
#
# An Agent turn may offer the scientist a small set of answers to click
# instead of typing. The options ride in the same trailing spec block the
# turn's five fields already use, are persisted per turn so a reopened chat
# still shows them, and are answered by an ordinary scientist turn.


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

    async def _fake_acompletion(**_kwargs: Any) -> Any:
        return _fake_stream(turn)

    install_completion_backend(monkeypatch, _fake_acompletion)


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

    monkeypatch.setattr(question_repair, "repair_questions", _fake_repair)
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


def test_question_repair_shares_the_interview_turn_budget(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    monkeypatch.setattr(settings, "app_llm_max_calls", 1)

    async def provider(**kwargs: Any) -> Any:
        assert kwargs.get("stream"), "repair must not dispatch over the cap"
        return _fake_stream(_wire_turn(_response("Which one?")))

    fake = install_completion_backend(monkeypatch, provider)
    with TestClient(app) as client:
        created = client.post(
            "/api/interviews",
            headers={"X-Client-ID": "scientist-a"},
            json={"research_challenge": "Reverse cardiac fibrosis"},
        )
    turn = _interview_payload(created)["turns"][-1]
    assert turn["content"] == "Which one?"
    assert turn["questions"] == []
    assert len(fake.requests) == 1


# The run link a reopened chat carries.
#
# ``GET /api/interviews/{id}`` reports the run this chat started, when it
# started one. The workbench reads it to decide whether the plan is still
# editable: without it, reopening a chat re-staged the completing turn as a
# draft with Start research live, beside a card saying the run was already
# under way -- one click from a second run on the same goal.
#
# The link lives in the run's config blob rather than on the interview row,
# so it is resolved per client (``store.run_id_for_interview``) and is never
# visible across clients.


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


# End-to-end tests for the durable, model-driven research interview.
#
# The two mutating endpoints stream Server-Sent Events so the scientist sees the
# model's real chain of thought as it is produced, so these tests read the
# terminal ``interview`` frame via :func:`_interview_payload` rather than
# ``response.json()``.


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
        _interview: dict[str, Any],
        _on_reasoning: Any = None,
        _on_prose: Any = None,
    ) -> dict[str, Any]:
        raise exc

    monkeypatch.setattr(interviews_model, "_call_interview_model", _unavailable)


def _patch_streaming_litellm(
    monkeypatch: pytest.MonkeyPatch,
    response: dict[str, Any],
    *,
    reasoning: str,
) -> None:
    """Swap ``litellm.acompletion`` for a fake DeepSeek-shaped stream."""

    async def _fake_acompletion(**_kwargs: Any) -> Any:
        return _fake_stream(_wire_turn(response), reasoning=reasoning)

    install_completion_backend(monkeypatch, _fake_acompletion)
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-v4-pro")


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
        _interview: dict[str, Any],
        _on_reasoning: Any = None,
        _on_prose: Any = None,
    ) -> dict[str, Any]:
        return _response("Which mechanism should be prioritized?")

    monkeypatch.setattr(interviews_model, "_call_interview_model", _model)
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
        _interview: dict[str, Any],
        _on_reasoning: Any = None,
        _on_prose: Any = None,
    ) -> dict[str, Any]:
        return _response("Clarify the focus area.")

    monkeypatch.setattr(interviews_model, "_call_interview_model", _model)
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
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    reachable_provider: None,
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
    # The answer's prose streams too, as `chunk` frames between the
    # reasoning and the resolved turn.
    assert [frame["type"] for frame in frames] == [
        "reasoning",
        "chunk",
        "interview",
    ]
    assert frames[0]["content"] == "No mechanism named yet, so ask for one."
    assert frames[1]["content"].strip() == (
        "Which mechanism should we prioritize?"
    )

    interview = frames[2]["interview"]
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
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    reachable_provider: None,
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

    prompt = json.loads(interviews_prompts._prompt(interview))
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


# Per-turn provenance for fallback-authored interview turns (A16).
#
# When no model credential is reachable the interview degrades to the
# deterministic scripted question flow. The turns that flow produces must be
# durably marked so the UI can signal the fallback instead of silently serving
# canned questions; turns a real model produced (deployment key or a
# bring-your-own-key credential) must carry no marker. Marking is per turn:
# an interview may mix the two when the model becomes reachable (or
# unreachable) mid-session.


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

    monkeypatch.setattr(interviews_model, "_call_interview_model", _model)


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

    monkeypatch.setattr(interviews_model, "_call_interview_model", _unavailable)
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

    monkeypatch.setattr(interviews_model, "_call_interview_model", _model)
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


# Lab-constraints elicitation and threading (fidelity-audit K5).
#
# The goal interview gains a ``lab_constraints`` structured field elicited
# alongside the existing fields ("none" is a valid answer), persisted on the
# interview, and threaded through run creation into the engine opts. The
# scripted offline fallback completes without eliciting the field, and an
# empty field leaves the engine prompts unchanged.


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

    monkeypatch.setattr(interviews_model, "_call_interview_model", _model)
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

    monkeypatch.setattr(interviews_model, "_call_interview_model", _model)
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

    monkeypatch.setattr(interviews_model, "_call_interview_model", _unavailable)
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

    opts = build_engine_opts(run.config, run.id, isolated_db)
    assert opts.get("lab_constraints") == ["Zebrafish facility only"]


def test_engine_opts_omit_lab_constraints_when_none_declared(
    isolated_db: str,
) -> None:
    """Empty constraints produce no opt, leaving engine prompts unchanged."""
    interview = store.create_interview("c5", "A challenge", db_path=isolated_db)
    run = _run_from_interview(interview["id"], isolated_db)

    opts = build_engine_opts(run.config, run.id, isolated_db)
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
    opts = build_engine_opts(run.config, run.id, isolated_db)
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
    opts = build_engine_opts(run.config, run.id, isolated_db)
    assert "lab_constraints" not in opts


# Tests for the interview model call in ``interviews.model``.
#
# These cases drive the model-call boundary directly rather than through the
# streaming endpoints: the turn's wire format and what a turn missing its
# spec block resolves to.


def _reasoning_only_stream(reasoning: str) -> Any:
    """A stream that reasons at length and ends without a content delta.

    Distinct from ``_fake_stream``, which always yields a content chunk
    (empty or not): the thinking-only shape this reproduces is a stream
    that never emits ``content`` at all, only ``reasoning_content``, then
    stops.
    """
    from types import SimpleNamespace

    def _chunk(reasoning_content: str) -> SimpleNamespace:
        delta = SimpleNamespace(
            reasoning_content=reasoning_content, content=None
        )
        return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])

    async def _chunks() -> Any:
        yield _chunk(reasoning)

    return _chunks()


async def test_interview_asks_for_prose_and_a_spec_block(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    """The turn carries no response_format, and says so in the prompt.

    Both response formats are gone with the JSON envelope they enforced --
    a json_schema request for providers that support it and a json_object
    downgrade for those that do not. The answer is prose plus a trailing
    block now, which no provider-side format can describe, so the shape is
    stated in the prompt and taken apart by ``interviews.wire``.
    """
    captured: dict[str, Any] = {}

    async def _fake_acompletion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _fake_stream(_wire_turn(_response("Which mechanism?")))

    install_completion_backend(monkeypatch, _fake_acompletion)
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-chat")

    interview = {
        "turns": [{"role": "user", "content": "restore susceptibility"}],
        "fields": {},
    }
    result = await interviews_model._call_interview_model(interview)

    assert "response_format" not in captured
    prompt_text = " ".join(m["content"] for m in captured["messages"])
    assert OPEN_MARKER in prompt_text
    assert CLOSE_MARKER in prompt_text
    assert result["assistant_message"] == "Which mechanism?"


async def test_interview_keeps_fields_when_a_turn_omits_its_block(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    """A turn with no spec block keeps the prose and the previous fields.

    The old format made this fatal: unparseable output raised 503 and the
    whole turn was discarded into the deterministic fallback. The fields are
    cumulative interview state, so a turn that reports none has simply
    learned nothing new about them, and the scientist should still be shown
    what the Agent said.
    """

    async def _fake_acompletion(**_kwargs: Any) -> Any:
        return _fake_stream("Which mechanism should we prioritize?")

    install_completion_backend(monkeypatch, _fake_acompletion)
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-chat")

    previous = {
        "research_challenge": "Restore susceptibility",
        "focus_area": ["Efflux-pump regulation"],
    }
    interview = {
        "turns": [{"role": "user", "content": "restore susceptibility"}],
        "fields": previous,
    }
    result = await interviews_model._call_interview_model(interview)

    assert (
        result["assistant_message"] == "Which mechanism should we prioritize?"
    )
    assert result["research_challenge"] == "Restore susceptibility"
    assert result["focus_area"] == ["Efflux-pump regulation"]
    assert result["completed"] is False


async def test_thinking_only_turn_retries_once_with_thinking_off(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    """A stream that reasons and writes nothing is retried, not surfaced.

    Production incident 2026-09-06: a thinking model spent its whole reply
    reasoning about the goal and ended the stream with no ``content`` delta
    at all. The turn used to resolve to an empty message and 502 as
    "Interview Agent returned no message." -- this asserts the streaming
    path now retries once with thinking off before that ever surfaces, and
    that the second stream's answer is what the turn resolves to.
    """
    from app.config import CONVERSATIONAL_REASONING_EFFORT

    calls: list[dict[str, Any]] = []
    streams = [
        _reasoning_only_stream("brainstorming dozens of candidate drugs..."),
        _fake_stream(_wire_turn(_response("Which mechanism?"))),
    ]

    async def _fake_acompletion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return streams[len(calls) - 1]

    install_completion_backend(monkeypatch, _fake_acompletion)
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-chat")

    reasoning_fragments: list[str] = []

    async def _on_reasoning(fragment: str) -> None:
        reasoning_fragments.append(fragment)

    interview = {
        "turns": [{"role": "user", "content": "restore susceptibility"}],
        "fields": {},
    }
    result = await interviews_model._call_interview_model(
        interview, on_reasoning=_on_reasoning
    )

    assert len(calls) == 2
    # The first request carries the interview's conversational tier, not
    # the engine's "high" floor.
    assert calls[0]["reasoning_effort"] == CONVERSATIONAL_REASONING_EFFORT
    # The retry turns thinking off outright rather than lowering it further.
    assert calls[1]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in calls[1]
    # The reader sees the model start over, not silence then an error.
    assert any("retrying" in fragment for fragment in reasoning_fragments)
    assert result["assistant_message"] == "Which mechanism?"


def test_prompt_tolerates_two_consecutive_scientist_turns() -> None:
    """The prompt builder accepts the shape a stopped turn leaves behind.

    A cancelled turn (see interviews.stream._advance_stream) persists
    nothing for the reply it never finished, so the transcript carries two
    consecutive "user" turns once the scientist sends the next message.
    The builder must not assume strict user/agent alternation.
    """
    interview = {
        "id": "orphaned-turn",
        "fields": {},
        "turns": [
            {"role": "user", "content": "Restore antibiotic susceptibility"},
            {"role": "user", "content": "Prioritize efflux-pump regulation."},
        ],
    }
    _model, messages = interviews_prompts._interview_request(interview)
    context = json.loads(messages[1]["content"])
    assert [t["role"] for t in context["transcript"]] == ["user", "user"]
    assert context["transcript"][0]["content"] == (
        "Restore antibiotic susceptibility"
    )
    assert context["transcript"][1]["content"] == (
        "Prioritize efflux-pump regulation."
    )
