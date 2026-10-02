"""PDF-discovery and content-fetch helpers for the literature review node.

Supports Phases 2.4 and 2.5: resolving per-source PDF-discovery and content
retrieval tool configs (with workflow-level fallbacks), selecting which
collected papers are eligible for each step, and defensively parsing the
tools' heterogeneous result shapes.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional, TypeVar, cast

if TYPE_CHECKING:
    from co_scientist.config import (
        SearchSourceConfig,
        ToolRegistry,
        WorkflowConfig,
    )

logger = logging.getLogger(__name__)

_ConfigT = TypeVar("_ConfigT")
_EntryT = TypeVar("_EntryT")

# Resolves one source's entry for a retrieval step. The source is None for
# the single-source default entry, where only workflow-level values apply.
_SourceToolResolver = Callable[
    [Optional["SearchSourceConfig"], "WorkflowConfig", "ToolRegistry"],
    _EntryT | None,
]


def _lookup_source_config(
    pid: str,
    paper_source_map: dict[str, str],
    config: dict[str, _ConfigT],
) -> _ConfigT | None:
    """Look up a paper's per-source config entry, if any.

    Keyed by the paper's originating source (recorded by
    merge_search_results), falling back to a single default config in
    single-source mode. Shared by both PDF discovery (``tuple[str, str]``
    values) and content retrieval (``ContentToolConfig`` values).
    """
    source_tool_id = paper_source_map.get(pid, "_default")
    return config.get(source_tool_id) or config.get("_default")


def _select_eligible_papers(
    all_paper_metadata: dict[str, dict[str, Any]],
    paper_source_map: dict[str, str],
    config: dict[str, _ConfigT],
    resolve: Callable[
        [str, dict[str, Any], dict[str, str], dict[str, _ConfigT]],
        _EntryT | None,
    ],
) -> list[_EntryT]:
    """Collect the per-paper entries a retrieval step is eligible to run.

    Both PDF discovery and content retrieval walk the collected papers in
    order and keep whatever their own ``_resolve_*_entry`` admits, so only
    that resolver differs between them.

    Args:
        all_paper_metadata: Collected paper metadata keyed by paper id.
        paper_source_map: Paper id to the source tool id that produced it.
        config: The step's per-source config mapping.
        resolve: The step's per-paper entry resolver, returning None for a
            paper the step should skip.

    Returns:
        The resolved entries, in ``all_paper_metadata`` order.
    """
    entries = (
        resolve(pid, meta, paper_source_map, config)
        for pid, meta in all_paper_metadata.items()
    )
    return [entry for entry in entries if entry is not None]


# =============================================================================
# Shared per-source tool resolution
# =============================================================================


@dataclass(frozen=True)
class _SourceToolFields:
    """Which config attributes back one retrieval step's tool resolution.

    Both PDF discovery and content retrieval resolve a tool id and a
    metadata URL field the same way - source-level override first, workflow
    default second - and differ only in which attribute names hold them.

    Attributes:
        tool_attr: Attribute holding the step's tool id.
        url_field_attr: Attribute holding the metadata field name whose
            value the step's tool is called with.
    """

    tool_attr: str
    url_field_attr: str


_PDF_FIELDS = _SourceToolFields(
    tool_attr="pdf_discovery_tool",
    url_field_attr="pdf_discovery_url_field",
)
_CONTENT_FIELDS = _SourceToolFields(
    tool_attr="content_tool",
    url_field_attr="content_url_field",
)


def _source_or_workflow(
    source: Optional["SearchSourceConfig"],
    workflow: "WorkflowConfig",
    attr: str,
) -> Any:
    """Return the source's override for ``attr``, else the workflow's value."""
    override = getattr(source, attr, None) if source is not None else None
    return override or getattr(workflow, attr, None)


def _resolve_source_tool(
    source: Optional["SearchSourceConfig"],
    workflow: "WorkflowConfig",
    tool_registry: "ToolRegistry",
    fields: _SourceToolFields,
) -> tuple[str, str] | None:
    """Resolve one step's (mcp_tool_name, url_field) for one source.

    A source-level override wins; otherwise the workflow-level default
    applies. Returns None when no tool is configured at either level, or
    when the configured tool id is not in the registry.
    """
    tool_id = _source_or_workflow(source, workflow, fields.tool_attr)
    if not tool_id:
        return None
    tool_cfg = tool_registry.get_tool(tool_id)
    if not tool_cfg:
        return None
    url_field = _source_or_workflow(source, workflow, fields.url_field_attr)
    return tool_cfg.mcp_tool_name, url_field


def _build_source_config(
    workflow: Optional["WorkflowConfig"],
    tool_registry: Optional["ToolRegistry"],
    is_multi_source: bool,
    resolve: _SourceToolResolver[_EntryT],
) -> dict[str, _EntryT]:
    """Build one retrieval step's config mapping for the configured mode.

    Multi-source mode resolves one entry per enabled source, keyed by
    source.tool so get_papers_needing_* can route each paper to the entry
    for the source it came from (via paper_source_map): sources differ in
    landing-page layout and in what their content tool needs. Single-source
    mode resolves the workflow-level defaults once, under "_default".

    Args:
        workflow: Resolved literature-review workflow config, if any.
        tool_registry: Resolved tool registry, if any.
        is_multi_source: Whether the workflow declares search sources.
        resolve: The step's per-source resolver (PDF discovery or content).

    Returns:
        Dict mapping source_tool_id -> the step's resolved entry.
    """
    if not workflow or not tool_registry:
        return {}

    if not is_multi_source:
        default = resolve(None, workflow, tool_registry)
        return {"_default": default} if default else {}

    config: dict[str, _EntryT] = {}
    for source in workflow.get_enabled_search_sources():
        resolved = resolve(source, workflow, tool_registry)
        if resolved:
            config[source.tool] = resolved
    return config


# =============================================================================
# PDF discovery helpers
# =============================================================================


def _resolve_pdf_discovery_tool(
    source: Optional["SearchSourceConfig"],
    workflow: "WorkflowConfig",
    tool_registry: "ToolRegistry",
) -> tuple[str, str] | None:
    """Resolve a single source's PDF discovery (mcp_tool_name, url_field).

    A source-level override wins; otherwise falls back to the workflow-level
    default discovery tool/field. Unlike content retrieval, PDF discovery
    has never carried extra call params - it is called with the landing-page
    URL alone.
    """
    return _resolve_source_tool(source, workflow, tool_registry, _PDF_FIELDS)


def build_pdf_discovery_config(
    workflow: Optional["WorkflowConfig"],
    tool_registry: Optional["ToolRegistry"],
    is_multi_source: bool,
) -> dict[str, tuple[str, str]]:
    """Build PDF discovery configuration mapping.

    Returns:
        Dict mapping source_tool_id -> (mcp_tool_name, url_field)
    """
    return _build_source_config(
        workflow, tool_registry, is_multi_source, _resolve_pdf_discovery_tool
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

    config = _lookup_source_config(pid, paper_source_map, pdf_discovery_config)
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
    return _select_eligible_papers(
        all_paper_metadata,
        paper_source_map,
        pdf_discovery_config,
        _resolve_pdf_discovery_entry,
    )


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
    source: Optional["SearchSourceConfig"],
    workflow: "WorkflowConfig",
    tool_registry: "ToolRegistry",
) -> ContentToolConfig | None:
    """Resolve a single source's content retrieval config.

    Same per-source-override-falls-back-to-workflow-default pattern as
    _resolve_pdf_discovery_tool, plus the call params only this step has:
    workflow params merged under source-specific params, source winning.
    """
    resolved = _resolve_source_tool(
        source, workflow, tool_registry, _CONTENT_FIELDS
    )
    if not resolved:
        return None
    mcp_tool_name, url_field = resolved
    src_params = source.content_params if source else {}
    return ContentToolConfig(
        mcp_tool_name=mcp_tool_name,
        url_field=url_field,
        content_params={**workflow.content_params, **src_params},
    )


def build_content_config(
    workflow: Optional["WorkflowConfig"],
    tool_registry: Optional["ToolRegistry"],
    is_multi_source: bool,
) -> dict[str, ContentToolConfig]:
    """Build content retrieval configuration mapping.

    Returns:
        Dict mapping source_tool_id -> ContentToolConfig
    """
    return _build_source_config(
        workflow, tool_registry, is_multi_source, _resolve_content_tool
    )


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

    cfg = _lookup_source_config(pid, paper_source_map, content_config)
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
    return _select_eligible_papers(
        all_paper_metadata,
        paper_source_map,
        content_config,
        _resolve_content_entry,
    )


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
