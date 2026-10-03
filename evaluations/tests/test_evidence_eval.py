"""Evidence eval regression tests."""

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

# Citation eval.


def test_challenge_panel_is_larger_and_reports_gates() -> None:
    """The adversarial challenge panel is scored with documented gates.

    The challenge dataset is intentionally larger and harder than v1; the
    report must carry a ``production_gates`` block whose checks name explicit
    thresholds, so the panel's gates are documented rather than implied.
    """
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
    """The lexical baseline must not pass the semantic production gates.

    This pins the honest finding that token overlap is not proof: the offline
    deterministic assessor, run over the adversarial panel, must miss enough
    negation-free contradictions and semantic mismatches to fail the gates. A
    future change that let the lexical assessor pass here would mean the panel
    stopped being adversarial.
    """
    report = citation_eval.run(
        dataset_path=citation_eval._CHALLENGE_DATASET,
    )
    assert report["production_gates"]["passed"] is False


def test_eval_runs_and_reports_metrics() -> None:
    """The eval produces a metrics report over the labeled dataset."""
    report = citation_eval.run()
    metrics = report["metrics"]
    assert metrics["n"] >= 10
    # Every label is exercised (precision/recall present for each).
    for label in ("supports", "contradicts", "insufficient"):
        assert label in metrics["per_label"]
    # Metrics are well-formed probabilities.
    assert 0.0 <= metrics["accuracy"] <= 1.0
    assert 0.0 <= metrics["contradiction_recall"] <= 1.0
    # The honest external gap is recorded, not hidden.
    assert "external_gap" in report


def test_by_kind_meets_offline_release_floor() -> None:
    """The offline fallback handles the release panel's hard paraphrases.

    The dataset now includes hard paraphrases (semantic entailment with low
    lexical overlap) and mixed-evidence items. The deterministic (lexical)
    fallback uses conservative concept normalization and polarity checks. It is
    not a substitute for the configured semantic assessor, but it must remain
    safe enough to satisfy the offline release floor when provider calls fail.
    """
    report = citation_eval.run()
    by_kind = report["metrics"]["by_kind"]
    assert set(by_kind) >= {"obvious", "hard_paraphrase", "mixed"}
    assert by_kind["obvious"]["accuracy"] >= 0.9
    assert by_kind["mixed"]["accuracy"] >= 0.9
    assert by_kind["hard_paraphrase"]["accuracy"] >= 0.8
    assert by_kind["hard_paraphrase"]["n"] >= 3


# Citation usefulness eval.


def test_every_panel_item_is_well_formed() -> None:
    """A typo in a label would silently shrink the panel."""
    items = load_dataset()["items"]

    assert len(items) >= 12
    assert {item["label"] for item in items} <= set(_LABELS)
    assert len({item["id"] for item in items}) == len(items)
    assert all(item["question"].strip() for item in items)
    assert all(item["span"].strip() for item in items)


def test_the_panel_separates_topic_from_answer() -> None:
    """The case a research loop exists to catch has to be in the panel.

    A span about embryonic expression is squarely on-topic for a question
    about adult expression and answers none of it. Without items like
    that, any word-overlap measure would score well and the metric would
    be measuring nothing.
    """
    items = load_dataset()["items"]
    by_question: dict[str, set[str]] = {}
    for item in items:
        by_question.setdefault(item["question"], set()).add(item["label"])

    assert any(
        {"useful", "useless"} <= labels for labels in by_question.values()
    )


def test_the_lexical_floor_is_a_floor() -> None:
    """Kept as a baseline, never as the answer.

    If this ever scored well it would mean the panel had lost the items
    that distinguish topic from answer, not that lexical coverage had
    become a good judge of relevance.
    """
    report = run_deterministic(load_dataset())

    assert report["judge"] == "deterministic_coverage"
    assert report["metrics"]["n"] == len(load_dataset()["items"])
    assert report["metrics"]["accuracy"] < 0.7


def test_a_span_repeating_the_question_reads_as_useful() -> None:
    """The floor's rule, stated so a threshold change is deliberate."""
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
    """The rate that matters: keeping a span that answers nothing."""
    metrics = score([("a", "useless", "useful"), ("b", "useless", "useless")])

    assert metrics["false_useful_rate"] == 0.5


# Claim support eval.


def test_a_run_with_no_assessed_claims_has_no_rate() -> None:
    """Nothing assessed is not perfect support, and must not print as it."""
    metrics = score_claims([{"assessed_claims": 0, "verified_claims": 0}])

    assert metrics["unsupported_claim_rate"] is None
    assert metrics["unverified_idea_rate"] is None


def test_the_rate_counts_claims_not_ideas() -> None:
    """One idea making ten unsupported claims is ten unsupported claims."""
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
    """What a reader sees badged Unverified is per idea, not per claim.

    An idea with one supported claim out of five is not unverified, so a
    retrieval change that only deepens already-supported ideas moves the
    claim rate and leaves this one alone -- which is the point of
    reporting both.
    """
    metrics = score_claims(
        [
            {"assessed_claims": 5, "verified_claims": 1},
            {"assessed_claims": 5, "verified_claims": 0},
            {"assessed_claims": 0, "verified_claims": 0},
        ]
    )

    # The claimless idea is outside the denominator entirely.
    assert metrics["ideas"] == 3
    assert metrics["ideas_with_assessed_claims"] == 2
    assert metrics["unverified_idea_rate"] == 0.5


# Retrieval replay eval.


def test_a_persisted_ledger_replays_exactly() -> None:
    """Everything the record needs to be reconstructable, end to end."""
    report = run(None)

    assert report["mode"] == "synthetic"
    assert report["calls"] == 2
    assert report["id_reproduction"] == 1.0
    assert report["result_set_completeness"] == 1.0
    # The evidence row written from a finding names the search that
    # surfaced it, and that id resolves against the same run's calls.
    assert report["evidence_with_provenance"] == 1
    assert report["evidence_resolution"] == 1.0


def test_a_rewritten_question_stops_the_id_reproducing() -> None:
    """The id is a hash over the fields, so this is the whole guarantee.

    A row whose question was edited after the fact keeps a stored id that
    no longer follows from its own contents -- which is exactly the state
    a replay cannot detect any other way.
    """
    call = {
        "id": "0" * 32,
        "source": "pubmed",
        "question": "what was actually asked",
        "query": "a query",
    }

    assert not _rederives(call)


def test_a_result_set_missing_what_was_read_is_incomplete() -> None:
    """Admitting a locator the record never saw is an unreplayable gap."""
    assert not _result_set_complete(
        {"hits": [{"locator": "1"}], "admitted": ["2"], "dropped": []}
    )
    assert _result_set_complete(
        {"hits": [{"locator": "1"}], "admitted": ["1"], "dropped": []}
    )
