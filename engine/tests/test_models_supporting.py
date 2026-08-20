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
    "retrieval_call_id",
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
    assert m.model_usage == {}


def test_execution_metrics_phase_times_not_shared() -> None:
    """``phase_times`` uses a per-instance ``default_factory`` dict."""
    a = ExecutionMetrics()
    b = ExecutionMetrics()
    a.phase_times["generate"] = 1.5
    assert b.phase_times == {}


def test_execution_metrics_model_usage_not_shared() -> None:
    """``model_usage`` uses a per-instance ``default_factory`` dict."""
    a = ExecutionMetrics()
    b = ExecutionMetrics()
    a.model_usage["generate::m"] = {"calls": 1}
    assert b.model_usage == {}


def test_execution_metrics_round_trips_model_usage() -> None:
    """``to_dict``/``from_dict`` preserve ``model_usage`` verbatim."""
    usage = {"generate::m": {"calls": 2, "prompt_tokens": 30}}
    m = ExecutionMetrics(model_usage=usage)
    restored = ExecutionMetrics.from_dict(m.to_dict())
    assert restored.model_usage == usage


def test_merge_metrics_sums_model_usage_across_nodes() -> None:
    """``merge_metrics`` sums per-(phase, model) usage across two deltas."""
    from co_scientist.models import merge_metrics

    first = ExecutionMetrics(
        model_usage={
            "generate::m": {
                "calls": 1,
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "reasoning_tokens": 0,
                "cost_usd": 0.01,
                "latency_seconds": 1.0,
                "retries": 0,
                "cache_hits": 0,
                "cache_misses": 1,
                "errors": {},
            }
        }
    )
    second = ExecutionMetrics(
        model_usage={
            "generate::m": {
                "calls": 1,
                "prompt_tokens": 20,
                "completion_tokens": 8,
                "reasoning_tokens": 2,
                "cost_usd": 0.02,
                "latency_seconds": 1.5,
                "retries": 1,
                "cache_hits": 0,
                "cache_misses": 1,
                "errors": {"TimeoutError": 1},
            },
            "review::m": {
                "calls": 1,
                "prompt_tokens": 5,
                "completion_tokens": 2,
                "reasoning_tokens": 0,
                "cost_usd": 0.0,
                "latency_seconds": 0.5,
                "retries": 0,
                "cache_hits": 1,
                "cache_misses": 0,
                "errors": {},
            },
        }
    )

    merged = merge_metrics(first, second)

    assert merged.model_usage["generate::m"]["calls"] == 2
    assert merged.model_usage["generate::m"]["prompt_tokens"] == 30
    assert merged.model_usage["generate::m"]["completion_tokens"] == 13
    assert merged.model_usage["generate::m"]["reasoning_tokens"] == 2
    assert merged.model_usage["generate::m"]["cost_usd"] == pytest.approx(0.03)
    assert merged.model_usage["generate::m"]["cache_misses"] == 2
    assert merged.model_usage["generate::m"]["errors"] == {"TimeoutError": 1}
    assert merged.model_usage["review::m"]["cache_hits"] == 1
    # Original operands are untouched (a new dict is built, not mutated).
    assert first.model_usage["generate::m"]["calls"] == 1


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
