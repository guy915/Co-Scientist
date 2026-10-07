import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest
from co_scientist.platform.llm.decisions import DecisionSettings, Question, SystemOneClient

from evaluations import decision_bakeoff
from evaluations.decision_cases import DecisionCase, read_corpus


def test_only_real_corpus_inputs_are_extracted_and_duplicate_text_is_removed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "recorded.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            "CREATE TABLE runs(id TEXT,research_goal TEXT,llm_backend TEXT);"
            "CREATE TABLE hypotheses(run_id TEXT,statement TEXT,mechanism TEXT,"
            "expected_effect TEXT,experimental_context TEXT);"
            "CREATE TABLE evidence(run_id TEXT,title TEXT,abstract TEXT);"
        )
        conn.executemany(
            "INSERT INTO runs VALUES (?,?,?)",
            [
                ("real", "goal", "real"),
                ("offline", "goal", "offline"),
            ],
        )
        conn.executemany(
            "INSERT INTO hypotheses VALUES (?,?,?,?,?)",
            [
                ("real", "hypothesis", "mechanism", "effect", "experiment"),
                ("real", "hypothesis", "mechanism", "effect", "experiment"),
                ("offline", "canned", "", "", ""),
            ],
        )
        conn.execute("INSERT INTO evidence VALUES ('real','paper','abstract')")
    hypotheses, papers = read_corpus(tmp_path)
    assert len(hypotheses) == len(papers) == 1
    assert hypotheses[0]["text"].startswith("hypothesis")


def test_small_panel_never_supplies_a_threshold_or_adoption_result() -> None:
    rows = [
        {
            "reference": {"winner": "A"},
            "decision": {"winner": "A"},
            "agrees": True,
            "confidence": 0.99,
        }
        for _ in range(99)
    ]
    result = decision_bakeoff.summarize("ranking_pairwise", rows)
    assert result["threshold"] is None
    assert result["held_out_cases"] == 0
    assert result["adoption_ready"] is False


def test_calibration_and_heldout_are_separate_and_errors_are_counted() -> None:
    rows = [
        {
            "reference": {"winner": "A"},
            "decision": {"winner": "A"},
            "agrees": True,
            "confidence": 0.99,
        }
        for _ in range(100)
    ]
    rows.extend(
        [
            {
                "reference": {"winner": "A"},
                "decision": {"winner": "B"},
                "agrees": False,
                "confidence": 0.99,
            },
            {"error": "TimeoutError"},
        ]
    )
    result = decision_bakeoff.summarize("ranking_pairwise", rows)
    assert result["threshold"] == 0.99
    assert result["accepted_held_out_agreement"] == 0
    assert result["errors"] == 1
    assert result["adoption_ready"] is False


def test_elo_replay_aligns_the_same_matchups_and_cascade_escalation() -> None:
    rows = [
        {
            "side_ids": ("first", "second"),
            "reference": {"winner": "A"},
            "decision": {"winner": "B"},
            "confidence": 0.6,
        }
    ]
    assert decision_bakeoff.elo_order_agreement(rows) == 0
    assert decision_bakeoff.elo_order_agreement(rows, threshold=0.9, cascade=True) == 1
    rows[0]["decision"] = {"winner": "A"}
    assert decision_bakeoff.elo_order_agreement(rows) == 1


def test_checkpoint_context_contains_review_data_without_credentials(tmp_path: Path) -> None:
    from evaluations.decision_cases import _checkpoint_sides

    review = {
        "review_summary": "review",
        "scores": {"novelty": 8},
        "safety_ethical_concerns": "none",
        "detailed_feedback": {},
        "constructive_feedback": "test",
        "overall_score": 8,
    }
    state = {
        "api_key": "credential-must-not-appear",
        "client_id": "owner-must-not-appear",
        "hypotheses": [
            {
                "text": "hypothesis",
                "reviews": [review],
                "reflection_notes": "recorded reflection",
                "api_key": "credential-must-not-appear",
                "owner": "owner-must-not-appear",
            }
        ],
    }
    with sqlite3.connect(tmp_path / "snapshots.db") as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE checkpoints(run_id TEXT,seq INT,state_json TEXT)")
        conn.execute("INSERT INTO checkpoints VALUES ('run',1,?)", (json.dumps({"state": state}),))
        sides = _checkpoint_sides(conn, "run")
    assert sides["hypothesis"]["review"]["overall_score"] == 8
    assert sides["hypothesis"]["reflection_notes"] == "recorded reflection"
    serialized = json.dumps(sides)
    assert "credential-must-not-appear" not in serialized
    assert "owner-must-not-appear" not in serialized


@pytest.mark.asyncio
async def test_panel_records_fresh_reference_and_fake_decision_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COSCIENTIST_DB_PATH", str(tmp_path / "admission.db"))

    async def reference(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"judgments": [{"relevance": 0.9}]}

    monkeypatch.setattr(decision_bakeoff, "call_llm_json", reference)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "model": "d1:free",
                "answers": {
                    "relevance": {
                        "type": "score",
                        "score": 3.9,
                        "confidence": 0.9,
                        "probabilities": {"0": 0, "1": 0, "2": 0, "3": 0.1, "4": 0.9},
                    }
                },
            },
        )
    )
    client = SystemOneClient(DecisionSettings(api_key="fake", enabled=True), transport=transport)
    case = DecisionCase(
        "id",
        "state",
        {},
        {"relevance": Question("score", "Rate", ("none", "slight", "partial", "strong", "direct"))},
    )
    report = await decision_bakeoff.run_panel(
        "literature_relevance", [case], client, "offline/deterministic", 0, tmp_path / "result.json"
    )
    assert report["summary"]["agreement"] == 1
    assert json.loads((tmp_path / "result.json").read_text())["rows"][0]["reference"] == {
        "relevance": 0.9
    }


def test_live_runner_rejects_presubmit_before_key_or_corpus_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setattr(
        "sys.argv",
        ["decision_bakeoff", "--site", "proximity", "--corpus", ".", "--output", "unused.json"],
    )
    with pytest.raises(ValueError, match="manual"):
        decision_bakeoff.main()


@pytest.mark.asyncio
async def test_account_metadata_excludes_key_and_identifying_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-key")
    original = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "data": {
                    "label": "private-key-label",
                    "key": "synthetic-key",
                    "is_free_tier": False,
                    "free_model_daily_requests": 7,
                }
            },
        )
    )
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs)
    )
    assert await decision_bakeoff.account_limits() == {
        "is_free_tier": False,
        "free_model_daily_requests": 7,
    }


@pytest.mark.asyncio
async def test_live_panel_marks_oversize_as_fallback_without_sending_or_truncating(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    questions = {"winner": Question("choice", "Pick", {"A": "first", "B": "second"})}
    cases = [
        DecisionCase("oversize", "full text " * 5000, {}, questions),
        DecisionCase("normal", "short state", {}, questions),
    ]
    seen = []

    async def panel(*args: Any) -> dict[str, Any]:
        seen.extend(args[1])
        return {"summary": {"completed_cases": len(args[1])}}

    async def limits() -> dict[str, Any]:
        return {"is_free_tier": False}

    monkeypatch.setenv("MODEL_NAME", "offline/deterministic")
    monkeypatch.setattr(decision_bakeoff, "run_panel", panel)
    monkeypatch.setattr(decision_bakeoff, "account_limits", limits)
    report = await decision_bakeoff.run_live(
        "ranking_pairwise", cases, DecisionSettings(), tmp_path / "result.json"
    )
    assert [case.identifier for case in seen] == ["normal"]
    assert report["preflight_oversized_ids"] == ["oversize"]
    assert cases[0].prompt == "full text " * 5000
