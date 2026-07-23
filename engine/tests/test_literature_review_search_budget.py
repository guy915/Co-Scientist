"""Tests for evidence-budget selection and reserved slots (search.py).

Covers ``select_within_budget`` -- pure-score truncation, reserved-slot rescue
of a low-ranked source, the reservation-as-ceiling semantics, the hard budget
cap -- and the enabled-source reconciliation that ``get_enabled_search_sources``
performs against per-run disabled tools. No network, LLM, or disk I/O.
"""

from typing import Any

from co_scientist.agents.generation.literature_review.helpers import (
    select_within_budget,
)
from co_scientist.config import SearchSourceConfig


def _ranked(*ids: str) -> dict[str, dict[str, Any]]:
    """Papers in ranked (best-first) order, as merge_search_results returns."""
    return {paper_id: {"title": paper_id} for paper_id in ids}


def test_selection_is_pure_score_when_nothing_is_reserved() -> None:
    """Sources that reserve nothing keep the previous truncation exactly."""
    ranked = _ranked("A", "B", "C", "D")
    source_map = {"A": "pubmed", "B": "pubmed", "C": "corpus", "D": "corpus"}
    sources = [
        SearchSourceConfig(tool="corpus"),
        SearchSourceConfig(tool="pubmed"),
    ]
    assert select_within_budget(ranked, source_map, sources, 2) == ["A", "B"]


def test_reserved_slots_rescue_a_source_that_score_would_truncate() -> None:
    """The defect this fixes: a source ranked last never survived the cap.

    Corpus papers have no citation count and no publication year, so they
    sort below every indexed paper; with a budget of 2 they were always cut
    despite matching the question. Reserving keeps them without reordering
    the rest.
    """
    ranked = _ranked("pm1", "pm2", "oa1", "c1", "c2", "c3")
    source_map = {
        "pm1": "pubmed",
        "pm2": "pubmed",
        "oa1": "openalex",
        "c1": "corpus",
        "c2": "corpus",
        "c3": "corpus",
    }
    sources = [
        SearchSourceConfig(tool="corpus", reserved_slots=2),
        SearchSourceConfig(tool="pubmed"),
        SearchSourceConfig(tool="openalex"),
    ]
    selected = select_within_budget(ranked, source_map, sources, 4)
    # Two corpus papers are guaranteed; the rest go to the best by score.
    assert selected == ["c1", "c2", "pm1", "pm2"]


def test_reserved_slots_are_not_padded_when_the_source_returns_fewer() -> None:
    """A reservation is a ceiling, not a quota to fill with nothing."""
    ranked = _ranked("pm1", "pm2", "pm3", "c1")
    source_map = {
        "pm1": "pubmed",
        "pm2": "pubmed",
        "pm3": "pubmed",
        "c1": "corpus",
    }
    sources = [
        SearchSourceConfig(tool="corpus", reserved_slots=2),
        SearchSourceConfig(tool="pubmed"),
    ]
    selected = select_within_budget(ranked, source_map, sources, 3)
    assert selected == ["c1", "pm1", "pm2"]


def test_reserved_slots_never_exceed_the_evidence_budget() -> None:
    """The budget is the hard ceiling; reserving cannot enlarge the review."""
    ranked = _ranked("c1", "c2", "c3", "pm1")
    source_map = {
        "c1": "corpus",
        "c2": "corpus",
        "c3": "corpus",
        "pm1": "pubmed",
    }
    sources = [
        SearchSourceConfig(tool="corpus", reserved_slots=3),
        SearchSourceConfig(tool="pubmed"),
    ]
    selected = select_within_budget(ranked, source_map, sources, 2)
    assert selected == ["c1", "c2"]
    assert select_within_budget(ranked, source_map, sources, 0) == []


def test_the_shipped_sources_reserve_no_slots() -> None:
    """The bundled literature-review sources all compete on score alone.

    The paper corpus was the only source that ever reserved slots (so its
    passages were not truncated away); now that the corpus reaches a run as an
    injected catalog rather than a search source, no bundled source reserves
    anything. `reserved_slots` remains a general capability of
    `SearchSourceConfig` (exercised by the tests above), just unused by the
    shipped config.
    """
    from co_scientist.config import ToolRegistry

    registry = ToolRegistry(skip_user_config=True)
    workflow = registry.get_workflow("literature_review")
    assert workflow is not None
    reserved = {
        source.tool: source.reserved_slots
        for source in workflow.get_enabled_search_sources()
    }
    assert set(reserved) == {"pubmed_fulltext", "openalex_search", "web_search"}
    assert all(slots == 0 for slots in reserved.values())


def test_enabled_search_sources_track_disabled_tools() -> None:
    """A per-run disabled tool stops being searched.

    The app's connector toggles map to disable_tools; the registry
    reconciles source flags with tool flags at load time, and the search
    phase trusts ``get_enabled_search_sources()`` -- so the disabled
    source must already be gone here.
    """
    from co_scientist.config.registry import ToolRegistry

    registry = ToolRegistry(disabled_tools=["web_search"])
    workflow = registry.get_workflow("literature_review")
    assert workflow is not None

    tools = [s.tool for s in workflow.get_enabled_search_sources()]
    assert "web_search" not in tools
    assert "pubmed_fulltext" in tools


def test_enabled_search_sources_keep_enabled_tools() -> None:
    """Nothing disabled means every configured source is searched."""
    from co_scientist.config.registry import ToolRegistry

    registry = ToolRegistry()
    workflow = registry.get_workflow("literature_review")
    assert workflow is not None

    tools = [s.tool for s in workflow.get_enabled_search_sources()]
    assert "web_search" in tools
