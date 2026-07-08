"""Literature review node.

Orchestrates a multi-phase literature review process:
1. Generate search queries (MCP tool or LLM)
2. Collect papers from configured sources
3. Discover PDF links (for sources returning landing pages)
4. Fetch content (for sources without fulltext)
5. Analyze each paper for gaps/limitations
6. Synthesize findings into articles_with_reasoning
"""
# pylint: disable=inconsistent-quotes

import asyncio
import json
import logging
import os
from typing import Any, cast, Optional, TYPE_CHECKING

from co_scientist.constants import (
    corpus_slug,
    DEFAULT_MAX_TOKENS,
    EXTENDED_MAX_TOKENS,
    HIGH_TEMPERATURE,
    LITERATURE_REVIEW_PAPERS_COUNT,
    LITERATURE_REVIEW_PAPERS_COUNT_DEV,
    LITERATURE_REVIEW_RECENCY_YEARS,
    LITERATURE_REVIEW_FAILED,
)
from co_scientist.cache import get_node_cache
from co_scientist.config.registry import parse_bool_env
from co_scientist.llm import call_llm, call_llm_json
from co_scientist.mcp_client import (
    get_mcp_client,
    check_literature_source_available,
    MCPToolClient,
)
from co_scientist.prompts import (
    get_literature_review_query_generation_prompt,
    get_literature_review_paper_analysis_prompt,
    get_literature_review_synthesis_prompt,
)
from co_scientist.schemas import (
    LITERATURE_QUERY_SCHEMA,
    LITERATURE_PAPER_ANALYSIS_SCHEMA,
)
from co_scientist.state import WorkflowState
from co_scientist.tools.response_parser import parse_mcp_result

from co_scientist.nodes.reflection_helpers import extract_entity_names
from co_scientist.nodes.literature_review_helpers import (
    SearchConfig,
    ContentToolConfig,
    extract_source_name,
    normalize_search_response,
    build_articles_from_metadata,
    count_papers_with_fulltext,
    get_papers_with_content,
    make_failure_result,
    make_success_result,
    parse_mcp_query_result,
    determine_query_source_type,
    calculate_papers_per_query,
    merge_search_results,
    build_pdf_discovery_config,
    get_papers_needing_pdf_discovery,
    parse_pdf_discovery_result,
    build_content_config,
    get_papers_needing_content,
    parse_content_result,
    get_paper_content_for_analysis,
    parse_year_from_metadata,
)
from co_scientist.nodes.progress import emit_progress

if TYPE_CHECKING:
    from co_scientist.config import ToolRegistry, ToolConfig, SearchSourceConfig

logger = logging.getLogger(__name__)


def _describe_exc(exc: BaseException) -> str:
    """Describe an exception by type and message for diagnostic logging.

    Unwraps ``ExceptionGroup`` (raised by the anyio task groups inside the MCP
    transport) down to its first leaf so the root cause - e.g. a connection
    error versus a validation error - is visible instead of the opaque group
    wrapper.

    Args:
        exc: The caught exception.

    Returns:
        A "TypeName: message" string describing the underlying cause.
    """
    current: BaseException = exc
    # ExceptionGroup (Python 3.11+) exposes an ``exceptions`` tuple; descend to
    # the first leaf so the real cause surfaces instead of the group wrapper.
    while getattr(current, "exceptions", None):
        current = current.exceptions[0]  # type: ignore[attr-defined]
    message = str(current).strip()
    return (f"{type(current).__name__}: {message}"
            if message else type(current).__name__)


# =============================================================================
# Configuration setup
# =============================================================================


def _get_search_config(state: WorkflowState) -> SearchConfig:
    """Extract search configuration from state and tool registry."""
    tool_registry = state.get("tool_registry")
    workflow = tool_registry.get_workflow(
        "literature_review") if tool_registry else None
    # config.is_multi_source is the branch point used throughout this file to
    # pick between the multi-source and single-source Phase 2 code paths.
    is_multi_source = bool(workflow and workflow.is_multi_source())

    # Defaults for backwards compatibility
    # If there is no tool registry (or no configured workflow), fall back to
    # the legacy hardcoded PubMed tool so the node still works without a
    # YAML tools config.
    search_tool_name = "pubmed_search_with_fulltext"
    source_name = "pubmed"
    search_tool_config = None

    if is_multi_source and workflow is not None:
        enabled_sources = workflow.get_enabled_search_sources()
        source_names = [s.tool for s in enabled_sources]
        logger.info("Multi-source mode: %s sources configured: %s",
                    len(enabled_sources), source_names)
    elif tool_registry and workflow and workflow.primary_search:
        search_tool_config = tool_registry.get_tool(workflow.primary_search)
        if search_tool_config:
            search_tool_name = search_tool_config.mcp_tool_name
            source_name = extract_source_name(search_tool_config)
            logger.info("Single-source mode: %s (source: %s)", search_tool_name,
                        source_name)

    # Dev mode detection
    # Dev mode uses a far smaller paper budget for fast iteration; a
    # per-run override in state takes priority over the default when not in
    # dev mode.
    is_dev_mode = parse_bool_env(os.getenv("COSCIENTIST_DEV_MODE", "false"))
    run_papers_count = state.get("literature_review_papers_count")
    papers_to_read_count = (LITERATURE_REVIEW_PAPERS_COUNT_DEV if is_dev_mode
                            else int(run_papers_count or
                                     LITERATURE_REVIEW_PAPERS_COUNT))

    return SearchConfig(
        tool_registry=tool_registry,
        workflow=workflow,
        is_multi_source=is_multi_source,
        search_tool_name=search_tool_name,
        search_tool_config=search_tool_config,
        source_name=source_name,
        papers_to_read_count=papers_to_read_count,
        is_dev_mode=is_dev_mode,
    )


# =============================================================================
# Phase 1: Query generation
# =============================================================================


async def _generate_queries_via_mcp(
    mcp_client: MCPToolClient,
    research_goal: str,
    tool_name: str,
    query_format: str,
) -> list[str]:
    """Generate queries using MCP tool."""
    try:
        result = await mcp_client.call_tool(
            tool_name,
            research_goal=research_goal,
            query_format=query_format,
        )
        queries = parse_mcp_query_result(result)
        logger.info("MCP query generation returned %s queries", len(queries))
        return queries
    except Exception as e:  # pylint: disable=broad-exception-caught
        # An empty list here (rather than raising) is the signal that lets
        # _phase1_generate_queries fall through to the LLM-based generator.
        logger.warning("MCP query generation failed: %s, falling back to LLM",
                       _describe_exc(e))
        return []


async def _generate_queries_via_llm(
    state: WorkflowState,
    config: SearchConfig,
) -> list[str]:
    """Generate queries using LLM with source-aware prompt."""
    # source_type steers the prompt wording (e.g. "academic" boolean search
    # phrasing vs "knowledge_graph" entity-oriented phrasing) so the LLM
    # produces queries that suit whatever source(s) are actually configured.
    source_type = determine_query_source_type(
        config.workflow,
        config.tool_registry,
        config.search_tool_config,
        config.is_multi_source,
    )
    logger.debug("Using %s query generation prompt", source_type)

    prompt = get_literature_review_query_generation_prompt(
        research_goal=state["research_goal"],
        source_type=source_type,
        preferences=state.get("preferences", ""),
        attributes=state.get("attributes", []),
        user_literature=state.get("literature", []),
        user_hypotheses=state.get("starting_hypotheses", []),
    )

    try:
        result = await call_llm_json(
            prompt=prompt,
            model_name=state["model_name"],
            max_tokens=DEFAULT_MAX_TOKENS,
            temperature=HIGH_TEMPERATURE,
            json_schema=LITERATURE_QUERY_SCHEMA,
        )
        return cast(list[str], result.get("queries", []))
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning("LLM query generation failed: %s", e)
        return []


async def _phase1_generate_queries(
    state: WorkflowState,
    config: SearchConfig,
    mcp_client: MCPToolClient,
) -> list[str]:
    """Phase 1: Generate search queries."""
    logger.info("Phase 1: generating search queries")

    queries = []

    # Try MCP-based generation first if configured
    if (config.tool_registry and config.workflow and
            config.workflow.query_generation_tool):
        tool_cfg = config.tool_registry.get_tool(
            config.workflow.query_generation_tool)
        if tool_cfg:
            query_format = config.workflow.query_format or "boolean"
            logger.info("Using MCP query generation: %s (format: %s)",
                        tool_cfg.mcp_tool_name, query_format)
            queries = await _generate_queries_via_mcp(
                mcp_client,
                state["research_goal"],
                tool_cfg.mcp_tool_name,
                query_format,
            )

    # Fallback to LLM-based generation
    # Also the primary path when no query_generation_tool is configured at
    # all.
    if not queries:
        queries = await _generate_queries_via_llm(state, config)

    # Final fallback to research goal
    # Guarantees Phase 2 always has at least one query to search with, even
    # if both generators failed.
    if not queries:
        logger.warning("No queries generated, using research goal")
        queries = [state["research_goal"]]

    # Limit to 3 queries max
    # Bounds the number of parallel search calls (and downstream
    # papers-per-query fan-out) regardless of how many queries either
    # generator returned.
    queries = queries[:3]

    logger.info("Generated %s search queries", len(queries))
    for i, q in enumerate(queries, 1):
        logger.debug("Query %s: %s", i, q)

    return queries


# =============================================================================
# Phase 2: Paper collection
# =============================================================================


async def _search_single_source(
    source_config: "SearchSourceConfig",
    queries: list[str],
    slug: str,
    run_id: str,
    tool_registry: "ToolRegistry",
    mcp_client: MCPToolClient,
    errors: Optional[list[str]] = None,
) -> tuple[str, dict[str, dict[str, Any]]]:
    """Search a single source with all queries."""
    tool_config = tool_registry.get_tool(source_config.tool)
    if not tool_config:
        logger.warning("Tool config not found for source: %s",
                       source_config.tool)
        return (source_config.tool, {})

    mcp_tool_name = tool_config.mcp_tool_name
    src_name = extract_source_name(tool_config)
    papers_per_query = source_config.papers_per_query

    logger.info("Searching %s (%s): %s papers/query", src_name, mcp_tool_name,
                papers_per_query)

    # Queries run sequentially (not gathered) within a single source, so
    # this source's total time is proportional to its query count; the
    # caller instead parallelizes across sources.
    source_results = {}
    for query in queries:
        try:
            # canonical_params uses the shared cross-source parameter names;
            # map_parameters() translates them into this specific tool's own
            # argument names/shapes per its YAML config.
            canonical_params = {
                "query": query,
                "slug": slug,
                "max_papers": papers_per_query,
                "recency_years": LITERATURE_REVIEW_RECENCY_YEARS,
                "run_id": run_id,
            }
            tool_params = tool_config.map_parameters(canonical_params)
            tool_params = {
                k: v for k, v in tool_params.items() if v is not None
            }

            result = await mcp_client.call_tool(mcp_tool_name, **tool_params)
            result_data = parse_mcp_result(result)
            normalized = normalize_search_response(result_data, tool_config)

            # Tag every paper with which source produced it so downstream
            # phases (PDF discovery, content fetching) can look up the
            # right per-source tool config via paper_source_map.
            for _, meta in normalized.items():
                if isinstance(meta, dict):
                    meta["_source_name"] = src_name
            source_results.update(normalized)

        except Exception as e:  # pylint: disable=broad-exception-caught
            # A failed query for this source is swallowed here (not raised)
            # so other queries/sources still complete; the caller aggregates
            # errors to distinguish "zero results" from "search broke".
            detail = _describe_exc(e)
            logger.error("Query failed for %s: %s", src_name, detail)
            if errors is not None:
                errors.append(f"{src_name}: {detail}")

    logger.info("Source %s: collected %s papers", src_name, len(source_results))
    return (source_config.tool, source_results)


async def _search_single_query(
    query: str,
    index: int,
    papers_count: int,
    slug: str,
    run_id: str,
    search_tool_name: str,
    search_tool_config: Optional["ToolConfig"],
    mcp_client: MCPToolClient,
    errors: Optional[list[str]] = None,
) -> tuple[int, dict[str, dict[str, Any]]]:
    """Search single query (for single-source mode)."""
    logger.debug("Searching query %s (%s papers): %s...", index, papers_count,
                 query[:80])

    try:
        canonical_params = {
            "query": query,
            "slug": slug,
            "max_papers": papers_count,
            "recency_years": LITERATURE_REVIEW_RECENCY_YEARS,
            "run_id": run_id,
        }

        # Without a search_tool_config (legacy/no-registry fallback), the
        # canonical params are passed straight through as tool args instead
        # of being mapped to a tool-specific parameter shape.
        if search_tool_config:
            tool_params = search_tool_config.map_parameters(canonical_params)
            tool_params = {
                k: v for k, v in tool_params.items() if v is not None
            }
        else:
            tool_params = canonical_params

        result = await mcp_client.call_tool(search_tool_name, **tool_params)
        result_data = parse_mcp_result(result)
        normalized = normalize_search_response(result_data, search_tool_config)

        logger.debug("Query %s: found %s papers", index, len(normalized))
        return (index, normalized)

    except Exception as e:  # pylint: disable=broad-exception-caught
        # Errors are recorded per-query index (not raised) so
        # asyncio.gather in the caller still completes for the other
        # queries; the aggregated errors list drives the "search broke" vs
        # "search found nothing" distinction in the main node function.
        detail = _describe_exc(e)
        logger.error("Query %s (%s) failed: %s", index, search_tool_name,
                     detail)
        if errors is not None:
            errors.append(f"query {index}: {detail}")
        return (index, {})


async def _phase2_collect_papers_multi_source(
    queries: list[str],
    slug: str,
    state: WorkflowState,
    config: SearchConfig,
    mcp_client: MCPToolClient,
    errors: Optional[list[str]] = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Phase 2 (multi-source): Collect papers from multiple sources in parallel.
    """
    # Multi-source mode guarantees a configured workflow and tool registry.
    assert config.workflow is not None
    assert config.tool_registry is not None
    enabled_sources = config.workflow.get_enabled_search_sources()
    logger.info("Phase 2: collecting papers from %s sources",
                len(enabled_sources))

    # Search all sources in parallel
    # Each _search_single_source call runs its own queries sequentially, so
    # overall latency is bounded by the slowest source rather than the sum
    # of all sources' query times.
    tasks = [
        _search_single_source(
            source,
            queries,
            slug,
            state["run_id"],
            config.tool_registry,
            mcp_client,
            errors,
        ) for source in enabled_sources
    ]
    source_results = await asyncio.gather(*tasks)

    # Merge results
    # Optionally dedupes by title (config-driven via
    # deduplicate_across_sources) and builds paper_source_map so later
    # phases know which source's tool config applies to each paper.
    all_paper_metadata, paper_source_map = merge_search_results(
        source_results,
        deduplicate=config.workflow.deduplicate_across_sources,
    )

    logger.info(
        "Multi-source search complete: %s unique papers from %s sources",
        len(all_paper_metadata), len(enabled_sources))

    return all_paper_metadata, paper_source_map


async def _phase2_collect_papers_single_source(
    queries: list[str],
    slug: str,
    state: WorkflowState,
    config: SearchConfig,
    mcp_client: MCPToolClient,
    errors: Optional[list[str]] = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Phase 2 (single-source): Collect papers with legacy distribution."""
    logger.info("Phase 2: collecting papers with %s", config.search_tool_name)

    # Distribute the fixed papers_to_read_count budget evenly across
    # queries; any remainder (from integer division) is handed to the first
    # `remainder` queries below so the total papers requested always sums to
    # papers_to_read_count.
    papers_per_query, remainder = calculate_papers_per_query(
        config.papers_to_read_count,
        len(queries),
    )

    logger.info("Distributing %s papers: %s per query (+ %s extra)",
                config.papers_to_read_count, papers_per_query, remainder)

    # Search all queries in parallel
    # Unlike multi-source mode, there is only one tool/source involved here
    # so no per-source serialization is needed.
    tasks = [
        _search_single_query(
            query,
            i + 1,
            papers_per_query + (1 if i < remainder else 0),
            slug,
            state["run_id"],
            config.search_tool_name,
            config.search_tool_config,
            mcp_client,
            errors,
        ) for i, query in enumerate(queries)
    ]
    search_results = await asyncio.gather(*tasks)

    # Merge results (no source tracking needed for single-source)
    # Every paper came from the same tool/source, so there is no
    # per-source config to track.
    all_paper_metadata = {}
    for _, result_data in search_results:
        all_paper_metadata.update(result_data)

    return all_paper_metadata, {}


# =============================================================================
# Phase 2.4: PDF discovery
# =============================================================================


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
    except Exception as e:  # pylint: disable=broad-exception-caught
        # Failure just leaves this paper without a pdf_url; Phase 2.5 will
        # then have nothing to fetch content from for it, and it may still
        # be usable for analysis via its abstract.
        logger.warning("Failed to discover PDF links for %s: %s", paper_id, e)
        return (paper_id, None)


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

    logger.info("Phase 2.4: discovering PDF links for %s papers",
                len(papers_needing_discovery))

    # Discover in parallel
    tasks = [
        _discover_pdf_link(pid, meta, tool_name, url_field, mcp_client)
        for pid, meta, tool_name, url_field in papers_needing_discovery
    ]
    results = await asyncio.gather(*tasks)

    # Update metadata
    # all_paper_metadata is mutated directly (this function returns None)
    # so Phase 2.5 and later phases see the newly discovered pdf_url values.
    discovered_count = 0
    for paper_id, pdf_url in results:
        if pdf_url and paper_id in all_paper_metadata:
            all_paper_metadata[paper_id]["pdf_url"] = pdf_url
            discovered_count += 1

    logger.info("PDF discovery complete: %s/%s papers", discovered_count,
                len(papers_needing_discovery))


# =============================================================================
# Phase 2.5: Content fetching
# =============================================================================


async def _fetch_paper_content(
    paper_id: str,
    metadata: dict[str, Any],
    content_cfg: "ContentToolConfig",
    mcp_client: MCPToolClient,
    runtime_context: dict[str, Any],
) -> tuple[str, str | None]:
    """Fetch content for a single paper."""
    # Imported locally to avoid a module-level import cycle between
    # config.schema and the nodes package.
    from co_scientist.config.schema import resolve_content_params  # pylint: disable=import-outside-toplevel

    content_url = metadata.get(content_cfg.url_field)
    if not content_url:
        return (paper_id, None)

    try:
        # Resolve content_params with runtime context
        # content_cfg's raw YAML params may contain placeholders (e.g.
        # referencing the research goal) that resolve_content_params fills
        # in from runtime_context before the tool call.
        resolved_params = resolve_content_params(content_cfg.content_params,
                                                 runtime_context)

        # Build tool call args: url is always required, add any resolved params
        tool_args = {"url": content_url, **resolved_params}

        logger.debug("Fetching content for %s via %s: %s", paper_id,
                     content_cfg.mcp_tool_name, content_url)
        if resolved_params:
            logger.debug("  with params: %s", list(resolved_params.keys()))

        result = await mcp_client.call_tool(content_cfg.mcp_tool_name,
                                            **tool_args)
        content = parse_content_result(result)
        if content:
            logger.debug("Retrieved %s chars for paper %s", len(content),
                         paper_id)
        return (paper_id, content)
    except Exception as e:  # pylint: disable=broad-exception-caught
        # Leaves the paper without fulltext; it may still be analyzable via
        # its abstract (see get_papers_with_content in the helpers module).
        logger.warning("Failed to fetch content for %s: %s", paper_id, e)
        return (paper_id, None)


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

    logger.info("Content retrieval configured for %s source(s)",
                len(content_config))

    # Only papers still missing fulltext but with a URL suitable for the
    # configured content tool (typically the pdf_url found in Phase 2.4).
    papers_needing_content = get_papers_needing_content(
        all_paper_metadata,
        paper_source_map,
        content_config,
    )

    if not papers_needing_content:
        return

    logger.info("Phase 2.5: fetching content for %s papers",
                len(papers_needing_content))

    # Build runtime context for param resolution
    runtime_context = {
        "research_goal": state.get("research_goal", ""),
        "focus_areas": [
        ],  # could be extracted from hypothesis categories later
    }

    # Fetch in parallel
    tasks = [
        _fetch_paper_content(pid, meta, content_cfg, mcp_client,
                             runtime_context)
        for pid, meta, content_cfg in papers_needing_content
    ]
    results = await asyncio.gather(*tasks)

    # Update metadata
    # Mutates all_paper_metadata in place (this function returns None) so
    # Phase 3 analysis picks up the newly fetched fulltext.
    fetched_count = 0
    for paper_id, content in results:
        if content and paper_id in all_paper_metadata:
            all_paper_metadata[paper_id]["fulltext"] = content
            fetched_count += 1

    logger.info("Content retrieval complete: %s/%s papers", fetched_count,
                len(papers_needing_content))


# =============================================================================
# Phase 2.6: Context enrichment (knowledge-graph / external tools)
# =============================================================================

# Max chars injected into synthesis prompt from all enrichment tools combined
_CONTEXT_ENRICHMENT_MAX_CHARS = 1500
# Max results requested per entity per tool call
_CONTEXT_ENRICHMENT_RESULTS_PER_ENTITY = 4


async def _call_enrichment_tool_for_entity(
    tool_name: str,
    mapped_params: dict[str, Any],
    mcp_client: MCPToolClient,
) -> Any:
    """Call one enrichment tool for one entity; returns raw result or None."""
    try:
        return await mcp_client.call_tool(tool_name, **mapped_params)
    except Exception as e:  # pylint: disable=broad-exception-caught
        # Enrichment is best-effort background context, not a required
        # input, so a failed call for one entity/tool just yields no
        # evidence for it rather than aborting the whole node.
        logger.debug("context enrichment call failed (%s): %s", tool_name, e)
        return None


def _parse_enrichment_result(raw: Any) -> tuple[str, list[dict[str, Any]]]:
    """Extract formatted text AND structured items from an enrichment result.

    Returns (display_text, structured_items) where structured_items is a
    list of dicts suitable for storage in context_enrichment_sources.
    """
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            # Not JSON: treat the raw string itself as the display text.
            text = raw[:300] if raw else ""
            return text, [{"display": text, "data": {}}] if text else []

    if isinstance(data, dict):
        # INDRA-shaped response: has a "statements" key (even when empty).
        # Never fall through to the raw-dict repr for this format.
        if "statements" in data:
            stmts = data.get("statements", [])
            if not stmts:
                return "", []  # entity had no results - skip cleanly
            lines = []
            items = []
            for s in stmts[:_CONTEXT_ENRICHMENT_RESULTS_PER_ENTITY]:
                # INDRA statements encode subject/object/relation triples
                # with a belief score; format as a readable causal edge for
                # the synthesis prompt.
                subj = (s.get("subj") or {}).get("name", "")
                obj = (s.get("obj") or {}).get("name", "")
                rel = s.get("type", "")
                belief = s.get("belief", 0)
                if subj and obj:
                    display = (f"{subj} \u2192 {obj} [{rel}]"
                               f" (belief: {belief:.2f})")
                    lines.append(f"- {display}")
                    items.append({"display": f"INDRA: {display}", "data": s})
            return "\n".join(lines), items

        # Generic "results" list shape (non-INDRA tools that wrap their
        # payload in a results key).
        results = data.get("results", [])
        if results:
            capped = results[:_CONTEXT_ENRICHMENT_RESULTS_PER_ENTITY]
            text = "\n".join(str(r)[:120] for r in capped)
            items = [{
                "display": str(r)[:120],
                "data": r if isinstance(r, dict) else {}
            } for r in capped]
            return text, items

        # Fallback: no "statements" or "results" key, so just stringify the
        # whole dict (truncated) as a single display item.
        text = str(data)[:300]
        return text, [{"display": text, "data": data}] if text else []

    if isinstance(data, list):
        # Generic bare-list response shape.
        capped = data[:_CONTEXT_ENRICHMENT_RESULTS_PER_ENTITY]
        text = "\n".join(str(item)[:120] for item in capped)
        items = [{
            "display": str(item)[:120],
            "data": item if isinstance(item, dict) else {}
        } for item in capped]
        return text, items

    # Scalar (or falsy) result: stringify directly.
    text = str(data)[:300] if data else ""
    return text, [{"display": text, "data": {}}] if text else []


async def _call_enrichment_tool_for_entities(
    tool_config: Any,
    entities: list[str],
    mcp_client: MCPToolClient,
) -> tuple[str, list[dict[str, Any]]]:
    """Call one enrichment tool for all entities in parallel.

    Returns (formatted_text, structured_items) where structured_items carry
    the tool_id so they can be stored in context_enrichment_sources.
    """
    tool_name = tool_config.mcp_tool_name
    tool_id = getattr(tool_config, "tool_id", tool_name)
    canonical = {
        "entity_name": "",
        "limit": _CONTEXT_ENRICHMENT_RESULTS_PER_ENTITY
    }

    async def _query_one(entity: str) -> tuple[str, list[dict[str, Any]]]:
        # map_parameters translates the canonical entity_name/limit pair
        # into this tool's own YAML-configured parameter names.
        params = tool_config.map_parameters({
            **canonical, "entity_name": entity
        })
        raw = await _call_enrichment_tool_for_entity(tool_name, params,
                                                     mcp_client)
        if raw is None:
            return "", []
        text, items = _parse_enrichment_result(raw)
        # Tag each item with entity and tool_id for citation building
        for item in items:
            item.setdefault("tool_id", tool_id)
            item.setdefault("entity", entity)
        return text, items

    # One tool call per entity, all in parallel.
    per_entity = await asyncio.gather(*[_query_one(e) for e in entities])

    text_lines: list[str] = []
    all_items: list[dict[str, Any]] = []
    for entity, (text, items) in zip(entities, per_entity):
        if text:
            text_lines.append(f"[{entity}]\n{text}")
        all_items.extend(items)

    return "\n\n".join(text_lines), all_items


async def _phase2_6_fetch_context_enrichment(
    state: WorkflowState,
    config: SearchConfig,
    mcp_client: MCPToolClient,
) -> tuple[str, list[dict[str, Any]]]:
    """Phase 2.6: fetch background context from knowledge-graph tools.

    Completely YAML-driven: only runs when the literature_review workflow
    lists tools under 'context_enrichment_tools'. Returns ("", []) when not
    configured, keeping lit review unchanged for other domains.

    Calls all configured tools × all extracted entities in parallel.
    Output text is capped to avoid bloating the synthesis prompt.

    Returns:
        (formatted_text_for_synthesis, structured_items_for_citation_index)
    """
    empty: tuple[str, list[dict[str, Any]]] = ("", [])

    # No context_enrichment_tools configured means this phase is entirely
    # skipped, keeping behavior unchanged for domains that don't use it.
    workflow = config.workflow
    if not workflow or not workflow.context_enrichment_tools:
        return empty

    tool_registry = config.tool_registry
    if not tool_registry:
        return empty

    # Entities (e.g. gene/protein names) are pulled from the research goal
    # text itself, not from any paper content, since enrichment runs
    # independently of/in parallel with paper search and content fetching.
    entities = extract_entity_names(state["research_goal"], max_entities=3)
    if not entities:
        logger.debug(
            "context enrichment: no entities extracted from research goal")
        return empty

    logger.info(
        "Phase 2.6: fetching context enrichment for entities %s via %s tool(s)",
        entities, len(workflow.context_enrichment_tools))

    tool_configs = []
    for tool_id in workflow.context_enrichment_tools:
        tc = tool_registry.get_tool(tool_id)
        if tc and tc.enabled and mcp_client.has_tool(tc.mcp_tool_name):
            # Stash the yaml tool_id for downstream citation building
            tc._yaml_tool_id = tool_id  # pylint: disable=protected-access
            tool_configs.append(tc)
        else:
            logger.debug(
                "context enrichment: tool '%s' unavailable or disabled",
                tool_id)

    if not tool_configs:
        return empty

    # Every configured tool queried for every extracted entity, all in
    # parallel; return_exceptions=True so one tool's failure doesn't drop
    # results from the others.
    tool_tasks = [
        _call_enrichment_tool_for_entities(tc, entities, mcp_client)
        for tc in tool_configs
    ]
    tool_results = await asyncio.gather(*tool_tasks, return_exceptions=True)

    sections: list[str] = []
    all_structured: list[dict[str, Any]] = []
    for tc, result in zip(tool_configs, tool_results):
        if isinstance(result, BaseException):
            logger.debug("context enrichment: %s raised %s", tc.mcp_tool_name,
                         result)
            continue
        text, items = result
        if text:
            sections.append(f"**{tc.display_name}**\n{text}")
        # Tag items with the yaml tool_id
        yaml_tool_id = getattr(tc, "_yaml_tool_id", tc.mcp_tool_name)
        for item in items:
            item["tool_id"] = yaml_tool_id
        all_structured.extend(items)

    if not sections and not all_structured:
        return empty

    # Cap the combined text injected into the synthesis prompt so
    # enrichment content (which can be large across several tools/entities)
    # cannot crowd out the paper-analysis content in the prompt budget.
    combined = "\n\n".join(sections)
    if len(combined) > _CONTEXT_ENRICHMENT_MAX_CHARS:
        combined = combined[:_CONTEXT_ENRICHMENT_MAX_CHARS] + "\n[...truncated]"

    logger.info(
        "Phase 2.6 complete: %s tool(s), %s structured items (%s chars)",
        len(sections), len(all_structured), len(combined))
    return combined, all_structured


# =============================================================================
# KG evidence section formatting (appended to synthesis after articles are
# built)
# =============================================================================


def _format_kg_section_with_keys(
    context_enrichment_sources: list[dict[str, Any]],
    paper_count: int,
) -> str:
    """Format context enrichment sources as a labeled [C*] section.

    Keys start at C{paper_count + 1}, exactly matching what
    build_reference_index will assign at generation time (papers fill
    C1..Cn first, then these entries follow). This lets the generation LLM
    see the same [C*] handles in articles_with_reasoning that appear in its
    Citation Reference List.
    """
    if not context_enrichment_sources:
        return ""
    lines = []
    for i, item in enumerate(context_enrichment_sources):
        # 1-indexed key offset by paper_count so these keys pick up exactly
        # where the paper citations ([C1]..[C{paper_count}]) leave off.
        key = f"C{paper_count + i + 1}"
        display = item.get("display", "External source")
        lines.append(f"[{key}] {display}")
    return "\n\n---\n\n## Knowledge Graph Evidence\n\n" + "\n\n".join(lines)


# =============================================================================
# Phase 3: Paper analysis
# =============================================================================


async def _analyze_single_paper(
    paper_id: str,
    metadata: dict[str, Any],
    research_goal: str,
    model_name: str,
) -> dict[str, Any] | None:
    """Analyze a single paper for gaps and opportunities."""
    try:
        year = parse_year_from_metadata(metadata)
        # Prefers fulltext, falls back to abstract, and truncates to a
        # bounded length so a single very long paper cannot blow the
        # analysis prompt's token budget.
        content = get_paper_content_for_analysis(metadata)

        prompt = get_literature_review_paper_analysis_prompt(
            research_goal=research_goal,
            title=metadata.get("title", "Unknown"),
            authors=metadata.get("authors", []),
            year=year,
            fulltext=content,
        )

        analysis = await call_llm_json(
            prompt=prompt,
            model_name=model_name,
            json_schema=LITERATURE_PAPER_ANALYSIS_SCHEMA,
            max_tokens=DEFAULT_MAX_TOKENS,
            temperature=HIGH_TEMPERATURE,
        )

        logger.debug("Analyzed paper %s: %s", paper_id,
                     metadata.get('title', 'Unknown')[:60])
        return {
            "paper_id": paper_id,
            "metadata": metadata,
            "analysis": analysis
        }

    except Exception as e:  # pylint: disable=broad-exception-caught
        # Returning None (not raising) lets _phase3_analyze_papers filter
        # this paper out and continue synthesizing from the rest.
        logger.error("Failed to analyze paper %s: %s", paper_id, e)
        return None


async def _phase3_analyze_papers(
    all_paper_metadata: dict[str, dict[str, Any]],
    state: WorkflowState,
) -> list[dict[str, Any]]:
    """Phase 3: Analyze papers with content for gaps and opportunities."""
    # Only papers with fulltext, or with a pdf_url + abstract fallback, are
    # eligible; papers with no usable content at all are silently excluded
    # from analysis (they still appear in the final `articles` list, just
    # with used_in_analysis effectively unsupported by real content).
    papers_with_content = get_papers_with_content(all_paper_metadata)

    if not papers_with_content:
        logger.error("No papers have content for analysis")
        return []

    logger.info("Phase 3: analyzing %s papers (parallel)",
                len(papers_with_content))

    # One LLM call per paper, all in parallel.
    tasks = [
        _analyze_single_paper(
            paper_id,
            metadata,
            state["research_goal"],
            state["model_name"],
        ) for paper_id, metadata in papers_with_content.items()
    ]
    results = await asyncio.gather(*tasks)

    # Filter out failed analyses
    analyses = [r for r in results if r is not None]
    logger.info("Completed %s/%s paper analyses", len(analyses),
                len(papers_with_content))

    # Debug logging
    if analyses:
        first = analyses[0]
        logger.debug("Sample analysis structure - keys: %s",
                     list(first.get('analysis', {}).keys()))

    return analyses


# =============================================================================
# Phase 4: Synthesis
# =============================================================================


async def _phase4_synthesize(
    paper_analyses: list[dict[str, Any]],
    state: WorkflowState,
    background_context: str = "",
) -> str:
    """Phase 4: Synthesize across papers to create articles_with_reasoning."""
    if not paper_analyses:
        # No analyses to synthesize from: return the failure sentinel so
        # downstream generation nodes fall back to no-literature mode
        # instead of treating an empty synthesis as valid grounding.
        logger.error("No paper analyses available for synthesis")
        return LITERATURE_REVIEW_FAILED

    logger.info("Phase 4: synthesizing across papers")

    try:
        # background_context is the (possibly empty) Phase 2.6 knowledge-
        # graph text; the synthesis prompt weaves it in alongside the
        # per-paper analyses so the LLM can ground statements in both.
        prompt = get_literature_review_synthesis_prompt(
            research_goal=state["research_goal"],
            paper_analyses=paper_analyses,
            background_context=background_context,
        )

        logger.info("Calling synthesis LLM with %s chars, %s papers",
                    len(prompt), len(paper_analyses))

        synthesis = await call_llm(
            prompt=prompt,
            model_name=state["model_name"],
            max_tokens=EXTENDED_MAX_TOKENS,
            temperature=HIGH_TEMPERATURE,
            run_id=state.get("run_id"),
            prompt_name="literature_review_synthesis",
            prompt_metadata={
                "prompt_length_chars": len(prompt),
                "papers_analyzed": len(paper_analyses),
            },
        )

        logger.info("Synthesis complete - length: %s chars", len(synthesis))
        logger.debug("Synthesis preview: %s...", synthesis[:500])

        return synthesis

    except Exception as e:  # pylint: disable=broad-exception-caught
        # Synthesis failure also degrades to the sentinel rather than
        # propagating, consistent with the empty-analyses branch above.
        logger.error("Synthesis failed: %s", e)
        return LITERATURE_REVIEW_FAILED


# =============================================================================
# Main node function
# =============================================================================


async def literature_review_node(state: WorkflowState) -> dict[str, Any]:
    """Conducts literature review using configured MCP tools with LLM analysis.

    Orchestrates the following phases:
    1. Generate search queries (MCP tool or LLM)
    2. Collect papers from configured sources
    3. Discover PDF links (for sources returning landing pages)
    4. Fetch content (for sources without fulltext)
    5. Analyze each paper for gaps/limitations
    6. Synthesize findings into articles_with_reasoning
    """
    logger.info("Starting literature review node")

    # Setup configuration
    config = _get_search_config(state)
    logger.info("Literature review config: dev_mode=%s, papers=%s",
                config.is_dev_mode, config.papers_to_read_count)

    # Check cache
    # Keyed only on research_goal, so identical goals across runs reuse the
    # full literature review output (queries, articles, and synthesis)
    # instead of re-running every phase below.
    node_cache = get_node_cache()
    cache_params = {"research_goal": state["research_goal"]}
    # dev_test_lit_tools_isolation forces cache use even when the global
    # cache is disabled, so a developer iterating on the downstream
    # lit-tools generation phase can skip re-running this expensive node
    # every time.
    force_cache = bool(state.get("dev_test_lit_tools_isolation", False))

    if force_cache:
        logger.info("Dev isolation mode: forcing literature review cache")

    cached = node_cache.get("literature_review",
                            force=force_cache,
                            **cache_params)
    if cached is not None:
        logger.info("Literature review cache hit")
        await emit_progress(state,
                            "literature_review_complete",
                            "Literature review completed (cached)",
                            0.2,
                            cached=True)
        return cached

    # Check source availability
    # Fails fast (before spending any LLM calls on query generation) if the
    # configured literature MCP tool is unreachable.
    source_available = await check_literature_source_available(
        tool_registry=config.tool_registry)
    if not source_available:
        logger.error("Literature source MCP service unavailable")
        await emit_progress(state, "literature_review_error",
                            "Literature review failed (source unavailable)",
                            0.2)
        return make_failure_result("literature source service unavailable")

    await emit_progress(state, "literature_review_start",
                        "Conducting literature review...", 0.1)

    # Initialize MCP client
    mcp_client = await get_mcp_client(tool_registry=config.tool_registry)

    # Phase 1: generate queries
    queries = await _phase1_generate_queries(state, config, mcp_client)

    # Phase 2: collect papers
    # slug ties this run's searches to the shared on-disk corpus (see
    # corpus_slug docstring) so a warm-started corpus from a prior run/
    # tool-based generation phase is reused rather than re-downloaded.
    slug = corpus_slug(state["research_goal"])

    search_errors: list[str] = []
    if config.is_multi_source:
        all_paper_metadata, paper_source_map = (
            await _phase2_collect_papers_multi_source(queries, slug, state,
                                                      config, mcp_client,
                                                      search_errors))
    else:
        all_paper_metadata, paper_source_map = (
            await _phase2_collect_papers_single_source(queries, slug, state,
                                                       config, mcp_client,
                                                       search_errors))

    # Distinguish a genuinely empty search from one where every call errored:
    # both otherwise surface as zero articles with no trace of the cause.
    if not all_paper_metadata:
        if search_errors:
            logger.error(
                "Literature review found no papers: %s of %s search call(s) "
                "errored: %s", len(search_errors), len(queries),
                "; ".join(search_errors[:5]))
            await emit_progress(
                state,
                "literature_review_error",
                "Literature search failed (no papers retrieved)",
                0.2,
                queries_count=len(queries),
                search_errors_count=len(search_errors),
                search_error_sample=search_errors[:5])
        else:
            logger.warning(
                "Literature review found no papers: all %s query/queries "
                "returned zero results (no errors)", len(queries))
            await emit_progress(state,
                                "literature_review_empty",
                                "Literature search returned no results",
                                0.2,
                                queries_count=len(queries),
                                search_errors_count=0)

    # Phase 2.4: discover PDF links
    # Mutates all_paper_metadata in place (no-op when no pdf_discovery_tool
    # is configured for any source).
    await _phase2_4_discover_pdf_links(all_paper_metadata, paper_source_map,
                                       config, mcp_client)

    # Phase 2.5 + 2.6: fetch content and context enrichment in parallel
    # These two phases are independent of each other (content fetching acts
    # on already-collected papers; enrichment queries external KG tools
    # using entities from the research goal), so running them concurrently
    # shaves wall-clock time off the node.
    content_task = _phase2_5_fetch_content(all_paper_metadata, paper_source_map,
                                           config, mcp_client, state)
    enrichment_task = _phase2_6_fetch_context_enrichment(
        state, config, mcp_client)
    _, enrichment_result = await asyncio.gather(content_task, enrichment_task)
    background_context, context_enrichment_sources = enrichment_result

    # Check fulltext availability
    with_fulltext, without_fulltext = count_papers_with_fulltext(
        all_paper_metadata)
    logger.info("Collected %s papers (%s with fulltext)",
                len(all_paper_metadata), with_fulltext)

    if without_fulltext > 0:
        logger.warning("%s papers do not have fulltexts available",
                       without_fulltext)

    # Handle edge cases
    # Zero papers collected is a hard failure (nothing to analyze or
    # synthesize from).
    if len(all_paper_metadata) == 0:
        logger.warning("No papers collected")
        await emit_progress(state, "literature_review_complete",
                            "Literature review completed (no papers found)",
                            0.2)
        return make_failure_result("no papers found", queries=queries)

    # Papers were found but none have any usable content (fulltext or
    # abstract fallback) for Phase 3 analysis. Still return the collected
    # metadata as `articles` (used_in_analysis defaults True in
    # build_article_from_metadata) so callers retain the paper list even
    # though the review itself failed.
    if with_fulltext == 0:
        logger.error(
            "No papers have fulltexts available - cannot perform analysis")
        n = len(all_paper_metadata)
        await emit_progress(
            state,
            "literature_review_complete",
            f"Literature review failed ({n} papers found but none"
            " have fulltexts)",
            0.2,
        )
        articles = build_articles_from_metadata(all_paper_metadata,
                                                config.source_name)
        return make_failure_result(
            f"{n} papers found but none have fulltexts for analysis",
            queries=queries,
            articles=articles,
        )

    # Log sample papers for debugging
    for paper_id, meta in list(all_paper_metadata.items())[:3]:
        has_ft = bool(
            meta.get("pmc_full_text_id") or meta.get("fulltext") or
            meta.get("pdf_url"))
        logger.debug("Paper %s: title='%s...' has_fulltext=%s", paper_id,
                     meta.get('title', '')[:60], has_ft)

    # Phase 3: analyze papers
    paper_analyses = await _phase3_analyze_papers(all_paper_metadata, state)

    # Phase 4: synthesize
    # Guards against calling the synthesis LLM with an empty analyses list
    # (redundant with _phase4_synthesize's own check, but avoids the
    # call/log noise entirely when Phase 3 produced nothing).
    if paper_analyses:
        synthesis = await _phase4_synthesize(paper_analyses, state,
                                             background_context)
    else:
        synthesis = LITERATURE_REVIEW_FAILED

    # Phase 5: create articles
    # Built from all_paper_metadata (not just the analyzed subset) so
    # `articles` in the returned state includes every collected paper,
    # whether or not it had content for Phase 3 analysis.
    logger.info("Phase 5: creating article objects")
    articles = build_articles_from_metadata(all_paper_metadata,
                                            config.source_name)
    logger.info("Created %s article objects", len(articles))

    # Append knowledge graph evidence with [C*] keys aligned to the reference
    # index. keys start after the analyzed papers so they match what
    # build_reference_index will assign at generation time — giving the
    # generation LLM explicit handles to cite.
    if context_enrichment_sources and synthesis != LITERATURE_REVIEW_FAILED:
        # used_paper_count must match the number of [C*] keys
        # build_reference_index will assign to papers at generation time, so
        # the KG section's keys start immediately after them.
        used_paper_count = sum(
            1 for a in articles if getattr(a, "used_in_analysis", False))
        kg_section = _format_kg_section_with_keys(context_enrichment_sources,
                                                  used_paper_count)
        if kg_section:
            synthesis = synthesis + kg_section
            logger.info(
                "Appended %s KG source(s) with [C%s...] keys to synthesis",
                len(context_enrichment_sources), used_paper_count + 1)

    # Emit completion
    await emit_progress(
        state,
        "literature_review_complete",
        "Literature review completed",
        0.2,
        queries_count=len(queries),
        articles_count=len(articles),
        search_errors_count=len(search_errors),
    )

    logger.info(
        "Literature review complete: %s articles from %s queries,"
        " %s char synthesis", len(articles), len(queries), len(synthesis))

    # Build and cache result
    # make_success_result always reports "success" even when synthesis is
    # the LITERATURE_REVIEW_FAILED sentinel (that case only reaches here via
    # the paper_analyses-empty branch above, which still returns a
    # normal-looking result dict rather than an early failure return) --
    # downstream nodes rely on checking articles_with_reasoning for the
    # sentinel rather than a top-level status field.
    result = make_success_result(synthesis, queries, articles)
    if context_enrichment_sources:
        result["context_enrichment_sources"] = context_enrichment_sources
    # Cached under the same force_cache flag used for the lookup above, so
    # a dev-isolation run that missed the cache still populates it for the
    # next call.
    node_cache.set("literature_review",
                   result,
                   force=force_cache,
                   **cache_params)

    return result
