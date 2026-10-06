from __future__ import annotations

import pytest

from co_scientist.models import (
    ExecutionMetrics,
    GenerationMethod,
    Hypothesis,
    HypothesisOrigin,
    HypothesisReview,
)
from tests._state import make_review


def test_hypothesis_mutable_defaults_not_shared() -> None:
    a = Hypothesis(text="a")
    b = Hypothesis(text="b")
    a.evolution_history.append("step 1")
    a.enrichments["k"] = "v"
    a.reviews.append(make_review())
    assert b.evolution_history == []
    assert b.enrichments == {}
    assert b.reviews == []


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


def test_win_rate_with_matches() -> None:
    hyp = Hypothesis(text="x", win_count=3, loss_count=1)
    assert hyp.win_rate == 75.0


def test_win_rate_zero_matches_guard() -> None:
    hyp = Hypothesis(text="x")
    assert hyp.total_matches == 0
    assert hyp.win_rate == 0.0


def test_hypothesis_id_excluded_from_equality() -> None:
    """Content equality keeps text-based dedup independent of minted ids."""
    a = Hypothesis(text="same", score=5.0)
    b = Hypothesis(text="same", score=5.0)
    assert a.id != b.id
    assert a == b


def test_hypothesis_from_dict_preserves_id() -> None:
    """Equality ignores ids, so a round-trip must compare the id itself."""
    original = Hypothesis(text="x", win_count=2, loss_count=1)
    restored = Hypothesis.from_dict(original.to_dict())
    assert restored.id == original.id
    assert restored.text == original.text
    assert restored.win_count == 2
    assert restored.loss_count == 1


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
