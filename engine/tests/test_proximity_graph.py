"""Tests for the weighted proximity graph builder (Milestone 3)."""

from co_scientist.nodes.proximity_graph import (
    PROXIMITY_METHOD,
    build_proximity_graph,
)


def _clusters() -> list[dict[str, object]]:
    """Two clusters: one with two similar members, one singleton."""
    return [
        {
            "cluster_id": "c1",
            "hypotheses": [
                {"hypothesis_text": "alpha", "similarity_degree": "high"},
                {"hypothesis_text": "beta", "similarity_degree": "medium"},
            ],
        },
        {
            "cluster_id": "c2",
            "hypotheses": [
                {"hypothesis_text": "gamma", "similarity_degree": "low"},
            ],
        },
    ]


_ID_BY_TEXT = {"alpha": "h-a", "beta": "h-b", "gamma": "h-c"}


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
            "hypotheses": [
                {"hypothesis_text": "alpha", "similarity_degree": "high"},
                {"hypothesis_text": "unknown", "similarity_degree": "high"},
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
