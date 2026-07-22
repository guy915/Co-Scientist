"""Tests for proximity_node: clustering and high-similarity deduplication.

The node's only external dependency is a single ``call_llm_json`` call that
returns similarity clusters; these tests stub that out and assert on the
deterministic clustering/dedup logic and the returned state update.
"""

from typing import Any

import pytest

from co_scientist.agents.proximity import proximity, proximity_node
from co_scientist.models import Hypothesis
from tests._state import make_hypothesis, make_state

# A two-member cluster whose members are both "high" similarity: dedup keeps
# only the top-Elo member. Shared verbatim across the high-similarity tests.
_HIGH_HIGH_CLUSTERS: dict[str, Any] = {
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
}


def _alpha_beta_pair() -> tuple[Hypothesis, Hypothesis]:
    """The low-Elo alpha / high-Elo beta hypotheses used by the dedup tests."""
    low = make_hypothesis(
        text="alpha pathway drives tumor growth", elo_rating=1200
    )
    high = make_hypothesis(
        text="beta pathway drives tumor growth", elo_rating=1400
    )
    return low, high


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
    low, high = _alpha_beta_pair()
    state = make_state(hypotheses=[low, high])
    _stub_clusters(monkeypatch, _HIGH_HIGH_CLUSTERS)
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
    low, high = _alpha_beta_pair()
    state = make_state(hypotheses=[low, high])
    _stub_clusters(monkeypatch, _HIGH_HIGH_CLUSTERS)
    result = await proximity_node(state)
    # One survivor after high-similarity dedup -> no pair -> no edges.
    assert len(result["hypotheses"]) == 1
    assert result["proximity_graph"]["edges"] == []


@pytest.mark.asyncio
async def test_cluster_members_match_by_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cluster member is resolved by the index the prompt already assigns.

    The response schema used to require each member to echo its hypothesis's
    full text, while matching only ever read the first 100 characters. On a
    large pool that echo cannot fit: 46 hypotheses averaging 1250 characters
    need roughly 14k output tokens against a 10k budget, so the JSON
    truncated, every retry truncated identically, and the node fell through
    to "no similarity clusters" -- burning five attempts and silently
    skipping deduplication. Returning the index keeps the same clustering
    judgement in an encoding that fits.
    """
    low, high = _alpha_beta_pair()
    state = make_state(hypotheses=[low, high])
    _stub_clusters(
        monkeypatch,
        {
            "similarity_clusters": [
                {
                    "cluster_id": "c1",
                    "similar_hypotheses": [
                        {"index": 0, "similarity_degree": "high"},
                        {"index": 1, "similarity_degree": "high"},
                    ],
                }
            ]
        },
    )

    result = await proximity_node(state)

    assert len(result["hypotheses"]) == 1
    assert result["hypotheses"][0].elo_rating == 1400
    assert len(result["removed_duplicates"]) == 1


@pytest.mark.asyncio
async def test_cluster_members_still_match_by_text_without_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Text matching stays as a fallback when a response omits the index.

    Text-prefix matching was chosen for robustness against the quoting drift
    a model introduces, so it remains the fallback rather than being replaced.
    """
    low, high = _alpha_beta_pair()
    state = make_state(hypotheses=[low, high])
    _stub_clusters(monkeypatch, _HIGH_HIGH_CLUSTERS)

    result = await proximity_node(state)

    assert len(result["hypotheses"]) == 1
    assert result["hypotheses"][0].elo_rating == 1400
