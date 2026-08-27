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
from typing import Any

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


def _every_section_inputs() -> tuple[list[Any], ...]:
    """Return (hyps, reviews, matches, history, manifest) for the prompt."""
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


def test_build_system_prompt_falls_back_when_sections_are_empty() -> None:
    prompt = qa.build_system_prompt(qa.QaRunContext("Goal", [], [], [], [], []))
    assert "(none yet)" in prompt
    assert "(none)" in prompt
    assert "(no evidence retrieved)" in prompt


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
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    monkeypatch.setitem(
        sys.modules, "litellm", _fake_litellm(["Hello", "", " world"])
    )

    assert _drain(qa.stream_llm_deltas("model", "sys prompt", "q?", [])) == [
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
        "goal",
        "default",
        "mock",
        {},
        store.RunCreateOptions(client_id="c1", db_path=isolated_db),
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
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    reachable_provider: None,
) -> None:
    monkeypatch.setitem(sys.modules, "litellm", _fake_litellm(["Ans", "wer"]))
    store.create_run(
        "goal",
        "default",
        "mock",
        {},
        store.RunCreateOptions(client_id="c1", db_path=isolated_db),
    )
    run_id = store.list_runs(client_id="c1", db_path=isolated_db)[0].id
    manifest = [
        {"n": 1, "evidence_id": "e1", "title": "T", "state": "verified"}
    ]

    frames = _drain(
        qa.stream_answer(
            run_id,
            qa.QaQuestion(text="Q?", message_id=1),
            qa.QaAnswerInputs("sys prompt", manifest),
        )
    )

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
        "goal",
        "default",
        "mock",
        {},
        store.RunCreateOptions(client_id="c2", db_path=isolated_db),
    )
    run_id = store.list_runs(client_id="c2", db_path=isolated_db)[0].id

    frames = _drain(
        qa.stream_answer(
            run_id,
            qa.QaQuestion(text="Q?", message_id=2),
            qa.QaAnswerInputs("sys prompt", []),
        )
    )

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
        "goal",
        "default",
        "mock",
        {},
        store.RunCreateOptions(client_id="c3", db_path=isolated_db),
    )
    run_id = store.list_runs(client_id="c3", db_path=isolated_db)[0].id

    frames = _drain(
        qa.stream_answer(
            run_id,
            qa.QaQuestion(text="Q?", message_id=3),
            qa.QaAnswerInputs("sys prompt", []),
        )
    )

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
        "Investigate ferroptosis", hyps, reviews, manifest, "Summarize this"
    )

    assert "Investigate ferroptosis" in answer
    assert "H1: rescue" in answer
    assert "1320" in answer
    assert "[1]" in answer  # cites the numbered manifest
    assert "Key paper" in answer


def test_build_offline_answer_echoes_the_question() -> None:
    """The offline answer states the question it is responding to."""
    answer = qa.build_offline_answer("Goal", [], [], [], "What about X?")
    assert "What about X?" in answer


def test_build_offline_answer_surfaces_question_matching_hypothesis() -> None:
    """A hypothesis matching the question's terms leads, even if lower-Elo.

    The offline answer must respond to what was asked rather than always
    reciting the same top-Elo summary regardless of the question.
    """
    hyps = [
        {
            "title": "H1: broad rescue pathway",
            "elo_rating": 1400,
            "win_count": 5,
        },
        {
            "title": "H2: ferroptosis specific mechanism",
            "elo_rating": 1200,
            "win_count": 1,
        },
    ]

    answer = qa.build_offline_answer(
        "Investigate cell death", hyps, [], [], "What about ferroptosis?"
    )

    lines = answer.splitlines()
    h1_line = next(i for i, line in enumerate(lines) if "H1:" in line)
    h2_line = next(i for i, line in enumerate(lines) if "H2:" in line)
    assert h2_line < h1_line


def test_offline_answer_falls_back_to_input_order_when_unrelated() -> None:
    """A question sharing no vocabulary reproduces the original ordering."""
    hyps = [
        {"title": "H1: alpha", "elo_rating": 1400, "win_count": 5},
        {"title": "H2: beta", "elo_rating": 1200, "win_count": 1},
    ]

    answer = qa.build_offline_answer(
        "Goal", hyps, [], [], "totally unrelated wombat"
    )

    lines = answer.splitlines()
    h1_line = next(i for i, line in enumerate(lines) if "H1:" in line)
    h2_line = next(i for i, line in enumerate(lines) if "H2:" in line)
    assert h1_line < h2_line


def test_build_offline_answer_handles_a_run_with_no_hypotheses() -> None:
    """With no hypotheses yet, the answer says so plainly rather than faking."""
    answer = qa.build_offline_answer("Goal", [], [], [], "Any results?")
    assert "no hypotheses" in answer.lower()


def test_stream_offline_answer_emits_sources_chunks_done_and_persists(
    isolated_db: str,
) -> None:
    """The offline stream mirrors the LLM SSE framing and persists it."""
    store.create_run(
        "goal",
        "default",
        "mock",
        {},
        store.RunCreateOptions(client_id="off1", db_path=isolated_db),
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
