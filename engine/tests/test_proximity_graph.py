"""Tests for the weighted proximity graph builder (Milestone 3).

These feed the builder the shape a live ``PROXIMITY_SCHEMA`` response emits:
``similarity_clusters[].similar_hypotheses[].index``, with no ``text`` key at
all (the schema sets ``additionalProperties: False`` and does not declare one).
Fixtures that echoed ``text`` instead exercised only the fallback path, so they
stayed green through the whole period in which every production graph was
empty.
"""

from co_scientist.agents.proximity.proximity_graph import (
    PROXIMITY_METHOD,
    PROXIMITY_METHOD_VERSION,
    SurvivorIndex,
    build_proximity_graph,
    member_match_key,
)


def _survivors(*ids: str) -> SurvivorIndex:
    """Build a survivor index from ids in prompt order (index i -> ids[i]).

    ``by_text`` is left empty on purpose: a live response carries no member
    text, so leaving the fallback table populated would let these tests
    resolve a member by text and pass even with the index path broken.
    """
    return SurvivorIndex(by_index=dict(enumerate(ids)), by_text={})


def _clusters() -> list[dict[str, object]]:
    """Two clusters (live schema shape): one pair, one singleton."""
    return [
        {
            "cluster_id": "c1",
            "similar_hypotheses": [
                {"index": 0, "similarity_degree": "high"},
                {"index": 1, "similarity_degree": "medium"},
            ],
        },
        {
            "cluster_id": "c2",
            "similar_hypotheses": [
                {"index": 2, "similarity_degree": "low"},
            ],
        },
    ]


_SURVIVORS = _survivors("h-a", "h-b", "h-c")


def test_builds_weighted_edges_within_clusters() -> None:
    """A same-cluster pair gets one edge weighted by the stronger degree."""
    graph = build_proximity_graph(
        _clusters(),
        _SURVIVORS,
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
        _SURVIVORS,
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
    """A member whose index is not a survivor's position is dropped."""
    clusters = [
        {
            "cluster_id": "c1",
            "similar_hypotheses": [
                {"index": 0, "similarity_degree": "high"},
                # No survivor sits at this position: either dedup removed it
                # or the model invented an out-of-range index.
                {"index": 7, "similarity_degree": "high"},
            ],
        }
    ]
    graph = build_proximity_graph(
        clusters,
        _SURVIVORS,
        research_goal="goal",
        model="m",
        updated_at=1.0,
    )
    # Only one resolvable member -> no pair -> no edges.
    assert graph["edges"] == []


def test_empty_clusters_yield_empty_graph() -> None:
    """No clusters yields an empty edge set with valid meta."""
    graph = build_proximity_graph(
        [], _SURVIVORS, research_goal="goal", model="m", updated_at=1.0
    )
    assert graph["edges"] == []
    assert graph["meta"]["edge_count"] == 0
    assert graph["meta"]["node_count"] == 0


def test_documented_local_algorithm_identity_and_weights() -> None:
    """The H2 documented local choice: llm-cluster v1, fixed degree weights.

    The paper leaves the similarity metric open ("e.g. text embeddings"),
    so this deployment's first-class algorithm is the LLM-judged cluster
    with the fixed qualitative-degree mapping. Pinning the identity and
    the weights keeps the documented algorithm and the implemented one the
    same thing; a future metric must register as a new method/version.
    """
    assert PROXIMITY_METHOD == "llm-cluster"
    assert PROXIMITY_METHOD_VERSION == "1"

    graph = build_proximity_graph(
        [
            {
                "cluster_id": "c1",
                "similar_hypotheses": [
                    {"index": 0, "similarity_degree": "high"},
                    {"index": 1, "similarity_degree": "medium"},
                    {"index": 2, "similarity_degree": "low"},
                ],
            }
        ],
        _survivors("h-a", "h-b", "h-c"),
        research_goal="goal",
        model="m",
        updated_at=1.0,
    )
    weights = {
        frozenset((edge["source"], edge["target"])): edge["similarity"]
        for edge in graph["edges"]
    }
    # The stronger of each pair's degrees sets the weight: high/medium and
    # high/low pairs both read 1.0, the medium/low pair reads 0.6.
    assert weights[frozenset({"h-a", "h-b"})] == 1.0
    assert weights[frozenset({"h-a", "h-c"})] == 1.0
    assert weights[frozenset({"h-b", "h-c"})] == 0.6
    assert graph["meta"]["method"] == PROXIMITY_METHOD
    assert graph["meta"]["version"] == PROXIMITY_METHOD_VERSION


def test_graph_is_deterministic_on_fixed_inputs() -> None:
    """Two builds from identical inputs are identical, edges and meta.

    The documented algorithm promises reproducibility: given a fixed
    clustering output, the persisted graph -- edge set, weights, order,
    and provenance -- is a pure function of it.
    """
    clusters = _clusters()
    first = build_proximity_graph(
        clusters,
        _SURVIVORS,
        research_goal="goal",
        model="fake/model",
        updated_at=42.0,
    )
    second = build_proximity_graph(
        clusters,
        _SURVIVORS,
        research_goal="goal",
        model="fake/model",
        updated_at=42.0,
    )
    assert first == second


def test_resolves_member_text_drifted_beyond_prefix() -> None:
    """A member echoed with drift past the first 100 chars still resolves.

    An older response echoes each hypothesis's text instead of its index, and
    may edit it past the first 100 characters (the reason the node matches on
    a 100-char prefix). The fallback must key on the same normalized prefix,
    or the edge is silently lost even though the node clustered the members.
    """
    prefix_a = "x" * 100
    prefix_b = "y" * 100
    survivors = SurvivorIndex(
        by_index={},
        by_text={
            member_match_key(prefix_a + " canonical tail"): "h-1",
            member_match_key(prefix_b + " canonical tail"): "h-2",
        },
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
        clusters, survivors, research_goal="g", model="m", updated_at=1.0
    )
    assert graph["meta"]["edge_count"] == 1
    assert {graph["edges"][0]["source"], graph["edges"][0]["target"]} == {
        "h-1",
        "h-2",
    }
