from __future__ import annotations

import asyncio
import contextlib
from typing import Any, NamedTuple

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.execution_policy import CAMPAIGN, CAMPAIGN_MODEL_NAME, STANDARD
from app.interviews import model as interviews_model
from app.interviews import stream as interviews_stream
from app.interviews import turns as interview_turns
from app.interviews.model import (
    CLOSE_MARKER,
    OPEN_MARKER,
    TurnSplitter,
)
from app.main import app
from app.store import interviews as store
from app.store.interviews import NewInterviewTurn
from tests._llm_fake_backend import install_completion_backend

from ._interviews_helpers import (
    InterviewFields,
    _interview_payload,
    _patch_model_sequence,
    _response,
)

# Revised conversations invalidate every downstream turn derived from the
# withdrawn text.


HEADERS = {"X-Client-ID": "revision-scientist"}


def _start(client: TestClient, challenge: str) -> dict[str, Any]:
    return _interview_payload(
        client.post(
            "/api/interviews",
            headers=HEADERS,
            json={"research_challenge": challenge},
        )
    )


def _texts(interview: dict[str, Any]) -> list[str]:
    return [turn["content"] for turn in interview["turns"]]


def test_editing_a_prompt_replaces_it_and_drops_what_followed(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    # Rewinding invalidates derived interview fields; carrying them forward
    # restores withdrawn conclusions.
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

    async def _model(
        interview: dict[str, Any],
        _on_reasoning: Any = None,
        _on_prose: Any = None,
    ) -> dict[str, Any]:
        seen.append(interview)
        return reply

    monkeypatch.setattr(interviews_model, "_call_interview_model", _model)


def test_retrying_an_answer_discards_it_before_asking_again(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    assert retried["fields"]["focus_area"] == []
    assert retried["fields"]["preferences"] == []


def test_a_revision_refuses_the_wrong_kind_of_turn(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
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

        assert (
            len(
                client.get(
                    f"/api/interviews/{started['id']}", headers=HEADERS
                ).json()["turns"]
            )
            == 2
        )


class _HangingStream:
    def __init__(self, started: asyncio.Event) -> None:
        self._started = started

    def __aiter__(self) -> _HangingStream:
        return self

    async def __anext__(self) -> Any:
        self._started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")  # pragma: no cover


def _seed_interview(db_path: str) -> str:
    # Cancelled replies leave consecutive scientist turns because their messages
    # were persisted before streaming.
    interview = store.create_interview(
        "stop-scientist", "Restore antibiotic susceptibility", db_path=db_path
    )
    store.append_interview_turn(
        str(interview["id"]),
        NewInterviewTurn("user", "Prioritize efflux-pump regulation."),
        db_path=db_path,
    )
    return str(interview["id"])


async def test_campaign_interview_stream_selects_campaign_route(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.execution_policy import effective_execution_model

    campaign = store.create_interview(
        "campaign-owner",
        "Campaign goal",
        execution_policy=CAMPAIGN,
        db_path=isolated_db,
    )
    standard = store.create_interview(
        "standard-owner",
        "Standard goal",
        execution_policy=STANDARD,
        db_path=isolated_db,
    )
    selected: dict[str, str | None] = {}

    async def advance(interview_id: str, *_args: Any) -> dict[str, Any]:
        selected[interview_id] = effective_execution_model(
            "configured/chat-role"
        )
        return {"id": interview_id}

    monkeypatch.setattr(interview_turns, "advance_turn", advance)
    for interview_id in (str(campaign["id"]), str(standard["id"])):
        async for _ in interviews_stream._advance_stream(interview_id):
            pass

    assert selected == {
        str(campaign["id"]): CAMPAIGN_MODEL_NAME,
        str(standard["id"]): "configured/chat-role",
    }


async def test_cancel_mid_model_call_leaves_transcript_unchanged(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    reachable_provider: None,
) -> None:
    # Cancellation must propagate without creating a scripted fallback turn or
    # leaking the provider task.
    interview_id = _seed_interview(isolated_db)
    before = store.get_interview(interview_id, db_path=isolated_db)

    started = asyncio.Event()

    async def _fake_acompletion(**_kwargs: Any) -> Any:
        return _HangingStream(started)

    install_completion_backend(monkeypatch, _fake_acompletion)
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-chat")

    gen = interviews_stream._advance_stream(interview_id)
    consumer = asyncio.ensure_future(gen.__anext__())
    await asyncio.wait_for(started.wait(), timeout=5)

    # Client disconnect cancels the iteration task; aclose cannot run alongside
    # pending anext.
    consumer.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await consumer

    after = store.get_interview(interview_id, db_path=isolated_db)
    assert after is not None
    assert after == before
    assert [t["role"] for t in after["turns"]] == ["user", "user"]

    pending = [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task() and not task.done()
    ]
    assert pending == []


async def test_closing_after_a_fragment_cancels_the_advance_task(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    interview_id = _seed_interview(isolated_db)
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def _fake_advance(
        _interview_id: str,
        on_reasoning: Any = None,
        _on_prose: Any = None,
    ) -> dict[str, Any]:
        assert on_reasoning is not None
        await on_reasoning("first")
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        raise AssertionError("unreachable")  # pragma: no cover

    monkeypatch.setattr(interview_turns, "advance_turn", _fake_advance)

    gen = interviews_stream._advance_stream(interview_id)
    assert "reasoning" in await gen.__anext__()
    await asyncio.wait_for(started.wait(), timeout=5)
    await gen.aclose()

    assert cancelled.is_set()
    pending = [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task() and not task.done()
    ]
    assert pending == []


_FIELDS = '{"research_challenge": "Reverse fibrosis", "completed": false}'


def _block(body: str = _FIELDS) -> str:
    return f"{OPEN_MARKER}\n{body}\n{CLOSE_MARKER}"


class _Streamed(NamedTuple):
    relayed: str
    whole: str
    fields: dict[str, Any] | None


def _stream(deltas: list[str]) -> _Streamed:
    splitter = TurnSplitter()
    relayed = [splitter.feed(delta) for delta in deltas]
    trailing, whole, fields = splitter.finish()
    return _Streamed("".join(relayed) + trailing, whole, fields)


def test_split_separates_prose_from_parsed_fields() -> None:
    _, prose, fields = _stream([f"Which model system?\n\n{_block()}"])

    assert prose == "Which model system?"
    assert fields == {
        "research_challenge": "Reverse fibrosis",
        "completed": False,
    }


def test_split_without_a_block_keeps_the_prose_and_reports_no_fields() -> None:
    _, prose, fields = _stream(["Which model system?"])

    assert prose == "Which model system?"
    assert fields is None


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ('{"research_challenge": "Reverse', "truncated mid-write"),
        ("not json at all", "not JSON"),
        ('["a", "b"]', "JSON, but not an object"),
    ],
)
def test_split_reports_no_fields_for_an_unusable_block(
    body: str, reason: str
) -> None:
    _, prose, fields = _stream([f"Question?\n{OPEN_MARKER}\n{body}"])

    assert prose == "Question?", reason
    assert fields is None, reason


def test_splitter_streams_prose_and_parses_the_block() -> None:
    streamed = _stream(["Which ", "model ", "system?\n\n", _block()])

    assert streamed.relayed == "Which model system?\n\n"
    assert streamed.whole == "Which model system?"
    assert streamed.fields == {
        "research_challenge": "Reverse fibrosis",
        "completed": False,
    }


@pytest.mark.parametrize(
    "deltas",
    [
        ["Question?", "<run_", "spec>", _FIELDS, CLOSE_MARKER],
        ["Question?", "<", "run_spec>", _FIELDS, CLOSE_MARKER],
        ["Question?<r", "un_s", "pec>", _FIELDS, CLOSE_MARKER],
        ["Question?", "<run_spec>" + _FIELDS + CLOSE_MARKER],
    ],
)
def test_marker_split_across_deltas_never_leaks_into_prose(
    deltas: list[str],
) -> None:
    # Buffer possible marker suffixes so raw wire markers never flash as
    # scientist-visible prose.
    streamed = _stream(deltas)

    assert streamed.relayed == "Question?"
    assert streamed.whole == "Question?"
    assert "<" not in streamed.relayed
    assert "run_spec" not in streamed.relayed
    assert streamed.fields == {
        "research_challenge": "Reverse fibrosis",
        "completed": False,
    }


def test_held_back_prose_is_flushed_when_the_turn_ends() -> None:
    # Flush marker-like tails that never complete or valid prose silently
    # disappears.
    assert _stream(["Compare A ", "< B"]).relayed == "Compare A < B"


def test_a_turn_that_is_only_a_block_relays_no_prose() -> None:
    streamed = _stream([_block()])

    assert streamed.relayed == ""
    assert streamed.whole == ""
    assert streamed.fields is not None


def test_single_delta_and_fragmented_turn_agree() -> None:
    text = f"**Bold** and a list:\n- one\n- two\n\n{_block()}"
    streamed = _stream(list(text))
    _, expected_prose, expected_fields = _stream([text])

    assert streamed.relayed.strip() == expected_prose
    assert streamed.whole == expected_prose
    assert streamed.fields == expected_fields
