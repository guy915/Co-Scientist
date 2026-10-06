from __future__ import annotations

import dataclasses
import time
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

import app.qa.manifest as qa_run_state
from app import qa
from app.config import CONVERSATIONAL_REASONING_EFFORT, settings
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


def test_build_system_prompt_falls_back_when_sections_are_empty() -> None:
    prompt = qa.build_system_prompt(qa.QaRunContext("Goal", [], [], [], [], []))
    assert "(none yet)" in prompt
    assert "(none)" in prompt
    assert "(no evidence retrieved)" in prompt


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


def test_build_offline_answer_grounds_in_run_hypotheses_and_sources() -> None:
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
    assert "[1]" in answer
    assert "Key paper" in answer
    assert "Summarize this" in answer
    unrelated = qa.build_offline_answer(
        "Goal", hyps, [], [], "What about buffer?"
    )
    assert unrelated.index("H2: buffer") < unrelated.index("H1: rescue")
    assert (
        "no hypotheses"
        in qa.build_offline_answer("Goal", [], [], [], "Any results?").lower()
    )


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


def test_manifest_is_capped() -> None:
    evidence = [_evidence(f"e{i}") for i in range(30)]
    manifest = build_evidence_manifest(evidence, [], cap=12)
    assert len(manifest) == 12
    assert manifest[-1]["n"] == 12


def test_stream_llm_deltas_requests_the_conversational_reasoning_tier(
    monkeypatch: pytest.MonkeyPatch, reachable_provider: None
) -> None:
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


def test_a_run_that_never_started_reports_no_elapsed_time() -> None:
    run = _seed_running_run()
    with db.connect() as conn:
        progress = qa_run_state.gather_run_progress(
            run, [], {}, conn, now=time.time()
        )

    assert progress.elapsed_seconds is None
    assert "not started yet" in qa_run_state.render_progress(progress)


def test_only_meta_review_notes_count_as_conclusions() -> None:
    run = _seed_running_run()
    reviews = [
        {"reviewer_agent": "review", "summary": "one idea's critique"},
        {"reviewer_agent": "meta_review", "summary": "the pattern so far"},
    ]
    with db.connect() as conn:
        progress = qa_run_state.gather_run_progress(
            run, reviews, {}, conn, now=time.time()
        )

    assert progress.conclusions == ["the pattern so far"]


def test_a_finished_run_stops_its_elapsed_clock() -> None:
    run = _seed_running_run()
    store_events.append_event(run.id, "lifecycle", {"event": "queued"})
    run = dataclasses.replace(
        run, status="completed", completed_at=time.time() + 60.0
    )
    with db.connect() as conn:
        progress = qa_run_state.gather_run_progress(
            run, [], {}, conn, now=time.time() + 9_000.0
        )

    assert progress.elapsed_seconds is not None
    assert progress.elapsed_seconds < 120.0
    assert not progress.is_running


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
    assert facts.counts["idea_count"] == 22
    assert facts.counts["hypothesis_count"] == 8
    assert facts.counts["verified_count"] == 3


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


def test_manifest_passages_are_grounded_and_truncated() -> None:
    manifest = build_evidence_manifest(
        [
            _evidence("e1", abstract="This paper shows X causes Y."),
            _evidence("e2"),
            _evidence("e3", abstract="x" * 2000),
        ],
        [],
    )

    assert manifest[0]["passage"] == "This paper shows X causes Y."
    assert manifest[1]["passage"] is None
    assert len(manifest[2]["passage"]) < 700
    assert manifest[2]["passage"].endswith("…")


def test_report_facts_render_every_section_and_tolerate_nothing() -> None:
    rendered = qa_run_state.render_report(
        qa_run_state.build_report_facts(_payload())
    )
    assert "Overview: The run converged on lipid repair." in rendered
    assert "- Aim one" in rendered
    assert "Recommended next steps" in rendered
    assert "- Validation: run isogenic controls" in rendered
    assert "- a bare recommendation" in rendered
    half_empty = qa_run_state.build_report_facts(
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
    assert half_empty.recommendations == [
        "Centre on homeostasis",
        "Run the controls",
    ]
    empty = qa_run_state.build_report_facts({})
    assert qa_run_state.render_report(empty).startswith("Ideas explored: 0")


def test_the_idea_index_names_every_idea_and_counts_those_it_cannot() -> None:
    ideas = [
        {"title": f"Idea {n}", "elo_rating": 1200 + n, "status": "active"}
        for n in range(12)
    ]
    index = qa_run_state.render_idea_index(ideas)
    assert index.count("\n") == 11
    assert "- Idea 11 (Elo 1211, active)" in index
    verdict = qa_run_state.render_idea_index(
        [
            {
                "title": "H",
                "status": "active",
                "verification_verdict": "supported",
            }
        ]
    )
    assert "supported" in verdict
    overflow = qa_run_state.render_idea_index(
        [{"title": f"Idea {n}"} for n in range(45)]
    )
    assert "...and 5 more (search to reach them)" in overflow
