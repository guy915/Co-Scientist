"""Coverage-focused tests for ``co_scientist.agents.evolution.evolve_context``.

``test_evolve.py`` drives ``evolve_node`` end to end, but always with small
hypothesis pools (<=5), so ``sample_context_hypotheses`` never takes its
">max_context others" branch (and therefore never samples). This file
targets those gaps directly, plus the token-coverage similarity metric and
the proximity-weighted peer lookup that replaced the old lexical Jaccard.
"""

import random

from co_scientist.agents.evolution.evolve_context import (
    _sample_up_to,
    combination_partners,
    find_nearest_peer,
    sample_context_hypotheses,
    token_coverage,
)
from co_scientist.models import rank_by_elo
from tests._state import make_hypothesis

# --- _sample_up_to -----------------------------------------------------------


def test_sample_up_to_empty_pool_returns_empty() -> None:
    """An empty pool returns an empty list without consuming random state."""
    assert _sample_up_to([], 5, random.Random(1)) == []


def test_sample_up_to_returns_requested_count() -> None:
    """A pool larger than count returns exactly count items, all from pool."""
    pool = [make_hypothesis(text=f"h{i}") for i in range(20)]
    sampled = _sample_up_to(pool, 10, random.Random(1))
    assert len(sampled) == 10
    assert all(h in pool for h in sampled)


def test_sample_up_to_caps_at_pool_size() -> None:
    """Requesting more than the pool holds returns the whole pool."""
    pool = [make_hypothesis(text=f"h{i}") for i in range(3)]
    sampled = _sample_up_to(pool, 10, random.Random(1))
    assert len(sampled) == 3


def test_sample_up_to_is_reproducible_under_its_seed() -> None:
    """The same seed draws the same sample; a run's context is stable."""
    pool = [make_hypothesis(text=f"h{i}") for i in range(20)]
    first = _sample_up_to(pool, 10, random.Random("run-seed"))
    again = _sample_up_to(pool, 10, random.Random("run-seed"))
    assert first == again


# --- sample_context_hypotheses: large-pool branch ---------------------------


def test_sample_context_hypotheses_large_pool_caps_at_max_context() -> None:
    """With more than max_context others, sampling caps at top-5 + 10 random.

    Twenty other hypotheses with distinct, descending Elo ratings exceed the
    default max_context of 15, forcing the top-5-plus-random-sample branch
    (and, transitively, _sample_up_to) that a small pool never reaches.
    """
    exclude = make_hypothesis(text="the hypothesis being evolved")
    others = [
        make_hypothesis(text=f"other hypothesis {i}", elo_rating=2000 - i)
        for i in range(20)
    ]
    all_hypotheses = [exclude, *others]

    result = sample_context_hypotheses(
        all_hypotheses,
        exclude_hypothesis=exclude,
        max_context=15,
        rng=random.Random(7),
    )

    # Top 5 (highest Elo: others[0..4]) + 10 randomly sampled from the
    # remaining 15 = 15 total, returned as hypothesis objects.
    assert len(result) == 15
    top_five_texts = {h.text for h in others[:5]}
    assert top_five_texts.issubset({h.text for h in result})
    # Every returned hypothesis belongs to the "others" pool, never the
    # excluded hypothesis itself.
    assert all(h.text != exclude.text for h in result)


def test_sample_context_hypotheses_seeded_draws_are_reproducible() -> None:
    """Equal seeds sample equal contexts; the diversity check is stable."""
    exclude = make_hypothesis(text="excluded")
    others = [
        make_hypothesis(text=f"other {i}", elo_rating=100 - i)
        for i in range(30)
    ]
    pool = [exclude, *others]

    first = sample_context_hypotheses(
        pool, exclude_hypothesis=exclude, rng=random.Random("seed-A")
    )
    again = sample_context_hypotheses(
        pool, exclude_hypothesis=exclude, rng=random.Random("seed-A")
    )
    assert first == again


def test_sample_context_hypotheses_small_pool_returns_all() -> None:
    """With others <= max_context, every other hypothesis is included."""
    exclude = make_hypothesis(text="excluded")
    others = [make_hypothesis(text=f"other {i}") for i in range(3)]
    result = sample_context_hypotheses(
        [exclude, *others], exclude_hypothesis=exclude, max_context=15
    )
    assert {h.text for h in result} == {h.text for h in others}


# --- combination_partners ----------------------------------------------------


def test_combination_partners_are_the_top_ranked_peers() -> None:
    """Partners are the strongest peers other than the parent, in order."""
    pool = [
        make_hypothesis(text=f"idea {i}", elo_rating=rating)
        for i, rating in enumerate((1100, 1500, 1300, 1200))
    ]
    ranked = rank_by_elo(pool)
    parent = pool[1]  # the strongest idea: partners are the next two

    partners = combination_partners(ranked, parent)

    assert [p.text for p in partners] == ["idea 2", "idea 3"]


def test_combination_partners_empty_for_a_one_idea_pool() -> None:
    """A pool holding only the parent offers no partners."""
    parent = make_hypothesis(text="the only idea")
    assert combination_partners([parent], parent) == []


# --- token_coverage ----------------------------------------------------------


def test_token_coverage_empty_text_returns_zero() -> None:
    """An empty derived text has no tokens to cover; coverage is 0.0."""
    assert token_coverage("", "some hypothesis text") == 0.0


def test_token_coverage_full_containment_scores_one() -> None:
    """A text whose tokens all appear in the peer is fully covered."""
    assert token_coverage("alpha beta", "alpha beta gamma delta") == 1.0


def test_token_coverage_is_not_dominated_by_peer_length() -> None:
    """Coverage divides by the derived text's tokens, never the union.

    The Jaccard this replaced scored the same pair near
    len(claim) / len(document) however perfectly the peer contained the
    text, which is how both duplicate bands became unreachable.
    """
    short = "alpha beta"
    long_peer = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
    # Contained short text: coverage stays 1.0 at any peer length.
    assert token_coverage(short, long_peer) == 1.0
    # A long refinement reusing a short peer's words is not its duplicate.
    assert token_coverage(long_peer, short) < 0.5


def test_token_coverage_partial_overlap() -> None:
    """Coverage reflects the fraction of the derived text's own tokens."""
    assert token_coverage("alpha beta gamma", "alpha beta delta") == 2 / 3


# --- find_nearest_peer -------------------------------------------------------


def test_find_nearest_peer_empty_candidates_returns_none() -> None:
    """No candidate peers yields (0.0, None)."""
    assert find_nearest_peer("alpha beta", "parent-id", []) == (0.0, None)


def test_find_nearest_peer_falls_back_to_token_coverage() -> None:
    """Without a proximity edge the lexical fallback decides."""
    refined = "alpha beta gamma delta"
    peers = [
        make_hypothesis(text="completely unrelated text"),
        make_hypothesis(text="alpha beta gamma epsilon"),
    ]
    similarity, nearest = find_nearest_peer(refined, "parent-id", peers)
    assert nearest is peers[1]
    assert similarity == 3 / 4


def test_find_nearest_peer_prefers_the_proximity_graph_weight() -> None:
    """A persisted parent-neighbor edge outranks the lexical estimate."""
    refined = "alpha beta gamma delta"
    lexical_peer = make_hypothesis(text="alpha beta gamma epsilon")
    graph_peer = make_hypothesis(text="a disjoint wording entirely")
    graph = {
        "edges": [
            {
                "source": "parent-id",
                "target": graph_peer.id,
                "similarity": 1.0,
            }
        ]
    }
    similarity, nearest = find_nearest_peer(
        refined, "parent-id", [lexical_peer, graph_peer], graph
    )
    assert nearest is graph_peer
    assert similarity == 1.0


def test_find_nearest_peer_reads_both_edge_orientations() -> None:
    """The graph is undirected: target->source edges resolve too."""
    graph_peer = make_hypothesis(text="a disjoint wording entirely")
    graph = {
        "edges": [
            {
                "source": graph_peer.id,
                "target": "parent-id",
                "similarity": 0.6,
            }
        ]
    }
    similarity, nearest = find_nearest_peer(
        "refined wording", "parent-id", [graph_peer], graph
    )
    assert nearest is graph_peer
    assert similarity == 0.6
