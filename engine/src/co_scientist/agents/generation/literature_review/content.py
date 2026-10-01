"""Phases 2.4 and 2.5: literature review PDF discovery and content fetching.

Both phases are optional and config-driven: Phase 2.4 discovers PDF links for
sources that return landing pages, and Phase 2.5 downloads fulltext for papers
that have a URL but no fulltext yet. When no relevant tool is configured, each
phase is a no-op.
"""

import asyncio
import logging
from typing import Any

from co_scientist.evidence.helpers import (
    ContentToolConfig,
    SearchConfig,
    build_content_config,
    build_pdf_discovery_config,
    get_papers_needing_content,
    get_papers_needing_pdf_discovery,
    parse_content_result,
    parse_pdf_discovery_result,
)
from co_scientist.mcp_client import MCPToolClient
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


async def _discover_pdf_link(
    paper_id: str,
    metadata: dict[str, Any],
    tool_name: str,
    url_field: str,
    mcp_client: MCPToolClient,
) -> tuple[str, str | None]:
    """Discover PDF link for a single paper."""
    landing_url = metadata.get(url_field)
    if not landing_url:
        return (paper_id, None)

    try:
        logger.debug("Discovering PDF links for %s: %s", paper_id, landing_url)
        result = await mcp_client.call_tool(tool_name, url=landing_url)
        pdf_url = parse_pdf_discovery_result(result)
        if pdf_url:
            logger.debug("Found PDF link for %s: %s", paper_id, pdf_url)
        return (paper_id, pdf_url)
    except Exception as e:
        # Failure just leaves this paper without a pdf_url; Phase 2.5 will
        # then have nothing to fetch content from for it, and it may still
        # be usable for analysis via its abstract.
        logger.warning("Failed to discover PDF links for %s: %s", paper_id, e)
        return (paper_id, None)


def _apply_metadata_field(
    all_paper_metadata: dict[str, dict[str, Any]],
    results: list[tuple[str, str | None]],
    field: str,
) -> int:
    """Write per-paper results back into a metadata field, in place.

    Shared by Phase 2.4 (``pdf_url``) and Phase 2.5 (``fulltext``): a result is
    applied only when it is non-empty and its paper is still present.

    Returns:
        The number of papers updated with a non-empty value.
    """
    updated_count = 0
    for paper_id, value in results:
        if value and paper_id in all_paper_metadata:
            all_paper_metadata[paper_id][field] = value
            updated_count += 1
    return updated_count


async def _run_pdf_discovery(
    papers_needing_discovery: list[tuple[str, dict[str, Any], str, str]],
    mcp_client: MCPToolClient,
    all_paper_metadata: dict[str, dict[str, Any]],
) -> int:
    """Discovers PDF links for the given papers in parallel and applies them.

    Mutates all_paper_metadata in place so Phase 2.5 and later phases see
    the newly discovered pdf_url values.

    Args:
        papers_needing_discovery: (paper_id, metadata, tool_name, url_field)
            tuples for papers eligible for PDF discovery.
        mcp_client: Client used to call each source's discovery tool.
        all_paper_metadata: Collected paper metadata keyed by paper id.

    Returns:
        The number of papers updated with a newly discovered pdf_url.
    """
    tasks = [
        _discover_pdf_link(pid, meta, tool_name, url_field, mcp_client)
        for pid, meta, tool_name, url_field in papers_needing_discovery
    ]
    results = await asyncio.gather(*tasks)
    return _apply_metadata_field(all_paper_metadata, results, "pdf_url")


async def _run_and_log_pdf_discovery(
    papers_needing_discovery: list[tuple[str, dict[str, Any], str, str]],
    mcp_client: MCPToolClient,
    all_paper_metadata: dict[str, dict[str, Any]],
) -> None:
    """Runs PDF discovery for the given papers and logs the outcome."""
    logger.info(
        "Phase 2.4: discovering PDF links for %s papers",
        len(papers_needing_discovery),
    )

    discovered_count = await _run_pdf_discovery(
        papers_needing_discovery, mcp_client, all_paper_metadata
    )

    logger.info(
        "PDF discovery complete: %s/%s papers",
        discovered_count,
        len(papers_needing_discovery),
    )


async def _phase2_4_discover_pdf_links(
    all_paper_metadata: dict[str, dict[str, Any]],
    paper_source_map: dict[str, str],
    config: SearchConfig,
    mcp_client: MCPToolClient,
) -> None:
    """Phase 2.4: Discover PDF links for papers with landing pages."""
    # This phase is entirely optional: if no source/workflow config wires up
    # a pdf_discovery_tool, build_pdf_discovery_config returns an empty
    # mapping and this function is a no-op (many sources return fulltext
    # directly and never need PDF discovery at all).
    pdf_discovery_config = build_pdf_discovery_config(
        config.workflow,
        config.tool_registry,
        config.is_multi_source,
    )

    if not pdf_discovery_config:
        return

    # Filters to only papers that lack a pdf_url already but do have a
    # landing-page URL and a discovery tool configured for their source.
    papers_needing_discovery = get_papers_needing_pdf_discovery(
        all_paper_metadata,
        paper_source_map,
        pdf_discovery_config,
    )

    if not papers_needing_discovery:
        return

    await _run_and_log_pdf_discovery(
        papers_needing_discovery, mcp_client, all_paper_metadata
    )


def _prepare_content_call_args(
    paper_id: str,
    content_url: str,
    content_cfg: "ContentToolConfig",
    runtime_context: dict[str, Any],
) -> dict[str, Any]:
    """Resolves per-tool content params and builds the MCP tool-call args.

    content_cfg's raw YAML params may contain placeholders (e.g. referencing
    the research goal) that resolve_content_params fills in from
    runtime_context before the tool call.
    """
    # Imported locally to avoid a module-level import cycle between
    # config.schema and the nodes package.
    from co_scientist.config.schema import (
        resolve_content_params,
    )

    resolved_params = resolve_content_params(
        content_cfg.content_params, runtime_context
    )
    tool_args = {"url": content_url, **resolved_params}

    logger.debug(
        "Fetching content for %s via %s: %s",
        paper_id,
        content_cfg.mcp_tool_name,
        content_url,
    )
    if resolved_params:
        logger.debug("  with params: %s", list(resolved_params.keys()))

    return tool_args


async def _fetch_paper_content(
    paper_id: str,
    metadata: dict[str, Any],
    content_cfg: "ContentToolConfig",
    mcp_client: MCPToolClient,
    runtime_context: dict[str, Any],
) -> tuple[str, str | None]:
    """Fetch content for a single paper."""
    content_url = metadata.get(content_cfg.url_field)
    if not content_url:
        return (paper_id, None)

    try:
        tool_args = _prepare_content_call_args(
            paper_id, content_url, content_cfg, runtime_context
        )
        result = await mcp_client.call_tool(
            content_cfg.mcp_tool_name, **tool_args
        )
        content = parse_content_result(result)
        if content:
            logger.debug(
                "Retrieved %s chars for paper %s", len(content), paper_id
            )
        return (paper_id, content)
    except Exception as e:
        # Leaves the paper without fulltext; it may still be analyzable via
        # its abstract (see get_papers_with_content in the helpers module).
        logger.warning("Failed to fetch content for %s: %s", paper_id, e)
        return (paper_id, None)


def _build_content_runtime_context(state: "WorkflowState") -> dict[str, Any]:
    """Builds the runtime context used to resolve per-tool content params.

    Args:
        state: Current workflow state.

    Returns:
        Runtime context dict consumed by resolve_content_params.
    """
    return {
        "research_goal": state.get("research_goal", ""),
        # Could be extracted from hypothesis categories later.
        "focus_areas": [],
    }


async def _run_content_fetch(
    papers_needing_content: list[
        tuple[str, dict[str, Any], "ContentToolConfig"]
    ],
    mcp_client: MCPToolClient,
    runtime_context: dict[str, Any],
    all_paper_metadata: dict[str, dict[str, Any]],
) -> int:
    """Fetches content for the given papers in parallel and applies it.

    Mutates all_paper_metadata in place so Phase 3 analysis picks up the
    newly fetched fulltext.

    Args:
        papers_needing_content: (paper_id, metadata, content_cfg) tuples for
            papers eligible for content retrieval.
        mcp_client: Client used to call each source's content tool.
        runtime_context: Context for resolving per-tool content params.
        all_paper_metadata: Collected paper metadata keyed by paper id.

    Returns:
        The number of papers updated with newly fetched fulltext.
    """
    tasks = [
        _fetch_paper_content(
            pid, meta, content_cfg, mcp_client, runtime_context
        )
        for pid, meta, content_cfg in papers_needing_content
    ]
    results = await asyncio.gather(*tasks)
    return _apply_metadata_field(all_paper_metadata, results, "fulltext")


async def _run_and_log_content_fetch(
    papers_needing_content: list[
        tuple[str, dict[str, Any], "ContentToolConfig"]
    ],
    mcp_client: MCPToolClient,
    runtime_context: dict[str, Any],
    all_paper_metadata: dict[str, dict[str, Any]],
) -> None:
    """Runs content fetch for the given papers and logs the outcome."""
    logger.info(
        "Phase 2.5: fetching content for %s papers", len(papers_needing_content)
    )

    fetched_count = await _run_content_fetch(
        papers_needing_content, mcp_client, runtime_context, all_paper_metadata
    )

    logger.info(
        "Content retrieval complete: %s/%s papers",
        fetched_count,
        len(papers_needing_content),
    )


async def _phase2_5_fetch_content(
    all_paper_metadata: dict[str, dict[str, Any]],
    paper_source_map: dict[str, str],
    config: SearchConfig,
    mcp_client: MCPToolClient,
    state: "WorkflowState",
) -> None:
    """Phase 2.5: Fetch content for papers with pdf_url but no fulltext."""
    # Also entirely optional/config-driven: no configured content_tool means
    # this is a no-op, same pattern as Phase 2.4's PDF discovery.
    content_config = build_content_config(
        config.workflow,
        config.tool_registry,
        config.is_multi_source,
    )

    if not content_config:
        return

    logger.info(
        "Content retrieval configured for %s source(s)", len(content_config)
    )

    # Only papers still missing fulltext but with a URL suitable for the
    # configured content tool (typically the pdf_url found in Phase 2.4).
    papers_needing_content = get_papers_needing_content(
        all_paper_metadata,
        paper_source_map,
        content_config,
    )

    if not papers_needing_content:
        return

    runtime_context = _build_content_runtime_context(state)
    await _run_and_log_content_fetch(
        papers_needing_content, mcp_client, runtime_context, all_paper_metadata
    )
