"""Tests for the paper-search helpers in literature_tools/validate_search.py.

These are pure/near-pure helpers (tool resolution, article-to-paper-dict
mapping, and the config-driven vs. legacy search dispatch), so most cases
here call them directly rather than going through the full
``validate_hypotheses`` pipeline.
"""

from typing import cast

import pytest

from co_scientist.agents.generation.literature_tools.validate_search import (
    _articles_to_paper_dict,
    _find_search_tool,
    _first,
    _NoveltySearchContext,
    _search_papers_for_hypothesis,
    _search_papers_via_tool_config,
)
from co_scientist.config import ToolConfig, ToolRegistry
from co_scientist.config.tool_schema import ResponseFormat
from tests._mcp import FakeCallToolClient
from tests._state import make_article

# -----------------------------------------------------------------------------
# _first
# -----------------------------------------------------------------------------


def test_first_returns_first_truthy_value() -> None:
    """The first truthy positional value wins."""
    assert _first(None, "", "b", "c") == "b"


def test_first_returns_last_value_when_none_truthy() -> None:
    """With no truthy value, the last (falsy) value is returned."""
    assert _first(None, "", 0) == 0


def test_first_returns_none_for_no_values() -> None:
    """Calling with zero values returns None."""
    assert _first() is None


# -----------------------------------------------------------------------------
# _articles_to_paper_dict
# -----------------------------------------------------------------------------


def test_articles_to_paper_dict_maps_fields_and_keys_by_source_id() -> None:
    """Articles are keyed by the first available id and content fallback."""
    articles = [
        make_article(
            title="Paper A",
            source_id="pmid-1",
            authors=["Smith"],
            year=2021,
            content="full body",
            abstract="short abstract",
        ),
        make_article(
            title="Paper B",
            source_id=None,
            url="http://example.test/b",
            content=None,
            abstract="only an abstract",
        ),
    ]

    result = _articles_to_paper_dict(articles)

    assert result["pmid-1"] == {
        "title": "Paper A",
        "authors": ["Smith"],
        "year": 2021,
        "fulltext": "full body",
    }
    assert result["http://example.test/b"]["fulltext"] == ("only an abstract")


# -----------------------------------------------------------------------------
# _find_search_tool
# -----------------------------------------------------------------------------


class _FakeRegistry:
    """Minimal stand-in exposing only what _find_search_tool reads."""

    def __init__(self, tool_ids: list[str], tools: dict[str, ToolConfig]):
        self._tool_ids = tool_ids
        self._tools = tools

    def get_tools_for_workflow(self, _workflow: str) -> list[str]:
        """Return the configured workflow tool ids."""
        return self._tool_ids

    def get_tool(self, tool_id: str) -> ToolConfig | None:
        """Resolve a tool id to its config, or None if unconfigured."""
        return self._tools.get(tool_id)


def test_find_search_tool_no_registry_returns_none() -> None:
    """A falsy tool_registry short-circuits to (None, None)."""
    assert _find_search_tool(None) == (None, None)


def test_find_search_tool_returns_first_matching_category() -> None:
    """The first search/search_with_content-category tool wins."""
    search_tool = ToolConfig(
        server="s", mcp_tool_name="search_x", category="search"
    )
    registry = cast(
        ToolRegistry,
        _FakeRegistry(["search_x"], {"search_x": search_tool}),
    )

    tool_id, tool_config = _find_search_tool(registry)

    assert tool_id == "search_x"
    assert tool_config is search_tool


def test_find_search_tool_skips_non_matching_categories() -> None:
    """Non-search-category tools are skipped, falling through to None."""
    utility_tool = ToolConfig(
        server="s", mcp_tool_name="util_x", category="utility"
    )
    registry = cast(
        ToolRegistry,
        _FakeRegistry(["util_x"], {"util_x": utility_tool}),
    )

    assert _find_search_tool(registry) == (None, None)


# -----------------------------------------------------------------------------
# _search_papers_via_tool_config
# -----------------------------------------------------------------------------


def _search_tool_config() -> ToolConfig:
    return ToolConfig(
        server="s",
        mcp_tool_name="search_papers",
        category="search",
        response_format=ResponseFormat(
            results_path=".",
            is_dict=True,
            field_mapping={
                "title": "title",
                "authors": "authors",
                "year": "year",
                "content": "fulltext",
                "source_id": "@key",
            },
        ),
    )


async def test_search_papers_via_tool_config_returns_paper_dict() -> None:
    """A config-driven search maps the parsed articles into a paper dict."""
    tool_config = _search_tool_config()
    mcp_client = FakeCallToolClient(
        {"p1": {"title": "Paper One", "authors": ["A"], "year": 2020}}
    )

    result = await _search_papers_via_tool_config(
        tool_config,
        "hypothesis text",
        _NoveltySearchContext(
            mcp_client=mcp_client,
            tool_registry=None,
            shared_slug="slug-1",
            run_id="run-1",
        ),
        max_papers=5,
    )

    assert result == {
        "p1": {
            "title": "Paper One",
            "authors": ["A"],
            "year": 2020,
            "fulltext": "",
        }
    }
    name, kwargs = mcp_client.calls[0]
    assert name == "search_papers"
    assert kwargs["run_id"] == "run-1"
    assert kwargs["slug"] == "slug-1"


async def test_search_papers_via_tool_config_omits_run_id_when_absent() -> None:
    """A falsy run_id is not injected into the canonical search params."""
    tool_config = _search_tool_config()
    mcp_client = FakeCallToolClient({})

    await _search_papers_via_tool_config(
        tool_config,
        "hypothesis text",
        _NoveltySearchContext(
            mcp_client=mcp_client,
            tool_registry=None,
            shared_slug="slug-1",
            run_id=None,
        ),
        max_papers=5,
    )

    _, kwargs = mcp_client.calls[0]
    assert "run_id" not in kwargs


# -----------------------------------------------------------------------------
# _search_papers_for_hypothesis
# -----------------------------------------------------------------------------


async def test_search_papers_for_hypothesis_uses_config_tool() -> None:
    """A resolved search tool routes through the config-driven path."""
    tool_config = _search_tool_config()
    registry = cast(
        ToolRegistry,
        _FakeRegistry(["search_papers"], {"search_papers": tool_config}),
    )
    mcp_client = FakeCallToolClient(
        {"p1": {"title": "Paper One", "authors": [], "year": 2020}}
    )

    result = await _search_papers_for_hypothesis(
        "hypothesis text",
        _NoveltySearchContext(
            mcp_client=mcp_client,
            tool_registry=registry,
            shared_slug="slug-1",
            run_id=None,
        ),
        max_papers=3,
    )

    assert "p1" in result


async def test_search_papers_for_hypothesis_no_tool_returns_empty(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A registry with no matching search tool skips the novelty search."""
    registry = cast(ToolRegistry, _FakeRegistry([], {}))
    mcp_client = FakeCallToolClient({})

    result = await _search_papers_for_hypothesis(
        "hypothesis text",
        _NoveltySearchContext(
            mcp_client=mcp_client,
            tool_registry=registry,
            shared_slug="slug-1",
            run_id=None,
        ),
        max_papers=3,
    )

    assert result == {}
    assert "skipping novelty search" in caplog.text


async def test_search_papers_for_hypothesis_legacy_fallback() -> None:
    """No tool_registry at all falls back to the legacy direct call."""
    mcp_client = FakeCallToolClient({"p1": {"title": "Legacy paper"}})

    result = await _search_papers_for_hypothesis(
        "hypothesis text",
        _NoveltySearchContext(
            mcp_client=mcp_client,
            tool_registry=None,
            shared_slug="slug-1",
            run_id=None,
        ),
        max_papers=3,
    )

    assert result == {"p1": {"title": "Legacy paper"}}
    name, kwargs = mcp_client.calls[0]
    assert name == "pubmed_search_with_fulltext"
    assert kwargs["slug"] == "slug-1"
