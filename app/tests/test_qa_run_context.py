from __future__ import annotations

import json
from typing import Any

import pytest

from app import qa
from app.qa import artifacts, snapshot
from app.runs.chat import _gather_qa_context
from app.store import checkpoints, db, hypotheses, interviews, runs
from app.store.checkpoints import NewCheckpoint
from app.store.models import RunRow, RunStatus
from app.store.runs import RunCreateOptions


def _run(config: dict[str, Any] | None = None) -> RunRow:
    run = runs.create_run(
        "Test scientific goal",
        "express",
        "mock",
        config or {},
        options=RunCreateOptions(client_id="owner"),
    )
    runs.update_run_status(run.id, RunStatus.RUNNING)
    result = runs.get_run(run.id)
    assert result is not None
    return result


def _checkpoint(run: Any, state: dict[str, Any], version: int = 1) -> None:
    checkpoints.save_checkpoint(
        run.id,
        NewCheckpoint(
            stage="reflection",
            schema_version=version,
            last_event_seq=0,
            state={"version": version, "state": state},
        ),
    )


def test_mid_run_reads_committed_science_without_draining_or_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run()
    state = {
        "hypotheses": [
            {
                "id": "h1",
                "title": "Lipid repair",
                "text": "Block lipid repair",
                "deep_verification_verdict": "unproven",
                "reviews": [
                    {
                        "review_summary": "Needs replication",
                        "reviewer": "reflection",
                    }
                ],
            }
        ],
        "articles": [
            {"title": "Full literature", "abstract": "Grounding text"}
        ],
        "tournament_matchups": [
            {"winner_id": "h1", "rationale": "Better controlled"}
        ],
        "meta_review": {"conclusion": "Still preliminary"},
        "supervisor_guidance": {"goal": "Test replication"},
        "constraints": ["Human cells"],
        "model_name": "secret runtime route",
    }
    _checkpoint(run, state)
    assert hypotheses.list_hypotheses(run.id) == []
    original = db.connect
    writes: list[str] = []
    from contextlib import contextmanager

    @contextmanager
    def readonly() -> Any:
        with original() as conn:
            conn.execute("PRAGMA query_only=ON")
            conn.set_trace_callback(writes.append)
            yield conn

    monkeypatch.setattr(db, "connect", readonly)
    context = _gather_qa_context(run)
    assert context.hypotheses[0]["statement"] == "Block lipid repair"
    assert context.hypotheses[0]["verification_verdict"] == "unproven"
    assert context.progress and context.progress.idea_count == 1
    assert context.reviews[0]["summary"] == "Needs replication"
    assert context.matches[0]["rationale"] == "Better controlled"
    assert context.manifest == []  # checkpoint literature is not verified
    for section in (
        "articles",
        "meta_review",
        "supervisor_guidance",
        "constraints",
    ):
        result = json.loads(
            artifacts.retrieve(context.artifacts, {"section": section})
        )
        assert result["records"]
    assert "secret runtime route" not in json.dumps(context.artifacts)
    assert not any(
        sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for sql in writes
    )


def test_interview_owner_is_checked_and_all_answers_are_retrievable() -> None:
    interview = interviews.create_interview("owner", "Initial challenge")
    run = _run(
        {"interview_id": interview["id"], "requirements": ["No animal work"]}
    )
    context = _gather_qa_context(run)
    assert context.artifacts["interview"][1]["content"] == "Initial challenge"
    assert context.artifacts["setup"][0]["requirements"] == ["No animal work"]
    run.client_id = "other"
    assert "interview" not in _gather_qa_context(run).artifacts


def test_unknown_checkpoint_version_falls_back_to_published_tables() -> None:
    run = _run()
    _checkpoint(
        run, {"hypotheses": [{"text": "Do not interpret"}]}, version=999
    )
    assert _gather_qa_context(run).hypotheses == []


def test_retrieval_reaches_records_and_text_beyond_both_caps() -> None:
    records = [{"text": "x" * 6000 + "LAST PAGE"} for _ in range(100)]
    result = json.loads(
        artifacts.retrieve(
            {"hypotheses": records},
            {
                "section": "hypotheses",
                "offset": 99,
                "character_offset": 6000,
                "limit": 999,
            },
        )
    )
    assert len(result["records"]) == 1
    assert "LAST PAGE" in result["records"][0]["text"]
    assert result["next_offset"] is None
    bounded = json.loads(
        artifacts.retrieve(
            {"hypotheses": records},
            {
                "section": "hypotheses",
                "limit": 999,
            },
        )
    )
    assert len(bounded["records"]) == 3
    assert all(
        len(r["text"]) <= artifacts.CHUNK_CHARS for r in bounded["records"]
    )


def test_prompt_stays_bounded_and_always_retains_grounding_rules() -> None:
    from types import SimpleNamespace

    context = qa.QaRunContext(
        research_goal="a" * 100000,
        hypotheses=[
            snapshot.idea_view({"text": "b" * 100000}) for _ in range(100)
        ],
        reviews=[],
        matches=[],
        manifest=[],
        history=[SimpleNamespace(sender="user", content="c" * 100000)] * 100,
        artifacts={"hypotheses": []},
    )
    prompt = qa.build_system_prompt(context)
    assert len(prompt) < 26000
    assert "never invent a citation" in prompt
    assert "untrusted data" in prompt
    assert "search_run_artifacts" in prompt


def test_search_returns_matching_passage_beyond_first_chunk() -> None:
    result = json.loads(
        artifacts.retrieve(
            {"report": ["x" * 9000 + "Rare finding"]},
            {
                "section": "report",
                "query": "Rare finding",
            },
        )
    )
    assert "Rare finding" in result["records"][0]["text"]
    assert result["records"][0]["character_offset"] > 0
