from __future__ import annotations

from evaluations import citation_eval
from evaluations.citation_usefulness_eval import (
    _LABELS,
    deterministic_label,
    load_dataset,
    run_deterministic,
    score,
)
from evaluations.claim_support_eval import score_claims
from evaluations.retrieval_replay_eval import (
    _rederives,
    _result_set_complete,
    run,
)


def test_challenge_panel_is_larger_and_reports_gates() -> None:
    report = citation_eval.run(
        dataset_path=citation_eval._CHALLENGE_DATASET,
    )
    assert report["metrics"]["n"] >= 30
    gates = report["production_gates"]
    assert set(gates["checks"]) == set(citation_eval._PRODUCTION_GATES)
    for name, check in gates["checks"].items():
        assert check["threshold"] == citation_eval._PRODUCTION_GATES[name]
        assert isinstance(check["passed"], bool)


def test_lexical_assessor_fails_challenge_gates() -> None:
    # Token overlap is not semantic proof; an adversarial panel must expose
    # lexical mistakes.
    report = citation_eval.run(
        dataset_path=citation_eval._CHALLENGE_DATASET,
    )
    assert report["production_gates"]["passed"] is False


def test_eval_runs_and_reports_metrics() -> None:
    report = citation_eval.run()
    metrics = report["metrics"]
    assert metrics["n"] >= 10
    for label in ("supports", "contradicts", "insufficient"):
        assert label in metrics["per_label"]
    assert 0.0 <= metrics["accuracy"] <= 1.0
    assert 0.0 <= metrics["contradiction_recall"] <= 1.0
    assert "external_gap" in report


def test_by_kind_meets_offline_release_floor() -> None:
    report = citation_eval.run()
    by_kind = report["metrics"]["by_kind"]
    assert set(by_kind) >= {"obvious", "hard_paraphrase", "mixed"}
    assert by_kind["obvious"]["accuracy"] >= 0.9
    assert by_kind["mixed"]["accuracy"] >= 0.9
    assert by_kind["hard_paraphrase"]["accuracy"] >= 0.8
    assert by_kind["hard_paraphrase"]["n"] >= 3


def test_every_panel_item_is_well_formed() -> None:
    items = load_dataset()["items"]

    assert len(items) >= 12
    assert {item["label"] for item in items} <= set(_LABELS)
    assert len({item["id"] for item in items}) == len(items)
    assert all(item["question"].strip() for item in items)
    assert all(item["span"].strip() for item in items)


def test_the_panel_separates_topic_from_answer() -> None:
    # On-topic evidence can fail to answer the question; lexical overlap must
    # not look sufficient.
    items = load_dataset()["items"]
    by_question: dict[str, set[str]] = {}
    for item in items:
        by_question.setdefault(item["question"], set()).add(item["label"])

    assert any(
        {"useful", "useless"} <= labels for labels in by_question.values()
    )


def test_the_lexical_floor_is_a_floor() -> None:
    # High lexical performance would expose a weak panel rather than prove
    # relevance judgment.
    report = run_deterministic(load_dataset())

    assert report["judge"] == "deterministic_coverage"
    assert report["metrics"]["n"] == len(load_dataset()["items"])
    assert report["metrics"]["accuracy"] < 0.7


def test_a_span_repeating_the_question_reads_as_useful() -> None:
    question = "Is the receptor expressed in adult human liver?"

    assert (
        deterministic_label(
            question, "The receptor is expressed in adult human liver."
        )
        == "useful"
    )
    assert (
        deterministic_label(question, "Unrelated prose entirely.") == "useless"
    )


def test_a_useless_span_accepted_as_useful_is_reported() -> None:
    metrics = score([("a", "useless", "useful"), ("b", "useless", "useless")])

    assert metrics["false_useful_rate"] == 0.5


def test_a_run_with_no_assessed_claims_has_no_rate() -> None:
    metrics = score_claims([{"assessed_claims": 0, "verified_claims": 0}])

    assert metrics["unsupported_claim_rate"] is None
    assert metrics["unverified_idea_rate"] is None


def test_the_rate_counts_claims_not_ideas() -> None:
    metrics = score_claims(
        [
            {"assessed_claims": 10, "verified_claims": 0},
            {"assessed_claims": 2, "verified_claims": 2},
        ]
    )

    assert metrics["claims_assessed"] == 12
    assert metrics["claims_supported"] == 2
    assert metrics["unsupported_claim_rate"] == round(10 / 12, 4)


def test_the_idea_rate_counts_ideas_with_nothing_behind_them() -> None:
    metrics = score_claims(
        [
            {"assessed_claims": 5, "verified_claims": 1},
            {"assessed_claims": 5, "verified_claims": 0},
            {"assessed_claims": 0, "verified_claims": 0},
        ]
    )

    assert metrics["ideas"] == 3
    assert metrics["ideas_with_assessed_claims"] == 2
    assert metrics["unverified_idea_rate"] == 0.5


def test_a_persisted_ledger_replays_exactly() -> None:
    report = run(None)

    assert report["mode"] == "synthetic"
    assert report["calls"] == 2
    assert report["id_reproduction"] == 1.0
    assert report["result_set_completeness"] == 1.0
    assert report["evidence_with_provenance"] == 1
    assert report["evidence_resolution"] == 1.0


def test_a_rewritten_question_stops_the_id_reproducing() -> None:
    # Stored ids hash the content; editing a question breaks replay identity.
    call = {
        "id": "0" * 32,
        "source": "pubmed",
        "question": "what was actually asked",
        "query": "a query",
    }

    assert not _rederives(call)


def test_a_result_set_missing_what_was_read_is_incomplete() -> None:
    assert not _result_set_complete(
        {"hits": [{"locator": "1"}], "admitted": ["2"], "dropped": []}
    )
    assert _result_set_complete(
        {"hits": [{"locator": "1"}], "admitted": ["1"], "dropped": []}
    )
