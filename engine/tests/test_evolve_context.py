"""Coverage-focused tests for ``co_scientist.nodes.evolve_context``.

``test_evolve.py`` drives ``evolve_node`` end to end, but always with small
hypothesis pools (<=5), so ``sample_context_hypotheses`` never takes its
">max_context others" branch (and therefore never calls ``_sample_up_to``).
It also never calls ``calculate_text_similarity`` with an empty text, or
``_find_most_similar`` with a genuinely more-similar candidate. This file
targets those gaps directly.
"""

from co_scientist.nodes.evolve_context import (
    _find_most_similar,
    _sample_up_to,
    calculate_text_similarity,
    sample_context_hypotheses,
)
from tests._state import make_hypothesis

# --- _sample_up_to -----------------------------------------------------------


def test_sample_up_to_empty_pool_returns_empty() -> None:
    """An empty pool returns an empty list without consuming random state."""
    assert _sample_up_to([], 5) == []


def test_sample_up_to_returns_requested_count() -> None:
    """A pool larger than count returns exactly count items, all from pool."""
    pool = [make_hypothesis(text=f"h{i}") for i in range(20)]
    sampled = _sample_up_to(pool, 10)
    assert len(sampled) == 10
    assert all(h in pool for h in sampled)


def test_sample_up_to_caps_at_pool_size() -> None:
    """Requesting more than the pool holds returns the whole pool."""
    pool = [make_hypothesis(text=f"h{i}") for i in range(3)]
    sampled = _sample_up_to(pool, 10)
    assert len(sampled) == 3


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
        all_hypotheses, exclude_hypothesis=exclude, max_context=15
    )

    # Top 5 (highest Elo: others[0..4]) + 10 randomly sampled from the
    # remaining 15 = 15 total.
    assert len(result) == 15
    top_five_texts = {h.text for h in others[:5]}
    assert top_five_texts.issubset(set(result))
    # Every returned text belongs to the "others" pool, never the excluded
    # hypothesis itself.
    other_texts = {h.text for h in others}
    assert set(result).issubset(other_texts)


def test_sample_context_hypotheses_small_pool_returns_all() -> None:
    """With others <= max_context, every other hypothesis is included."""
    exclude = make_hypothesis(text="excluded")
    others = [make_hypothesis(text=f"other {i}") for i in range(3)]
    result = sample_context_hypotheses(
        [exclude, *others], exclude_hypothesis=exclude, max_context=15
    )
    assert set(result) == {h.text for h in others}


# --- calculate_text_similarity ----------------------------------------------


def test_calculate_text_similarity_empty_text_returns_zero() -> None:
    """An empty text has no words to overlap with; similarity is 0.0."""
    assert calculate_text_similarity("", "some hypothesis text") == 0.0
    assert calculate_text_similarity("some hypothesis text", "") == 0.0
    assert calculate_text_similarity("", "") == 0.0


def test_calculate_text_similarity_partial_overlap() -> None:
    """Jaccard similarity reflects the word-set intersection over union."""
    similarity = calculate_text_similarity(
        "alpha beta gamma", "alpha beta delta"
    )
    # Intersection {alpha, beta} = 2, union {alpha, beta, gamma, delta} = 4.
    assert similarity == 0.5


# --- _find_most_similar -------------------------------------------------


def test_find_most_similar_empty_candidates_returns_none() -> None:
    """No candidate texts yields (0.0, None)."""
    assert _find_most_similar("alpha beta", []) == (0.0, None)


def test_find_most_similar_picks_highest_similarity_candidate() -> None:
    """The candidate with the greatest word overlap is returned."""
    refined = "alpha beta gamma delta"
    candidates = [
        "completely unrelated text",
        "alpha beta gamma epsilon",  # 3/5 overlap, the closest match
        "alpha only",
    ]
    similarity, most_similar = _find_most_similar(refined, candidates)
    assert most_similar == "alpha beta gamma epsilon"
    assert similarity > 0.0
