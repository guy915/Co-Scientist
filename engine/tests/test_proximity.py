from __future__ import annotations

from typing import Any

import pytest

from co_scientist.agents.proximity import (
    proximity,
    proximity_dedup,
    proximity_node,
)
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
    token_coverage,
)
from co_scientist.models import Hypothesis
from tests._state import make_hypothesis, make_state

# Legacy text-echo fixtures exercise fallback; live responses use indices.
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


# Live schemas name members by index and forbid echoed text.
_HIGH_HIGH_BY_INDEX: dict[str, Any] = {
    "similarity_clusters": [
        {
            "cluster_id": "c1",
            "similar_hypotheses": [
                {"index": 0, "similarity_degree": "high"},
                {"index": 1, "similarity_degree": "high"},
            ],
        }
    ]
}


def _alpha_beta_pair() -> tuple[Hypothesis, Hypothesis]:
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

    async def fake(**_: Any) -> dict[str, Any]:
        return response

    monkeypatch.setattr(proximity, "call_llm_json", fake)


async def test_single_hypothesis_skips_analysis() -> None:
    state = make_state(
        hypotheses=[make_hypothesis(text="only one")], current_iteration=2
    )
    result = await proximity_node(state)
    assert len(result["hypotheses"]) == 1
    assert "current_iteration" not in result


async def test_high_similarity_duplicate_removed_keeping_best_elo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    state = make_state(
        hypotheses=[make_hypothesis(text="aaa"), make_hypothesis(text="bbb")]
    )
    _stub_clusters(monkeypatch, {"similarity_clusters": []})
    result = await proximity_node(state)
    assert len(result["hypotheses"]) == 2
    assert "current_iteration" not in result


async def test_proximity_graph_has_weighted_edge_for_surviving_cluster(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live schemas name members by index and forbid echoed text."""
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
                        {"index": 0, "similarity_degree": "medium"},
                        {"index": 1, "similarity_degree": "medium"},
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
    assert edge["similarity"] == 0.6
    assert edge["cluster_id"] == "c1"


async def test_proximity_graph_excludes_deduped_high_similarity_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Removed prompt positions must not resolve to newly shifted survivors."""
    low, high = _alpha_beta_pair()
    state = make_state(hypotheses=[low, high])
    _stub_clusters(monkeypatch, _HIGH_HIGH_BY_INDEX)
    result = await proximity_node(state)
    assert len(result["hypotheses"]) == 1
    assert result["proximity_graph"]["edges"] == []


@pytest.mark.asyncio
async def test_cluster_members_match_by_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Echoing full hypotheses can exceed output budgets and truncate every
    retry."""
    low, high = _alpha_beta_pair()
    state = make_state(hypotheses=[low, high])
    _stub_clusters(monkeypatch, _HIGH_HIGH_BY_INDEX)

    result = await proximity_node(state)

    assert len(result["hypotheses"]) == 1
    assert result["hypotheses"][0].elo_rating == 1400
    assert len(result["removed_duplicates"]) == 1


@pytest.mark.asyncio
async def test_cluster_members_still_match_by_text_without_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Text prefixes tolerate model quoting drift in legacy responses."""
    low, high = _alpha_beta_pair()
    state = make_state(hypotheses=[low, high])
    _stub_clusters(monkeypatch, _HIGH_HIGH_CLUSTERS)

    result = await proximity_node(state)

    assert len(result["hypotheses"]) == 1
    assert result["hypotheses"][0].elo_rating == 1400


def test_echoed_member_resolves_through_the_normalized_key() -> None:
    hypothesis = make_hypothesis(text="alpha pathway drives tumor growth")

    proximity_dedup._assign_cluster_ids(
        [hypothesis],
        [
            {
                "cluster_id": "c1",
                "similar_hypotheses": [
                    {
                        "text": "  Alpha Pathway Drives Tumor Growth ",
                        "similarity_degree": "high",
                    }
                ],
            }
        ],
    )

    assert hypothesis.similarity_cluster_id == "c1"
    assert hypothesis.similarity_degree == "high"


async def test_drifted_echo_dedupes_and_leaves_no_stale_edge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dedup and graph resolution must agree on member identity."""
    low, high = _alpha_beta_pair()
    state = make_state(hypotheses=[low, high])
    _stub_clusters(
        monkeypatch,
        {
            "similarity_clusters": [
                {
                    "cluster_id": "c1",
                    "similar_hypotheses": [
                        {
                            "text": "  Alpha Pathway Drives Tumor Growth",
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
    assert result["proximity_graph"]["edges"] == []


def test_short_hypotheses_are_sent_whole() -> None:
    from co_scientist.agents.proximity.proximity import (
        _prepare_hypotheses_for_analysis,
    )

    text = "alpha pathway drives tumor growth"
    payload = _prepare_hypotheses_for_analysis([make_hypothesis(text=text)])

    assert payload[0]["text"] == text


def test_long_hypotheses_are_sent_whole() -> None:
    """Deletion decisions need tail differences in methods, assumptions and
    uses."""
    from co_scientist.agents.proximity.proximity import (
        _prepare_hypotheses_for_analysis,
    )

    # Two hypotheses that agree for a long opening and diverge only at the
    # end -- the case a head-only payload silently collapses into one.
    shared_opening = "The alpha pathway drives tumor growth. " * 60
    first = shared_opening + "We propose testing this by CRISPR knockout."
    second = shared_opening + "We propose testing this by serum proteomics."

    payload = _prepare_hypotheses_for_analysis(
        [make_hypothesis(text=first), make_hypothesis(text=second)]
    )

    assert payload[0]["text"] == first
    assert payload[1]["text"] == second
    assert payload[0]["text"] != payload[1]["text"]


def _disjoint_texts(*ids: str) -> dict[str, str]:
    """Disjoint vocabulary suppresses computed edges, isolating judged
    clusters."""
    return {
        hyp_id: " ".join(f"{hyp_id}word{n}" for n in range(6)) for hyp_id in ids
    }


def _survivors(*ids: str, texts: dict[str, str] | None = None) -> SurvivorIndex:
    """An empty text fallback prevents broken index resolution from passing."""
    return SurvivorIndex(
        by_index=dict(enumerate(ids)),
        by_text={},
        texts=texts or _disjoint_texts(*ids),
    )


def _clusters() -> list[dict[str, object]]:
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
    graph = build_proximity_graph(
        _clusters(),
        _SURVIVORS,
        research_goal="goal",
        model="fake/model",
        updated_at=123.0,
    )
    edges = graph["edges"]
    assert len(edges) == 1
    edge = edges[0]
    assert {edge["source"], edge["target"]} == {"h-a", "h-b"}
    assert edge["similarity"] == 1.0
    assert edge["degree"] == "high"
    assert edge["cluster_id"] == "c1"


def test_graph_meta_records_provenance() -> None:
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
    clusters = [
        {
            "cluster_id": "c1",
            "similar_hypotheses": [
                {"index": 0, "similarity_degree": "high"},
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
    assert graph["edges"] == []


def test_empty_clusters_yield_empty_graph() -> None:
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
    """New metrics need new versions so persisted algorithm identities stay
    true."""
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
    assert weights[frozenset({"h-a", "h-b"})] == 1.0
    assert weights[frozenset({"h-a", "h-c"})] == 1.0
    assert weights[frozenset({"h-b", "h-c"})] == 0.6
    assert graph["meta"]["method"] == PROXIMITY_METHOD
    assert graph["meta"]["version"] == PROXIMITY_METHOD_VERSION


def test_graph_is_deterministic_on_fixed_inputs() -> None:
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
    """Legacy echoed members may drift beyond the matching prefix."""
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


_RELATED_TEXTS = {
    "h-a": "autocrine TGF-beta signaling sustains myofibroblast activation",
    "h-b": "myofibroblast activation is sustained by autocrine TGF-beta",
    "h-c": "senescent clearance reduces myofibroblast activation in fibrosis",
}


def _edges_by_pair(graph: dict[str, Any]) -> dict[frozenset[str], Any]:
    return {
        frozenset({str(edge["source"]), str(edge["target"])}): edge
        for edge in graph["edges"]
    }


def _related_graph(clusters: list[dict[str, Any]]) -> dict[str, Any]:
    return build_proximity_graph(
        clusters,
        _survivors("h-a", "h-b", "h-c", texts=_RELATED_TEXTS),
        research_goal="goal",
        model="m",
        updated_at=1.0,
    )


def test_every_pair_of_the_pool_carries_an_edge() -> None:
    graph = _related_graph([])
    by_pair = _edges_by_pair(graph)
    assert len(by_pair) == 3
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
    """Computed similarities fill only pairs the scientific judge left
    unjudged."""
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
    assert _related_graph([]) == _related_graph([])


def test_graph_meta_counts_judged_and_computed_edges_apart() -> None:
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
    """Older checkpoints predate computed edges; their edges are real
    judgments."""
    assert is_judged_edge({"source": "h-a", "target": "h-b"})
    assert not is_judged_edge({"method": PROXIMITY_COMPUTED_METHOD})


def test_a_computed_edge_does_not_reach_the_duplicate_guard() -> None:
    """A parent-peer metric cannot detect child-peer convergence."""
    from co_scientist.agents.evolution.evolve_prompt import find_nearest_peer
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


_HYPOTHESIS = (
    "Autocrine TGF-beta signaling makes myofibroblast activation "
    "self-sustaining in established pulmonary fibrosis."
)


def test_identical_texts_score_at_the_top_of_the_range() -> None:
    assert pair_similarity(_HYPOTHESIS, _HYPOTHESIS) == 1.0


def test_disjoint_vocabulary_scores_at_the_bottom() -> None:
    unrelated = "Tidal mixing redistributes heat across the Southern Ocean."
    assert pair_similarity("alpha beta gamma delta", unrelated) == 0.0


def test_similarity_is_symmetric() -> None:
    other = (
        "Senescent cell clearance reduces inflammation without reversing "
        "established pulmonary fibrosis."
    )
    forward = pair_similarity(_HYPOTHESIS, other)
    assert 0.0 < forward < 1.0
    assert forward == pair_similarity(other, _HYPOTHESIS)


def test_containment_alone_does_not_score_as_identical() -> None:
    """One-sided token containment would misclassify short/long ideas as
    duplicates."""
    short = "alpha beta"
    long_text = "alpha beta " + " ".join(f"term{i}" for i in range(20))
    assert token_coverage(short, long_text) == 1.0
    assert pair_similarity(short, long_text) < 0.25


def test_empty_text_scores_zero() -> None:
    assert pair_similarity("", _HYPOTHESIS) == 0.0
    assert pair_similarity(_HYPOTHESIS, "") == 0.0
