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
                    "usage_daily": "synthetic-key",
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


def test_relevance_calibration_preserves_whole_batches_and_reports_batch_risk() -> None:
    rows = []
    for batch, size in enumerate([8] + [10] * 13):
        names = [f"relevance_{i}" for i in range(1, size + 1)]
        reference = dict.fromkeys(names, 1.0)
        decision = dict(reference)
        if batch == 13:
            decision[names[0]] = 0.0
        rows.append(
            {
                "id": str(batch),
                "reference": reference,
                "decision": decision,
                "confidence": 0.99,
                "agrees": decision == reference,
                "answers": {name: {"confidence": 0.99} for name in names},
            }
        )
    summary = decision_bakeoff.summarize("literature_relevance", rows)
    assert summary["calibration_cases"] == 108
    assert summary["held_out_cases"] == 30
    assert summary["held_out_batches"] == 3
    assert summary["accepted_held_out_agreement"] == pytest.approx(29 / 30)
    assert summary["accepted_batch_agreement"] == pytest.approx(2 / 3)
    assert summary["adoption_ready"] is False


def test_reference_batch_reorders_indices_and_rejects_missing_labels() -> None:
    result = decision_bakeoff.reference_values(
        "literature_relevance",
        {"judgments": [{"index": 2, "relevance": 0.9}, {"index": 1, "relevance": 0.1}]},
        ["relevance_1", "relevance_2"],
    )
    assert result == {"relevance_1": 0.1, "relevance_2": 0.9}
    with pytest.raises(ValueError, match="incomplete"):
        decision_bakeoff.reference_values(
            "literature_relevance",
            {"judgments": [{"index": 1, "relevance": 0.1}]},
            ["relevance_1", "relevance_2"],
        )


@pytest.mark.asyncio
async def test_live_panel_receives_and_records_selected_pacing_without_provider_io(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    delays = []

    async def panel(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["continue_on_rate_limit"] is False
        delays.append(args[4])
        return {"summary": {"completed_cases": 0}, "rows": []}

    async def limits() -> dict[str, Any]:
        return {}

    monkeypatch.setenv("MODEL_NAME", "offline/deterministic")
    monkeypatch.setattr(decision_bakeoff, "run_panel", panel)
    monkeypatch.setattr(decision_bakeoff, "account_limits", limits)
    output = tmp_path / "report.json"
    report = await decision_bakeoff.run_live(
        "literature_relevance", [], DecisionSettings(), output, delay=30
    )
    assert delays == [30]
    assert report["evaluation_pacing_seconds"] == 30
    assert json.loads(output.read_text())["evaluation_pacing_seconds"] == 30


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("statuses", "continuation", "expected_cases"),
    [([429, 200, 429, 200], True, 4), ([429] * 5, True, 3), ([429, 200], False, 1)],
)
async def test_rate_limit_continuation_uses_distinct_cases_and_stops_when_bounded(
    statuses: list[int],
    continuation: bool,
    expected_cases: int,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from co_scientist.platform.llm.decisions import DecisionUnavailableError
    from co_scientist.platform.llm.decisions.types import Answer, DecisionResult

    decided = []
    sleeps = []

    async def reference(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"judgments": [{"relevance": 1.0}]}

    async def decide(state: str, questions: Any) -> DecisionResult:
        decided.append(state)
        if statuses[len(decided) - 1] == 429:
            raise DecisionUnavailableError(
                "limited", status_code=429, rate_limits={"retry-after": "1"}
            )
        return DecisionResult("d1:free", {"relevance": Answer("score", 4, 0.99, {"4": 1})}, 10)

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    client = SystemOneClient(DecisionSettings())
    monkeypatch.setattr(client, "decide", decide)
    monkeypatch.setattr(decision_bakeoff, "call_llm_json", reference)
    monkeypatch.setattr("evaluations.decision_bakeoff.asyncio.sleep", sleep)
    cases = [
        DecisionCase(
            str(i),
            f"distinct input {i}",
            {},
            {
                "relevance": Question(
                    "score", "Rate", ("none", "slight", "partial", "strong", "direct")
                )
            },
        )
        for i in range(len(statuses))
    ]
    report = await decision_bakeoff.run_panel(
        "literature_relevance",
        cases,
        client,
        "offline/deterministic",
        4,
        tmp_path / "report.json",
        continue_on_rate_limit=continuation,
    )
    assert len(report["rows"]) == len(set(decided)) == expected_cases
    assert report["summary"]["provider_refusals"] == sum(
        s == 429 for s in statuses[:expected_cases]
    )
    assert all(seconds >= 60 for seconds in sleeps if seconds != 4)
    assert any(seconds == 60 for seconds in sleeps) is continuation


def test_long_or_unknown_cooldown_stops_instead_of_probing() -> None:
    for value in ("600", "nan", "-1", "unknown"):
        assert decision_bakeoff._rate_limit_pause({"retry-after": value}) is None
    assert decision_bakeoff._rate_limit_pause({"retry-after": "120"}) == 120


def test_heldout_provider_refusal_counts_as_batch_escalation() -> None:
    rows = [
        {
            "id": str(i),
            "reference": {"relevance": 1.0},
            "decision": {"relevance": 1.0},
            "confidence": 0.99,
            "agrees": True,
        }
        for i in range(101)
    ]
    rows.append(
        {
            "id": "refused",
            "reference": {"relevance": 1.0},
            "error": "DecisionUnavailableError",
            "provider_status": 429,
        }
    )
    summary = decision_bakeoff.summarize("literature_relevance", rows)
    assert summary["held_out_batches"] == 1
    assert summary["held_out_batch_attempts"] == 2
    assert summary["held_out_batch_escalation"] == 0.5
    assert summary["decision_served_fraction"] == pytest.approx(101 / 102)
