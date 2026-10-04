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
from app.config import settings
from app.engine_adapter.opts import build_engine_opts
from app.interviews import model as interviews_model
from app.interviews.model import CLOSE_MARKER, OPEN_MARKER, _normalized_fields
from app.interviews.questions import normalized_questions
from app.main import app
from app.store import documents, runs
from app.store import interviews as store
from app.store.documents import NewStagedDocument
from app.store.interviews import NewInterviewTurn
from app.store.runs import RunCreateOptions
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

_OWNER = {"X-Client-ID": "chat-owner"}
_OTHER = {"X-Client-ID": "someone-else"}


def _make_chat(owner: str = "chat-owner", turns: int = 2) -> str:
    interview = store.create_interview(owner, "Why do biofilms resist drugs?")
    interview_id: str = str(interview["id"])
    for index in range(turns):
        store.append_interview_turn(
            interview_id, NewInterviewTurn("user", f"answer {index}")
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

    assert response.status_code == 404
    assert store.get_interview(chat_id) is not None


def test_an_identity_less_caller_cannot_delete_it() -> None:
    client: TestClient = make_client()
    chat_id = _make_chat(owner="")

    response = client.delete(
        f"/api/interviews/{chat_id}", headers={"X-Client-ID": ""}
    )

    assert response.status_code == 404
    assert store.get_interview(chat_id) is not None


def test_deleting_an_unknown_chat_is_a_404() -> None:
    client: TestClient = make_client()

    response = client.delete("/api/interviews/no-such-chat", headers=_OWNER)

    assert response.status_code == 404


def test_a_deleted_chat_leaves_its_staged_document_behind() -> None:
    client: TestClient = make_client()
    chat_id = _make_chat()
    document_id = documents.add_staged_document(
        NewStagedDocument(
            client_id="chat-owner",
            title="notes.txt",
            text="cryoprotectant toxicity notes",
            mime_type="text/plain",
            sha256="0" * 64,
            byte_size=29,
            extraction_tool="test",
        )
    )
    documents.attach_documents_to_interview(
        chat_id, [document_id], "chat-owner"
    )

    body = client.delete(f"/api/interviews/{chat_id}", headers=_OWNER).json()

    assert body["counts"]["staged_documents_detached"] == 1
    assert documents.get_staged_documents([document_id], "chat-owner")


# Option repair must not cost the scientist an otherwise valid prose turn.


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
    # Repair reads existing prose rather than inventing a question the scientist
    # was never asked.
    _patch_call(monkeypatch, {**_ANSWER, "question": "", "options": []})

    assert await repair.repair_questions("Understood -- noted.") == []


async def test_a_failed_repair_costs_the_turn_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_call(monkeypatch, RuntimeError("provider down"))

    assert await repair.repair_questions("Which model system?") == []


async def test_a_single_option_is_not_a_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_call(monkeypatch, {**_ANSWER, "options": [{"label": "Yes"}]})

    assert await repair.repair_questions("Proceed?") == []


async def test_an_empty_message_never_reaches_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_call(monkeypatch, _ANSWER)

    assert await repair.repair_questions("   ") == []
    assert calls == []


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
        NewInterviewTurn("agent", "Which model system?", questions=_QUESTIONS),
    )
    reloaded = store.get_interview(interview["id"])
    assert reloaded is not None
    assert reloaded["turns"][-1]["questions"] == _QUESTIONS


def test_a_turn_without_questions_reads_as_an_empty_list(
    isolated_db: str,
) -> None:
    interview = store.create_interview("client-1", "Reverse cardiac fibrosis")
    reloaded = store.get_interview(interview["id"])
    assert reloaded is not None
    assert reloaded["turns"][0]["questions"] == []


def test_a_well_formed_question_survives_normalization() -> None:
    assert normalized_questions(_QUESTIONS) == _QUESTIONS


def test_options_default_their_optional_parts() -> None:
    # json_object mode does not enforce optional fields; recover valid choices
    # with defaults.
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
    assert (
        normalized_questions(
            [{"question": "Proceed?", "options": [{"label": "Yes"}]}]
        )
        == []
    )


def test_malformed_questions_are_dropped_rather_than_failing_the_turn() -> None:
    # Clickable options are an affordance; repair failure must never discard the
    # scientist-visible answer.
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
    response = _response("Which model system should we build around?")
    return _wire_turn({**response, "questions": questions})


def _patch_stream(monkeypatch: pytest.MonkeyPatch, turn: str) -> None:

    async def _fake_acompletion(**_kwargs: Any) -> Any:
        return _fake_stream(turn)

    install_completion_backend(monkeypatch, _fake_acompletion)


def _created_turn(monkeypatch: pytest.MonkeyPatch, turn: str) -> dict[str, Any]:
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
    turn = _created_turn(monkeypatch, _turn_offering(_QUESTIONS))
    assert turn["questions"] == _QUESTIONS


def test_the_options_never_leak_into_the_prose_the_scientist_reads(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    turn = _created_turn(monkeypatch, _turn_offering(_QUESTIONS))
    assert turn["content"] == "Which model system should we build around?"


def _patch_repair(
    monkeypatch: pytest.MonkeyPatch, questions: list[dict[str, Any]]
) -> list[str]:
    seen: list[str] = []

    async def _fake_repair(message: str) -> list[dict[str, Any]]:
        seen.append(message)
        return questions

    monkeypatch.setattr(question_repair, "repair_questions", _fake_repair)
    return seen


def test_a_turn_offering_no_questions_persists_none(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    seen = _patch_repair(monkeypatch, [])
    turn = _created_turn(monkeypatch, _wire_turn(_response("Which one?")))
    assert turn["questions"] == []
    assert seen == ["Which one?"]


def test_a_question_asked_in_prose_alone_gets_its_options_back(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    # The trailing options block is lost first on truncation; recover the
    # question from surviving prose.
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


# Resolve started-run links per client so reopened chats cannot start duplicate
# or foreign runs.


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


def test_reopened_chat_reports_the_run_it_started(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    assert before["run_id"] is None
    assert after["run_id"] == run["id"]


def _stream_frames(response: Any) -> list[dict[str, Any]]:
    return [
        json.loads(line[len("data: ") :])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def _patch_model_raising(
    monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> None:

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

    async def _fake_acompletion(**_kwargs: Any) -> Any:
        return _fake_stream(_wire_turn(response), reasoning=reasoning)

    install_completion_backend(monkeypatch, _fake_acompletion)
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-v4-pro")


def test_interview_persists_turns_progress_and_final_plan(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    # Displayed thinking is provider reasoning, persisted separately so it never
    # becomes the answer.
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
    assert [turn["reasoning"] for turn in agent_turns] == [
        "No mechanism named yet, so ask for one."
    ]


def test_persisted_reasoning_returns_to_the_model_next_turn(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    reachable_provider: None,
) -> None:
    # Subsequent chat prompts retain reasoning the scientist can already see.
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
    # Explicit no-constraints completion is valid; empty preferences must not
    # strand the interview.
    _patch_model_sequence(
        monkeypatch,
        [
            _response("Which pathways should this research prioritize?"),
            _response(
                "The goal is finalized. Proceeding with the analysis.",
                InterviewFields(
                    focus=["PI3K/AKT/mTOR pathway"],
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


# Fallback provenance is per turn because provider reachability can change
# within a chat.


_KEY = "sk-fallback-probe-123"
_BYOK_HEADERS = {
    "X-LLM-API-Key": _KEY,
    "X-LLM-Provider": "deepseek",
    "X-Client-ID": "byok-fallback-scientist",
}


def _flags(interview: dict[str, Any], role: str) -> list[bool]:
    return [
        bool(turn["fallback"])
        for turn in interview["turns"]
        if turn["role"] == role
    ]


def _patch_model_failing_after(
    monkeypatch: pytest.MonkeyPatch, responses: list[dict[str, Any]]
) -> None:
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
    assert _flags(_interview_payload(second), "user") == [False, False]


def test_credentialed_turns_are_not_marked(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
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
        resumed = client.get(
            f"/api/interviews/{interview_id}", headers=headers
        ).json()

    assert _flags(payload, "agent") == [False, True]
    assert _flags(resumed, "agent") == [False, True]


def test_byok_turn_is_not_marked(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:

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


_HEADERS = {"X-Client-ID": "lab-constraints-scientist"}


def _lab_response(message: str, lab_constraints: list[str]) -> dict[str, Any]:
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
    interview = store.create_interview(
        "c1", "Study resistance", db_path=isolated_db
    )
    assert interview["fields"]["lab_constraints"] == []


def test_model_turn_persists_elicited_lab_constraints(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:

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
    # A plain trailing JSON block may carry a bare focus string; preserve that
    # answered state.
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
    # Offline interviews never elicit lab constraints; an empty field must not
    # block completion.

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
    return runs.create_run(
        "a goal",
        "standard",
        "engine",
        {"interview_id": interview_id},
        RunCreateOptions(db_path=isolated_db),
    )


def test_engine_opts_thread_interview_lab_constraints(
    isolated_db: str,
) -> None:
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
    interview = store.create_interview("c5", "A challenge", db_path=isolated_db)
    run = _run_from_interview(interview["id"], isolated_db)

    opts = build_engine_opts(run.config, run.id, isolated_db)
    assert "lab_constraints" not in opts


def test_engine_opts_without_interview_carry_no_lab_constraints(
    isolated_db: str,
) -> None:
    run = runs.create_run(
        "a goal",
        "standard",
        "engine",
        {},
        RunCreateOptions(db_path=isolated_db),
    )
    opts = build_engine_opts(run.config, run.id, isolated_db)
    assert "lab_constraints" not in opts


def test_engine_opts_survive_a_missing_interview_row(
    isolated_db: str,
) -> None:
    run = runs.create_run(
        "a goal",
        "standard",
        "engine",
        {"interview_id": "no-such-interview"},
        RunCreateOptions(db_path=isolated_db),
    )
    opts = build_engine_opts(run.config, run.id, isolated_db)
    assert "lab_constraints" not in opts


def _reasoning_only_stream(reasoning: str) -> Any:
    # Thinking-only streams never emit content, unlike an empty content chunk.
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
    # Prose plus trailing JSON has no provider response_format; the prompt
    # defines its wire shape.
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
    # Missing spec blocks mean no new fields, not a lost turn; keep cumulative
    # state and prose.

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
    # Thinking-only streams need one thinking-off retry before surfacing an
    # empty-answer failure.
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
    assert calls[0]["reasoning_effort"] == CONVERSATIONAL_REASONING_EFFORT
    assert calls[1]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in calls[1]
    assert any("retrying" in fragment for fragment in reasoning_fragments)
    assert result["assistant_message"] == "Which mechanism?"


def test_prompt_tolerates_two_consecutive_scientist_turns() -> None:
    # Cancelled replies are not persisted, so transcripts can legitimately
    # contain consecutive user turns.
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
