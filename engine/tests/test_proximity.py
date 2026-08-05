"""Tests for proximity_node: clustering and high-similarity deduplication.

The node's only external dependency is a single ``call_llm_json`` call that
returns similarity clusters; these tests stub that out and assert on the
deterministic clustering/dedup logic and the returned state update.
"""

from typing import Any

import pytest

from co_scientist.agents.proximity import (
    proximity,
    proximity_dedup,
    proximity_node,
)
from co_scientist.models import Hypothesis
from tests._state import make_hypothesis, make_state

# A two-member cluster whose members are both "high" similarity: dedup keeps
# only the top-Elo member. This is the retired text-echo shape, kept for the
# tests that exercise the echoed-text fallback specifically; anything asserting
# on what production does should use _HIGH_HIGH_BY_INDEX below.
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


# The same two-member "high"/"high" cluster in the live schema shape: members
# are named by the index the prompt assigned and carry no ``text`` key at all,
# which is what PROXIMITY_SCHEMA permits.
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

    Regression guard for the schema-contract bug, which recurred once the
    schema stopped echoing member text: the graph builder resolved members by
    ``text`` only, ``PROXIMITY_SCHEMA`` emits ``index`` and forbids ``text``,
    so every member resolved to nothing and every production graph was empty
    while deduplication (which resolves by index) kept working. The members
    below carry no ``text`` key, exactly as a live response does, so the
    index path is the only way this edge can exist. Both are "medium" so both
    survive dedup and become graph nodes.
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
    assert edge["similarity"] == 0.6  # both members "medium"
    assert edge["cluster_id"] == "c1"


async def test_proximity_graph_excludes_deduped_high_similarity_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A removed high-similarity duplicate is not a graph node.

    The graph is built over dedup survivors, so a cluster whose members are
    all "high" (one kept, the rest removed) leaves no surviving pair and
    therefore no edge. Members carry the live ``index`` shape, so this pins
    survivors-only resolution on the path production actually takes: the
    dropped duplicate's prompt position must resolve to nothing rather than
    to whichever hypothesis now sits at that position. A later change cannot
    "fix" empty edges by pairing against a removed hypothesis, which would
    persist edges to ideas the report no longer contains.
    """
    low, high = _alpha_beta_pair()
    state = make_state(hypotheses=[low, high])
    _stub_clusters(monkeypatch, _HIGH_HIGH_BY_INDEX)
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
    _stub_clusters(monkeypatch, _HIGH_HIGH_BY_INDEX)

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


def test_echoed_member_resolves_through_the_normalized_key() -> None:
    """Case and whitespace drift in an echoed member still resolves.

    The fallback compares a re-quote against the stored text, so it has to
    normalize the way the persisted graph's own lookup does. Comparing raw
    prefixes made a capitalized or space-padded re-quote a stranger to
    clustering and a member to the graph, from one model response.
    """
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
    """Dedup and the persisted graph agree on who a cluster member is.

    They resolve the same echoed text with the same key, so a member either
    counts for both or for neither. Resolving it only in the graph left a
    persisted high-similarity edge between two hypotheses deduplication had
    just judged distinct enough to both keep.
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
    # The dropped member is gone from the graph too, rather than persisting
    # as an edge to a survivor that no longer has a neighbour.
    assert result["proximity_graph"]["edges"] == []


# --- Prompt payload clipping -------------------------------------------------


def test_short_hypotheses_are_sent_whole() -> None:
    """A hypothesis inside the budget reaches the prompt untouched."""
    from co_scientist.agents.proximity.proximity import (
        _prepare_hypotheses_for_analysis,
    )

    text = "alpha pathway drives tumor growth"
    payload = _prepare_hypotheses_for_analysis([make_hypothesis(text=text)])

    assert payload[0]["text"] == text


def test_long_hypotheses_are_sent_whole() -> None:
    """The clustering payload is never truncated, however long the text.

    Proximity is the tempting place to economise -- it is the only node that
    puts the whole pool in one prompt -- and the wrong one. Its verdict
    deletes work, and the differences that spare a hypothesis from a "high"
    are argued in the tail: methodology, assumptions, applications. A head
    that reads identically to a neighbour's is not evidence the two are
    duplicates. Truncation here was tried and reverted; this pins it out.
    """
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
