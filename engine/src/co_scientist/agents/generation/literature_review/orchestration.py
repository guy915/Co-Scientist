"""Literature-review collection, content retrieval and phase orchestration."""

import asyncio
import dataclasses
import logging
from dataclasses import dataclass
from typing import Any, NamedTuple, cast

from co_scientist.agents.generation.literature_review.enrichment import (
    _format_kg_section_with_keys,
    _phase2_6_fetch_context_enrichment,
)
from co_scientist.agents.generation.literature_review.synthesis import (
    _phase3_analyze_papers,
    _phase4_synthesize,
)
from co_scientist.cache import NodeCache
from co_scientist.constants import (
    LITERATURE_REVIEW_FAILED,
)
from co_scientist.evidence.article_support import (
    _has_fulltext,
    build_articles_from_metadata,
    count_papers_with_fulltext,
    get_papers_with_content,
    make_failure_result,
)
from co_scientist.evidence.retrieval_support import (
    ContentToolConfig,
    build_content_config,
    build_pdf_discovery_config,
    get_papers_needing_content,
    get_papers_needing_pdf_discovery,
    parse_content_result,
    parse_pdf_discovery_result,
)
from co_scientist.evidence.search_support import (
    SearchConfig,
)
from co_scientist.mcp_client import MCPToolClient
from co_scientist.models import Article
from co_scientist.progress import emit_progress
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


async def _emit_search_errors_diagnostic(
    state: WorkflowState,
    queries: list[str],
    search_errors: list[str],
) -> None:
    """Log and report progress when every Phase 2 search call errored."""
    logger.error(
        "Literature review found no papers: %s of %s search call(s) "
        "errored: %s",
        len(search_errors),
        len(queries),
        "; ".join(search_errors[:5]),
    )
    await emit_progress(
        state,
        "literature_review_error",
        "Literature search failed (no papers retrieved)",
        0.2,
        queries_count=len(queries),
        search_errors_count=len(search_errors),
        search_error_sample=search_errors[:5],
    )


async def _emit_empty_results_diagnostic(
    state: WorkflowState,
    queries: list[str],
) -> None:
    """Log and report progress when Phase 2 search cleanly found nothing."""
    logger.warning(
        "Literature review found no papers: all %s query/queries "
        "returned zero results (no errors)",
        len(queries),
    )
    await emit_progress(
        state,
        "literature_review_empty",
        "Literature search returned no results",
        0.2,
        queries_count=len(queries),
        search_errors_count=0,
    )


async def _emit_empty_search_diagnostics(
    state: WorkflowState,
    queries: list[str],
    search_errors: list[str],
) -> None:
    """Log and report progress when Phase 2 collected zero papers.

    Distinguishes a genuinely empty search from one where every call
    errored: both otherwise surface as zero articles with no trace of the
    cause.
    """
    if search_errors:
        await _emit_search_errors_diagnostic(state, queries, search_errors)
    else:
        await _emit_empty_results_diagnostic(state, queries)


async def _handle_no_papers_found(
    state: WorkflowState,
    queries: list[str],
) -> dict[str, Any]:
    """Build the failure result when Phase 2 collected zero papers."""
    logger.warning("No papers collected")
    await emit_progress(
        state,
        "literature_review_complete",
        "Literature review completed (no papers found)",
        0.2,
    )
    return make_failure_result("no papers found", queries=queries)


async def _handle_no_fulltext_available(
    state: WorkflowState,
    all_paper_metadata: dict[str, dict[str, Any]],
    queries: list[str],
    source_name: str,
) -> dict[str, Any]:
    """Build the failure result when no collected paper has usable content.

    Papers were found but none have any usable content (fulltext or
    abstract fallback) for Phase 3 analysis. The collected metadata remains
    visible as articles, explicitly marked unused in analysis.
    """
    logger.error(
        "No papers have fulltext or abstracts available - cannot analyze"
    )
    n = len(all_paper_metadata)
    await emit_progress(
        state,
        "literature_review_complete",
        f"Literature review failed ({n} papers found but none have fulltexts)",
        0.2,
    )
    articles = build_articles_from_metadata(all_paper_metadata, source_name)
    return make_failure_result(
        f"{n} papers found but none have fulltexts for analysis",
        queries=queries,
        articles=articles,
    )


def _log_sample_papers(all_paper_metadata: dict[str, dict[str, Any]]) -> None:
    """Debug-log a small sample of collected papers before Phase 3 analysis."""
    for paper_id, meta in list(all_paper_metadata.items())[:3]:
        has_ft = _has_fulltext(meta)
        logger.debug(
            "Paper %s: title='%s...' has_fulltext=%s",
            paper_id,
            meta.get("title", "")[:60],
            has_ft,
        )


@dataclasses.dataclass
class _CollectionResult:
    """Bundled output of Phases 2 through 2.6 for the orchestrator.

    Attributes:
        all_paper_metadata: Collected paper metadata keyed by paper ID.
        paper_source_map: Maps paper ID to the source name it came from.
        search_errors: Error strings from any failed search calls.
        background_context: Context-enrichment text for Phase 4 synthesis.
        context_enrichment_sources: Raw KG source dicts for citation keys.
    """

    all_paper_metadata: dict[str, dict[str, Any]]
    paper_source_map: dict[str, str]
    search_errors: list[str]
    background_context: str
    context_enrichment_sources: list[dict[str, Any]]


def _merge_private_sources(
    state: WorkflowState,
    background_context: str,
    context_enrichment_sources: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """Prepends any per-run private-corpus sources ahead of fetched ones."""
    private_sources = state.get("context_enrichment_sources") or []
    if not private_sources:
        return background_context, context_enrichment_sources

    context_enrichment_sources = [
        *private_sources,
        *context_enrichment_sources,
    ]
    private_context = "\n\n".join(
        str(item.get("display") or "") for item in private_sources
    )
    background_context = "\n\n".join(
        part for part in (private_context, background_context) if part
    )
    return background_context, context_enrichment_sources


def _log_collection_summary(
    all_paper_metadata: dict[str, dict[str, Any]],
) -> None:
    """Logs the fulltext / no-fulltext paper counts collected this run."""
    with_fulltext, without_fulltext = count_papers_with_fulltext(
        all_paper_metadata
    )
    # One line, both halves. A paper without a fulltext is the ordinary case
    # -- most of the literature is paywalled and the review works from the
    # abstract -- so it was raised as a warning on essentially every run, and
    # a condition that is always true carries no information. The count is
    # kept because the ratio is worth reading; it just is not a problem.
    logger.info(
        "Collected %s papers (%s with fulltext, %s abstract only)",
        len(all_paper_metadata),
        with_fulltext,
        without_fulltext,
    )


async def _collect_papers_with_diagnostics(
    queries: list[str],
    state: WorkflowState,
    config: SearchConfig,
    mcp_client: MCPToolClient,
) -> tuple[dict[str, dict[str, Any]], dict[str, str], list[str]]:
    """Runs Phase 2 collection and emits diagnostics if it found nothing."""
    # Resolve the shared operation at call time, including installed patches.
    from co_scientist.evidence.search import (
        collect_papers,
    )

    search_errors: list[str] = []
    all_paper_metadata, paper_source_map = await collect_papers(
        queries, state, config, mcp_client, search_errors
    )
    if not all_paper_metadata:
        await _emit_empty_search_diagnostics(state, queries, search_errors)
    return all_paper_metadata, paper_source_map, search_errors


async def _enrich_collected_papers(
    all_paper_metadata: dict[str, dict[str, Any]],
    paper_source_map: dict[str, str],
    config: SearchConfig,
    mcp_client: MCPToolClient,
    state: WorkflowState,
) -> tuple[str, list[dict[str, Any]]]:
    """Phases 2.4-2.6: discover PDFs, fetch content/enrichment, and merge.

    Mutates all_paper_metadata in place via Phases 2.4/2.5 (a no-op when no
    relevant tool is configured for any source).

    Returns:
        (background_context, context_enrichment_sources) ready for
        synthesis, with any per-run private-corpus sources merged in.
    """
    (
        background_context,
        context_enrichment_sources,
    ) = await _fetch_content_and_enrichment(
        all_paper_metadata, paper_source_map, config, mcp_client, state
    )
    return _merge_private_sources(
        state, background_context, context_enrichment_sources
    )


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


def _count_used_papers(articles: list[Article]) -> int:
    """Count articles already flagged as used in the synthesis analysis.

    used_paper_count must match the number of [C*] keys
    build_reference_index will assign to papers at generation time, so the
    KG section's keys start immediately after them.
    """
    return sum(1 for a in articles if getattr(a, "used_in_analysis", False))


def _append_kg_evidence_section(
    synthesis: str,
    articles: list[Article],
    context_enrichment_sources: list[dict[str, Any]],
) -> str:
    """Append knowledge graph evidence with [C*] keys to the synthesis text.

    Keys start after the analyzed papers so they match what
    build_reference_index will assign at generation time, giving the
    generation LLM explicit handles to cite.
    """
    if not context_enrichment_sources or synthesis == LITERATURE_REVIEW_FAILED:
        return synthesis

    used_paper_count = _count_used_papers(articles)
    kg_section = _format_kg_section_with_keys(
        context_enrichment_sources, used_paper_count
    )
    if not kg_section:
        return synthesis

    logger.info(
        "Appended %s KG source(s) with [C%s...] keys to synthesis",
        len(context_enrichment_sources),
        used_paper_count + 1,
    )
    return synthesis + kg_section


async def _discover_then_fetch_content(
    all_paper_metadata: dict[str, dict[str, Any]],
    paper_source_map: dict[str, str],
    config: SearchConfig,
    mcp_client: MCPToolClient,
    state: WorkflowState,
) -> None:
    """Phase 2.4 then 2.5: discover PDF links, then fetch their content.

    These two are sequential on purpose: Phase 2.5 fetches from the pdf_url
    values Phase 2.4 writes into all_paper_metadata, so it has nothing to
    fetch until 2.4 has finished.
    """
    await _phase2_4_discover_pdf_links(
        all_paper_metadata, paper_source_map, config, mcp_client
    )
    await _phase2_5_fetch_content(
        all_paper_metadata, paper_source_map, config, mcp_client, state
    )


async def _fetch_content_and_enrichment(
    all_paper_metadata: dict[str, dict[str, Any]],
    paper_source_map: dict[str, str],
    config: SearchConfig,
    mcp_client: MCPToolClient,
    state: WorkflowState,
) -> tuple[str, list[dict[str, Any]]]:
    """Phases 2.4-2.6: paper retrieval and context enrichment in parallel.

    Enrichment is independent of paper collection *entirely*: it queries
    external KG tools for entities extracted from the research goal and
    reads nothing the retrieval phases write, so it starts alongside PDF
    discovery rather than queueing behind it. Running them concurrently
    shaves wall-clock time off the node, which sits on the run's serial
    spine.

    Because they are independent, they also fail independently: an
    exception out of either one is isolated rather than allowed to cancel
    the other mid-flight. Running them concurrently must not make one
    branch's fault discard the other's finished work -- retrieval's output
    is the papers it already wrote into ``all_paper_metadata``, and
    enrichment's absence is a state the synthesis already handles (it is
    the same ("", []) an unconfigured domain returns).

    Returns:
        (background_context, context_enrichment_sources) from Phase 2.6,
        or ("", []) when enrichment failed.
    """
    retrieval_task = _discover_then_fetch_content(
        all_paper_metadata, paper_source_map, config, mcp_client, state
    )
    enrichment_task = _phase2_6_fetch_context_enrichment(
        state, config, mcp_client
    )
    retrieval_result, enrichment_result = await asyncio.gather(
        retrieval_task, enrichment_task, return_exceptions=True
    )
    if isinstance(retrieval_result, BaseException):
        logger.error("Paper retrieval failed: %s", retrieval_result)
    if isinstance(enrichment_result, BaseException):
        logger.error("Context enrichment failed: %s", enrichment_result)
        return "", []
    return cast(tuple[str, list[dict[str, Any]]], enrichment_result)


@dataclass(frozen=True)
class _ReviewCachePlan:
    """Cache lookup/store plan resolved once per literature review run.

    Attributes:
        node_cache: Node cache the review result is looked up in/stored to.
        cache_params: Material inputs that key the cached result.
        force_cache: Whether dev isolation forces cache use.
    """

    node_cache: NodeCache
    cache_params: dict[str, Any]
    force_cache: bool


def _cache_result(
    result: dict[str, Any], cache_plan: _ReviewCachePlan
) -> dict[str, Any]:
    """Store the finished literature-review result under its cache key.

    Cached under the same force_cache flag used for the lookup, so a
    dev-isolation run that missed the cache still populates it for the next
    call.
    """
    cache_plan.node_cache.set(
        "literature_review",
        result,
        force=cache_plan.force_cache,
        **cache_plan.cache_params,
    )
    return result


async def _collect_and_enrich_papers(
    queries: list[str],
    state: WorkflowState,
    config: SearchConfig,
    mcp_client: MCPToolClient,
) -> _CollectionResult:
    """Phases 2 through 2.6: collect, discover PDFs, fetch content/enrichment.

    Returns:
        A _CollectionResult bundling the collected papers and enrichment
        context.
    """
    (
        all_paper_metadata,
        paper_source_map,
        search_errors,
    ) = await _collect_papers_with_diagnostics(
        queries, state, config, mcp_client
    )

    (
        background_context,
        context_enrichment_sources,
    ) = await _enrich_collected_papers(
        all_paper_metadata, paper_source_map, config, mcp_client, state
    )

    _log_collection_summary(all_paper_metadata)

    return _CollectionResult(
        all_paper_metadata=all_paper_metadata,
        paper_source_map=paper_source_map,
        search_errors=search_errors,
        background_context=background_context,
        context_enrichment_sources=context_enrichment_sources,
    )


async def _handle_collection_edge_cases(
    state: WorkflowState,
    collected: _CollectionResult,
    queries: list[str],
    config: SearchConfig,
) -> dict[str, Any] | None:
    """Builds an early failure result if collection yielded nothing usable.

    Zero papers collected is a hard failure (nothing to analyze or
    synthesize from); papers with neither fulltext nor abstracts also fail
    Phase 3, though their metadata remains visible.

    Returns:
        A failure result dict if either edge case applies, else None to
        continue to analysis.
    """
    if len(collected.all_paper_metadata) == 0:
        return await _handle_no_papers_found(state, queries)

    if not get_papers_with_content(collected.all_paper_metadata):
        return await _handle_no_fulltext_available(
            state, collected.all_paper_metadata, queries, config.source_name
        )

    return None


class _ReviewSynthesis(NamedTuple):
    """Phases 3 and 4 together: what was read, and what it amounts to.

    ``analyses`` travels with the synthesis because Phase 6 seeds its
    research from the gaps the papers themselves stated, and those are
    recorded here and nowhere else.

    Attributes:
        text: The synthesis, or the LITERATURE_REVIEW_FAILED sentinel.
        llm_calls: Real calls spent, a floor rather than an exact total.
        analyses: One entry per successfully analyzed paper.
    """

    text: str
    llm_calls: int
    analyses: list[dict[str, Any]]


async def _analyze_and_synthesize(
    all_paper_metadata: dict[str, dict[str, Any]],
    state: WorkflowState,
    background_context: str,
) -> _ReviewSynthesis:
    """Phase 3 + 4: analyze papers for gaps/limitations, then synthesize.

    Guards against calling the synthesis LLM with an empty analyses list
    (redundant with _phase4_synthesize's own check, but avoids the
    call/log noise entirely when Phase 3 produced nothing).

    Returns:
        The synthesis, the call count, and the analyses it was built
        from (see :class:`_ReviewSynthesis`). synthesis is the
        LITERATURE_REVIEW_FAILED sentinel if Phase 3 produced no analyses.
        llm_call_count is one real call per successfully-analyzed paper
        (Phase 3 filters out failed attempts, so this is a floor, not an
        exact total -- the same convention other nodes use for a call
        count that is real but not exhaustive) plus one for the synthesis
        call when Phase 3 produced anything to synthesize (finding L3 --
        literature review previously reported no llm_calls at all).
    """
    paper_analyses = await _phase3_analyze_papers(all_paper_metadata, state)
    if not paper_analyses:
        return _ReviewSynthesis(LITERATURE_REVIEW_FAILED, 0, [])
    synthesis = await _phase4_synthesize(
        paper_analyses, state, background_context
    )
    return _ReviewSynthesis(synthesis, len(paper_analyses) + 1, paper_analyses)


def _finalize_synthesis_and_articles(
    synthesis: str,
    all_paper_metadata: dict[str, dict[str, Any]],
    context_enrichment_sources: list[dict[str, Any]],
    source_name: str,
) -> tuple[str, list[Article]]:
    """Phase 5: builds article objects and appends KG evidence to synthesis.

    Built from all_paper_metadata (not just the analyzed subset) so
    `articles` in the returned state includes every collected paper,
    whether or not it had content for Phase 3 analysis. KG evidence keys
    are appended aligned to the reference index (see
    _append_kg_evidence_section for why the keys line up).

    Returns:
        The (synthesis, articles) pair to return from the node.
    """
    logger.info("Phase 5: creating article objects")
    articles = build_articles_from_metadata(all_paper_metadata, source_name)
    logger.info("Created %s article objects", len(articles))

    synthesis = _append_kg_evidence_section(
        synthesis, articles, context_enrichment_sources
    )
    return synthesis, articles


async def _emit_and_log_completion(
    state: WorkflowState,
    queries: list[str],
    articles: list[Article],
    search_errors: list[str],
    synthesis: str,
) -> None:
    """Emits the completion progress event and logs the final summary."""
    await emit_progress(
        state,
        "literature_review_complete",
        "Literature review completed",
        0.2,
        queries_count=len(queries),
        articles_count=len(articles),
        articles_analyzed=_count_used_papers(articles),
        fulltext_analyzed=sum(
            bool(article.used_in_analysis and article.content)
            for article in articles
        ),
        abstract_only_analyzed=sum(
            bool(
                article.used_in_analysis
                and not article.content
                and article.abstract
            )
            for article in articles
        ),
        search_errors_count=len(search_errors),
    )

    logger.info(
        "Literature review complete: %s articles from %s queries,"
        " %s char synthesis",
        len(articles),
        len(queries),
        len(synthesis),
    )
