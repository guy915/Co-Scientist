"""Tests for the PDF-discovery and content-fetch config helpers.

Covers the tool-resolution and paper-eligibility functions in
``literature_review.retrieval_support``: resolving a
source's (or the workflow default's) PDF-discovery/content tool config,
building the per-source config maps, looking a paper's config up by its
originating source, and filtering collected papers down to the ones
eligible for each step. Also covers the ``parse_pdf_discovery_result``
branches not already exercised by ``test_literature_review_helpers_
parsing`` (empty list, dict without any link field, and a decoded-JSON
scalar).

Every dependency here is a plain dataclass (``SearchSourceConfig``,
``WorkflowConfig``, ``ToolConfig``) or a tiny duck-typed registry fake; no
LLM, MCP, or network mocking is needed since this module does no I/O.
"""

import json
from typing import Any, cast

from co_scientist.agents.generation.literature_review import (
    retrieval_support as rs,
)
from co_scientist.config import ToolRegistry
from co_scientist.config.schema import (
    SearchSourceConfig,
    ToolConfig,
    WorkflowConfig,
)


class _FakeToolRegistry:
    """Duck-typed stand-in exposing only the ``get_tool`` lookup used here."""

    def __init__(self, tools: dict[str, ToolConfig]) -> None:
        """Store the tool_id -> ToolConfig map returned by ``get_tool``."""
        self._tools = tools

    def get_tool(self, tool_id: str) -> ToolConfig | None:
        """Return the configured tool, or None for an unknown id."""
        return self._tools.get(tool_id)


def _registry(tools: dict[str, ToolConfig]) -> ToolRegistry:
    """Build a fake registry typed as ToolRegistry for the helper signatures."""
    return cast(ToolRegistry, _FakeToolRegistry(tools))


def _tool(mcp_tool_name: str) -> ToolConfig:
    """Build a minimal ToolConfig with the given MCP-facing tool name."""
    return ToolConfig(server="s", mcp_tool_name=mcp_tool_name)


# =============================================================================
# _resolve_pdf_discovery_tool
# =============================================================================


def test_resolve_pdf_discovery_tool_source_override_wins() -> None:
    """A source-level discovery tool takes priority over the workflow's."""
    source = SearchSourceConfig(
        tool="arxiv_search",
        pdf_discovery_tool="src_discovery",
        pdf_discovery_url_field="src_url",
    )
    workflow = WorkflowConfig(
        pdf_discovery_tool="wf_discovery", pdf_discovery_url_field="wf_url"
    )
    registry = _registry({"src_discovery": _tool("mcp_src_discovery")})

    result = rs._resolve_pdf_discovery_tool(source, workflow, registry)

    assert result == ("mcp_src_discovery", "src_url")


def test_resolve_pdf_discovery_tool_falls_back_to_workflow() -> None:
    """With no source-level override, the workflow default tool/field apply."""
    source = SearchSourceConfig(tool="arxiv_search")
    workflow = WorkflowConfig(
        pdf_discovery_tool="wf_discovery", pdf_discovery_url_field="wf_url"
    )
    registry = _registry({"wf_discovery": _tool("mcp_wf_discovery")})

    result = rs._resolve_pdf_discovery_tool(source, workflow, registry)

    assert result == ("mcp_wf_discovery", "wf_url")


def test_resolve_pdf_discovery_tool_none_configured_returns_none() -> None:
    """Neither the source nor the workflow configures a discovery tool."""
    source = SearchSourceConfig(tool="arxiv_search")
    workflow = WorkflowConfig()
    registry = _registry({})

    assert rs._resolve_pdf_discovery_tool(source, workflow, registry) is None


def test_resolve_pdf_discovery_tool_dangling_reference_returns_none() -> None:
    """A discovery tool id absent from the registry resolves to None."""
    source = SearchSourceConfig(tool="arxiv_search", pdf_discovery_tool="ghost")
    workflow = WorkflowConfig()
    registry = _registry({})

    assert rs._resolve_pdf_discovery_tool(source, workflow, registry) is None


# =============================================================================
# _build_multi_source_pdf_config
# =============================================================================


def test_build_multi_source_pdf_config_keys_by_source_tool() -> None:
    """Only sources that resolve a discovery tool appear in the config."""
    workflow = WorkflowConfig(
        search_sources=[
            SearchSourceConfig(
                tool="scholar",
                pdf_discovery_tool="scholar_discovery",
                pdf_discovery_url_field="url",
            ),
            SearchSourceConfig(tool="pubmed"),  # no discovery tool anywhere
        ]
    )
    registry = _registry({"scholar_discovery": _tool("mcp_scholar_discovery")})

    config = rs._build_multi_source_pdf_config(workflow, registry)

    assert config == {"scholar": ("mcp_scholar_discovery", "url")}


# =============================================================================
# _build_default_pdf_config
# =============================================================================


def test_build_default_pdf_config_success() -> None:
    """A workflow-level discovery tool yields a ``_default`` config entry."""
    workflow = WorkflowConfig(
        pdf_discovery_tool="wf_discovery", pdf_discovery_url_field="landing_url"
    )
    registry = _registry({"wf_discovery": _tool("mcp_wf_discovery")})

    config = rs._build_default_pdf_config(workflow, registry)

    assert config == {"_default": ("mcp_wf_discovery", "landing_url")}


def test_build_default_pdf_config_no_tool_configured() -> None:
    """No workflow-level discovery tool yields an empty config."""
    workflow = WorkflowConfig()
    assert rs._build_default_pdf_config(workflow, _registry({})) == {}


def test_build_default_pdf_config_dangling_reference() -> None:
    """A workflow discovery tool id absent from the registry yields empty."""
    workflow = WorkflowConfig(pdf_discovery_tool="ghost")
    assert rs._build_default_pdf_config(workflow, _registry({})) == {}


# =============================================================================
# build_pdf_discovery_config
# =============================================================================


def test_build_pdf_discovery_config_no_workflow_returns_empty() -> None:
    """A missing workflow short-circuits to an empty config."""
    registry = _registry({})
    assert rs.build_pdf_discovery_config(None, registry, False) == {}


def test_build_pdf_discovery_config_no_registry_returns_empty() -> None:
    """A missing tool registry short-circuits to an empty config."""
    workflow = WorkflowConfig(pdf_discovery_tool="wf_discovery")
    assert rs.build_pdf_discovery_config(workflow, None, False) == {}


def test_build_pdf_discovery_config_multi_source_dispatch() -> None:
    """``is_multi_source=True`` dispatches to the per-source builder."""
    workflow = WorkflowConfig(
        search_sources=[
            SearchSourceConfig(
                tool="scholar",
                pdf_discovery_tool="scholar_discovery",
                pdf_discovery_url_field="url",
            )
        ]
    )
    registry = _registry({"scholar_discovery": _tool("mcp_scholar_discovery")})

    config = rs.build_pdf_discovery_config(workflow, registry, True)

    assert config == {"scholar": ("mcp_scholar_discovery", "url")}


def test_build_pdf_discovery_config_single_source_dispatch() -> None:
    """``is_multi_source=False`` dispatches to the single default builder."""
    workflow = WorkflowConfig(
        pdf_discovery_tool="wf_discovery", pdf_discovery_url_field="url"
    )
    registry = _registry({"wf_discovery": _tool("mcp_wf_discovery")})

    config = rs.build_pdf_discovery_config(workflow, registry, False)

    assert config == {"_default": ("mcp_wf_discovery", "url")}


# =============================================================================
# _lookup_pdf_discovery_config
# =============================================================================


def test_lookup_pdf_discovery_config_by_source() -> None:
    """A paper's own source config is preferred when present."""
    config = {"pubmed": ("mcp_pubmed", "url"), "_default": ("mcp_def", "url2")}
    result = rs._lookup_pdf_discovery_config("p1", {"p1": "pubmed"}, config)
    assert result == ("mcp_pubmed", "url")


def test_lookup_pdf_discovery_config_falls_back_to_default() -> None:
    """An unmapped source falls back to the ``_default`` config entry."""
    config = {"_default": ("mcp_def", "url2")}
    result = rs._lookup_pdf_discovery_config("p1", {}, config)
    assert result == ("mcp_def", "url2")


def test_lookup_pdf_discovery_config_none_available() -> None:
    """No matching source config and no default returns None."""
    assert rs._lookup_pdf_discovery_config("p1", {}, {}) is None


# =============================================================================
# _resolve_pdf_discovery_entry
# =============================================================================


def _pdf_config() -> dict[str, tuple[str, str]]:
    """Build a single-default PDF-discovery config for entry tests."""
    return {"_default": ("mcp_discovery", "url")}


def test_resolve_pdf_discovery_entry_non_dict_metadata_returns_none() -> None:
    """Non-dict metadata (a malformed entry) is skipped."""
    bad_meta = cast(dict[str, Any], "not-a-dict")
    assert (
        rs._resolve_pdf_discovery_entry("p1", bad_meta, {}, _pdf_config())
        is None
    )


def test_resolve_pdf_discovery_entry_already_has_pdf_url_returns_none() -> None:
    """A paper that already has a pdf_url needs no discovery."""
    meta = {"pdf_url": "http://already.pdf", "url": "http://landing"}
    assert (
        rs._resolve_pdf_discovery_entry("p1", meta, {}, _pdf_config()) is None
    )


def test_resolve_pdf_discovery_entry_no_config_returns_none() -> None:
    """A paper whose source has no resolvable discovery config is skipped."""
    meta = {"url": "http://landing"}
    assert rs._resolve_pdf_discovery_entry("p1", meta, {}, {}) is None


def test_resolve_pdf_discovery_entry_no_landing_url_returns_none() -> None:
    """A paper missing the configured landing-page field is skipped."""
    meta = {"title": "no url field"}
    assert (
        rs._resolve_pdf_discovery_entry("p1", meta, {}, _pdf_config()) is None
    )


def test_resolve_pdf_discovery_entry_success() -> None:
    """An eligible paper resolves to (id, metadata, tool_name, url_field)."""
    meta = {"url": "http://landing"}
    result = rs._resolve_pdf_discovery_entry("p1", meta, {}, _pdf_config())
    assert result == ("p1", meta, "mcp_discovery", "url")


# =============================================================================
# get_papers_needing_pdf_discovery
# =============================================================================


def test_get_papers_needing_pdf_discovery_filters_eligible() -> None:
    """Only papers eligible for discovery are returned, others are skipped."""
    all_metadata = {
        "eligible": {"url": "http://landing"},
        "already_has_pdf": {"pdf_url": "http://x.pdf", "url": "http://landing"},
        "no_url": {"title": "nothing to discover from"},
    }
    result = rs.get_papers_needing_pdf_discovery(
        all_metadata, {}, _pdf_config()
    )
    assert [pid for pid, *_ in result] == ["eligible"]


def test_get_papers_needing_pdf_discovery_empty_metadata() -> None:
    """An empty metadata mapping yields an empty result list."""
    assert rs.get_papers_needing_pdf_discovery({}, {}, _pdf_config()) == []


# =============================================================================
# parse_pdf_discovery_result -- branches beyond the plain-string/list cases
# =============================================================================


def test_parse_pdf_discovery_result_empty_json_list_returns_none() -> None:
    """A JSON-encoded empty list decodes to no PDF URL."""
    assert rs.parse_pdf_discovery_result(json.dumps([])) is None


def test_parse_pdf_discovery_result_dict_without_link_fields_returns_none() -> (
    None
):
    """A JSON dict lacking both ``pdf_links`` and ``links`` yields None."""
    assert rs.parse_pdf_discovery_result(json.dumps({"other": "value"})) is None


def test_parse_pdf_discovery_result_scalar_json_returns_none() -> None:
    """A JSON scalar (neither list nor dict) yields None."""
    assert rs.parse_pdf_discovery_result(json.dumps(42)) is None


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
# _build_multi_source_content_config
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

    config = rs._build_multi_source_content_config(workflow, registry)

    assert set(config) == {"arxiv"}
    assert config["arxiv"].mcp_tool_name == "mcp_arxiv_content"


# =============================================================================
# _build_default_content_config
# =============================================================================


def test_build_default_content_config_success() -> None:
    """A configured workflow-level content tool yields a ``_default`` entry."""
    workflow = WorkflowConfig(
        content_tool="wf_content",
        content_url_field="pdf_url",
        content_params={"depth": "full"},
    )
    registry = _registry({"wf_content": _tool("mcp_wf_content")})

    config = rs._build_default_content_config(workflow, registry)

    assert set(config) == {"_default"}
    assert config["_default"].mcp_tool_name == "mcp_wf_content"
    assert config["_default"].url_field == "pdf_url"
    assert config["_default"].content_params == {"depth": "full"}


def test_build_default_content_config_no_tool_configured() -> None:
    """No workflow-level content tool yields an empty config."""
    assert (
        rs._build_default_content_config(WorkflowConfig(), _registry({})) == {}
    )


def test_build_default_content_config_dangling_reference() -> None:
    """A workflow content tool id absent from the registry yields empty."""
    workflow = WorkflowConfig(content_tool="ghost")
    assert rs._build_default_content_config(workflow, _registry({})) == {}


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
# _lookup_content_config
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

    result = rs._lookup_content_config("p1", {"p1": "arxiv"}, config)

    assert result is cfg


def test_lookup_content_config_falls_back_to_default() -> None:
    """An unmapped source falls back to the ``_default`` config entry."""
    default_cfg = rs.ContentToolConfig(
        mcp_tool_name="mcp_def", url_field="pdf_url", content_params={}
    )
    result = rs._lookup_content_config("p1", {}, {"_default": default_cfg})
    assert result is default_cfg


def test_lookup_content_config_none_available() -> None:
    """No matching source config and no default returns None."""
    assert rs._lookup_content_config("p1", {}, {}) is None


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
