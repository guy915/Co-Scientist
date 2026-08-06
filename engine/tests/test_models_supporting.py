"""Regression tests for the supporting ``co_scientist.models`` dataclasses.

Covers ``HypothesisReview``, ``ExecutionMetrics``, and ``Article`` (the
``Hypothesis`` dataclass is exercised in ``test_models.py``), pinning their
construction defaults, serialization shape, and equality semantics.
"""

import pytest

from co_scientist.models import (
    Article,
    ExecutionMetrics,
    HypothesisReview,
)

_ARTICLE_DICT_KEYS = {
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
    "doi",
    "is_retracted",
    "correction_status",
    "publication_type",
    "pdf_links",
    "used_in_analysis",
    "retrieved_at",
    "retrieval_score",
    "retrieval_rationale",
    "retriever_version",
}


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
    """Only ``title`` required; ``citations`` and ``source`` have defaults."""
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
        doi="10.1000/example",
        is_retracted=True,
        correction_status="retracted",
        publication_type="Retracted Publication",
        pdf_links=["http://example.com/a.pdf"],
        used_in_analysis=True,
    )
    d = art.to_dict()
    assert set(d.keys()) == _ARTICLE_DICT_KEYS
    assert d["doi"] == "10.1000/example"
    assert d["is_retracted"] is True
    assert d["correction_status"] == "retracted"
    assert d["publication_type"] == "Retracted Publication"
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
