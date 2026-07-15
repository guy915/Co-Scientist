"""PDF-discovery and content-fetch helpers for the literature review node.

Supports Phases 2.4 and 2.5: resolving per-source PDF-discovery and content
retrieval tool configs (with workflow-level fallbacks), selecting which
collected papers are eligible for each step, and defensively parsing the
tools' heterogeneous result shapes.
"""

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional, cast

if TYPE_CHECKING:
    from co_scientist.config import (
        SearchSourceConfig,
        ToolRegistry,
        WorkflowConfig,
    )

logger = logging.getLogger(__name__)

# =============================================================================
# PDF discovery helpers
# =============================================================================


def _resolve_pdf_discovery_tool(
    source: "SearchSourceConfig",
    workflow: "WorkflowConfig",
    tool_registry: "ToolRegistry",
) -> tuple[str, str] | None:
    """Resolve a single source's PDF discovery (mcp_tool_name, url_field).

    A source-level override wins; otherwise falls back to the workflow-level
    default discovery tool/field.
    """
    discovery_tool = source.pdf_discovery_tool or workflow.pdf_discovery_tool
    if not discovery_tool:
        return None
    tool_cfg = tool_registry.get_tool(discovery_tool)
    if not tool_cfg:
        return None
    discovery_url_field = (
        source.pdf_discovery_url_field or workflow.pdf_discovery_url_field
    )
    return tool_cfg.mcp_tool_name, discovery_url_field


def _build_multi_source_pdf_config(
    workflow: "WorkflowConfig",
    tool_registry: "ToolRegistry",
) -> dict[str, tuple[str, str]]:
    """Build per-source PDF discovery config for multi-source mode.

    Per-source keys let get_papers_needing_pdf_discovery route each paper
    to the tool/field for the source it came from (via paper_source_map),
    since sources can have different landing-page layouts.
    """
    config: dict[str, tuple[str, str]] = {}
    for source in workflow.get_enabled_search_sources():
        resolved = _resolve_pdf_discovery_tool(source, workflow, tool_registry)
        if resolved:
            config[source.tool] = resolved
    return config


def _build_default_pdf_config(
    workflow: "WorkflowConfig",
    tool_registry: "ToolRegistry",
) -> dict[str, tuple[str, str]]:
    """Build the single-source default PDF discovery config."""
    if not workflow.pdf_discovery_tool:
        return {}
    tool_cfg = tool_registry.get_tool(workflow.pdf_discovery_tool)
    if not tool_cfg:
        return {}
    return {
        "_default": (tool_cfg.mcp_tool_name, workflow.pdf_discovery_url_field)
    }


def build_pdf_discovery_config(
    workflow: Optional["WorkflowConfig"],
    tool_registry: Optional["ToolRegistry"],
    is_multi_source: bool,
) -> dict[str, tuple[str, str]]:
    """Build PDF discovery configuration mapping.

    Returns:
        Dict mapping source_tool_id -> (mcp_tool_name, url_field)
    """
    if not workflow or not tool_registry:
        return {}
    if is_multi_source:
        return _build_multi_source_pdf_config(workflow, tool_registry)
    # Single-source mode: one default entry under the "_default" key.
    return _build_default_pdf_config(workflow, tool_registry)


def _lookup_pdf_discovery_config(
    pid: str,
    paper_source_map: dict[str, str],
    pdf_discovery_config: dict[str, tuple[str, str]],
) -> tuple[str, str] | None:
    """Look up a paper's PDF-discovery (tool_name, url_field), if any.

    Keyed by the paper's originating source (recorded by
    merge_search_results), falling back to a single default config in
    single-source mode.
    """
    source_tool_id = paper_source_map.get(pid, "_default")
    return pdf_discovery_config.get(source_tool_id) or pdf_discovery_config.get(
        "_default"
    )


def _resolve_pdf_discovery_entry(
    pid: str,
    meta: dict[str, Any],
    paper_source_map: dict[str, str],
    pdf_discovery_config: dict[str, tuple[str, str]],
) -> tuple[str, dict[str, Any], str, str] | None:
    """Resolve one paper's PDF-discovery entry, or None if not eligible.

    Skips papers that already have a pdf_url, have no resolvable discovery
    config for their source, or have no landing-page URL to discover from.
    """
    if not isinstance(meta, dict) or meta.get("pdf_url"):
        return None

    config = _lookup_pdf_discovery_config(
        pid, paper_source_map, pdf_discovery_config
    )
    if not config:
        return None

    tool_name, url_field = config
    landing_url = meta.get(url_field)
    if not landing_url:
        return None
    return pid, meta, tool_name, url_field


def get_papers_needing_pdf_discovery(
    all_paper_metadata: dict[str, dict[str, Any]],
    paper_source_map: dict[str, str],
    pdf_discovery_config: dict[str, tuple[str, str]],
) -> list[tuple[str, dict[str, Any], str, str]]:
    """Identify papers that need PDF discovery.

    Returns:
        List of (paper_id, metadata, tool_name, url_field) tuples
    """
    papers = []
    for pid, meta in all_paper_metadata.items():
        entry = _resolve_pdf_discovery_entry(
            pid, meta, paper_source_map, pdf_discovery_config
        )
        if entry:
            papers.append(entry)

    return papers


def _first_link_url(link: Any) -> str | None:
    """Extract a URL from a link entry that may be a bare string or dict."""
    return link if isinstance(link, str) else link.get("url")


def _pdf_url_from_list(result_data: list[Any]) -> str | None:
    """Extract a PDF URL from a list-shaped discovery result."""
    if not result_data:
        return None
    return cast(str | None, result_data[0])


def _pdf_url_from_dict(result_data: dict[str, Any]) -> str | None:
    """Extract a PDF URL from a dict-shaped discovery result."""
    links = result_data.get("pdf_links") or result_data.get("links") or []
    if not links:
        return None
    return _first_link_url(links[0])


def _pdf_url_from_parsed(result_data: Any) -> str | None:
    """Extract a PDF URL from an already-JSON-parsed discovery result."""
    if isinstance(result_data, list):
        return _pdf_url_from_list(result_data)
    if isinstance(result_data, dict):
        return _pdf_url_from_dict(result_data)
    return None


def _parse_pdf_url_from_string(result: str) -> str | None:
    """Parse a JSON-encoded or bare-URL string discovery result."""
    try:
        result_data = json.loads(result)
    except json.JSONDecodeError:
        # Not JSON at all; treat a bare URL string as the result.
        return result if result.startswith("http") else None
    return _pdf_url_from_parsed(result_data)


def parse_pdf_discovery_result(result: Any) -> str | None:
    """Parse PDF discovery result to extract PDF URL.

    Defensive parsing: different MCP tools serialize their PDF-discovery
    results differently (raw JSON string, parsed dict/list, or a bare URL
    string), so every shape is handled explicitly.
    """
    if isinstance(result, str):
        return _parse_pdf_url_from_string(result)
    if isinstance(result, list) and result:
        return _first_link_url(result[0])
    return None


# =============================================================================
# Content fetching helpers
# =============================================================================


@dataclass
class ContentToolConfig:
    """Configuration for a content retrieval tool."""

    # Bundles the resolved tool name, which metadata field holds the URL to
    # fetch, and any extra call params, so Phase 2.5 call sites don't
    # re-derive this from the raw WorkflowConfig/SearchSourceConfig per
    # paper.
    mcp_tool_name: str
    url_field: str
    content_params: dict[str, Any]


def _resolve_content_tool(
    source: "SearchSourceConfig",
    workflow: "WorkflowConfig",
    tool_registry: "ToolRegistry",
) -> ContentToolConfig | None:
    """Resolve a single source's content retrieval config.

    Same per-source-override-falls-back-to-workflow-default pattern as
    _resolve_pdf_discovery_tool.
    """
    src_content_tool = source.content_tool or workflow.content_tool
    if not src_content_tool:
        return None
    tool_cfg = tool_registry.get_tool(src_content_tool)
    if not tool_cfg:
        return None
    src_url_field = source.content_url_field or workflow.content_url_field
    # Merge workflow params with source-specific params (source takes
    # priority)
    src_params = {**workflow.content_params, **source.content_params}
    return ContentToolConfig(
        mcp_tool_name=tool_cfg.mcp_tool_name,
        url_field=src_url_field,
        content_params=src_params,
    )


def _build_multi_source_content_config(
    workflow: "WorkflowConfig",
    tool_registry: "ToolRegistry",
) -> dict[str, ContentToolConfig]:
    """Build per-source content retrieval config for multi-source mode.

    Keyed by source.tool so get_papers_needing_content can look it up via
    paper_source_map.
    """
    config: dict[str, ContentToolConfig] = {}
    for source in workflow.get_enabled_search_sources():
        resolved = _resolve_content_tool(source, workflow, tool_registry)
        if resolved:
            config[source.tool] = resolved
    return config


def _build_default_content_config(
    workflow: "WorkflowConfig",
    tool_registry: "ToolRegistry",
) -> dict[str, ContentToolConfig]:
    """Build the single-source default content retrieval config."""
    if not workflow.content_tool:
        return {}
    tool_cfg = tool_registry.get_tool(workflow.content_tool)
    if not tool_cfg:
        return {}
    return {
        "_default": ContentToolConfig(
            mcp_tool_name=tool_cfg.mcp_tool_name,
            url_field=workflow.content_url_field,
            content_params=workflow.content_params,
        )
    }


def build_content_config(
    workflow: Optional["WorkflowConfig"],
    tool_registry: Optional["ToolRegistry"],
    is_multi_source: bool,
) -> dict[str, ContentToolConfig]:
    """Build content retrieval configuration mapping.

    Returns:
        Dict mapping source_tool_id -> ContentToolConfig
    """
    if not workflow or not tool_registry:
        return {}
    if is_multi_source:
        return _build_multi_source_content_config(workflow, tool_registry)
    # Single-source mode: one default entry under the "_default" key.
    return _build_default_content_config(workflow, tool_registry)


def _lookup_content_config(
    pid: str,
    paper_source_map: dict[str, str],
    content_config: dict[str, ContentToolConfig],
) -> ContentToolConfig | None:
    """Look up a paper's content-retrieval config, if any.

    Keyed by the paper's originating source (recorded by
    merge_search_results), falling back to a single default config in
    single-source mode.
    """
    source_tool_id = paper_source_map.get(pid, "_default")
    return content_config.get(source_tool_id) or content_config.get("_default")


def _resolve_content_entry(
    pid: str,
    meta: dict[str, Any],
    paper_source_map: dict[str, str],
    content_config: dict[str, ContentToolConfig],
) -> tuple[str, dict[str, Any], ContentToolConfig] | None:
    """Resolve one paper's content-retrieval entry, or None if not eligible.

    Skips papers that already have fulltext, have no resolvable content
    config for their source, or have no URL to fetch content from
    (typically the pdf_url discovered in Phase 2.4).
    """
    if not isinstance(meta, dict) or meta.get("fulltext"):
        return None

    cfg = _lookup_content_config(pid, paper_source_map, content_config)
    if not cfg:
        return None

    content_url = meta.get(cfg.url_field)
    if not content_url:
        return None
    return pid, meta, cfg


def get_papers_needing_content(
    all_paper_metadata: dict[str, dict[str, Any]],
    paper_source_map: dict[str, str],
    content_config: dict[str, ContentToolConfig],
) -> list[tuple[str, dict[str, Any], ContentToolConfig]]:
    """Identify papers that need content retrieval.

    Returns:
        List of (paper_id, metadata, content_tool_config) tuples
    """
    papers = []
    for pid, meta in all_paper_metadata.items():
        entry = _resolve_content_entry(
            pid, meta, paper_source_map, content_config
        )
        if entry:
            papers.append(entry)

    return papers


def _content_or_text_field(data: dict[str, Any]) -> str | None:
    """Return the "content" or "text" field from a dict payload, if set."""
    return cast(str | None, data.get("content") or data.get("text"))


def _parse_content_from_string(result: str) -> str | None:
    """Parse a string content-fetch result (JSON-encoded or raw text).

    Mirrors the dict-payload assumption a successfully-decoded JSON result
    is dict-shaped; falls back to the raw string itself when the field is
    unset or the string isn't JSON at all.
    """
    try:
        result_data = json.loads(result)
    except json.JSONDecodeError:
        return result
    field = _content_or_text_field(cast(dict[str, Any], result_data))
    return field or result


def _parse_content_from_dict(result: dict[str, Any]) -> str:
    """Parse a dict-shaped content-fetch result."""
    field = _content_or_text_field(result)
    return field or str(result)


def parse_content_result(result: Any) -> str | None:
    """Parse content fetch result to extract text content."""
    # As with parse_pdf_discovery_result, different content-fetch tools
    # serialize differently, so each shape is handled explicitly.
    if isinstance(result, str):
        return _parse_content_from_string(result)
    if isinstance(result, dict):
        return _parse_content_from_dict(result)
    return str(result) if result else None
