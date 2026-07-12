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


def test_by_kind_shows_lexical_gap_on_hard_paraphrases() -> None:
    """The per-kind split exposes where the lexical assessor fails.

    The dataset now includes hard paraphrases (semantic entailment with low
    lexical overlap) and mixed-evidence items. The deterministic (lexical)
    assessor must handle the obvious/mixed cases but fail the hard paraphrases
    — precisely the gap the semantic/NLI assessor closes.
    """
    report = citation_eval.run()
    by_kind = report["metrics"]["by_kind"]
    assert set(by_kind) >= {"obvious", "hard_paraphrase", "mixed"}
    # Lexical overlap resolves the obvious and mixed (retrieval + dominance)
    # cases...
    assert by_kind["obvious"]["accuracy"] >= 0.9
    assert by_kind["mixed"]["accuracy"] >= 0.9
    # ...but not the hard paraphrases, which need semantic entailment.
    assert by_kind["hard_paraphrase"]["accuracy"] < 0.5
    assert by_kind["hard_paraphrase"]["n"] >= 3
