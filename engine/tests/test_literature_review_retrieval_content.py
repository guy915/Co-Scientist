"""Tests for the content-fetch config helpers.

Covers the content-fetch half of the tool-resolution and paper-eligibility
functions in ``evidence.retrieval_support``: resolving a source's
(or the workflow default's) content tool config (including content_params
merging), building the per-source config maps, looking a paper's config up
by its originating source, and filtering collected papers down to the ones
eligible for a content fetch. The PDF-discovery half lives in
``test_literature_review_retrieval_support``.

Every dependency here is a plain dataclass (``SearchSourceConfig``,
``WorkflowConfig``, ``ToolConfig``) or a tiny duck-typed registry fake; no
LLM, MCP, or network mocking is needed since this module does no I/O.
"""

from typing import Any, cast

from co_scientist.config.schema import (
    SearchSourceConfig,
    WorkflowConfig,
)
from co_scientist.evidence import (
    retrieval_support as rs,
)
from tests._mcp import make_tool_lookup_registry as _registry
from tests._retrieval_config import make_tool_config as _tool

# =============================================================================
# _resolve_content_tool
# =============================================================================


def test_resolve_content_tool_source_override_wins() -> None:
    """A source-level content tool takes priority over the workflow default."""
    source = SearchSourceConfig(
        tool="arxiv_search",
        content_tool="src_content",
        content_url_field="src_field",
    )
    workflow = WorkflowConfig(
        content_tool="wf_content", content_url_field="wf_field"
    )
    registry = _registry({"src_content": _tool("mcp_src_content")})

    result = rs._resolve_content_tool(source, workflow, registry)

    assert result is not None
    assert result.mcp_tool_name == "mcp_src_content"
    assert result.url_field == "src_field"


def test_resolve_content_tool_merges_params_source_wins() -> None:
    """content_params merge workflow and source values; source wins ties."""
    source = SearchSourceConfig(
        tool="arxiv_search",
        content_tool="src_content",
        content_params={"b": "source-b", "c": "source-c"},
    )
    workflow = WorkflowConfig(
        content_tool="wf_content",
        content_params={"a": "wf-a", "b": "wf-b"},
    )
    registry = _registry({"src_content": _tool("mcp_src_content")})

    result = rs._resolve_content_tool(source, workflow, registry)

    assert result is not None
    assert result.content_params == {
        "a": "wf-a",
        "b": "source-b",
        "c": "source-c",
    }


def test_resolve_content_tool_falls_back_to_workflow() -> None:
    """With no source-level override, the workflow default tool/field apply."""
    source = SearchSourceConfig(tool="arxiv_search")
    workflow = WorkflowConfig(
        content_tool="wf_content", content_url_field="wf_field"
    )
    registry = _registry({"wf_content": _tool("mcp_wf_content")})

    result = rs._resolve_content_tool(source, workflow, registry)

    assert result is not None
    assert result.mcp_tool_name == "mcp_wf_content"
    assert result.url_field == "wf_field"


def test_resolve_content_tool_none_configured_returns_none() -> None:
    """Neither the source nor the workflow configures a content tool."""
    source = SearchSourceConfig(tool="arxiv_search")
    workflow = WorkflowConfig()
    assert rs._resolve_content_tool(source, workflow, _registry({})) is None


def test_resolve_content_tool_dangling_reference_returns_none() -> None:
    """A content tool id absent from the registry resolves to None."""
    source = SearchSourceConfig(tool="arxiv_search", content_tool="ghost")
    workflow = WorkflowConfig()
    assert rs._resolve_content_tool(source, workflow, _registry({})) is None


# =============================================================================
# build_content_config -- multi-source entries
# =============================================================================


def test_build_multi_source_content_config_keys_by_source_tool() -> None:
    """Only sources that resolve a content tool appear in the config."""
    workflow = WorkflowConfig(
        search_sources=[
            SearchSourceConfig(
                tool="arxiv", content_tool="arxiv_content", enabled=True
            ),
            SearchSourceConfig(tool="pubmed"),  # no content tool anywhere
        ]
    )
    registry = _registry({"arxiv_content": _tool("mcp_arxiv_content")})

    config = rs.build_content_config(workflow, registry, True)

    assert set(config) == {"arxiv"}
    assert config["arxiv"].mcp_tool_name == "mcp_arxiv_content"


# =============================================================================
# build_content_config -- single-source default entry
# =============================================================================


def test_build_default_content_config_success() -> None:
    """A configured workflow-level content tool yields a ``_default`` entry."""
    workflow = WorkflowConfig(
        content_tool="wf_content",
        content_url_field="pdf_url",
        content_params={"depth": "full"},
    )
    registry = _registry({"wf_content": _tool("mcp_wf_content")})

    config = rs.build_content_config(workflow, registry, False)

    assert set(config) == {"_default"}
    assert config["_default"].mcp_tool_name == "mcp_wf_content"
    assert config["_default"].url_field == "pdf_url"
    assert config["_default"].content_params == {"depth": "full"}


def test_build_default_content_config_no_tool_configured() -> None:
    """No workflow-level content tool yields an empty config."""
    assert rs.build_content_config(WorkflowConfig(), _registry({}), False) == {}


def test_build_default_content_config_dangling_reference() -> None:
    """A workflow content tool id absent from the registry yields empty."""
    workflow = WorkflowConfig(content_tool="ghost")
    assert rs.build_content_config(workflow, _registry({}), False) == {}


# =============================================================================
# build_content_config
# =============================================================================


def test_build_content_config_no_workflow_returns_empty() -> None:
    """A missing workflow short-circuits to an empty config."""
    assert rs.build_content_config(None, _registry({}), False) == {}


def test_build_content_config_no_registry_returns_empty() -> None:
    """A missing tool registry short-circuits to an empty config."""
    workflow = WorkflowConfig(content_tool="wf_content")
    assert rs.build_content_config(workflow, None, False) == {}


def test_build_content_config_multi_source_dispatch() -> None:
    """``is_multi_source=True`` dispatches to the per-source builder."""
    workflow = WorkflowConfig(
        search_sources=[
            SearchSourceConfig(tool="arxiv", content_tool="arxiv_content")
        ]
    )
    registry = _registry({"arxiv_content": _tool("mcp_arxiv_content")})

    config = rs.build_content_config(workflow, registry, True)

    assert set(config) == {"arxiv"}


def test_build_content_config_single_source_dispatch() -> None:
    """``is_multi_source=False`` dispatches to the single default builder."""
    workflow = WorkflowConfig(content_tool="wf_content")
    registry = _registry({"wf_content": _tool("mcp_wf_content")})

    config = rs.build_content_config(workflow, registry, False)

    assert set(config) == {"_default"}


# =============================================================================
# _lookup_source_config (ContentToolConfig values)
# =============================================================================


def test_lookup_content_config_by_source() -> None:
    """A paper's own source config is preferred when present."""
    cfg = rs.ContentToolConfig(
        mcp_tool_name="mcp_arxiv", url_field="pdf_url", content_params={}
    )
    default_cfg = rs.ContentToolConfig(
        mcp_tool_name="mcp_def", url_field="pdf_url", content_params={}
    )
    config = {"arxiv": cfg, "_default": default_cfg}

    result = rs._lookup_source_config("p1", {"p1": "arxiv"}, config)

    assert result is cfg


def test_lookup_content_config_falls_back_to_default() -> None:
    """An unmapped source falls back to the ``_default`` config entry."""
    default_cfg = rs.ContentToolConfig(
        mcp_tool_name="mcp_def", url_field="pdf_url", content_params={}
    )
    result = rs._lookup_source_config("p1", {}, {"_default": default_cfg})
    assert result is default_cfg


def test_lookup_content_config_none_available() -> None:
    """No matching source config and no default returns None."""
    assert rs._lookup_source_config("p1", {}, {}) is None


# =============================================================================
# _resolve_content_entry
# =============================================================================


def _content_config() -> dict[str, rs.ContentToolConfig]:
    """Build a single-default content config for entry-resolution tests."""
    return {
        "_default": rs.ContentToolConfig(
            mcp_tool_name="mcp_content", url_field="pdf_url", content_params={}
        )
    }


def test_resolve_content_entry_non_dict_metadata_returns_none() -> None:
    """Non-dict metadata (a malformed entry) is skipped."""
    bad_meta = cast(dict[str, Any], "not-a-dict")
    assert (
        rs._resolve_content_entry("p1", bad_meta, {}, _content_config()) is None
    )


def test_resolve_content_entry_already_has_fulltext_returns_none() -> None:
    """A paper that already has fulltext needs no content fetch."""
    meta = {"fulltext": "already have it", "pdf_url": "http://x.pdf"}
    assert rs._resolve_content_entry("p1", meta, {}, _content_config()) is None


def test_resolve_content_entry_no_config_returns_none() -> None:
    """A paper whose source has no resolvable content config is skipped."""
    meta = {"pdf_url": "http://x.pdf"}
    assert rs._resolve_content_entry("p1", meta, {}, {}) is None


def test_resolve_content_entry_no_content_url_returns_none() -> None:
    """A paper missing the configured content-url field is skipped."""
    meta = {"title": "no pdf_url field"}
    assert rs._resolve_content_entry("p1", meta, {}, _content_config()) is None


def test_resolve_content_entry_success() -> None:
    """An eligible paper resolves to (id, metadata, content_tool_config)."""
    meta = {"pdf_url": "http://x.pdf"}
    result = rs._resolve_content_entry("p1", meta, {}, _content_config())
    assert result is not None
    pid, resolved_meta, cfg = result
    assert pid == "p1"
    assert resolved_meta is meta
    assert cfg.mcp_tool_name == "mcp_content"


# =============================================================================
# get_papers_needing_content
# =============================================================================


def test_get_papers_needing_content_filters_eligible() -> None:
    """Only papers eligible for content fetch are returned, others skipped."""
    all_metadata = {
        "eligible": {"pdf_url": "http://x.pdf"},
        "already_has_fulltext": {
            "pdf_url": "http://y.pdf",
            "fulltext": "already have it",
        },
        "no_pdf_url": {"title": "nothing to fetch"},
    }
    result = rs.get_papers_needing_content(all_metadata, {}, _content_config())
    assert [pid for pid, *_ in result] == ["eligible"]


def test_get_papers_needing_content_empty_metadata() -> None:
    """An empty metadata mapping yields an empty result list."""
    assert rs.get_papers_needing_content({}, {}, _content_config()) == []
