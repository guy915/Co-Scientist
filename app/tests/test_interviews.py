from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.interviews.model as interviews_prompts
import app.interviews.questions as question_repair
from app.config import CONVERSATIONAL_REASONING_EFFORT, settings
from app.engine_adapter.opts import build_engine_opts
from app.interviews import model as interviews_model
from app.main import app
from app.store import documents
from app.store import interviews as store
from app.store.documents import NewStagedDocument
from app.store.interviews import NewInterviewTurn
from tests._client import create_run as _create_run
from tests._llm_fake_backend import install_completion_backend
from tests._store_helpers import seed_run

from ._client import make_client
from ._interviews_helpers import (
    InterviewFields,
    _antibiotic_responses,
    _fake_stream,
    _interview_payload,
    _patch_model_failing_after,
    _patch_model_raising,
    _patch_model_sequence,
    _response,
    _run_antibiotic_interview,
    _send_turn,
    _start_interview,
    _wire_turn,
)

_OWNER = {"X-Client-ID": "chat-owner"}


def _make_chat(owner: str = "chat-owner", turns: int = 2) -> str:
    interview = store.create_interview(owner, "Why do biofilms resist drugs?")
    interview_id: str = str(interview["id"])
    for index in range(turns):
        store.append_interview_turn(
            interview_id, NewInterviewTurn("user", f"answer {index}")
        )
    return interview_id


def test_deleting_a_chat_removes_it_and_its_transcript() -> None:
    client: TestClient = make_client()
    kept, removed = _make_chat(), _make_chat()

    response = client.delete(f"/api/interviews/{removed}", headers=_OWNER)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deleted"] is True
    assert body["counts"]["interviews"] == 1
    assert body["counts"]["interview_turns"] >= 2
    assert store.get_interview(removed) is None
    ids = {
        chat["id"]
        for chat in client.get("/api/interviews", headers=_OWNER).json()
    }
    assert kept in ids
    assert removed not in ids


@pytest.mark.parametrize(
    ("owner", "caller"),
    [
        ("chat-owner", "someone-else"),
        ("", ""),
    ],
    ids=["another-client", "identity-less"],
)
def test_only_the_owner_can_delete_a_chat(owner: str, caller: str) -> None:
    client: TestClient = make_client()
    chat_id = _make_chat(owner=owner)

    response = client.delete(
        f"/api/interviews/{chat_id}", headers={"X-Client-ID": caller}
    )

    assert response.status_code == 404
    assert store.get_interview(chat_id) is not None
    missing = client.delete("/api/interviews/no-such-chat", headers=_OWNER)
    assert missing.status_code == 404


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


def _patch_repair_call(
    monkeypatch: pytest.MonkeyPatch, result: Any
) -> list[str]:
    prompts: list[str] = []

    async def _fake_call(prompt: str, spec: Any, **kwargs: Any) -> Any:
        prompts.append(prompt)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(question_repair, "call_llm_json", _fake_call)
    monkeypatch.setattr("app.offline_guard.remote_chat_allowed", lambda: True)
    return prompts


async def test_the_question_the_prose_asked_comes_back_as_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts = _patch_repair_call(monkeypatch, _QUESTIONS[0])

    questions = await question_repair.repair_questions("Which model system?")

    assert questions == _QUESTIONS
    assert "Which model system?" in prompts[0]


@pytest.mark.parametrize(
    ("message", "model_result"),
    [
        (
            "Understood -- noted.",
            {**_QUESTIONS[0], "question": "", "options": []},
        ),
        ("Proceed?", {**_QUESTIONS[0], "options": [{"label": "Yes"}]}),
        ("Which model system?", RuntimeError("provider down")),
        ("   ", _QUESTIONS[0]),
    ],
    ids=["asks-nothing", "single-option", "provider-failure", "empty-message"],
)
async def test_repair_never_invents_or_forces_a_question(
    monkeypatch: pytest.MonkeyPatch, message: str, model_result: Any
) -> None:
    _patch_repair_call(monkeypatch, model_result)

    assert await question_repair.repair_questions(message) == []


def _turn_offering(questions: Any) -> str:
    response = _response("Which model system should we build around?")
    return _wire_turn({**response, "questions": questions})


def _created_turn(
    monkeypatch: pytest.MonkeyPatch,
    turn: str,
    repaired: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    async def _fake_acompletion(**_kwargs: Any) -> Any:
        return _fake_stream(turn)

    install_completion_backend(monkeypatch, _fake_acompletion)
    if repaired is not None:

        async def _fake_repair(_message: str) -> list[dict[str, Any]]:
            return repaired

        monkeypatch.setattr(question_repair, "repair_questions", _fake_repair)
    with TestClient(app) as client:
        created = _start_interview(
            client, {"X-Client-ID": "scientist-a"}, "Reverse cardiac fibrosis"
        )
    agent_turn: dict[str, Any] = _interview_payload(created)["turns"][-1]
    return agent_turn


def test_a_streamed_turn_carries_its_questions_without_leaking_the_block(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    turn = _created_turn(monkeypatch, _turn_offering(_QUESTIONS), repaired=[])

    assert turn["questions"] == _QUESTIONS
    assert turn["content"] == "Which model system should we build around?"


def test_a_question_asked_in_prose_alone_gets_its_options_back(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    turn = _created_turn(
        monkeypatch,
        _wire_turn(_response("Which one?")),
        repaired=_QUESTIONS,
    )

    assert turn["questions"] == _QUESTIONS


def test_a_completing_turn_is_never_repaired(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    completing = _response(
        "That is enough to start.",
        InterviewFields(
            focus=["Efflux pumps"],
            preferences=["Mechanistic novelty"],
            completed=True,
        ),
    )

    turn = _created_turn(
        monkeypatch, _wire_turn(completing), repaired=_QUESTIONS
    )

    assert turn["questions"] == []


def test_question_repair_shares_the_interview_turn_budget(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    monkeypatch.setattr(settings, "app_llm_max_calls", 1)

    async def provider(**kwargs: Any) -> Any:
        assert kwargs.get("stream"), "repair must not dispatch over the cap"
        return _fake_stream(_wire_turn(_response("Which one?")))

    fake = install_completion_backend(monkeypatch, provider)
    with TestClient(app) as client:
        created = _start_interview(
            client, {"X-Client-ID": "scientist-a"}, "Reverse cardiac fibrosis"
        )
    turn = _interview_payload(created)["turns"][-1]
    assert turn["content"] == "Which one?"
    assert turn["questions"] == []
    assert len(fake.requests) == 1


# Resolve started-run links per client so reopened chats cannot start duplicate
# or foreign runs.


def _stream_frames(response: Any) -> list[dict[str, Any]]:
    return [
        json.loads(line[len("data: ") :])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


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


def test_a_completed_interview_seeds_its_run_and_links_the_chat_to_it(
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
        before = client.get("/api/interviews", headers=headers).json()
        run = _create_run(
            client,
            "client placeholder is not authoritative",
            headers=headers,
            interview_id=interview_id,
            tier="ultra",
        )
        after = client.get("/api/interviews", headers=headers).json()
        reopened = client.get(
            f"/api/interviews/{interview_id}", headers=headers
        ).json()
        other = client.get(
            "/api/interviews", headers={"X-Client-ID": "scientist-b"}
        ).json()

    run_payload = run.json()
    assert run.status_code == 200
    assert (
        run_payload["research_goal"] == payload["fields"]["research_challenge"]
    )
    assert run_payload["title"] == "Restoring Antibiotic Susceptibility"
    assert run_payload["config"]["interview_id"] == interview_id
    assert [chat["id"] for chat in before] == [interview_id]
    assert before[0]["run_id"] is None
    assert before[0]["title"] == "Restoring Antibiotic Susceptibility"
    assert after[0]["run_id"] == run_payload["id"]
    assert reopened["fields"] == payload["fields"]
    assert reopened["run_id"] == run_payload["id"]
    assert other == []


def test_scientist_can_edit_and_finalize_fields(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_model_sequence(
        monkeypatch,
        [
            _response(
                "Clarify the focus area.",
                InterviewFields(title="Derived research title"),
            )
        ],
    )
    headers = {"X-Client-ID": "editor"}
    with TestClient(app) as client:
        created = _start_interview(client, headers, "Study resistance")
        interview_id = _interview_payload(created)["id"]
        edited = client.put(
            f"/api/interviews/{interview_id}/fields",
            headers=headers,
            json={
                "research_challenge": "Test efflux-pump suppression",
                "focus_area": ["AcrAB-TolC"],
                "preferences": ["Use isogenic controls"],
                "lab_constraints": ["  Plate reader available  ", ""],
            },
        )
    assert edited.status_code == 200
    assert edited.json()["status"] == "completed"
    assert edited.json()["fields"]["title"] == "Derived research title"
    assert edited.json()["fields"]["lab_constraints"] == [
        "Plate reader available"
    ]


def test_model_turn_persists_elicited_lab_constraints(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = _response(
        "The goal is ready for run configuration.",
        InterviewFields(
            focus=["Efflux-pump regulation"],
            preferences=["Clinical isolates"],
            completed=True,
        ),
    )
    response["lab_constraints"] = ["Zebrafish facility only", "No BSL-3 work"]
    _patch_model_sequence(monkeypatch, [response])
    with TestClient(app) as client:
        created = _start_interview(
            client,
            {"X-Client-ID": "lab-constraints-scientist"},
            "Restore antibiotic susceptibility",
        )

    payload = _interview_payload(created)
    assert payload["status"] == "completed"
    assert payload["fields"]["lab_constraints"] == response["lab_constraints"]


def test_interview_is_owner_scoped_and_requires_completion(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_model_sequence(
        monkeypatch, [_response("Which mechanism should be prioritized?")]
    )
    with TestClient(app) as client:
        created = _start_interview(
            client, {"X-Client-ID": "owner"}, "Study resistance"
        )
        interview_id = _interview_payload(created)["id"]
        denied = client.get(
            f"/api/interviews/{interview_id}",
            headers={"X-Client-ID": "other"},
        )
        premature = _create_run(
            client,
            "Study resistance",
            headers={"X-Client-ID": "owner"},
            interview_id=interview_id,
        )
    assert denied.status_code == 404
    assert premature.status_code == 409


def test_turn_streams_reasoning_that_is_persisted_and_returned_to_the_model(
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
        created = _start_interview(
            client, {"X-Client-ID": "thinker"}, "Study resistance"
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
    prompt = json.loads(interviews_prompts._prompt(interview))
    assert "No mechanism named yet, so ask for one." in [
        turn.get("reasoning") for turn in prompt["transcript"]
    ]


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
        created = _start_interview(
            client, headers, "Repurpose a drug for glioblastoma"
        )
        interview_id = _interview_payload(created)["id"]
        assert _interview_payload(created)["status"] == "active"
        done = _send_turn(
            client,
            headers,
            interview_id,
            "PI3K/AKT/mTOR; no other constraints, proceed.",
        )

    payload = _interview_payload(done)
    assert payload["status"] == "completed"
    assert payload["fields"]["preferences"] == []


def _flags(interview: dict[str, Any], role: str) -> list[bool]:
    return [
        bool(turn["fallback"])
        for turn in interview["turns"]
        if turn["role"] == role
    ]


def test_interview_stays_usable_and_marks_fallback_turns_during_model_outage(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_model_raising(monkeypatch)
    headers = {"X-Client-ID": "offline-scientist"}
    with TestClient(app) as client:
        created = _start_interview(
            client, headers, "Test astrocyte lactate transport"
        )
        interview_id = _interview_payload(created)["id"]
        focused = _send_turn(
            client,
            headers,
            interview_id,
            "Prioritize MCT1 and MCT4 mechanisms.",
        )
        completed = _send_turn(
            client,
            headers,
            interview_id,
            "Use human organoids and exclude animal work.",
        )

    assert created.status_code == 200
    assert _flags(_interview_payload(created), "agent") == [True]
    assert _flags(_interview_payload(focused), "agent") == [True, True]
    assert _flags(_interview_payload(focused), "user") == [False, False]
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


def test_mixed_interview_marks_only_its_fallback_turns(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_model_failing_after(
        monkeypatch, [_response("Which mechanisms should we prioritize?")]
    )
    headers = {"X-Client-ID": "mixed-scientist"}
    with TestClient(app) as client:
        created = _start_interview(client, headers, "Study resistance")
        interview_id = _interview_payload(created)["id"]
        second = _send_turn(
            client, headers, interview_id, "Prioritize efflux-pump regulation."
        )
        payload = _interview_payload(second)
        resumed = client.get(
            f"/api/interviews/{interview_id}", headers=headers
        ).json()

    assert _flags(payload, "agent") == [False, True]
    assert _flags(resumed, "agent") == [False, True]


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
    run = seed_run(
        "a goal", config={"interview_id": interview["id"]}, db_path=isolated_db
    )

    opts = build_engine_opts(run.config, run.id, isolated_db)

    assert opts.get("lab_constraints") == ["Zebrafish facility only"]


def _reasoning_only_stream(reasoning: str) -> Any:
    # Thinking-only streams never emit content, unlike an empty content chunk.
    def _chunk(reasoning_content: str) -> SimpleNamespace:
        delta = SimpleNamespace(
            reasoning_content=reasoning_content, content=None
        )
        return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])

    async def _chunks() -> Any:
        yield _chunk(reasoning)

    return _chunks()


async def test_thinking_only_turn_retries_once_with_thinking_off(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
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
    assert [t["content"] for t in context["transcript"]] == [
        "Restore antibiotic susceptibility",
        "Prioritize efflux-pump regulation.",
    ]
