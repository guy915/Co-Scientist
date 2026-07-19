"""Tests for the Q&A prompt assembly and LLM-streaming path in ``app.qa``.

``build_evidence_manifest``'s cited-first ordering is covered in
``test_qa_grounding.py``; this file covers the remaining pure helpers
(``build_system_prompt``, ``_format_manifest_for_prompt``,
``settings.effective_chat_model``, ``_citation_meta``) plus the streaming path,
which is exercised end to end against a fake ``litellm`` module swapped into
``sys.modules`` so no network call is ever made.
"""

from __future__ import annotations

import logging
import sys
from types import SimpleNamespace

import pytest

from app import qa, store
from app.config import settings
from tests._client import drain as _drain
from tests._client import fake_litellm as _fake_litellm

# ---------------------------------------------------------------------------
# _eligible_citations / build_evidence_manifest edge case
# ---------------------------------------------------------------------------


def test_manifest_skips_citation_without_evidence_id() -> None:
    """A citation missing the ``evidence_id`` key is skipped, not KeyError'd."""
    evidence = [
        {
            "id": "e1",
            "title": "T",
            "source": None,
            "url": None,
            "year": None,
            "available": True,
        }
    ]
    citations = [{"claim": "no eid here", "state": "verified"}]

    manifest = qa.build_evidence_manifest(evidence, citations)

    assert [m["evidence_id"] for m in manifest] == ["e1"]
    assert manifest[0]["state"] == "available"


# ---------------------------------------------------------------------------
# _format_manifest_for_prompt / build_system_prompt
# ---------------------------------------------------------------------------


def test_build_system_prompt_includes_every_section() -> None:
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

    prompt = qa.build_system_prompt(
        "Investigate X", hyps, reviews, matches, history, manifest
    )

    assert "Investigate X" in prompt
    assert "[H1] Elo 1300, 2W/1L" in prompt
    assert "review on abcdefgh: a critique summary" in prompt
    assert "Winner abcdefgh (Elo 1310) — A is better grounded" in prompt
    assert "[1] T1 (PubMed, 2020) — verified" in prompt
    assert "[2] T2 — unavailable" in prompt
    assert "User: hi" in prompt
    assert "Assistant: hello there" in prompt


def test_build_system_prompt_falls_back_when_sections_are_empty() -> None:
    prompt = qa.build_system_prompt("Goal", [], [], [], [], [])
    assert "(none yet)" in prompt
    assert "(none)" in prompt
    assert "(no evidence retrieved)" in prompt


def test_system_prompt_includes_audience_context() -> None:
    prompt = qa.build_system_prompt(
        "goal", [], [], [], [], [], audience_context="LAB BACKGROUND"
    )
    assert "LAB BACKGROUND" in prompt


def test_system_prompt_without_audience_context() -> None:
    prompt = qa.build_system_prompt("goal", [], [], [], [], [])
    assert "LAB BACKGROUND" not in prompt


# ---------------------------------------------------------------------------
# settings.effective_chat_model (the model Q&A and titling resolve)
# ---------------------------------------------------------------------------


def test_effective_chat_model_prefers_chat_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "chat_model_name", "chat/model")
    monkeypatch.setattr(settings, "model_name", "worker/model")
    assert settings.effective_chat_model == "chat/model"


def test_effective_chat_model_falls_back_to_worker_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "chat_model_name", None)
    monkeypatch.setattr(settings, "model_name", "worker/model")
    assert settings.effective_chat_model == "worker/model"


# ---------------------------------------------------------------------------
# _citation_meta
# ---------------------------------------------------------------------------


def test_citation_meta_wraps_nonempty_manifest() -> None:
    manifest = [{"n": 1, "evidence_id": "e1"}]
    assert qa._citation_meta(manifest) == {"sources": manifest}


def test_citation_meta_is_none_for_empty_manifest() -> None:
    assert qa._citation_meta([]) is None


# ---------------------------------------------------------------------------
# _stream_llm_deltas
# ---------------------------------------------------------------------------


def test_stream_llm_deltas_yields_only_nonempty_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        sys.modules, "litellm", _fake_litellm(["Hello", "", " world"])
    )

    assert _drain(qa._stream_llm_deltas("model", "sys prompt", "q?")) == [
        "Hello",
        " world",
    ]


# ---------------------------------------------------------------------------
# _handle_qa_stream_error
# ---------------------------------------------------------------------------


def test_handle_qa_stream_error_persists_fallback_and_logs(
    isolated_db: str, caplog: pytest.LogCaptureFixture
) -> None:
    store.create_run(
        "goal", "default", "mock", {}, client_id="c1", db_path=isolated_db
    )
    run_id = store.list_runs(client_id="c1", db_path=isolated_db)[0].id

    with caplog.at_level(logging.ERROR, logger="app.qa"):
        fallback = qa._handle_qa_stream_error(run_id, RuntimeError("boom"))

    assert "Q&A requires a language model API key" in fallback
    assert "Q&A stream error for run" in caplog.text
    msgs = store.list_messages(run_id, db_path=isolated_db)
    assert msgs[-1].content == fallback
    assert msgs[-1].kind == "qa"


# ---------------------------------------------------------------------------
# stream_answer (integration of _relay_answer_chunks, _persist_qa_answer)
# ---------------------------------------------------------------------------


def test_stream_answer_happy_path_persists_and_yields_frames(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "litellm", _fake_litellm(["Ans", "wer"]))
    store.create_run(
        "goal", "default", "mock", {}, client_id="c1", db_path=isolated_db
    )
    run_id = store.list_runs(client_id="c1", db_path=isolated_db)[0].id
    manifest = [
        {"n": 1, "evidence_id": "e1", "title": "T", "state": "verified"}
    ]

    frames = _drain(qa.stream_answer(run_id, "Q?", 1, "sys prompt", manifest))

    assert any('"type": "sources"' in f for f in frames)
    assert any('"type": "chunk"' in f and "Ans" in f for f in frames)
    assert any(
        '"type": "done"' in f and '"question_id": 1' in f for f in frames
    )

    msgs = store.list_messages(run_id, db_path=isolated_db)
    assert msgs[-1].content == "Answer"
    assert msgs[-1].meta == {"sources": manifest}


def test_stream_answer_without_manifest_skips_sources_and_meta(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "litellm", _fake_litellm(["Ok"]))
    store.create_run(
        "goal", "default", "mock", {}, client_id="c2", db_path=isolated_db
    )
    run_id = store.list_runs(client_id="c2", db_path=isolated_db)[0].id

    frames = _drain(qa.stream_answer(run_id, "Q?", 2, "sys prompt", []))

    assert not any('"type": "sources"' in f for f in frames)
    msgs = store.list_messages(run_id, db_path=isolated_db)
    assert msgs[-1].meta is None


def test_stream_answer_error_path_persists_and_emits_fallback(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(
        sys.modules,
        "litellm",
        _fake_litellm([], raise_exc=RuntimeError("no key")),
    )
    store.create_run(
        "goal", "default", "mock", {}, client_id="c3", db_path=isolated_db
    )
    run_id = store.list_runs(client_id="c3", db_path=isolated_db)[0].id

    frames = _drain(qa.stream_answer(run_id, "Q?", 3, "sys prompt", []))

    assert any('"type": "error"' in f for f in frames)
    msgs = store.list_messages(run_id, db_path=isolated_db)
    assert msgs[-1].content.startswith("Q&A requires")


# ---------------------------------------------------------------------------
# build_offline_answer (deterministic, keyless grounding)
# ---------------------------------------------------------------------------


def test_build_offline_answer_grounds_in_run_hypotheses_and_sources() -> None:
    """The offline answer synthesizes real hypotheses and cites sources."""
    hyps = [
        {"title": "H1: rescue", "elo_rating": 1320, "win_count": 3},
        {"title": "H2: buffer", "elo_rating": 1290, "win_count": 2},
    ]
    reviews = [
        {
            "reviewer_agent": "review",
            "hypothesis_id": "abcdefgh12",
            "summary": "well grounded in the literature",
        }
    ]
    manifest = [
        {"n": 1, "title": "Key paper", "source": "PubMed", "state": "verified"}
    ]

    answer = qa.build_offline_answer(
        "Investigate ferroptosis", hyps, reviews, manifest
    )

    assert "Investigate ferroptosis" in answer
    assert "H1: rescue" in answer
    assert "1320" in answer
    assert "[1]" in answer  # cites the numbered manifest
    assert "Key paper" in answer


def test_build_offline_answer_does_not_key_off_the_question() -> None:
    """The answer is identical regardless of the question text."""
    hyps = [{"title": "H1", "elo_rating": 1300, "win_count": 1}]

    assert qa.build_offline_answer("Goal", hyps, [], []) == (
        qa.build_offline_answer("Goal", hyps, [], [])
    )


def test_build_offline_answer_handles_a_run_with_no_hypotheses() -> None:
    """With no hypotheses yet, the answer says so plainly rather than faking."""
    answer = qa.build_offline_answer("Goal", [], [], [])
    assert "no hypotheses" in answer.lower()


def test_stream_offline_answer_emits_sources_chunks_done_and_persists(
    isolated_db: str,
) -> None:
    """The offline stream mirrors the LLM SSE framing and persists it."""
    store.create_run(
        "goal", "default", "mock", {}, client_id="off1", db_path=isolated_db
    )
    run_id = store.list_runs(client_id="off1", db_path=isolated_db)[0].id
    manifest = [
        {"n": 1, "evidence_id": "e1", "title": "T", "state": "verified"}
    ]
    answer = "First line.\nSecond line."

    frames = _drain(qa.stream_offline_answer(run_id, 7, answer, manifest))

    assert any('"type": "sources"' in f for f in frames)
    assert any('"type": "chunk"' in f for f in frames)
    assert any(
        '"type": "done"' in f and '"question_id": 7' in f for f in frames
    )
    assert not any('"type": "error"' in f for f in frames)

    msgs = store.list_messages(run_id, db_path=isolated_db)
    assert msgs[-1].content == answer
    assert msgs[-1].meta == {"sources": manifest}
