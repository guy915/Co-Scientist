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


def _stub_clusters(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, Any]
) -> None:
    """Patch proximity's call_llm_json to return a fixed clusters response."""

    async def fake(**_: Any) -> dict[str, Any]:
        return response

    monkeypatch.setattr(proximity, "call_llm_json", fake)


async def test_single_hypothesis_skips_analysis() -> None:
    """A single hypothesis returns unchanged.

    Proximity no longer advances the iteration counter — the orchestrator owns
    loop bookkeeping (Milestone 2), so the counter is untouched here.
    """
    state = make_state(
        hypotheses=[make_hypothesis(text="only one")], current_iteration=2
    )
    result = await proximity_node(state)
    assert len(result["hypotheses"]) == 1
    assert "current_iteration" not in result


async def test_high_similarity_duplicate_removed_keeping_best_elo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Within a high-similarity cluster, only the top-Elo hypothesis wins."""
    low = make_hypothesis(
        text="alpha pathway drives tumor growth", elo_rating=1200
    )
    high = make_hypothesis(
        text="beta pathway drives tumor growth", elo_rating=1400
    )
    state = make_state(hypotheses=[low, high])
    _stub_clusters(
        monkeypatch,
        {
            "similarity_clusters": [
                {
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
                }
            ]
        },
    )
    result = await proximity_node(state)
    assert len(result["hypotheses"]) == 1
    assert result["hypotheses"][0].elo_rating == 1400
    assert len(result["removed_duplicates"]) == 1
    assert result["removed_duplicates"][0]["elo_rating"] == 1200
    archived = result["removed_duplicates"][0]
    assert archived["hypothesis"]["id"]
    assert archived["hypothesis"]["text"] == archived["text"]
    assert archived["kept_hypothesis_id"]


async def test_low_similarity_keeps_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clusters with no high-similarity members remove nothing."""
    state = make_state(
        hypotheses=[make_hypothesis(text="aaa"), make_hypothesis(text="bbb")]
    )
    _stub_clusters(
        monkeypatch,
        {
            "similarity_clusters": [
                {
                    "cluster_id": "c1",
                    "similar_hypotheses": [
                        {"text": "aaa", "similarity_degree": "low"},
                        {"text": "bbb", "similarity_degree": "medium"},
                    ],
                }
            ]
        },
    )
    result = await proximity_node(state)
    assert len(result["hypotheses"]) == 2
    assert result["removed_duplicates"] == []


async def test_empty_clusters_returns_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty clusters response short-circuits to the original hypotheses."""
    state = make_state(
        hypotheses=[make_hypothesis(text="aaa"), make_hypothesis(text="bbb")]
    )
    _stub_clusters(monkeypatch, {"similarity_clusters": []})
    result = await proximity_node(state)
    assert len(result["hypotheses"]) == 2
    # Proximity no longer touches the iteration counter (orchestrator owns it).
    assert "current_iteration" not in result


async def test_proximity_graph_has_weighted_edge_for_surviving_cluster(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live 2-member cluster yields one weighted edge in the graph.

    Regression guard for the schema-contract bug: the graph builder consumed
    a ``hypotheses`` key while the proximity schema emits
    ``similar_hypotheses``, so production graphs were always empty. This feeds
    the real schema shape through ``proximity_node`` (which calls
    ``_build_proximity_update``) and asserts a nonzero weighted edge. Both
    members are "medium" so both survive dedup and become graph nodes.
    """
    state = make_state(
        hypotheses=[make_hypothesis(text="aaa"), make_hypothesis(text="bbb")]
    )
    _stub_clusters(
        monkeypatch,
        {
            "similarity_clusters": [
                {
                    "cluster_id": "c1",
                    "similar_hypotheses": [
                        {"text": "aaa", "similarity_degree": "medium"},
                        {"text": "bbb", "similarity_degree": "medium"},
                    ],
                }
            ]
        },
    )
    result = await proximity_node(state)
    graph = result["proximity_graph"]
    assert graph["meta"]["edge_count"] == 1
    assert graph["meta"]["node_count"] == 2
    edge = graph["edges"][0]
    assert edge["similarity"] == 0.6  # both members "medium"
    assert edge["cluster_id"] == "c1"


async def test_proximity_graph_excludes_deduped_high_similarity_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A removed high-similarity duplicate is not a graph node.

    The graph is built over dedup survivors (``hypotheses_to_keep``), so a
    cluster whose members are all "high" (one kept, the rest removed) leaves
    no surviving pair and therefore no edge. This pins survivors-only keying
    so a later change cannot "fix" empty edges by pairing against a removed
    hypothesis, which would make the matchmaker compare deleted ideas.
    """
    low = make_hypothesis(
        text="alpha pathway drives tumor growth", elo_rating=1200
    )
    high = make_hypothesis(
        text="beta pathway drives tumor growth", elo_rating=1400
    )
    state = make_state(hypotheses=[low, high])
    _stub_clusters(
        monkeypatch,
        {
            "similarity_clusters": [
                {
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
                }
            ]
        },
    )
    result = await proximity_node(state)
    # One survivor after high-similarity dedup -> no pair -> no edges.
    assert len(result["hypotheses"]) == 1
    assert result["proximity_graph"]["edges"] == []
