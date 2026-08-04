"""Tests for the Phase 2.4/2.5 PDF-discovery and content-fetch node phases.

Covers ``literature_review.content``: per-paper PDF
discovery and content fetching (success, "nothing to do", and exception
branches), the in-place metadata-mutation helpers, the parallel-gather
orchestration, and the two config-driven phase entry points (each a no-op
when the workflow doesn't configure the relevant tool).

The only external seam is ``MCPToolClient``, stood in for by a tiny
duck-typed fake exposing ``call_tool`` (records every call and returns a
per-tool canned result, or raises for tools listed as failing). Everything
else (``SearchConfig``, ``WorkflowConfig``, ``ToolConfig``) is a plain,
directly-constructed dataclass -- this module does no other I/O.
"""

import json
from typing import Any, cast

from co_scientist.agents.generation.literature_review import (
    content as lr_content,
)
from co_scientist.agents.generation.literature_review.helpers import (
    ContentToolConfig,
)
from co_scientist.config.schema import ToolConfig, WorkflowConfig
from co_scientist.mcp_client import MCPToolClient
from tests._mcp import (
    FakeToolResultsClient,
    make_tool_results_client,
)
from tests._mcp import (
    make_tool_lookup_registry as _registry,
)
from tests._search_fixtures import make_search_config
from tests._state import make_state

# =============================================================================
# _discover_pdf_link
# =============================================================================


async def test_discover_pdf_link_no_landing_url_skips_call() -> None:
    """A paper with no value under url_field is skipped without a tool call."""
    client = FakeToolResultsClient()
    result = await lr_content._discover_pdf_link(
        "p1", {}, "discover_tool", "url", cast(MCPToolClient, client)
    )
    assert result == ("p1", None)
    assert client.calls == []


async def test_discover_pdf_link_success_returns_parsed_url() -> None:
    """A successful discovery call yields the parsed PDF URL."""
    payload = json.dumps(["http://example.test/paper.pdf"])
    client = FakeToolResultsClient(results={"discover_tool": payload})

    result = await lr_content._discover_pdf_link(
        "p1",
        {"url": "http://example.test/landing"},
        "discover_tool",
        "url",
        cast(MCPToolClient, client),
    )

    assert result == ("p1", "http://example.test/paper.pdf")
    assert client.calls == [
        ("discover_tool", {"url": "http://example.test/landing"})
    ]


async def test_discover_pdf_link_no_pdf_found_returns_none() -> None:
    """A discovery call that yields no PDF URL still returns cleanly."""
    client = FakeToolResultsClient(results={"discover_tool": json.dumps([])})

    result = await lr_content._discover_pdf_link(
        "p1",
        {"url": "http://example.test/landing"},
        "discover_tool",
        "url",
        cast(MCPToolClient, client),
    )

    assert result == ("p1", None)


async def test_discover_pdf_link_tool_error_returns_none() -> None:
    """A raising discovery tool leaves the paper without a pdf_url."""
    client = FakeToolResultsClient(error_tools={"discover_tool"})

    result = await lr_content._discover_pdf_link(
        "p1",
        {"url": "http://example.test/landing"},
        "discover_tool",
        "url",
        cast(MCPToolClient, client),
    )

    assert result == ("p1", None)


# =============================================================================
# _apply_metadata_field (pdf_url)
# =============================================================================


def test_apply_metadata_field_pdf_url_updates_matching_papers() -> None:
    """Discovered URLs are written back only for papers present with a hit."""
    metadata = {"p1": {"title": "A"}, "p2": {"title": "B"}}
    results = [
        ("p1", "http://x/a.pdf"),
        ("p2", None),  # no discovery: left untouched
        ("missing", "http://x/c.pdf"),  # not in metadata: ignored
    ]

    count = lr_content._apply_metadata_field(metadata, results, "pdf_url")

    assert count == 1
    assert metadata["p1"]["pdf_url"] == "http://x/a.pdf"
    assert "pdf_url" not in metadata["p2"]


def test_apply_metadata_field_empty_list() -> None:
    """An empty results list updates nothing and counts zero."""
    metadata: dict[str, dict[str, Any]] = {"p1": {"title": "A"}}
    assert lr_content._apply_metadata_field(metadata, [], "pdf_url") == 0


# =============================================================================
# _run_pdf_discovery
# =============================================================================


async def test_run_pdf_discovery_mixed_success_and_failure() -> None:
    """Parallel discovery applies successful hits and skips failed lookups."""
    metadata = {
        "p1": {"url": "http://landing1"},
        "p2": {"url": "http://landing2"},
    }
    client = FakeToolResultsClient(
        results={"good_tool": json.dumps(["http://x/p1.pdf"])},
        error_tools={"bad_tool"},
    )
    papers_needing_discovery = [
        ("p1", metadata["p1"], "good_tool", "url"),
        ("p2", metadata["p2"], "bad_tool", "url"),
    ]

    count = await lr_content._run_pdf_discovery(
        papers_needing_discovery, cast(MCPToolClient, client), metadata
    )

    assert count == 1
    assert metadata["p1"]["pdf_url"] == "http://x/p1.pdf"
    assert "pdf_url" not in metadata["p2"]


# =============================================================================
# _phase2_4_discover_pdf_links
# =============================================================================


async def test_phase2_4_no_workflow_is_noop() -> None:
    """With no workflow configured, discovery config is empty and no-op."""
    metadata = {"p1": {"url": "http://landing"}}
    client = make_tool_results_client()

    await lr_content._phase2_4_discover_pdf_links(
        metadata, {}, make_search_config(), client
    )

    assert "pdf_url" not in metadata["p1"]
    assert cast(FakeToolResultsClient, client).calls == []


async def test_phase2_4_no_eligible_papers_is_noop() -> None:
    """A configured discovery tool with nothing eligible makes no calls."""
    workflow = WorkflowConfig(
        pdf_discovery_tool="discover", pdf_discovery_url_field="url"
    )
    registry = _registry(
        {"discover": ToolConfig(server="s", mcp_tool_name="mcp_discover")}
    )
    metadata = {"p1": {"pdf_url": "http://already.pdf"}}
    client = make_tool_results_client()

    await lr_content._phase2_4_discover_pdf_links(
        metadata,
        {},
        make_search_config(workflow=workflow, tool_registry=registry),
        client,
    )

    assert cast(FakeToolResultsClient, client).calls == []


async def test_phase2_4_success_populates_pdf_url() -> None:
    """An eligible paper gets its pdf_url discovered and written back."""
    workflow = WorkflowConfig(
        pdf_discovery_tool="discover", pdf_discovery_url_field="url"
    )
    registry = _registry(
        {"discover": ToolConfig(server="s", mcp_tool_name="mcp_discover")}
    )
    metadata = {"p1": {"url": "http://landing"}}
    client = make_tool_results_client(
        results={"mcp_discover": json.dumps(["http://x/found.pdf"])}
    )

    await lr_content._phase2_4_discover_pdf_links(
        metadata,
        {},
        make_search_config(workflow=workflow, tool_registry=registry),
        client,
    )

    assert metadata["p1"]["pdf_url"] == "http://x/found.pdf"


# =============================================================================
# _fetch_paper_content
# =============================================================================


async def test_fetch_paper_content_no_url_skips_call() -> None:
    """A paper with no value under url_field is skipped without a tool call."""
    client = FakeToolResultsClient()
    cfg = ContentToolConfig(
        mcp_tool_name="content_tool", url_field="pdf_url", content_params={}
    )

    result = await lr_content._fetch_paper_content(
        "p1", {}, cfg, cast(MCPToolClient, client), {}
    )

    assert result == ("p1", None)
    assert client.calls == []


async def test_fetch_paper_content_success_resolves_params() -> None:
    """A successful fetch resolves placeholders and returns the content."""
    client = FakeToolResultsClient(
        results={"content_tool": {"content": "the fetched body"}}
    )
    cfg = ContentToolConfig(
        mcp_tool_name="content_tool",
        url_field="pdf_url",
        content_params={"goal": "{research_goal}"},
    )
    runtime_context = {"research_goal": "understand KRAS signaling"}

    result = await lr_content._fetch_paper_content(
        "p1",
        {"pdf_url": "http://x/p1.pdf"},
        cfg,
        cast(MCPToolClient, client),
        runtime_context,
    )

    assert result == ("p1", "the fetched body")
    assert client.calls == [
        (
            "content_tool",
            {
                "url": "http://x/p1.pdf",
                "goal": "understand KRAS signaling",
            },
        )
    ]


async def test_fetch_paper_content_tool_error_returns_none() -> None:
    """A raising content tool leaves the paper without fulltext."""
    client = FakeToolResultsClient(error_tools={"content_tool"})
    cfg = ContentToolConfig(
        mcp_tool_name="content_tool", url_field="pdf_url", content_params={}
    )

    result = await lr_content._fetch_paper_content(
        "p1",
        {"pdf_url": "http://x/p1.pdf"},
        cfg,
        cast(MCPToolClient, client),
        {},
    )

    assert result == ("p1", None)


# =============================================================================
# _apply_metadata_field (fulltext)
# =============================================================================


def test_apply_metadata_field_fulltext_updates_matching_papers() -> None:
    """Fetched fulltext is written back only for papers present with a hit."""
    metadata = {"p1": {"title": "A"}, "p2": {"title": "B"}}
    results = [
        ("p1", "the full body"),
        ("p2", None),
        ("missing", "orphan content"),
    ]

    count = lr_content._apply_metadata_field(metadata, results, "fulltext")

    assert count == 1
    assert metadata["p1"]["fulltext"] == "the full body"
    assert "fulltext" not in metadata["p2"]


# =============================================================================
# _build_content_runtime_context
# =============================================================================


def test_build_content_runtime_context_carries_research_goal() -> None:
    """The runtime context surfaces the research goal and empty focus areas."""
    state = make_state(research_goal="investigate BRCA1 variants")
    context = lr_content._build_content_runtime_context(state)
    assert context == {
        "research_goal": "investigate BRCA1 variants",
        "focus_areas": [],
    }


# =============================================================================
# _run_content_fetch
# =============================================================================


async def test_run_content_fetch_mixed_success_and_failure() -> None:
    """Parallel content fetch applies successful hits and skips failures."""
    metadata = {
        "p1": {"pdf_url": "http://x/p1.pdf"},
        "p2": {"pdf_url": "http://x/p2.pdf"},
    }
    client = FakeToolResultsClient(
        results={"good_tool": {"content": "body one"}},
        error_tools={"bad_tool"},
    )
    good_cfg = ContentToolConfig(
        mcp_tool_name="good_tool", url_field="pdf_url", content_params={}
    )
    bad_cfg = ContentToolConfig(
        mcp_tool_name="bad_tool", url_field="pdf_url", content_params={}
    )
    papers_needing_content = [
        ("p1", metadata["p1"], good_cfg),
        ("p2", metadata["p2"], bad_cfg),
    ]

    count = await lr_content._run_content_fetch(
        papers_needing_content, cast(MCPToolClient, client), {}, metadata
    )

    assert count == 1
    assert metadata["p1"]["fulltext"] == "body one"
    assert "fulltext" not in metadata["p2"]


# =============================================================================
# _phase2_5_fetch_content
# =============================================================================


async def test_phase2_5_no_workflow_is_noop() -> None:
    """With no workflow configured, content config is empty and no-op."""
    metadata = {"p1": {"pdf_url": "http://x/p1.pdf"}}
    client = make_tool_results_client()
    state = make_state(research_goal="goal")

    await lr_content._phase2_5_fetch_content(
        metadata, {}, make_search_config(), client, state
    )

    assert "fulltext" not in metadata["p1"]
    assert cast(FakeToolResultsClient, client).calls == []


async def test_phase2_5_no_eligible_papers_is_noop() -> None:
    """A configured content tool with nothing eligible makes no calls."""
    workflow = WorkflowConfig(
        content_tool="content", content_url_field="pdf_url"
    )
    registry = _registry(
        {"content": ToolConfig(server="s", mcp_tool_name="mcp_content")}
    )
    metadata = {
        "p1": {"pdf_url": "http://x.pdf", "fulltext": "already have it"}
    }
    client = make_tool_results_client()
    state = make_state(research_goal="goal")

    await lr_content._phase2_5_fetch_content(
        metadata,
        {},
        make_search_config(workflow=workflow, tool_registry=registry),
        client,
        state,
    )

    assert cast(FakeToolResultsClient, client).calls == []


async def test_phase2_5_success_populates_fulltext() -> None:
    """An eligible paper gets its fulltext fetched and written back."""
    workflow = WorkflowConfig(
        content_tool="content", content_url_field="pdf_url"
    )
    registry = _registry(
        {"content": ToolConfig(server="s", mcp_tool_name="mcp_content")}
    )
    metadata = {"p1": {"pdf_url": "http://x/p1.pdf"}}
    client = make_tool_results_client(
        results={"mcp_content": {"content": "fetched body"}}
    )
    state = make_state(research_goal="goal")

    await lr_content._phase2_5_fetch_content(
        metadata,
        {},
        make_search_config(workflow=workflow, tool_registry=registry),
        client,
        state,
    )

    assert metadata["p1"]["fulltext"] == "fetched body"
