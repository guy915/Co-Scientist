"""Tests for the weighted proximity graph builder (Milestone 3).

These feed the builder the shape a live ``PROXIMITY_SCHEMA`` response emits:
``similarity_clusters[].similar_hypotheses[].index``, with no ``text`` key at
all (the schema sets ``additionalProperties: False`` and does not declare one).
Fixtures that echoed ``text`` instead exercised only the fallback path, so they
stayed green through the whole period in which every production graph was
empty.
"""

from co_scientist.agents.proximity.proximity_graph import (
    _DEGREE_WEIGHT,
    PROXIMITY_FLOOR_NEIGHBOUR_CAP,
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


# --- Total graph: a floor edge for every pair the clustering left apart ---
#
# Listing 06 quantifies over every pair ("FOR EACH pair of hypotheses in the
# HypothesesList"), so a pair the clustering did not relate must carry a
# low-weight edge rather than no edge. These pin the shape of that, not its
# numbers: the floor edges live under their own key, are capped per node, and
# are deterministic.


def _pair_keys(edges: list[dict[str, object]]) -> set[frozenset[str]]:
    """Unordered endpoint pairs of a graph edge list."""
    return {frozenset({str(e["source"]), str(e["target"])}) for e in edges}


def test_unclustered_pairs_get_a_floor_edge() -> None:
    """A pair no cluster related is connected at the floor weight."""
    graph = build_proximity_graph(
        _clusters(),
        _SURVIVORS,
        research_goal="goal",
        model="fake/model",
        updated_at=1.0,
    )
    floor = graph["floor_edges"]
    assert _pair_keys(floor) == {
        frozenset({"h-a", "h-c"}),
        frozenset({"h-b", "h-c"}),
    }
    assert all(edge["similarity"] < _DEGREE_WEIGHT["low"] for edge in floor)
    assert all(edge["cluster_id"] is None for edge in floor)


def test_floor_edges_never_shadow_a_cluster_edge() -> None:
    """A pair the clustering related keeps its judged weight only."""
    graph = build_proximity_graph(
        _clusters(),
        _SURVIVORS,
        research_goal="goal",
        model="fake/model",
        updated_at=1.0,
    )
    judged = _pair_keys(graph["edges"])
    assert judged & _pair_keys(graph["floor_edges"]) == set()


def test_floor_edges_are_capped_per_node() -> None:
    """No node exceeds the neighbour cap once floor edges are added."""
    survivors = _survivors(*[f"h-{i}" for i in range(22)])
    graph = build_proximity_graph(
        [], survivors, research_goal="goal", model="m", updated_at=1.0
    )
    degrees: dict[str, int] = {}
    for edge in graph["floor_edges"]:
        for side in ("source", "target"):
            node = str(edge[side])
            degrees[node] = degrees.get(node, 0) + 1
    assert degrees, "a 22-node pool must gain floor edges"
    assert max(degrees.values()) <= PROXIMITY_FLOOR_NEIGHBOUR_CAP
    # Capped, so the graph is far short of the 231 pairs a complete graph has.
    assert len(graph["floor_edges"]) < 22 * 21 // 2


def test_floor_edges_are_deterministic() -> None:
    """The same pool yields byte-identical floor edges."""
    survivors = _survivors(*[f"h-{i}" for i in range(9)])
    graphs = [
        build_proximity_graph(
            [], survivors, research_goal="goal", model="m", updated_at=1.0
        )
        for _ in range(2)
    ]
    assert graphs[0]["floor_edges"] == graphs[1]["floor_edges"]


def test_floor_edges_do_not_reach_the_evolution_duplicate_guard() -> None:
    """Evolution's peer similarity must not read a floor edge as a judgement.

    ``find_nearest_peer`` prefers a proximity edge's weight over its own
    token-coverage measurement, so a floor edge under ``edges`` would replace
    a real measurement with a placeholder and let a near-duplicate child pass
    the guard. That is why the floor edges carry their own key. Imported from
    the evolution package on purpose: this fails the moment someone folds the
    two lists together.
    """
    from co_scientist.agents.evolution.evolve_context import (
        proximity_weights_for,
    )

    survivors = _survivors("h-a", "h-b", "h-c")
    graph = build_proximity_graph(
        [], survivors, research_goal="goal", model="m", updated_at=1.0
    )
    assert graph["floor_edges"], "the pool must have gained floor edges"
    assert proximity_weights_for(graph, "h-a") == {}


def test_graph_meta_records_the_floor_edges() -> None:
    """Meta reports the floor edge count and the cap that bounded it."""
    graph = build_proximity_graph(
        _clusters(),
        _SURVIVORS,
        research_goal="goal",
        model="m",
        updated_at=1.0,
    )
    meta = graph["meta"]
    assert meta["floor_edge_count"] == len(graph["floor_edges"])
    assert meta["neighbour_cap"] == PROXIMITY_FLOOR_NEIGHBOUR_CAP
    # Version 1 edges are unchanged; the floor list is additive.
    assert meta["version"] == PROXIMITY_METHOD_VERSION
    assert meta["edge_count"] == len(graph["edges"])
