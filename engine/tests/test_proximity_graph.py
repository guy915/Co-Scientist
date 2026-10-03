"""Tests for the weighted proximity graph builder (Milestone 3).

These feed the builder the shape a live ``PROXIMITY_SCHEMA`` response emits:
``similarity_clusters[].similar_hypotheses[].index``, with no ``text`` key at
all (the schema sets ``additionalProperties: False`` and does not declare one).
Fixtures that echoed ``text`` instead exercised only the fallback path, so they
stayed green through the whole period in which every production graph was
empty.
"""

from typing import Any

from co_scientist.agents.proximity.proximity_graph import (
    PROXIMITY_COMPUTED_DEGREE,
    PROXIMITY_COMPUTED_METHOD,
    PROXIMITY_EDGE_FLOOR,
    PROXIMITY_METHOD,
    PROXIMITY_METHOD_VERSION,
    SurvivorIndex,
    build_proximity_graph,
    is_judged_edge,
    member_match_key,
    pair_similarity,
)


def _disjoint_texts(*ids: str) -> dict[str, str]:
    """One text per id, sharing no vocabulary with any of the others.

    The cluster fixtures below assert on the *judged* edges alone, so their
    hypotheses are given deliberately disjoint wording: every computed pair
    scores 0.0, which is below ``PROXIMITY_EDGE_FLOOR``, so no computed edge
    joins the graph and the counts stay about what the clustering said.
    ``test_a_disjoint_pair_is_below_the_floor`` pins that this is by design
    rather than by luck.
    """
    return {
        hyp_id: " ".join(f"{hyp_id}word{n}" for n in range(6)) for hyp_id in ids
    }


def _survivors(*ids: str, texts: dict[str, str] | None = None) -> SurvivorIndex:
    """Build a survivor index from ids in prompt order (index i -> ids[i]).

    Texts default to ``_disjoint_texts``, so a fixture that says nothing
    about them gets no computed edges at all and its assertions are about
    the clustering alone.

    ``by_text`` is left empty on purpose: a live response carries no member
    text, so leaving the fallback table populated would let these tests
    resolve a member by text and pass even with the index path broken.
    """
    return SurvivorIndex(
        by_index=dict(enumerate(ids)),
        by_text={},
        texts=texts or _disjoint_texts(*ids),
    )


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
        [],
        _SURVIVORS,
        research_goal="goal",
        model="m",
        updated_at=1.0,
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
        texts={
            "h-1": prefix_a + " canonical tail",
            "h-2": prefix_b + " canonical tail",
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
        clusters,
        survivors,
        research_goal="g",
        model="m",
        updated_at=1.0,
    )
    assert graph["meta"]["edge_count"] == 1
    assert {graph["edges"][0]["source"], graph["edges"][0]["target"]} == {
        "h-1",
        "h-2",
    }


# --- Every pair: a computed edge wherever the clustering drew none ----------
#
# Listing 06 quantifies over every pair of hypotheses, and the clustering call
# relates only the pairs it chose to cluster. The builder measures the rest
# deterministically (``proximity_graph.pair_similarity``, zero extra LLM
# calls) and keeps the ones at or above ``PROXIMITY_EDGE_FLOOR``. These pin
# that coverage, the precedence of a judged edge over a computed one, and the
# two ends of the metric's range.

_RELATED_TEXTS = {
    "h-a": "autocrine TGF-beta signaling sustains myofibroblast activation",
    "h-b": "myofibroblast activation is sustained by autocrine TGF-beta",
    "h-c": "senescent clearance reduces myofibroblast activation in fibrosis",
}


def _edges_by_pair(graph: dict[str, Any]) -> dict[frozenset[str], Any]:
    """Index a graph's edges by their unordered endpoint pair."""
    return {
        frozenset({str(edge["source"]), str(edge["target"])}): edge
        for edge in graph["edges"]
    }


def _related_graph(clusters: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the graph over ``_RELATED_TEXTS`` with the given clustering."""
    return build_proximity_graph(
        clusters,
        _survivors("h-a", "h-b", "h-c", texts=_RELATED_TEXTS),
        research_goal="goal",
        model="m",
        updated_at=1.0,
    )


def test_every_pair_of_the_pool_carries_an_edge() -> None:
    """With no clustering at all, all n(n-1)/2 pairs are still measured."""
    graph = _related_graph([])
    by_pair = _edges_by_pair(graph)
    assert len(by_pair) == 3  # 3 * 2 / 2
    assert set(by_pair) == {
        frozenset({"h-a", "h-b"}),
        frozenset({"h-a", "h-c"}),
        frozenset({"h-b", "h-c"}),
    }
    for pair, edge in by_pair.items():
        left, right = sorted(pair)
        assert edge["similarity"] == pair_similarity(
            _RELATED_TEXTS[left], _RELATED_TEXTS[right]
        )
        assert edge["method"] == PROXIMITY_COMPUTED_METHOD
        assert edge["degree"] == PROXIMITY_COMPUTED_DEGREE
        assert edge["cluster_id"] is None


def test_a_judged_edge_overrides_the_computed_value() -> None:
    """Where the clustering spoke, its verdict is the pair's only edge.

    ``h-a``/``h-b`` are near-paraphrases, so the computed metric scores them
    far above the "low" degree the clustering assigned. The judged weight
    still wins: the LLM pass is the first-class algorithm and the computed
    value only fills in the pairs it left unjudged.
    """
    computed = pair_similarity(_RELATED_TEXTS["h-a"], _RELATED_TEXTS["h-b"])
    graph = _related_graph(
        [
            {
                "cluster_id": "c1",
                "similar_hypotheses": [
                    {"index": 0, "similarity_degree": "low"},
                    {"index": 1, "similarity_degree": "low"},
                ],
            }
        ]
    )
    edge = _edges_by_pair(graph)[frozenset({"h-a", "h-b"})]
    assert computed > 0.3
    assert edge["similarity"] == 0.3
    assert edge["degree"] == "low"
    assert edge["cluster_id"] == "c1"
    assert edge["method"] == PROXIMITY_METHOD
    assert is_judged_edge(edge)


def test_a_computed_edge_is_symmetric() -> None:
    """Swapping the pool order leaves every computed weight unchanged."""
    forward = _edges_by_pair(_related_graph([]))
    reversed_pool = build_proximity_graph(
        [],
        _survivors("h-c", "h-b", "h-a", texts=_RELATED_TEXTS),
        research_goal="goal",
        model="m",
        updated_at=1.0,
    )
    backward = _edges_by_pair(reversed_pool)
    assert {pair: edge["similarity"] for pair, edge in forward.items()} == {
        pair: edge["similarity"] for pair, edge in backward.items()
    }


def test_an_identical_pair_scores_at_the_top_of_the_range() -> None:
    """Two verbatim-identical survivors are measured as fully similar."""
    text = _RELATED_TEXTS["h-a"]
    graph = build_proximity_graph(
        [],
        _survivors("h-a", "h-b", texts={"h-a": text, "h-b": text}),
        research_goal="goal",
        model="m",
        updated_at=1.0,
    )
    assert graph["edges"][0]["similarity"] == 1.0


def test_a_disjoint_pair_is_below_the_floor() -> None:
    """A topically unrelated pair is measured, scores 0.0, and is not stored.

    The floor is what bounds the persisted graph (see its constant), so the
    below-floor case must be absent *because it was measured and found
    unrelated*, not because the pair was never considered. Asserting the
    measurement here is what makes the absence a design, not an accident.
    """
    texts = _disjoint_texts("h-a", "h-b")
    assert pair_similarity(texts["h-a"], texts["h-b"]) < PROXIMITY_EDGE_FLOOR
    graph = build_proximity_graph(
        [],
        _survivors("h-a", "h-b", texts=texts),
        research_goal="goal",
        model="m",
        updated_at=1.0,
    )
    assert graph["edges"] == []
    assert graph["meta"]["edge_floor"] == PROXIMITY_EDGE_FLOOR


def test_computed_edges_are_deterministic() -> None:
    """The same pool and texts yield a byte-identical graph."""
    assert _related_graph([]) == _related_graph([])


def test_graph_meta_counts_judged_and_computed_edges_apart() -> None:
    """Meta keeps ``edge_count`` judged-only and reports computed beside it."""
    graph = _related_graph(
        [
            {
                "cluster_id": "c1",
                "similar_hypotheses": [
                    {"index": 0, "similarity_degree": "high"},
                    {"index": 1, "similarity_degree": "high"},
                ],
            }
        ]
    )
    meta = graph["meta"]
    assert meta["edge_count"] == 1
    assert meta["computed_edge_count"] == 2
    assert len(graph["edges"]) == 3
    assert meta["version"] == PROXIMITY_METHOD_VERSION


def test_an_edge_without_a_method_reads_as_judged() -> None:
    """A graph checkpointed before this change resumes as all-judged.

    Every edge under ``edges`` in an older checkpoint came from the
    clustering call -- the computed ones did not exist and the placeholder
    ones lived under a separate key nothing reads now -- so a missing
    ``method`` must not demote a real judgement to a computed value.
    """
    assert is_judged_edge({"source": "h-a", "target": "h-b"})
    assert not is_judged_edge({"method": PROXIMITY_COMPUTED_METHOD})


def test_a_computed_edge_does_not_reach_the_duplicate_guard() -> None:
    """Evolution measures the child against the peer, never the parent.

    ``find_nearest_peer`` prefers a proximity edge's weight over its own
    token-coverage reading, and a computed edge scores the *parent* against
    the peer -- which cannot see a child that converged onto that peer. So
    only judged edges are consulted there, and the guard's own child-vs-peer
    measurement decides the rest. Imported from the evolution package on
    purpose: this fails the moment the filter is dropped.
    """
    from co_scientist.agents.evolution.evolve_context import find_nearest_peer
    from tests._state import make_hypothesis

    peer = make_hypothesis(text="alpha beta gamma delta epsilon zeta")
    graph = {
        "edges": [
            {
                "source": "parent-id",
                "target": peer.id,
                "similarity": 0.4,
                "method": PROXIMITY_COMPUTED_METHOD,
            }
        ]
    }
    similarity, nearest = find_nearest_peer(
        peer.text, "parent-id", [peer], graph
    )
    assert nearest is peer
    assert similarity == 1.0
