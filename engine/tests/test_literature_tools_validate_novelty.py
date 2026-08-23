"""Tests for the Stage 1 novelty-analysis prompt builder.

``_build_novelty_analysis_prompt`` is the seam where a candidate paper's
metadata (title/authors/year/fulltext) enters the per-paper novelty
LLM call -- the tool-based validation path's analogue of the literature
review's per-paper analysis prompt.
"""

from co_scientist.agents.generation.literature_tools.validate_novelty import (
    _build_novelty_analysis_prompt,
)


def test_novelty_prompt_strips_citation_markers() -> None:
    """The candidate paper's own citation markers do not reach the prompt.

    Left in, the novelty-verdict model can copy one into its own
    reasoning -- a real-looking reference attached to a claim the cited
    source never made.
    """
    metadata = {
        "title": "Prior work",
        "authors": ["Doe"],
        "year": 2020,
        "fulltext": "This confirms an earlier result (Smith et al. 2019) [12].",
    }

    prompt = _build_novelty_analysis_prompt("a draft hypothesis", metadata)

    assert "(Smith et al. 2019)" not in prompt
    assert "[12]" not in prompt


def test_novelty_prompt_leaves_stored_metadata_unchanged() -> None:
    """Stripping is for the prompt copy only, never for storage."""
    original = "This confirms an earlier result (Smith et al. 2019) [12]."
    metadata = {
        "title": "Prior work",
        "authors": ["Doe"],
        "year": 2020,
        "fulltext": original,
    }

    _build_novelty_analysis_prompt("a draft hypothesis", metadata)

    assert metadata["fulltext"] == original
