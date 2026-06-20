"""Regression tests for the ``co_scientist.models`` dataclasses.

These tests lock in the *current* construction defaults, computed properties,
serialization shape, and equality semantics of ``Hypothesis``,
``HypothesisReview``, ``ExecutionMetrics``, and ``Article``, giving upcoming
refactors a safety net.
"""

import pytest

from co_scientist.models import Article
from co_scientist.models import ExecutionMetrics
from co_scientist.models import GenerationMethod
from co_scientist.models import Hypothesis
from co_scientist.models import HypothesisReview

# --- Hypothesis: construction and defaults ----------------------------------


def test_hypothesis_minimal_construction_defaults() -> None:
    """Only ``text`` is required; every other field has its documented default.
    """
    hyp = Hypothesis(text="A hypothesis")
    assert hyp.text == "A hypothesis"
    assert hyp.explanation is None
    assert hyp.literature_grounding is None
    assert hyp.experiment is None
    assert hyp.novelty_validation is None
    assert hyp.enrichments == {}
    assert hyp.citation_map == {}
    assert hyp.score == 0.0
    assert hyp.elo_rating == 1200
    assert hyp.reviews == []
    assert hyp.similarity_cluster_id is None
    assert hyp.similarity_degree is None
    assert hyp.evolution_history == []
    assert hyp.reflection_notes is None
    assert hyp.generation_method is None
    assert hyp.debate_id is None
    assert hyp.win_count == 0
    assert hyp.loss_count == 0


def test_hypothesis_mutable_defaults_not_shared() -> None:
    """``default_factory`` fields are independent per instance (no sharing)."""
    a = Hypothesis(text="a")
    b = Hypothesis(text="b")
    a.evolution_history.append("step 1")
    a.enrichments["k"] = "v"
    a.reviews.append(_make_review())
    assert b.evolution_history == []
    assert b.enrichments == {}
    assert b.reviews == []


# --- Hypothesis: lineage / evolution ----------------------------------------


def test_gen_zero_hypothesis_has_no_lineage() -> None:
    """A fresh (gen-0) hypothesis carries no parent / evolution lineage.

    ``models.py`` has no ``parent_id``/``generation`` field; lineage is tracked
    via ``evolution_history`` (empty), ``debate_id`` (None), and
    ``generation_method`` (None). These are the real defaults.
    """
    hyp = Hypothesis(text="origin")
    assert hyp.evolution_history == []
    assert hyp.debate_id is None
    assert hyp.generation_method is None


def test_evolved_hypothesis_records_lineage() -> None:
    """An evolved hypothesis references its origin via ``evolution_history``."""
    evolved = Hypothesis(
        text="refined",
        evolution_history=["Evolved from: origin hypothesis"],
        generation_method=GenerationMethod.DEBATE,
        debate_id=3,
    )
    assert evolved.evolution_history == ["Evolved from: origin hypothesis"]
    assert evolved.generation_method == "debate"
    assert evolved.debate_id == 3


# --- Hypothesis: computed properties ----------------------------------------


def test_total_matches_sums_wins_and_losses() -> None:
    """``total_matches`` is ``win_count + loss_count``."""
    hyp = Hypothesis(text="x", win_count=3, loss_count=2)
    assert hyp.total_matches == 5


def test_win_rate_with_matches() -> None:
    """``win_rate`` is a 0-100 percentage of wins over total matches."""
    hyp = Hypothesis(text="x", win_count=3, loss_count=1)
    assert hyp.win_rate == 75.0


def test_win_rate_zero_matches_guard() -> None:
    """No matches yields ``0.0`` win rate (no ZeroDivisionError)."""
    hyp = Hypothesis(text="x")
    assert hyp.total_matches == 0
    assert hyp.win_rate == 0.0


# --- Hypothesis: serialization ----------------------------------------------


def test_hypothesis_to_dict_shape_and_computed_fields() -> None:
    """``to_dict`` adds computed fields and omits ``similarity_degree``.

    The computed ``total_matches``/``win_rate`` properties are serialized while
    the ``similarity_degree`` field is intentionally left out.
    """
    hyp = Hypothesis(text="x", win_count=2, loss_count=2)
    d = hyp.to_dict()
    # Computed fields are serialized even though they are properties.
    assert d["total_matches"] == 4
    assert d["win_rate"] == 50.0
    # similarity_degree is a real field but is intentionally NOT serialized.
    assert "similarity_degree" not in d
    # Exact key set is part of the contract this regression net pins.
    expected_keys = {
        "text",
        "explanation",
        "literature_grounding",
        "experiment",
        "novelty_validation",
        "enrichments",
        "citation_map",
        "score",
        "elo_rating",
        "reviews",
        "similarity_cluster_id",
        "evolution_history",
        "reflection_notes",
        "deep_verification_probes",
        "deep_verification_verdict",
        "generation_method",
        "debate_id",
        "win_count",
        "loss_count",
        "total_matches",
        "win_rate",
    }
    assert set(d.keys()) == expected_keys


def test_hypothesis_to_dict_serializes_reviews() -> None:
    """Nested reviews are flattened to plain dicts inside ``to_dict``."""
    review = _make_review()
    hyp = Hypothesis(text="x", reviews=[review])
    d = hyp.to_dict()
    assert len(d["reviews"]) == 1
    serialized = d["reviews"][0]
    assert serialized["review_summary"] == review.review_summary
    assert serialized["overall_score"] == review.overall_score
    assert serialized["scores"] == review.scores


# --- Hypothesis: equality and hashing ---------------------------------------


def test_hypothesis_equality_is_field_based() -> None:
    """Dataclass equality compares all fields; identical fields are equal."""
    a = Hypothesis(text="same", score=5.0)
    b = Hypothesis(text="same", score=5.0)
    c = Hypothesis(text="same", score=6.0)
    assert a == b
    assert a != c


def test_hypothesis_is_unhashable() -> None:
    """The dataclass is unhashable (eq=True, not frozen): ``hash`` raises."""
    with pytest.raises(TypeError):
        hash(Hypothesis(text="x"))


# --- HypothesisReview -------------------------------------------------------


def test_hypothesis_review_requires_all_fields() -> None:
    """``HypothesisReview`` has no defaults; all six fields are required."""
    with pytest.raises(TypeError):
        HypothesisReview()  # type: ignore[call-arg]


def test_hypothesis_review_construction() -> None:
    """A fully-specified review stores each field verbatim."""
    review = HypothesisReview(
        review_summary="Solid",
        scores={"novelty": 8},
        safety_ethical_concerns="None",
        detailed_feedback={"novelty": "novel angle"},
        constructive_feedback="Add an experiment.",
        overall_score=7.5,
    )
    assert review.scores == {"novelty": 8}
    assert review.overall_score == 7.5
    assert review.detailed_feedback == {"novelty": "novel angle"}


# --- ExecutionMetrics -------------------------------------------------------


def test_execution_metrics_defaults() -> None:
    """All ``ExecutionMetrics`` fields default to zero / empty."""
    m = ExecutionMetrics()
    assert m.total_time == 0.0
    assert m.hypothesis_count == 0
    assert m.reviews_count == 0
    assert m.tournaments_count == 0
    assert m.evolutions_count == 0
    assert m.llm_calls == 0
    assert m.phase_times == {}


def test_execution_metrics_phase_times_not_shared() -> None:
    """``phase_times`` uses a per-instance ``default_factory`` dict."""
    a = ExecutionMetrics()
    b = ExecutionMetrics()
    a.phase_times["generate"] = 1.5
    assert b.phase_times == {}


# --- Article ----------------------------------------------------------------


def test_article_minimal_construction_defaults() -> None:
    """Only ``title`` is required; ``citations`` and ``source`` have defaults."""
    art = Article(title="A paper")
    assert art.title == "A paper"
    assert art.url is None
    assert art.authors == []
    assert art.year is None
    assert art.venue is None
    assert art.citations == 0
    assert art.abstract is None
    assert art.content is None
    assert art.source_id is None
    assert art.source == "pubmed"
    assert art.pdf_links == []
    assert art.used_in_analysis is False


def test_article_mutable_defaults_not_shared() -> None:
    """``authors`` and ``pdf_links`` are independent per instance."""
    a = Article(title="a")
    b = Article(title="b")
    a.authors.append("Doe, J.")
    a.pdf_links.append("http://example.com/a.pdf")
    assert b.authors == []
    assert b.pdf_links == []


def test_article_to_dict_shape() -> None:
    """``Article.to_dict`` round-trips every field with no extras."""
    art = Article(
        title="A paper",
        url="http://example.com",
        authors=["Doe, J."],
        year=2024,
        venue="Nature",
        citations=12,
        abstract="An abstract.",
        content="Full text.",
        source_id="PMID:123",
        source="pubmed",
        pdf_links=["http://example.com/a.pdf"],
        used_in_analysis=True,
    )
    d = art.to_dict()
    expected_keys = {
        "title",
        "url",
        "authors",
        "year",
        "venue",
        "citations",
        "abstract",
        "content",
        "source_id",
        "source",
        "pdf_links",
        "used_in_analysis",
    }
    assert set(d.keys()) == expected_keys
    assert d["citations"] == 12
    assert d["authors"] == ["Doe, J."]
    assert d["used_in_analysis"] is True


def test_article_equality_is_field_based() -> None:
    """Dataclass equality compares all fields."""
    a = Article(title="same", citations=3)
    b = Article(title="same", citations=3)
    c = Article(title="same", citations=4)
    assert a == b
    assert a != c


# --- Helpers ----------------------------------------------------------------


def _make_review() -> HypothesisReview:
    """Builds a minimal valid ``HypothesisReview`` for serialization tests.

    Returns:
        A ``HypothesisReview`` with all six required fields populated.
    """
    return HypothesisReview(
        review_summary="ok",
        scores={"novelty": 5},
        safety_ethical_concerns="none",
        detailed_feedback={"novelty": "fine"},
        constructive_feedback="ship it",
        overall_score=5.0,
    )


# --- Hypothesis: deep-verification fields -----------------------------------


def test_hypothesis_deep_verification_fields_default_empty() -> None:
    """A fresh hypothesis has no deep-verification probes or verdict."""
    h = Hypothesis(text="X inhibits Y")
    assert h.deep_verification_probes == []
    assert h.deep_verification_verdict is None


def test_hypothesis_to_dict_includes_deep_verification() -> None:
    """``to_dict`` serializes the deep-verification probes and verdict."""
    h = Hypothesis(text="X inhibits Y")
    h.deep_verification_probes = [{
        "question": "q",
        "answer": "a",
        "reasoning": "r",
        "assumption_is_fundamental": True,
    }]
    h.deep_verification_verdict = "weakened"
    d = h.to_dict()
    assert d["deep_verification_probes"][0]["question"] == "q"
    assert d["deep_verification_verdict"] == "weakened"
