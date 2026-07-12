"""Tests for the citation/claim-entailment evaluation runner (Milestone 5)."""

from __future__ import annotations

from evaluations import citation_eval


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
