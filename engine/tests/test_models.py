from __future__ import annotations

import pytest

from co_scientist.models import (
    Article,
    ExecutionMetrics,
    GenerationMethod,
    Hypothesis,
    HypothesisOrigin,
    HypothesisReview,
)
from tests._state import make_review

_HYPOTHESIS_DICT_KEYS = {
    "id",
    "parent_id",
    "parent_ids",
    "generation",
    "origin",
    "creation_iteration",
    "text",
    "title",
    "category",
    "introduction",
    "recent_findings",
    "safety_and_toxicity",
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
    "deep_verification_fingerprint",
    "review_disposition",
    "safety_status",
    "generation_method",
    "debate_id",
    "win_count",
    "loss_count",
    "total_matches",
    "win_rate",
}


def test_hypothesis_minimal_construction_defaults() -> None:
    hyp = Hypothesis(text="A hypothesis")
    assert hyp.text == "A hypothesis"
    assert hyp.category is None
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
    a = Hypothesis(text="a")
    b = Hypothesis(text="b")
    a.evolution_history.append("step 1")
    a.enrichments["k"] = "v"
    a.reviews.append(make_review())
    assert b.evolution_history == []
    assert b.enrichments == {}
    assert b.reviews == []


def test_gen_zero_hypothesis_has_no_lineage() -> None:
    hyp = Hypothesis(text="origin")
    assert hyp.parent_id is None
    assert hyp.generation == 0
    assert hyp.origin is HypothesisOrigin.GENERATION
    assert hyp.creation_iteration is None
    assert hyp.evolution_history == []
    assert hyp.debate_id is None
    assert hyp.generation_method is None


def test_evolved_hypothesis_records_lineage() -> None:
    parent = Hypothesis(text="origin")
    evolved = Hypothesis(
        text="refined",
        parent_id=parent.id,
        generation=1,
        origin=HypothesisOrigin.EVOLUTION,
        creation_iteration=2,
        evolution_history=["origin"],
    )
    assert evolved.parent_id == parent.id
    assert evolved.generation == 1
    assert evolved.origin is HypothesisOrigin.EVOLUTION
    assert evolved.creation_iteration == 2
    assert evolved.id != parent.id


def test_multi_parent_lineage_records_every_parent() -> None:
    primary = Hypothesis(text="primary parent")
    partner = Hypothesis(text="partner parent")
    child = Hypothesis(
        text="combined child",
        parent_id=primary.id,
        parent_ids=[primary.id, partner.id],
        generation=1,
        origin=HypothesisOrigin.EVOLUTION,
    )
    assert child.parent_id == primary.id
    assert child.parent_ids == [primary.id, partner.id]
    restored = Hypothesis.from_dict(child.to_dict())
    assert restored.parent_id == primary.id
    assert restored.parent_ids == [primary.id, partner.id]


def test_parent_ids_default_empty_and_legacy_payloads_load() -> None:
    assert Hypothesis(text="x").parent_ids == []
    legacy = Hypothesis(text="x").to_dict()
    legacy.pop("parent_ids")
    assert Hypothesis.from_dict(legacy).parent_ids == []


def test_total_matches_sums_wins_and_losses() -> None:
    hyp = Hypothesis(text="x", win_count=3, loss_count=2)
    assert hyp.total_matches == 5


def test_win_rate_with_matches() -> None:
    hyp = Hypothesis(text="x", win_count=3, loss_count=1)
    assert hyp.win_rate == 75.0


def test_win_rate_zero_matches_guard() -> None:
    hyp = Hypothesis(text="x")
    assert hyp.total_matches == 0
    assert hyp.win_rate == 0.0


def test_hypothesis_to_dict_shape_and_computed_fields() -> None:
    hyp = Hypothesis(text="x", win_count=2, loss_count=2)
    d = hyp.to_dict()
    assert d["total_matches"] == 4
    assert d["win_rate"] == 50.0
    assert "similarity_degree" not in d
    assert set(d.keys()) == _HYPOTHESIS_DICT_KEYS


def test_hypothesis_to_dict_serializes_reviews() -> None:
    review = make_review()
    hyp = Hypothesis(text="x", reviews=[review])
    d = hyp.to_dict()
    assert len(d["reviews"]) == 1
    serialized = d["reviews"][0]
    assert serialized["review_summary"] == review.review_summary
    assert serialized["overall_score"] == review.overall_score
    assert serialized["scores"] == review.scores


def test_hypothesis_equality_is_field_based() -> None:
    a = Hypothesis(text="same", score=5.0)
    b = Hypothesis(text="same", score=5.0)
    c = Hypothesis(text="same", score=6.0)
    assert a == b
    assert a != c


def test_hypothesis_is_unhashable() -> None:
    with pytest.raises(TypeError):
        hash(Hypothesis(text="x"))


def test_hypothesis_id_present_and_unique() -> None:
    a = Hypothesis(text="x")
    b = Hypothesis(text="x")
    assert a.id
    assert b.id
    assert a.id != b.id


def test_hypothesis_id_excluded_from_equality() -> None:
    """Content equality keeps text-based dedup independent of minted ids."""
    a = Hypothesis(text="same", score=5.0)
    b = Hypothesis(text="same", score=5.0)
    assert a.id != b.id
    assert a == b


def test_hypothesis_to_dict_includes_id() -> None:
    hyp = Hypothesis(text="x")
    assert hyp.to_dict()["id"] == hyp.id


def test_hypothesis_from_dict_preserves_id() -> None:
    """Equality ignores ids, so a round-trip must compare the id itself."""
    original = Hypothesis(text="x", win_count=2, loss_count=1)
    restored = Hypothesis.from_dict(original.to_dict())
    assert restored.id == original.id
    assert restored.text == original.text
    assert restored.win_count == 2
    assert restored.loss_count == 1


def test_hypothesis_category_round_trips() -> None:
    hyp = Hypothesis(text="x", category="Metabolic reprogramming")
    d = hyp.to_dict()
    assert d["category"] == "Metabolic reprogramming"
    restored = Hypothesis.from_dict(d)
    assert restored.category == "Metabolic reprogramming"


def test_hypothesis_lineage_round_trips() -> None:
    child = Hypothesis(
        text="child",
        parent_id="parent-123",
        generation=2,
        origin=HypothesisOrigin.EVOLUTION,
        creation_iteration=3,
    )
    d = child.to_dict()
    assert d["parent_id"] == "parent-123"
    assert d["generation"] == 2
    assert d["origin"] == "evolution"
    assert d["creation_iteration"] == 3
    restored = Hypothesis.from_dict(d)
    assert restored.parent_id == "parent-123"
    assert restored.generation == 2
    assert restored.origin is HypothesisOrigin.EVOLUTION
    assert restored.creation_iteration == 3


def test_hypothesis_from_dict_pre_lineage_payload_defaults() -> None:
    payload = Hypothesis(text="legacy").to_dict()
    for key in ("parent_id", "generation", "origin", "creation_iteration"):
        del payload[key]
    restored = Hypothesis.from_dict(payload)
    assert restored.parent_id is None
    assert restored.generation == 0
    assert restored.origin is HypothesisOrigin.GENERATION
    assert restored.creation_iteration is None


def test_hypothesis_from_dict_generates_id_when_absent() -> None:
    payload = Hypothesis(text="legacy").to_dict()
    del payload["id"]
    restored = Hypothesis.from_dict(payload)
    assert restored.id
    assert restored.text == "legacy"


def test_hypothesis_from_dict_restores_enum_and_reviews() -> None:
    """Raw strings/dicts cannot support the next serialization round-trip."""
    hyp = Hypothesis(
        text="x",
        generation_method=GenerationMethod.DEBATE,
        reviews=[make_review()],
    )
    restored = Hypothesis.from_dict(hyp.to_dict())
    assert restored.generation_method == GenerationMethod.DEBATE
    assert isinstance(restored.reviews[0], HypothesisReview)
    assert restored.to_dict()["generation_method"] == "debate"


def test_hypothesis_deep_verification_fields_default_empty() -> None:
    h = Hypothesis(text="X inhibits Y")
    assert h.deep_verification_probes == []
    assert h.deep_verification_verdict is None


def test_hypothesis_to_dict_includes_deep_verification() -> None:
    h = Hypothesis(text="X inhibits Y")
    h.deep_verification_probes = [
        {
            "question": "q",
            "answer": "a",
            "reasoning": "r",
            "assumption_is_fundamental": True,
        }
    ]
    h.deep_verification_verdict = "weakened"
    d = h.to_dict()
    assert d["deep_verification_probes"][0]["question"] == "q"
    assert d["deep_verification_verdict"] == "weakened"


def test_review_summary_none_when_no_reviews() -> None:
    hyp = Hypothesis(text="x")
    assert hyp.review_summary() is None


def test_review_summary_projects_latest_review() -> None:
    review = make_review(
        review_summary="Solid mechanism, weak controls.",
        scores={"novelty": 7, "rigor": 5},
        constructive_feedback="Add a dose-response arm.",
        overall_score=6.5,
    )
    hyp = Hypothesis(text="x", reviews=[review])
    assert hyp.review_summary() == {
        "overall_score": 6.5,
        "review_summary": "Solid mechanism, weak controls.",
        "constructive_feedback": "Add a dose-response arm.",
        "scores": {"novelty": 7, "rigor": 5},
    }


def test_review_summary_uses_the_latest_of_several_reviews() -> None:
    first = make_review(overall_score=3.0)
    second = make_review(overall_score=8.0)
    hyp = Hypothesis(text="x", reviews=[first, second])
    summary = hyp.review_summary()
    assert summary is not None
    assert summary["overall_score"] == 8.0


def test_deep_verification_summary_none_when_no_probes() -> None:
    """None lets prompt builders omit the block rather than emit hollow
    evidence."""
    hyp = Hypothesis(text="x")
    assert hyp.deep_verification_summary() is None


def test_deep_verification_summary_returns_probes_and_verdict() -> None:
    probes = [
        {
            "question": "does it hold under X?",
            "answer": "yes",
            "reasoning": "because Y",
            "assumption_is_fundamental": True,
        }
    ]
    hyp = Hypothesis(
        text="x",
        deep_verification_probes=probes,
        deep_verification_verdict="holds",
    )
    assert hyp.deep_verification_summary() == {
        "probes": probes,
        "verdict": "holds",
    }


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


def test_hypothesis_review_requires_all_fields() -> None:
    with pytest.raises(TypeError):
        HypothesisReview()  # type: ignore[call-arg]


def test_hypothesis_review_construction() -> None:
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


def test_execution_metrics_defaults() -> None:
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
    a = ExecutionMetrics()
    b = ExecutionMetrics()
    a.phase_times["generate"] = 1.5
    assert b.phase_times == {}


def test_execution_metrics_model_usage_not_shared() -> None:
    a = ExecutionMetrics()
    b = ExecutionMetrics()
    a.model_usage["generate::m"] = {"calls": 1}
    assert b.model_usage == {}


def test_execution_metrics_round_trips_model_usage() -> None:
    usage = {"generate::m": {"calls": 2, "prompt_tokens": 30}}
    m = ExecutionMetrics(model_usage=usage)
    restored = ExecutionMetrics.from_dict(m.to_dict())
    assert restored.model_usage == usage


def test_merge_metrics_sums_model_usage_across_nodes() -> None:
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
    assert first.model_usage["generate::m"]["calls"] == 1


def test_article_minimal_construction_defaults() -> None:
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
    a = Article(title="a")
    b = Article(title="b")
    a.authors.append("Doe, J.")
    a.pdf_links.append("http://example.com/a.pdf")
    assert b.authors == []
    assert b.pdf_links == []


def test_article_to_dict_shape() -> None:
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
    a = Article(title="same", citations=3)
    b = Article(title="same", citations=3)
    c = Article(title="same", citations=4)
    assert a == b
    assert a != c
