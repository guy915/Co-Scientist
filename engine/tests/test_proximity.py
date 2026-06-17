"""Tests for proximity_node: clustering and high-similarity deduplication.

The node's only external dependency is a single ``call_llm_json`` call that
returns similarity clusters; these tests stub that out and assert on the
deterministic clustering/dedup logic and the returned state update.
"""

from typing import Any

import pytest

from co_scientist.nodes import proximity
from co_scientist.nodes.proximity import proximity_node
from tests._state import make_hypothesis, make_state


def _stub_clusters(monkeypatch: pytest.MonkeyPatch,
                   response: dict[str, Any]) -> None:
    """Patch proximity's call_llm_json to return a fixed clusters response."""

    async def fake(**_: Any) -> dict[str, Any]:
        return response

    monkeypatch.setattr(proximity, "call_llm_json", fake)


async def test_single_hypothesis_skips_analysis() -> None:
    """A single hypothesis returns unchanged with the iteration advanced."""
    state = make_state(hypotheses=[make_hypothesis(text="only one")],
                       current_iteration=2)
    result = await proximity_node(state)
    assert len(result["hypotheses"]) == 1
    assert result["current_iteration"] == 3


async def test_high_similarity_duplicate_removed_keeping_best_elo(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Within a high-similarity cluster, only the top-Elo hypothesis survives."""
    low = make_hypothesis(text="alpha pathway drives tumor growth",
                          elo_rating=1200)
    high = make_hypothesis(text="beta pathway drives tumor growth",
                           elo_rating=1400)
    state = make_state(hypotheses=[low, high])
    _stub_clusters(
        monkeypatch, {
            "similarity_clusters": [{
                "cluster_id": "c1",
                "similar_hypotheses": [
                    {
                        "text": "alpha pathway drives tumor growth",
                        "similarity_degree": "high",
                    },
                    {
                        "text": "beta pathway drives tumor growth",
                        "similarity_degree": "high",
                    },
                ],
            }]
        })
    result = await proximity_node(state)
    assert len(result["hypotheses"]) == 1
    assert result["hypotheses"][0].elo_rating == 1400
    assert len(result["removed_duplicates"]) == 1
    assert result["removed_duplicates"][0]["elo_rating"] == 1200


async def test_low_similarity_keeps_all(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Clusters with no high-similarity members remove nothing."""
    state = make_state(
        hypotheses=[make_hypothesis(text="aaa"),
                    make_hypothesis(text="bbb")])
    _stub_clusters(
        monkeypatch, {
            "similarity_clusters": [{
                "cluster_id": "c1",
                "similar_hypotheses": [
                    {"text": "aaa", "similarity_degree": "low"},
                    {"text": "bbb", "similarity_degree": "medium"},
                ],
            }]
        })
    result = await proximity_node(state)
    assert len(result["hypotheses"]) == 2
    assert result["removed_duplicates"] == []


async def test_empty_clusters_returns_all(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty clusters response short-circuits to the original hypotheses."""
    state = make_state(
        hypotheses=[make_hypothesis(text="aaa"),
                    make_hypothesis(text="bbb")])
    _stub_clusters(monkeypatch, {"similarity_clusters": []})
    result = await proximity_node(state)
    assert len(result["hypotheses"]) == 2
    assert result["current_iteration"] == 1
