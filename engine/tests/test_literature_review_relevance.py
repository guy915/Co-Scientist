"""Tests for the hybrid lexical + semantic retrieval scorer.

Covers fidelity-audit G5: the pure combination math
(:func:`combine_hybrid_score`, :func:`normalize_lexical`) without an LLM,
and the end-to-end re-ranking (:func:`apply_semantic_relevance`) against
the deterministic offline router -- both for its bounded pool sizing and
for its byte-identical determinism on repeated runs.
"""

import pytest

from co_scientist import offline_llm
from co_scientist.agents.generation.literature_review import relevance
from tests._offline_helpers import isolate_offline_router


@pytest.fixture(autouse=True)
def _isolate_offline_router(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_offline_router(monkeypatch)
    offline_llm.install_offline_router()


# --- normalize_lexical / combine_hybrid_score (pure) ------------------------


def test_normalize_lexical_clamps_to_documented_range() -> None:
    """The RRF-fused rank score, already on [0, 1], passes through clamped."""
    assert relevance.normalize_lexical(0.0) == 0.0
    assert relevance.normalize_lexical(1.0) == 1.0
    assert relevance.normalize_lexical(0.5) == 0.5
    # Out-of-range inputs (e.g. floating point noise) still clamp rather
    # than producing a score outside [0, 1].
    assert relevance.normalize_lexical(-0.2) == 0.0
    assert relevance.normalize_lexical(1.5) == 1.0


def test_combine_hybrid_score_without_semantic_is_lexical_only() -> None:
    """An unjudged candidate's score is the normalized lexical score alone."""
    assert relevance.combine_hybrid_score(0.5, None) == 0.5


def test_combine_hybrid_score_averages_lexical_and_semantic() -> None:
    """A judged candidate's score is the documented 50/50 blend."""
    assert relevance.combine_hybrid_score(0.5, 1.0) == 0.75
    assert relevance.combine_hybrid_score(0.0, 0.0) == 0.0


def test_combine_hybrid_score_clamps_out_of_range_semantic() -> None:
    """A malformed model response outside [0, 1] does not skew the blend."""
    assert relevance.combine_hybrid_score(
        0.5, 4.0
    ) == relevance.combine_hybrid_score(0.5, 1.0)
    assert relevance.combine_hybrid_score(
        0.5, -2.0
    ) == relevance.combine_hybrid_score(0.5, 0.0)


def test_semantic_pool_size_is_bounded() -> None:
    """The pool never exceeds the absolute cap.

    However large the candidate set or the multiplier-scaled budget would
    otherwise allow.
    """
    assert relevance._semantic_pool_size(1000, budget=50) == (
        relevance._SEMANTIC_POOL_CAP
    )
    assert relevance._semantic_pool_size(2, budget=50) == 2
    assert relevance._semantic_pool_size(1000, budget=0) == 0


# --- apply_semantic_relevance (end to end, offline router) ------------------


def _candidate(title: str, lexical_score: float) -> dict[str, object]:
    return {
        "title": title,
        "abstract": f"Abstract for {title}.",
        "retrieval_score": lexical_score,
    }


async def test_apply_semantic_relevance_stamps_every_candidate() -> None:
    """Every candidate gets a normalized score and version, judged or not."""
    ranked = {
        "p1": _candidate("Paper One", 1.0),
        "p2": _candidate("Paper Two", 0.0),
    }
    result = await relevance.apply_semantic_relevance(
        ranked,
        research_goal="a research goal",
        model_name=offline_llm.DEFAULT_OFFLINE_MODEL,
        budget=5,
    )
    for metadata in result.values():
        assert 0.0 <= metadata["retrieval_score"] <= 1.0
        assert metadata["retriever_version"] == relevance._HYBRID_VERSION
        assert isinstance(metadata["retrieval_rationale"], str)


async def test_apply_semantic_relevance_skips_pool_without_goal() -> None:
    """An empty research goal never triggers an LLM call.

    Candidates still get the normalized lexical-only baseline, so the
    persisted score is on the same [0, 1] scale whether or not the
    semantic pass ran.
    """
    ranked = {"p1": _candidate("Paper One", 1.0)}
    result = await relevance.apply_semantic_relevance(
        ranked,
        research_goal="",
        model_name=offline_llm.DEFAULT_OFFLINE_MODEL,
        budget=5,
    )
    assert result["p1"]["retrieval_score"] == 1.0
    assert result["p1"]["retriever_version"] == relevance._LEXICAL_ONLY_VERSION


async def test_apply_semantic_relevance_preserves_lexical_differentiation() -> (
    None
):
    """A better-lexical candidate still scores higher after the semantic pass.

    Regression guard: ``_stamp_hybrid_score`` must read each candidate's
    original raw lexical score, not the already-combined value its own
    first (baseline) pass wrote back onto the same metadata dict -- an
    earlier version of this function fed that combined value into
    :func:`combine_hybrid_score` a second time, silently double-weighting
    the semantic term so every candidate collapsed onto the exact same
    score regardless of its real lexical quality.
    """
    ranked = {
        "best": _candidate("Best lexical", 1.0),
        "worst": _candidate("Worst lexical", 0.0),
    }
    result = await relevance.apply_semantic_relevance(
        ranked,
        research_goal="a research goal",
        model_name=offline_llm.DEFAULT_OFFLINE_MODEL,
        budget=5,
    )
    assert (
        result["best"]["retrieval_score"] > result["worst"]["retrieval_score"]
    )
    # The offline router's deterministic filler answers every "number"
    # field with 4.0 (co_scientist.offline_llm._SCALAR_DEFAULTS), which
    # combine_hybrid_score clamps to 1.0 -- identical for both candidates,
    # so any observed difference in the final score comes only from the
    # lexical half.
    assert result["best"]["retrieval_score"] == relevance.combine_hybrid_score(
        1.0, 1.0
    )
    assert result["worst"]["retrieval_score"] == relevance.combine_hybrid_score(
        0.0, 1.0
    )


async def test_apply_semantic_relevance_bounds_pool_by_budget() -> None:
    """Candidates outside the over-fetched pool stay lexical-only."""
    ranked = {
        "best": _candidate("Best", 1.0),
        "worst": _candidate("Worst", 0.0),
    }
    result = await relevance.apply_semantic_relevance(
        ranked,
        research_goal="a research goal",
        model_name=offline_llm.DEFAULT_OFFLINE_MODEL,
        # budget=0 disables the pool entirely regardless of candidate count.
        budget=0,
    )
    assert result["best"]["retriever_version"] == (
        relevance._LEXICAL_ONLY_VERSION
    )
    assert result["worst"]["retriever_version"] == (
        relevance._LEXICAL_ONLY_VERSION
    )


async def test_apply_semantic_relevance_is_deterministic() -> None:
    """The same candidates and goal score identically on repeated runs."""
    ranked = {
        "p1": _candidate("Paper One", 0.8),
        "p2": _candidate("Paper Two", 0.4),
    }
    first = await relevance.apply_semantic_relevance(
        {k: dict(v) for k, v in ranked.items()},
        research_goal="a fixed research goal",
        model_name=offline_llm.DEFAULT_OFFLINE_MODEL,
        budget=5,
    )
    second = await relevance.apply_semantic_relevance(
        {k: dict(v) for k, v in ranked.items()},
        research_goal="a fixed research goal",
        model_name=offline_llm.DEFAULT_OFFLINE_MODEL,
        budget=5,
    )
    assert list(first.keys()) == list(second.keys())
    for key in first:
        assert first[key]["retrieval_score"] == second[key]["retrieval_score"]
        assert (
            first[key]["retrieval_rationale"]
            == second[key]["retrieval_rationale"]
        )
