from __future__ import annotations

from evaluations import citation_eval, safety_eval
from evaluations.citation_usefulness_eval import (
    _LABELS,
    load_dataset,
    run_deterministic,
)
from evaluations.claim_support_eval import score_claims
from evaluations.retrieval_replay_eval import (
    _rederives,
    _result_set_complete,
    run,
)


def test_offline_citation_panel_meets_its_release_floor() -> None:
    report = citation_eval.run()
    metrics = report["metrics"]
    assert metrics["n"] >= 10
    for label in ("supports", "contradicts", "insufficient"):
        assert label in metrics["per_label"]
    by_kind = metrics["by_kind"]
    assert by_kind["obvious"]["accuracy"] >= 0.9
    assert by_kind["mixed"]["accuracy"] >= 0.9
    assert by_kind["hard_paraphrase"]["accuracy"] >= 0.8
    assert "external_gap" in report


def test_lexical_assessor_fails_the_adversarial_challenge_gates() -> None:
    # Token overlap is not semantic proof; the challenge panel must expose it.
    report = citation_eval.run(dataset_path=citation_eval._CHALLENGE_DATASET)
    assert report["metrics"]["n"] >= 30
    gates = report["production_gates"]
    assert set(gates["checks"]) == set(citation_eval._PRODUCTION_GATES)
    assert gates["passed"] is False


def test_usefulness_panel_is_well_formed_and_beats_only_a_lexical_floor() -> (
    None
):
    dataset = load_dataset()
    items = dataset["items"]
    assert {item["label"] for item in items} <= set(_LABELS)
    assert len({item["id"] for item in items}) == len(items)
    # On-topic evidence can fail to answer the question.
    labels_by_question: dict[str, set[str]] = {}
    for item in items:
        labels_by_question.setdefault(item["question"], set()).add(
            item["label"]
        )
    assert any(
        {"useful", "useless"} <= labels
        for labels in labels_by_question.values()
    )

    report = run_deterministic(dataset)

    assert report["judge"] == "deterministic_coverage"
    assert report["metrics"]["n"] == len(items)
    assert report["metrics"]["accuracy"] < 0.7


def test_claim_rates_count_claims_not_ideas() -> None:
    empty = score_claims([{"assessed_claims": 0, "verified_claims": 0}])
    assert empty["unsupported_claim_rate"] is None
    assert empty["unverified_idea_rate"] is None

    metrics = score_claims(
        [
            {"assessed_claims": 10, "verified_claims": 0},
            {"assessed_claims": 2, "verified_claims": 2},
            {"assessed_claims": 0, "verified_claims": 0},
        ]
    )

    assert metrics["claims_assessed"] == 12
    assert metrics["claims_supported"] == 2
    assert metrics["unsupported_claim_rate"] == round(10 / 12, 4)
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


def test_replay_rejects_rewritten_questions_and_incomplete_result_sets() -> (
    None
):
    # Stored ids hash the content, so editing a question breaks identity.
    rewritten = {"id": "0" * 32, "source": "pubmed", "question": "edited"}
    hits = [{"locator": "1"}]
    assert not _rederives({**rewritten, "query": "a query"})
    assert not _result_set_complete(
        {"hits": hits, "admitted": ["2"], "dropped": []}
    )
    assert _result_set_complete(
        {"hits": hits, "admitted": ["1"], "dropped": []}
    )


def test_safety_eval_reports_both_arms_and_the_easy_baseline_is_exact() -> None:
    report = safety_eval.run()
    metrics = report["metrics"]
    assert metrics["n_adversarial"] >= 15
    assert metrics["n_control"] >= 25
    assert report["policy_version"]
    assert "external_gap" in report
    easy = metrics["by_difficulty"]["easy"]
    assert easy["false_positive_rate"] == 0.0
    assert easy["false_negative_rate"] == 0.0
    # The hard split measures the deterministic boundary; it is not gated.
    assert metrics["by_difficulty"]["hard"]["n"] > 0
    per_category = metrics["per_category"]
    assert sum(b["total"] for b in per_category.values()) == metrics["n"]
