"""Tests for the pure value objects/helpers in ``co_scientist.llm_types``."""

from co_scientist.llm_types import indexed_prompt_name

# --- indexed_prompt_name -----------------------------------------------------


def test_indexed_prompt_name_appends_index_when_given() -> None:
    """A given index is appended to the stem with an underscore."""
    assert indexed_prompt_name("evolve", 3) == "evolve_3"


def test_indexed_prompt_name_appends_zero_index() -> None:
    """Index 0 is still appended -- the check is "is not None", not truthy."""
    assert indexed_prompt_name("ranking_matchup", 0) == "ranking_matchup_0"


def test_indexed_prompt_name_bare_stem_when_index_is_none() -> None:
    """A None index yields the bare stem, with no trailing underscore."""
    assert indexed_prompt_name("review_individual", None) == "review_individual"
