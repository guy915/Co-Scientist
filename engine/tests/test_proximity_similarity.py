"""Tests for the proximity graph's deterministic pairwise similarity.

These pin the *shape* of the metric, not tuned numbers: symmetry, the two
ends of its range, and the containment case that rules out the maximum of
the two directional coverages.
"""

from co_scientist.agents.proximity.proximity_similarity import (
    pair_similarity,
    token_coverage,
)

_HYPOTHESIS = (
    "Autocrine TGF-beta signaling makes myofibroblast activation "
    "self-sustaining in established pulmonary fibrosis."
)


def test_identical_texts_score_at_the_top_of_the_range() -> None:
    """A verbatim-identical pair is the maximum the metric can report."""
    assert pair_similarity(_HYPOTHESIS, _HYPOTHESIS) == 1.0


def test_disjoint_vocabulary_scores_at_the_bottom() -> None:
    """A topically unrelated pair shares no tokens and scores zero."""
    unrelated = "Tidal mixing redistributes heat across the Southern Ocean."
    assert pair_similarity("alpha beta gamma delta", unrelated) == 0.0


def test_similarity_is_symmetric() -> None:
    """Neither hypothesis is privileged: the two orders agree exactly."""
    other = (
        "Senescent cell clearance reduces inflammation without reversing "
        "established pulmonary fibrosis."
    )
    forward = pair_similarity(_HYPOTHESIS, other)
    assert 0.0 < forward < 1.0
    assert forward == pair_similarity(other, _HYPOTHESIS)


def test_containment_alone_does_not_score_as_identical() -> None:
    """A short text wholly inside a long one is not a duplicate of it.

    The maximum of the two directional coverages would read 1.0 here --
    every token of the short side appears in the long one -- and assert a
    duplicate between two hypotheses that are nothing of the sort. The
    harmonic mean pays for the length gap instead.
    """
    short = "alpha beta"
    long_text = "alpha beta " + " ".join(f"term{i}" for i in range(20))
    assert token_coverage(short, long_text) == 1.0
    assert pair_similarity(short, long_text) < 0.25


def test_empty_text_scores_zero() -> None:
    """A text with no tokens has nothing to share."""
    assert pair_similarity("", _HYPOTHESIS) == 0.0
    assert pair_similarity(_HYPOTHESIS, "") == 0.0
