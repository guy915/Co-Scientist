"""Tests for question answering."""

from __future__ import annotations

import dataclasses
import logging
import time
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

import app.qa.manifest as qa_run_state
from app import qa, store
from app.config import CONVERSATIONAL_REASONING_EFFORT, settings
from app.qa import QaRunContext, build_evidence_manifest, build_system_prompt
from app.store.models import RunRow
from tests._client import drain as _drain
from tests._client import fake_litellm as _fake_litellm
from tests._client import make_client as _client
from tests._client import wait_for_status as _wait_status
from tests._llm_fake_backend import install_completion_backend
from tests._process_mode_helpers import FakeProcessMode

# Tests for the Q&A prompt assembly and LLM-streaming path in ``app.qa``.
#
# ``build_evidence_manifest``'s cited-first ordering is covered in
# ``test_qa_grounding.py``; this file covers the remaining pure helpers
# (``build_system_prompt``, ``_format_manifest_for_prompt``,
# ``settings.effective_chat_model``, ``_citation_meta``) plus the streaming
# path,
# exercised through an installed fake completion backend.


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
    assert qa._citation_meta(manifest, "") == {"sources": manifest}


def test_citation_meta_is_none_when_both_are_empty() -> None:
    assert qa._citation_meta([], "") is None


def test_citation_meta_carries_reasoning_without_a_manifest() -> None:
    assert qa._citation_meta([], "Weighing two mechanisms.") == {
        "reasoning": "Weighing two mechanisms."
    }


def test_citation_meta_carries_both_when_both_are_present() -> None:
    manifest = [{"n": 1, "evidence_id": "e1"}]
    assert qa._citation_meta(manifest, "A thought.") == {
        "sources": manifest,
        "reasoning": "A thought.",
    }


# ---------------------------------------------------------------------------
# _stream_llm_deltas
# ---------------------------------------------------------------------------


def test_stream_llm_deltas_yields_only_nonempty_chunks(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    install_completion_backend(
        monkeypatch, (_fake_litellm(["Hello", "", " world"])).acompletion
    )

    assert _drain(qa.stream_llm_deltas("model", "sys prompt", "q?", [])) == [
        ("chunk", "Hello"),
        ("chunk", " world"),
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
    install_completion_backend(
        monkeypatch, (_fake_litellm(["Ans", "wer"])).acompletion
    )
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
    install_completion_backend(monkeypatch, (_fake_litellm(["Ok"])).acompletion)
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


def _thinking_litellm(reasoning: str, prose: str) -> SimpleNamespace:
    """A fake litellm whose stream reasons before it writes, as DeepSeek does.

    Mirrors ``test_run_start_announcement.py::_thinking_litellm`` --
    ``fake_litellm`` streams content deltas only, so the reasoning channel
    needs its own stand-in.
    """

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


def test_stream_answer_relays_and_persists_reasoning(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    reachable_provider: None,
) -> None:
    """The post-run chat already pays for reasoning.

    This is where it stops discarding it -- streamed as its own frame and
    persisted with the answer, exactly as ``run_start_announcement``
    already does.
    """
    install_completion_backend(
        monkeypatch,
        (
            _thinking_litellm("Checking the evidence first.", "Answer.")
        ).acompletion,
    )
    store.create_run(
        "goal",
        "default",
        "mock",
        {},
        store.RunCreateOptions(client_id="c4", db_path=isolated_db),
    )
    run_id = store.list_runs(client_id="c4", db_path=isolated_db)[0].id

    frames = _drain(
        qa.stream_answer(
            run_id,
            qa.QaQuestion(text="Q?", message_id=4),
            qa.QaAnswerInputs("sys prompt", []),
        )
    )

    body = "".join(frames)
    assert '"type": "reasoning"' in body
    assert body.index('"type": "reasoning"') < body.index('"type": "chunk"')
    msgs = store.list_messages(run_id, db_path=isolated_db)
    assert msgs[-1].content == "Answer."
    assert msgs[-1].meta == {"reasoning": "Checking the evidence first."}


def test_stream_answer_error_path_persists_and_emits_fallback(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_completion_backend(
        monkeypatch,
        (_fake_litellm([], raise_exc=RuntimeError("no key"))).acompletion,
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


# Endpoint tests for ``POST /api/runs/{id}/messages/ask``.
#
# Covers the provider branch: the keyless mock posture must yield a grounded
# offline answer (not an API-key error), while a configured provider still
# streams a model answer through the unchanged litellm path.


def _completed_run_id() -> str:
    """Create + run an offline engine workflow to done; return its run id."""
    c = _client()
    rid = c.post(
        "/api/runs",
        json={
            "research_goal": "Investigate ferroptosis in cancer",
            "tier": "express",
        },
    ).json()["id"]
    c.post(f"/api/runs/{rid}/start", json={})
    assert _wait_status(c, rid, "completed", timeout=30.0)
    return str(rid)


def test_ask_offline_returns_grounded_answer_not_error() -> None:
    """With no provider key (mock), the ask stream is a grounded answer."""
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

    # The persisted answer is grounded in the run's own artifacts.
    msgs = store.list_messages(rid)
    answer = next(
        m for m in reversed(msgs) if m.kind == "qa" and m.sender == "system"
    )
    assert "Investigate ferroptosis in cancer" in answer.content
    assert "offline mode" in answer.content.lower()


def test_ask_uses_real_llm_when_provider_key_present(
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    """A configured provider still streams through the litellm path."""
    rid = _completed_run_id()
    # The Q&A endpoint routes on the LLM backend now, not the retired mock
    # provider: a real (non-offline) backend takes the streaming litellm path.
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
    """Return the system prompt the Q&A endpoint would send for ``rid``."""
    from app import qa
    from app.runs import chat as runs_chat

    run = store.get_run(rid)
    assert run is not None
    return qa.build_system_prompt(runs_chat._gather_qa_context(run))


def test_the_prompt_carries_the_runs_progress_and_its_report() -> None:
    """The chat can answer "how is it going" and "what did it conclude".

    The scientist keeps talking to the chat after the run starts, so the
    context is not only the run's artifacts: what the prompt must carry is
    how far the run got, what it produced, and -- once it finishes -- what
    its report concluded.
    """
    prompt = _prompt_for(_completed_run_id())

    assert "Run status:" in prompt
    assert "Ideas generated so far:" in prompt
    assert "Final report:" in prompt
    assert "Ideas explored:" in prompt
    # Idea *titles* are in the prompt; their bodies are the tool's job.
    assert "call the search_ideas tool" in prompt


def test_a_running_run_carries_no_final_report_section() -> None:
    """A run still going must not be given an empty report to answer out of."""
    c = _client()
    rid = c.post(
        "/api/runs",
        json={"research_goal": "Investigate X", "tier": "express"},
    ).json()["id"]
    store.update_run_status(rid, store.RunStatus.RUNNING)

    prompt = _prompt_for(rid)

    assert "Run status:" in prompt
    assert "Final report:" not in prompt


# Tests for citation-grounded Q&A: the evidence manifest and message meta.
#
# ``build_evidence_manifest`` is a pure function (no DB), so it is tested
# directly. Message ``meta`` persistence is exercised through the store with an
# isolated per-test database.


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


def test_manifest_lists_cited_evidence_first() -> None:
    """Cited evidence is numbered before uncited evidence."""
    evidence = [_evidence("e1"), _evidence("e2"), _evidence("e3")]
    citations = [_citation("e3", "verified"), _citation("e1", "partial")]
    manifest = build_evidence_manifest(evidence, citations)

    # e3 and e1 are cited (in citation order), e2 trails as uncited.
    assert [m["evidence_id"] for m in manifest] == ["e3", "e1", "e2"]
    assert [m["n"] for m in manifest] == [1, 2, 3]
    assert manifest[0]["state"] == "verified"
    assert manifest[1]["state"] == "partial"


def test_system_prompt_enforces_grounding_only() -> None:
    """The Q&A prompt instructs answering only from the run's own artifacts.

    Grounding is the M7 invariant: the assistant must answer from the run's
    hypotheses/reviews/matches/evidence, cite only the numbered manifest, and
    decline rather than draw on outside knowledge.
    """
    prompt = build_system_prompt(
        QaRunContext(
            research_goal="A goal",
            hypotheses=[
                {
                    "title": "H1",
                    "elo_rating": 1200,
                    "win_count": 1,
                    "loss_count": 0,
                }
            ],
            reviews=[],
            matches=[],
            history=[],
            manifest=build_evidence_manifest([_evidence("e1")], []),
        ),
    )
    lowered = prompt.lower()
    # Claims about the run are confined to the run's own artifacts, and the
    # assistant declines rather than filling the gap when they fall short.
    assert "must come only from the context above" in lowered
    assert "do not contain the answer" in lowered
    # It grounds citations to the numbered manifest, never invented ones.
    assert "never invent a citation" in lowered
    # The run's own goal and hypothesis are in the grounding context.
    assert "A goal" in prompt
    assert "H1" in prompt


def test_manifest_keeps_strongest_state_per_evidence() -> None:
    """When an item is cited by several claims, the strongest state wins."""
    evidence = [_evidence("e1")]
    citations = [_citation("e1", "unsupported"), _citation("e1", "verified")]
    manifest = build_evidence_manifest(evidence, citations)
    assert manifest[0]["state"] == "verified"


def test_manifest_marks_uncited_availability() -> None:
    """Uncited, available evidence is labelled by its availability flag."""
    evidence = [_evidence("e1", available=True)]
    manifest = build_evidence_manifest(evidence, [])
    assert manifest[0]["state"] == "available"


def test_manifest_withholds_unavailable_evidence() -> None:
    """Uncited evidence that could not be resolved is withheld, not listed.

    An unavailable source has no content the model could ground a citation
    in, so it must not enter the numbered list at all -- there is nothing
    for [n] to point at.
    """
    evidence = [_evidence("e1", available=False)]
    manifest = build_evidence_manifest(evidence, [])
    assert manifest == []


def test_manifest_withholds_unsupported_citations() -> None:
    """A citation checked and found not to support its claim is withheld.

    Letting it into the context under the "unsupported" label still invites
    the model to cite it as though it were evidence.
    """
    evidence = [_evidence("e1"), _evidence("e2")]
    citations = [_citation("e1", "unsupported"), _citation("e2", "verified")]
    manifest = build_evidence_manifest(evidence, citations)
    assert [m["evidence_id"] for m in manifest] == ["e2"]


def test_manifest_includes_grounding_passage() -> None:
    """A source with an abstract carries a bounded passage to cite against.

    Not just a title.
    """
    evidence = [_evidence("e1", abstract="This paper shows X causes Y.")]
    manifest = build_evidence_manifest(evidence, [])
    assert manifest[0]["passage"] == "This paper shows X causes Y."


def test_manifest_passage_is_none_without_an_abstract() -> None:
    """A source with no abstract carries no passage, rather than a blank."""
    evidence = [_evidence("e1")]
    manifest = build_evidence_manifest(evidence, [])
    assert manifest[0]["passage"] is None


def test_manifest_passage_is_truncated() -> None:
    """A very long abstract is bounded so it cannot dominate the prompt."""
    evidence = [_evidence("e1", abstract="x" * 2000)]
    manifest = build_evidence_manifest(evidence, [])
    passage = manifest[0]["passage"]
    assert passage is not None
    assert len(passage) < 700
    assert passage.endswith("…")


def test_manifest_is_capped() -> None:
    """The manifest is bounded to keep the prompt size predictable."""
    evidence = [_evidence(f"e{i}") for i in range(30)]
    manifest = build_evidence_manifest(evidence, [], cap=12)
    assert len(manifest) == 12
    assert manifest[-1]["n"] == 12


def test_manifest_ignores_citations_to_unknown_evidence() -> None:
    """A citation pointing at missing evidence is skipped, not crashed on."""
    evidence = [_evidence("e1")]
    citations = [_citation("ghost", "verified"), _citation("e1", "partial")]
    manifest = build_evidence_manifest(evidence, citations)
    assert [m["evidence_id"] for m in manifest] == ["e1"]
    assert manifest[0]["state"] == "partial"


def test_message_meta_round_trips(isolated_db: str) -> None:
    """A message's structured meta survives a write/read cycle."""
    store.create_run(
        "rg",
        "default",
        "engine",
        {},
        store.RunCreateOptions(client_id="c1", db_path=isolated_db),
    )
    run_id = store.list_runs(client_id="c1", db_path=isolated_db)[0].id

    sources = [{"n": 1, "evidence_id": "e1", "title": "T", "state": "verified"}]
    store.append_message(
        store.NewMessage(
            run_id=run_id,
            sender="system",
            content="Answer [1].",
            kind="qa",
            meta={"sources": sources},
        ),
        db_path=isolated_db,
    )

    msgs = store.list_messages(run_id, db_path=isolated_db)
    assert len(msgs) == 1
    assert msgs[0].meta == {"sources": sources}
    assert msgs[0].to_dict()["meta"] == {"sources": sources}


def test_message_without_meta_is_none(isolated_db: str) -> None:
    """Messages written without meta read back as ``None`` (back-compat)."""
    store.create_run(
        "rg",
        "default",
        "engine",
        {},
        store.RunCreateOptions(client_id="c1", db_path=isolated_db),
    )
    run_id = store.list_runs(client_id="c1", db_path=isolated_db)[0].id
    store.append_message(
        store.NewMessage(
            run_id=run_id, sender="user", content="hi", kind="steering"
        ),
        db_path=isolated_db,
    )
    msgs = store.list_messages(run_id, db_path=isolated_db)
    assert msgs[0].meta is None


def test_stream_llm_deltas_requests_the_conversational_reasoning_tier(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
    """The interview and chat turns think at a lower tier than the science."""
    seen: dict[str, Any] = {}

    async def _capturing_acompletion(**kwargs: Any) -> Any:
        seen.update(kwargs)

        async def _chunks() -> AsyncIterator[Any]:
            delta = SimpleNamespace(content="hi", reasoning_content=None)
            yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)])

        return _chunks()

    install_completion_backend(
        monkeypatch,
        (SimpleNamespace(acompletion=_capturing_acompletion)).acompletion,
    )
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-chat")

    _drain(
        qa.stream_llm_deltas(
            settings.effective_chat_model, "sys prompt", "q?", []
        )
    )

    assert seen["reasoning_effort"] == CONVERSATIONAL_REASONING_EFFORT


# What the chat can see about a run's progress and its finished report.
#
# Covers ``app.qa.manifest``: the live-progress facts gathered while a run
# executes, the report synthesis carried once it completes, and the idea
# index that replaces dumping every idea into the prompt.


def _event(activity: str | None, event_type: str = "engine") -> dict[str, Any]:
    payload = {"activity": activity} if activity else {}
    return {"seq": 1, "type": event_type, "payload": payload, "created_at": 1.0}


# ---------------------------------------------------------------------------
# steps
# ---------------------------------------------------------------------------


def test_consecutive_events_of_one_activity_collapse_to_one_step() -> None:
    # A tournament wave is dozens of events of one kind; rendered raw it
    # would be the whole step narrative and crowd out everything before it.
    events = [
        _event("drafting"),
        _event("tournament"),
        _event("tournament"),
        _event("tournament"),
        _event("review"),
    ]
    assert qa_run_state._collapse_steps(events) == [
        "drafting",
        "tournament",
        "review",
    ]


def test_step_narrative_names_unclassified_events_by_type() -> None:
    # 'other' covers both a genuinely unclassifiable event and every
    # control-plane one, and the latter has a perfectly good name already.
    steps = qa_run_state._collapse_steps([_event("other", "lifecycle")])
    assert steps == ["lifecycle"]


def test_status_events_are_not_steps() -> None:
    assert qa_run_state._collapse_steps([_event(None, "status")]) == []


# ---------------------------------------------------------------------------
# gather_run_progress
# ---------------------------------------------------------------------------


def _seed_running_run() -> RunRow:
    """Create a real run row (the autouse isolated_db fixture owns the file)."""
    run = store.create_run("A goal", "standard", "engine", {})
    store.update_run_status(run.id, store.RunStatus.RUNNING)
    return dataclasses.replace(run, status="running")


def test_elapsed_is_measured_from_execution_start_not_draft_creation() -> None:
    # A plan drafted before lunch and started after it did not spend the
    # lunch break working, so the run row's created_at is the wrong clock.
    run = _seed_running_run()
    store.append_event(run.id, "lifecycle", {"event": "queued"})
    with store.connect() as conn:
        progress = qa_run_state.gather_run_progress(
            run, [], {"ideas": 2}, conn, now=time.time() + 120.0
        )

    assert progress.elapsed_seconds is not None
    assert 110.0 < progress.elapsed_seconds < 130.0
    assert progress.idea_count == 2
    assert progress.is_running


def test_a_run_that_never_started_reports_no_elapsed_time() -> None:
    run = _seed_running_run()
    with store.connect() as conn:
        progress = qa_run_state.gather_run_progress(
            run, [], {}, conn, now=time.time()
        )

    assert progress.elapsed_seconds is None
    assert "not started yet" in qa_run_state.render_progress(progress)


def test_only_meta_review_notes_count_as_conclusions() -> None:
    # Per-hypothesis reviews are critiques of one idea; the meta-review is
    # the only synthesis the store holds before a report exists.
    run = _seed_running_run()
    reviews = [
        {"reviewer_agent": "review", "summary": "one idea's critique"},
        {"reviewer_agent": "meta_review", "summary": "the pattern so far"},
    ]
    with store.connect() as conn:
        progress = qa_run_state.gather_run_progress(
            run, reviews, {}, conn, now=time.time()
        )

    assert progress.conclusions == ["the pattern so far"]


def test_a_finished_run_stops_its_elapsed_clock() -> None:
    # The clock stops at completion; a run finished an hour ago still
    # reports how long it took, not how long ago it was.
    run = _seed_running_run()
    store.append_event(run.id, "lifecycle", {"event": "queued"})
    run = dataclasses.replace(
        run, status="completed", completed_at=time.time() + 60.0
    )
    with store.connect() as conn:
        progress = qa_run_state.gather_run_progress(
            run, [], {}, conn, now=time.time() + 9_000.0
        )

    assert progress.elapsed_seconds is not None
    assert progress.elapsed_seconds < 120.0
    assert not progress.is_running


def test_progress_renders_the_current_step_only_while_running() -> None:
    running = qa_run_state.RunProgress(
        status="running",
        elapsed_seconds=90.0,
        idea_count=4,
        evidence_count=7,
        match_count=2,
        active_task="engine.node.ranking",
        completed_tasks=11,
        queued_tasks=3,
        steps=["drafting", "tournament"],
        conclusions=[],
    )
    rendered = qa_run_state.render_progress(running)

    assert "Ideas generated so far: 4" in rendered
    assert "engine.node.ranking" in rendered
    assert "drafting, tournament" in rendered
    # A finished run has no current step, and saying "between steps" of one
    # that ended reads as a run still going.
    finished = qa_run_state.render_progress(
        qa_run_state.RunProgress(
            status="completed",
            elapsed_seconds=90.0,
            idea_count=4,
            evidence_count=7,
            match_count=2,
            active_task=None,
            completed_tasks=11,
            queued_tasks=0,
            steps=[],
            conclusions=[],
        )
    )
    assert "Current step" not in finished
    assert "completed" in finished


# ---------------------------------------------------------------------------
# report facts
# ---------------------------------------------------------------------------


def _payload() -> dict[str, Any]:
    return {
        "idea_count": 22,
        "hypothesis_count": 8,
        "verified_count": 3,
        "evidence_count": 47,
        "research_overview": {
            "summary": "The run converged on lipid repair.",
            "specific_aims": ["Aim one", "Aim two"],
        },
        "meta_review": {
            "common_strengths": ["mechanistic detail"],
            "common_weaknesses": ["thin controls"],
            "strategic_recommendations": [
                {
                    "focus_area": "Validation",
                    "recommendation": "run isogenic controls",
                    "justification": "because",
                },
                "a bare recommendation",
            ],
        },
        "agent_insights": {"key_findings": ["GPX4-independent repair"]},
    }


def test_report_facts_carry_the_synthesis_and_every_count() -> None:
    facts = qa_run_state.build_report_facts(_payload())

    assert facts.summary == "The run converged on lipid repair."
    assert facts.aims == ["Aim one", "Aim two"]
    assert facts.key_findings == ["GPX4-independent repair"]
    assert facts.weaknesses == ["thin controls"]
    # The three idea counts name different things and must not collapse
    # into one another.
    assert facts.counts["idea_count"] == 22
    assert facts.counts["hypothesis_count"] == 8
    assert facts.counts["verified_count"] == 3


def test_structured_and_bare_recommendations_both_render() -> None:
    facts = qa_run_state.build_report_facts(_payload())
    assert facts.recommendations == [
        "Validation: run isogenic controls",
        "a bare recommendation",
    ]


def test_report_facts_tolerate_a_payload_with_nothing_in_it() -> None:
    # A run whose generation failed still finalizes, and its report's
    # sections are empty rather than absent.
    facts = qa_run_state.build_report_facts({})
    assert qa_run_state.render_report(facts).startswith("Ideas explored: 0")


def test_rendered_report_carries_each_section() -> None:
    rendered = qa_run_state.render_report(
        qa_run_state.build_report_facts(_payload())
    )
    assert "Overview: The run converged on lipid repair." in rendered
    assert "- Aim one" in rendered
    assert "Recommended next steps" in rendered


# ---------------------------------------------------------------------------
# idea index
# ---------------------------------------------------------------------------


def test_idea_index_names_every_idea_not_just_the_leaders() -> None:
    # The index is what tells the model which ideas it can look up; an idea
    # it cannot see exists is one it will never search for.
    ideas = [
        {"title": f"Idea {n}", "elo_rating": 1200 + n, "status": "active"}
        for n in range(12)
    ]
    index = qa_run_state.render_idea_index(ideas)
    assert index.count("\n") == 11
    assert "- Idea 11 (Elo 1211, active)" in index


def test_idea_index_says_how_many_it_could_not_name() -> None:
    ideas = [{"title": f"Idea {n}"} for n in range(45)]
    index = qa_run_state.render_idea_index(ideas)
    assert "...and 5 more (search to reach them)" in index


def test_idea_index_carries_a_verification_verdict_when_there_is_one() -> None:
    index = qa_run_state.render_idea_index(
        [
            {
                "title": "H",
                "status": "active",
                "verification_verdict": "supported",
            }
        ]
    )
    assert "supported" in index


def test_a_half_empty_recommendation_renders_without_a_dangling_colon() -> None:
    # A model that puts the whole recommendation in `focus_area` must not
    # render as a heading followed by a colon and nothing at all.
    facts = qa_run_state.build_report_facts(
        {
            "meta_review": {
                "strategic_recommendations": [
                    {
                        "focus_area": "Centre on homeostasis",
                        "recommendation": "",
                    },
                    {"focus_area": "", "recommendation": "Run the controls"},
                ]
            }
        }
    )
    assert facts.recommendations == [
        "Centre on homeostasis",
        "Run the controls",
    ]
