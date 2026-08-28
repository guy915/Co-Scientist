"""Corroborates the transcription pinned in the sibling invariants module.

``test_published_pseudocode_invariants.py`` checks the engine against
literals transcribed from Nature SI Note 8's pseudo-code and cited there to
the extracted file they came from. This module re-reads those same files
and asserts the transcription still matches what is on disk -- catching a
copy-paste mistake, or a future edit to the corpus, that the pin itself
cannot see because it no longer touches disk.

Unlike the pin module, every test here goes through
``tests._published_corpus``, which skips outright when
``references/`` is absent and fails when only one file under it has moved
or been deleted. Losing this module on ``references/`` deletion is
expected and safe: the values it exists to corroborate are already
guarded, without disk access, by the sibling pin module.
"""

from __future__ import annotations

import re

from tests._published_corpus import published_pseudocode
from tests.test_published_pseudocode_invariants import (
    _EVOLUTION_STATED_PARENT_COUNT,
    _EVOLUTION_STATED_REVIEW_TASK_LINE,
    _EVOLUTION_STATED_TREAT_AS_NEW_LINE,
    _GENERATION_STATED_STRATEGIES,
    _META_REVIEW_STATED_GATHER_LINE,
    _META_REVIEW_STATED_TOP_N,
    _RANKING_STATED_ENTRY_RATING,
    _RANKING_STATED_PAIRING_LINE,
    _REFLECTION_STATED_ASSUMPTION_LINES,
    _SUPERVISOR_TERMINATION_PREDICATES,
)

_WHITESPACE = re.compile(r"\s+")


def _states(listing: str, phrase: str) -> bool:
    """Whether the listing states a phrase, ignoring its line breaks.

    The source wraps prompts and comments mid-sentence, so a literal
    containment check would depend on where a line happened to break.

    Args:
        listing: The pseudo-code to search.
        phrase: The phrase to look for.

    Returns:
        Whether the phrase appears, comparing whitespace-collapsed text.
    """
    return _WHITESPACE.sub(" ", phrase) in _WHITESPACE.sub(" ", listing)


def _stated_number(listing: str, pattern: str) -> int:
    """Return the single number the listing states for one pattern.

    Args:
        listing: The pseudo-code to read it out of.
        pattern: Regex with one capturing group around the number.

    Returns:
        The captured number.
    """
    matches = re.findall(pattern, listing)
    assert len(matches) == 1, f"expected one {pattern!r}, got {matches}"
    return int(matches[0])


def test_ranking_listing_still_states_the_pinned_entry_rating() -> None:
    """04-ranking.md still assigns the rating pinned above."""
    listing = published_pseudocode("04-ranking")
    stated = _stated_number(listing, r"SET HypothesisToAdd\.EloRating TO (\d+)")
    assert stated == _RANKING_STATED_ENTRY_RATING


def test_ranking_listing_still_states_the_pinned_pairing_line() -> None:
    """04-ranking.md still names the pinned pairing priority."""
    listing = published_pseudocode("04-ranking")
    assert _states(listing, _RANKING_STATED_PAIRING_LINE)


def test_supervisor_listing_still_states_the_pinned_predicates() -> None:
    """01-supervisor.md still names both pinned termination predicates."""
    listing = published_pseudocode("01-supervisor")
    for phrase in _SUPERVISOR_TERMINATION_PREDICATES:
        assert _states(listing, phrase)


def test_evolution_listing_still_states_the_pinned_parent_count() -> None:
    """05-evolution.md still fetches the pinned number of parents."""
    listing = published_pseudocode("05-evolution")
    stated = _stated_number(
        listing, r"FETCH the top (\d+) hypotheses from the HypothesesList"
    )
    assert stated == _EVOLUTION_STATED_PARENT_COUNT


def test_evolution_listing_still_states_the_pinned_review_lines() -> None:
    """05-evolution.md still treats an evolved idea like a new one."""
    listing = published_pseudocode("05-evolution")
    assert _states(listing, _EVOLUTION_STATED_TREAT_AS_NEW_LINE)
    assert _states(listing, _EVOLUTION_STATED_REVIEW_TASK_LINE)


def test_meta_review_listing_still_states_the_pinned_top_n() -> None:
    """07-meta-review.md still synthesizes the pinned number of leaders."""
    listing = published_pseudocode("07-meta-review")
    stated = _stated_number(
        listing, r"FETCH the top (\d+) hypotheses from SharedMemory"
    )
    assert stated == _META_REVIEW_STATED_TOP_N


def test_meta_review_listing_still_states_the_pinned_gather_line() -> None:
    """07-meta-review.md still gathers both named inputs."""
    listing = published_pseudocode("07-meta-review")
    assert _states(listing, _META_REVIEW_STATED_GATHER_LINE)


def test_reflection_listing_still_states_the_pinned_assumption_lines() -> None:
    """03-reflection.md still decomposes into and checks assumptions."""
    listing = published_pseudocode("03-reflection")
    for phrase in _REFLECTION_STATED_ASSUMPTION_LINES:
        assert _states(listing, phrase)


def test_generation_listing_still_states_the_pinned_strategies() -> None:
    """02-generation.md still names both pinned generation strategies."""
    listing = published_pseudocode("02-generation")
    for phrase in _GENERATION_STATED_STRATEGIES:
        assert _states(listing, phrase)
