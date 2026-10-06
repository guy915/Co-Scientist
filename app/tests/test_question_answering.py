from __future__ import annotations

import dataclasses
import time
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

import app.qa.manifest as qa_run_state
from app import qa
from app.config import settings
from app.qa import build_evidence_manifest
from app.store import db, runs
from app.store import events as store_events
from app.store import messages as store
from app.store.messages import NewMessage
from app.store.models import RunRow, RunStatus
from tests._client import create_run as _create_run
from tests._client import drain as _drain
from tests._client import fake_litellm as _fake_litellm
from tests._client import make_client as _client
from tests._client import wait_for_status as _wait_status
from tests._llm_fake_backend import install_completion_backend
from tests._process_mode_helpers import FakeProcessMode
from tests._store_helpers import seed_run


def _every_section_inputs() -> tuple[list[Any], ...]:
    hyps = [
        {"title": "H1", "elo_rating": 1300, "win_count": 2, "loss_count": 1}
    ]
    reviews = [
        {
            "reviewer_agent": "review",
            "hypothesis_id": "abcdefgh12",
            "summary": "a critique summary",
        }
    ]
    matches = [
        {
            "winner_id": "abcdefgh12",
            "winner_elo_after": 1310,
            "rationale": "A is better grounded",
        }
    ]
    history = [
        SimpleNamespace(sender="user", content="hi"),
        SimpleNamespace(sender="system", content="hello there"),
    ]
    manifest = [
        {
            "n": 1,
            "title": "T1",
            "source": "PubMed",
            "year": 2020,
            "state": "verified",
        },
        {
            "n": 2,
            "title": "T2",
            "source": None,
            "year": None,
            "state": "unavailable",
        },
    ]
    return hyps, reviews, matches, history, manifest


def test_build_system_prompt_includes_every_section() -> None:
    hyps, reviews, matches, history, manifest = _every_section_inputs()

    prompt = qa.build_system_prompt(
        qa.QaRunContext(
            "Investigate X", hyps, reviews, matches, history, manifest
        )
    )

    assert "Investigate X" in prompt
    assert "- H1 (Elo 1300, active)" in prompt
    assert "review on abcdefgh: a critique summary" in prompt
    assert "Winner abcdefgh (Elo 1310) — A is better grounded" in prompt
    assert "[1] T1 (PubMed, 2020) — verified" in prompt
    assert "[2] T2 — unavailable" in prompt
    assert "User: hi" in prompt
    assert "Assistant: hello there" in prompt


def _thinking_litellm(reasoning: str, prose: str) -> SimpleNamespace:

    async def _chunk_stream() -> AsyncIterator[Any]:
        for field, text in (
            ("reasoning_content", reasoning),
            ("content", prose),
        ):
            delta = SimpleNamespace(content=None, reasoning_content=None)
            setattr(delta, field, text)
            yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)])

    async def _acompletion(**_kwargs: Any) -> AsyncIterator[Any]:
        return _chunk_stream()

    return SimpleNamespace(acompletion=_acompletion)


def _stream_answer(
    db_path: str, manifest: list[dict[str, Any]]
) -> tuple[str, Any]:
    run = seed_run("goal", profile="default", client_id="c1", db_path=db_path)
    question = store.append_message(NewMessage(run.id, "user", "Q?", "qa"))
    frames = _drain(
        qa.stream_answer(
            run.id,
            qa.QaQuestion(text="Q?", message_id=question.id),
            qa.QaAnswerInputs("sys prompt", manifest),
        )
    )
    return "".join(frames), store.list_messages(run.id, db_path=db_path)[-1]


def test_a_streamed_answer_relays_frames_and_persists_sources_or_reasoning(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    reachable_provider: None,
) -> None:
    manifest = [
        {"n": 1, "evidence_id": "e1", "title": "T", "state": "verified"}
    ]
    install_completion_backend(
        monkeypatch, _fake_litellm(["Ans", "", "wer"]).acompletion
    )
    body, answer = _stream_answer(isolated_db, manifest)
    assert '"type": "sources"' in body
    assert '"type": "chunk"' in body
    assert '"type": "done"' in body
    assert (answer.content, answer.meta) == ("Answer", {"sources": manifest})

    install_completion_backend(
        monkeypatch,
        _thinking_litellm("Checking the evidence", "Answer.").acompletion,
    )
    body, answer = _stream_answer(isolated_db, [])
    assert body.index('"type": "reasoning"') < body.index('"type": "chunk"')
    assert '"type": "sources"' not in body
    assert answer.content == "Answer."
    assert answer.meta == {"reasoning": "Checking the evidence"}


def test_a_failed_model_call_persists_and_emits_the_fallback_answer(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_completion_backend(
        monkeypatch,
        _fake_litellm([], raise_exc=RuntimeError("no key")).acompletion,
    )

    body, answer = _stream_answer(isolated_db, [])

    assert '"type": "error"' in body
    assert answer.content.startswith("Q&A requires")


def _completed_run_id() -> str:
    c = _client()
    rid = _create_run(
        c, "Investigate ferroptosis in cancer", tier="express"
    ).json()["id"]
    c.post(f"/api/runs/{rid}/start", json={})
    assert _wait_status(c, rid, "completed", timeout=30.0)
    return str(rid)


def test_ask_offline_returns_grounded_answer_not_error() -> None:
    rid = _completed_run_id()
    c = _client()

    res = c.post(f"/api/runs/{rid}/messages/ask", json={"question": "Summary?"})

    assert res.status_code == 200
    body = res.text
    assert '"type": "chunk"' in body
    assert '"type": "done"' in body
    assert '"type": "error"' not in body
    assert "requires a language model" not in body
    assert "requires an API key" not in body

    msgs = store.list_messages(rid)
    answer = next(
        m for m in reversed(msgs) if m.kind == "qa" and m.sender == "system"
    )
    assert "Investigate ferroptosis in cancer" in answer.content
    assert "offline mode" in answer.content.lower()


def test_ask_uses_real_llm_when_provider_key_present(
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    rid = _completed_run_id()
    fake_process_mode.online()
    install_completion_backend(
        monkeypatch, (_fake_litellm(["Model ", "text"])).acompletion
    )

    c = _client()
    res = c.post(f"/api/runs/{rid}/messages/ask", json={"question": "Summary?"})

    assert res.status_code == 200
    body = res.text
    assert "Model " in body and "text" in body
    assert "offline mode" not in body.lower()

    msgs = store.list_messages(rid)
    answer = next(
        m for m in reversed(msgs) if m.kind == "qa" and m.sender == "system"
    )
    assert answer.content == "Model text"


def _prompt_for(rid: str) -> str:
    from app import qa
    from app.runs import chat as runs_chat

    run = runs.get_run(rid)
    assert run is not None
    return qa.build_system_prompt(runs_chat._gather_qa_context(run))


def test_the_prompt_carries_the_runs_progress_and_its_report() -> None:
    prompt = _prompt_for(_completed_run_id())

    assert "Run status:" in prompt
    assert "Ideas generated so far:" in prompt
    assert "Final report:" in prompt
    assert "Ideas explored:" in prompt
    assert "call the search_ideas tool" in prompt


def test_a_running_run_carries_no_final_report_section() -> None:
    c = _client()
    rid = _create_run(c, "Investigate X", tier="express").json()["id"]
    runs.update_run_status(rid, RunStatus.RUNNING)

    prompt = _prompt_for(rid)

    assert "Run status:" in prompt
    assert "Final report:" not in prompt


def _evidence(eid: str, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": eid,
        "title": f"Title {eid}",
        "source": "PubMed",
        "url": f"https://example/{eid}",
        "year": 2023,
        "available": True,
    }
    base.update(over)
    return base


def _citation(eid: str, state: str) -> dict[str, Any]:
    return {"evidence_id": eid, "state": state, "claim": "c"}


def _seed_running_run() -> RunRow:
    run = seed_run("A goal")
    runs.update_run_status(run.id, RunStatus.RUNNING)
    return dataclasses.replace(run, status="running")


def test_elapsed_is_measured_from_execution_start_not_draft_creation() -> None:
    run = _seed_running_run()
    store_events.append_event(run.id, "lifecycle", {"event": "queued"})
    with db.connect() as conn:
        progress = qa_run_state.gather_run_progress(
            run, [], {"ideas": 2}, conn, now=time.time() + 120.0
        )

    assert progress.elapsed_seconds is not None
    assert 110.0 < progress.elapsed_seconds < 130.0
    assert progress.idea_count == 2
    assert progress.is_running


@pytest.mark.parametrize(
    ("chat_model", "expected"),
    [("chat/model", "chat/model"), (None, "worker/model")],
)
def test_the_chat_model_falls_back_to_the_worker_model(
    monkeypatch: pytest.MonkeyPatch, chat_model: str | None, expected: str
) -> None:
    monkeypatch.setattr(settings, "chat_model_name", chat_model)
    monkeypatch.setattr(settings, "model_name", "worker/model")
    assert settings.effective_chat_model == expected


@pytest.mark.parametrize(
    ("evidence", "citations", "expected"),
    [
        (
            [_evidence("e1"), _evidence("e2"), _evidence("e3")],
            [_citation("e3", "verified"), _citation("e1", "partial")],
            [("e3", "verified"), ("e1", "partial"), ("e2", "available")],
        ),
        (
            [_evidence("e1")],
            [_citation("e1", "unsupported"), _citation("e1", "verified")],
            [("e1", "verified")],
        ),
        (
            [_evidence("e1"), _evidence("e2", available=False)],
            [],
            [("e1", "available")],
        ),
        (
            [_evidence("e1"), _evidence("e2")],
            [_citation("e1", "unsupported"), _citation("e2", "verified")],
            [("e2", "verified")],
        ),
        (
            [_evidence("e1")],
            [
                _citation("ghost", "verified"),
                {"claim": "no evidence id", "state": "verified"},
                _citation("e1", "partial"),
            ],
            [("e1", "partial")],
        ),
    ],
    ids=[
        "cited-first",
        "strongest-state",
        "unavailable-uncited-withheld",
        "unsupported-withheld",
        "unknown-or-anonymous-citations-ignored",
    ],
)
def test_manifest_lists_only_citable_evidence_strongest_state_first(
    evidence: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    expected: list[tuple[str, str]],
) -> None:
    manifest = build_evidence_manifest(evidence, citations)

    assert [(m["evidence_id"], m["state"]) for m in manifest] == expected
    assert [m["n"] for m in manifest] == list(range(1, len(expected) + 1))
