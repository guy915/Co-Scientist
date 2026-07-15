"""Tests for the weighted proximity graph builder (Milestone 3).

These feed the builder the *real* proximity-schema shape
(``similarity_clusters[].similar_hypotheses[].text``) that ``proximity_node``
passes in production, not the earlier hand-shaped ``hypotheses`` key that never
existed in a live response.
"""

from co_scientist.agents.proximity.proximity_graph import (
    PROXIMITY_METHOD,
    build_proximity_graph,
    member_match_key,
)


def _id_map(*pairs: tuple[str, str]) -> dict[str, str]:
    """Build a match-key -> id map the way the node does (prefix-normalized)."""
    return {member_match_key(text): hyp_id for text, hyp_id in pairs}


def _clusters() -> list[dict[str, object]]:
    """Two clusters (real schema shape): one pair, one singleton."""
    return [
        {
            "cluster_id": "c1",
            "similar_hypotheses": [
                {"text": "alpha", "similarity_degree": "high"},
                {"text": "beta", "similarity_degree": "medium"},
            ],
        },
        {
            "cluster_id": "c2",
            "similar_hypotheses": [
                {"text": "gamma", "similarity_degree": "low"},
            ],
        },
    ]


_ID_BY_TEXT = _id_map(("alpha", "h-a"), ("beta", "h-b"), ("gamma", "h-c"))


def test_builds_weighted_edges_within_clusters() -> None:
    """A same-cluster pair gets one edge weighted by the stronger degree."""
    graph = build_proximity_graph(
        _clusters(),
        _ID_BY_TEXT,
        research_goal="goal",
        model="fake/model",
        updated_at=123.0,
    )
    edges = graph["edges"]
    assert len(edges) == 1  # only c1 has a pair; c2 is a singleton
    edge = edges[0]
    assert {edge["source"], edge["target"]} == {"h-a", "h-b"}
    # Weight is the stronger of the two members' degrees (high -> 1.0).
    assert edge["similarity"] == 1.0
    assert edge["degree"] == "high"
    assert edge["cluster_id"] == "c1"


def test_graph_meta_records_provenance() -> None:
    """The graph meta carries method/version/model/goal/update-time."""
    graph = build_proximity_graph(
        _clusters(),
        _ID_BY_TEXT,
        research_goal="my goal",
        model="fake/model",
        updated_at=999.0,
    )
    meta = graph["meta"]
    assert meta["method"] == PROXIMITY_METHOD
    assert meta["version"]
    assert meta["model"] == "fake/model"
    assert meta["research_goal"] == "my goal"
    assert meta["updated_at"] == 999.0
    assert meta["edge_count"] == 1
    assert meta["node_count"] == 2


def test_unresolvable_members_are_skipped() -> None:
    """A cluster member whose text is not in the id map is dropped."""
    clusters = [
        {
            "cluster_id": "c1",
            "similar_hypotheses": [
                {"text": "alpha", "similarity_degree": "high"},
                {"text": "unknown", "similarity_degree": "high"},
            ],
        }
    ]
    graph = build_proximity_graph(
        clusters,
        _ID_BY_TEXT,
        research_goal="goal",
        model="m",
        updated_at=1.0,
    )
    # Only one resolvable member -> no pair -> no edges.
    assert graph["edges"] == []


def test_empty_clusters_yield_empty_graph() -> None:
    """No clusters yields an empty edge set with valid meta."""
    graph = build_proximity_graph(
        [], _ID_BY_TEXT, research_goal="goal", model="m", updated_at=1.0
    )
    assert graph["edges"] == []
    assert graph["meta"]["edge_count"] == 0
    assert graph["meta"]["node_count"] == 0


def test_resolves_member_text_drifted_beyond_prefix() -> None:
    """A member echoed with drift past the first 100 chars still resolves.

    The proximity LLM re-quotes each hypothesis's text, and may edit it past
    the first 100 characters (the reason the node matches on a 100-char
    prefix). The graph must key on the same normalized prefix, or the edge is
    silently lost even though the node clustered the members.
    """
    prefix_a = "x" * 100
    prefix_b = "y" * 100
    id_map = _id_map(
        (prefix_a + " canonical tail", "h-1"),
        (prefix_b + " canonical tail", "h-2"),
    )
    clusters = [
        {
            "cluster_id": "c1",
            "similar_hypotheses": [
                # Same first 100 chars as h-1, different tail.
                {
                    "text": prefix_a + " DIFFERENT tail",
                    "similarity_degree": "medium",
                },
                {
                    "text": prefix_b + " also different",
                    "similarity_degree": "medium",
                },
            ],
        }
    ]
    graph = build_proximity_graph(
        clusters, id_map, research_goal="g", model="m", updated_at=1.0
    )
    assert graph["meta"]["edge_count"] == 1
    assert {graph["edges"][0]["source"], graph["edges"][0]["target"]} == {
        "h-1",
        "h-2",
    }
