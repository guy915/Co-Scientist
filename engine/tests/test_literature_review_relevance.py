"""Tests for the hybrid lexical + semantic retrieval scorer.

Covers fidelity-audit G5: the pure combination math
(:func:`combine_hybrid_score`, :func:`normalize_lexical`) without an LLM,
the end-to-end re-ranking (:func:`apply_semantic_relevance`) against the
deterministic offline router -- both for its bounded pool sizing and for
its byte-identical determinism on repeated runs -- and the batched
judgment call (:func:`_judge_batch`, :func:`_match_batch_judgments`)
against a stubbed ``call_llm_json``, for call-count, index-mapping, and
degraded-response behavior an offline-router test cannot exercise (the
offline filler always answers, so it cannot produce a missing index or a
raised exception).
"""

from typing import Any

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
    # field with 4.0 (co_scientist.offline_schema_fill._SCALAR_DEFAULTS;
    # "literature_relevance" carries no scalar-value override), which
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


# --- batched judgment call (stubbed call_llm_json) --------------------------


def _stub_judgments(*, count: int, start_relevance: float = 0.0) -> list[Any]:
    """Builds ``count`` in-order judgments, relevance increasing by index."""
    return [
        {
            "index": i,
            "relevance": start_relevance + i,
            "rationale": f"reason {i}",
        }
        for i in range(1, count + 1)
    ]


def _pool(n: int) -> dict[str, dict[str, object]]:
    return {
        f"p{i}": _candidate(f"Paper {i}", 1.0 - i / (n + 1))
        for i in range(1, n + 1)
    }


async def test_apply_semantic_relevance_batches_calls_by_batch_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """25 candidates at batch size 10 costs exactly 3 calls, not 25.

    The pool cap (``_SEMANTIC_POOL_CAP`` = 24) means the 25th candidate is
    never judged at all -- it stays lexical-only -- and the 24 that are
    judged split into batches of 10, 10, 4.
    """
    monkeypatch.setattr(relevance, "_RELEVANCE_BATCH_SIZE", 10)
    calls: list[int] = []

    async def fake_call_llm_json(*, prompt: str, spec: Any) -> dict[str, Any]:
        candidate_count = prompt.count("**Candidate ")
        calls.append(candidate_count)
        return {"judgments": _stub_judgments(count=candidate_count)}

    monkeypatch.setattr(relevance, "call_llm_json", fake_call_llm_json)

    ranked = _pool(25)
    result = await relevance.apply_semantic_relevance(
        ranked, research_goal="a goal", model_name="stub/model", budget=10
    )

    assert len(calls) == 3
    assert sorted(calls) == [4, 10, 10]
    # The 25th candidate (worst lexical score) fell outside the capped
    # pool and was never sent to a batch call.
    assert result["p25"]["retriever_version"] == relevance._LEXICAL_ONLY_VERSION


async def test_apply_semantic_relevance_maps_verdicts_back_by_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A batch response out of prompt order still lands on the right paper."""

    async def fake_call_llm_json(*, prompt: str, spec: Any) -> dict[str, Any]:
        # Reversed order plus a distinct relevance per index -- if the
        # mapping used list position instead of `index`, scores would
        # land on the wrong candidates.
        return {
            "judgments": [
                {"index": 3, "relevance": 0.3, "rationale": "third"},
                {"index": 1, "relevance": 0.9, "rationale": "first"},
                {"index": 2, "relevance": 0.1, "rationale": "second"},
            ]
        }

    monkeypatch.setattr(relevance, "call_llm_json", fake_call_llm_json)

    ranked = _pool(3)
    result = await relevance.apply_semantic_relevance(
        ranked, research_goal="a goal", model_name="stub/model", budget=5
    )

    assert result["p1"]["retrieval_rationale"] == "first"
    assert result["p2"]["retrieval_rationale"] == "second"
    assert result["p3"]["retrieval_rationale"] == "third"


async def test_apply_semantic_relevance_batch_failure_degrades_like_single(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A whole-batch call failure degrades every candidate in it to 0.0.

    Mirrors the single-call path's failure handling: a bad call never
    aborts the search, it just leaves that candidate's semantic score at
    0.0 with a rationale naming the failure.
    """

    async def failing_call_llm_json(*, prompt: str, spec: Any) -> Any:
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(relevance, "call_llm_json", failing_call_llm_json)

    ranked = _pool(2)
    result = await relevance.apply_semantic_relevance(
        ranked, research_goal="a goal", model_name="stub/model", budget=5
    )

    for metadata in result.values():
        assert metadata["retrieval_rationale"] == (
            relevance._FAILED_JUDGMENT_RATIONALE
        )
        assert metadata["retriever_version"] == relevance._HYBRID_VERSION


async def test_apply_semantic_relevance_bad_relevance_type_degrades_only_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-numeric ``relevance`` degrades only that one candidate.

    Under the json_object downgrade (no server-side schema enforcement) a
    field can hold the wrong type entirely. This must not raise out of
    the batch call -- that would abort every sibling batch through
    ``asyncio.gather`` and fail the whole search over one bad field.
    """

    async def fake_call_llm_json(*, prompt: str, spec: Any) -> dict[str, Any]:
        return {
            "judgments": [
                {"index": 1, "relevance": "n/a", "rationale": "bad type"},
                {"index": 2, "relevance": 0.8, "rationale": "fine"},
            ]
        }

    monkeypatch.setattr(relevance, "call_llm_json", fake_call_llm_json)

    ranked = _pool(2)
    result = await relevance.apply_semantic_relevance(
        ranked, research_goal="a goal", model_name="stub/model", budget=5
    )

    assert result["p1"]["retrieval_rationale"] == (
        relevance._FAILED_JUDGMENT_RATIONALE
    )
    assert result["p2"]["retrieval_rationale"] == "fine"


async def test_apply_semantic_relevance_handles_short_response_array(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A response array shorter than the batch never raises an index error.

    Regression guard for the offline backend's own filler, which sizes
    every array to one item unless an explicit hint says otherwise (see
    "offline backend under-populates" -- a hint bug elsewhere could
    silently starve this schema too). A short response should degrade the
    candidates it left unnamed, not crash the whole review.
    """

    async def fake_call_llm_json(*, prompt: str, spec: Any) -> dict[str, Any]:
        # Only one judgment for a three-candidate batch.
        return {
            "judgments": [{"index": 1, "relevance": 0.7, "rationale": "ok"}]
        }

    monkeypatch.setattr(relevance, "call_llm_json", fake_call_llm_json)

    ranked = _pool(3)
    result = await relevance.apply_semantic_relevance(
        ranked, research_goal="a goal", model_name="stub/model", budget=5
    )

    assert result["p1"]["retrieval_rationale"] == "ok"
    assert result["p2"]["retrieval_rationale"] == (
        relevance._FAILED_JUDGMENT_RATIONALE
    )
    assert result["p3"]["retrieval_rationale"] == (
        relevance._FAILED_JUDGMENT_RATIONALE
    )


def test_match_batch_judgments_missing_index_falls_back_to_list_order() -> None:
    """An entry with no usable index still fills a slot, in list order."""
    judgments: list[Any] = [
        {"relevance": 0.5, "rationale": "no index"},
        {"index": 1, "relevance": 0.9, "rationale": "explicit"},
    ]
    matched = relevance._match_batch_judgments(judgments, ["p1", "p2"])
    # p1 (index 1) claims its explicit slot; the indexless entry fills
    # the remaining empty slot (p2) rather than being dropped.
    assert matched[0]["rationale"] == "explicit"
    assert matched[1]["rationale"] == "no index"


def test_match_batch_judgments_duplicate_index_falls_back_for_the_second() -> (
    None
):
    """Two entries claiming the same index: only the first wins that slot."""
    judgments: list[Any] = [
        {"index": 1, "relevance": 0.9, "rationale": "first claim"},
        {"index": 1, "relevance": 0.1, "rationale": "duplicate claim"},
    ]
    matched = relevance._match_batch_judgments(judgments, ["p1", "p2"])
    assert matched[0]["rationale"] == "first claim"
    assert matched[1]["rationale"] == "duplicate claim"
