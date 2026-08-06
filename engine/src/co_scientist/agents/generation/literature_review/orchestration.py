"""Phase orchestration helpers for the literature review node.

Each helper wraps one self-contained step of ``literature_review_node``'s
phase sequence - paper collection and enrichment (Phases 2-2.6), collection
edge-case handling, analysis and synthesis (Phases 3-4), article/KG-evidence
finalization (Phase 5), and result caching - factored out purely to keep the
orchestrator's phase sequence readable.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, cast

from co_scientist.agents.generation.literature_review.analysis import (
    _phase3_analyze_papers,
)
from co_scientist.agents.generation.literature_review.content import (
    _phase2_4_discover_pdf_links,
    _phase2_5_fetch_content,
)
from co_scientist.agents.generation.literature_review.enrichment import (
    _format_kg_section_with_keys,
    _phase2_6_fetch_context_enrichment,
)
from co_scientist.agents.generation.literature_review.helpers import (
    SearchConfig,
    build_articles_from_metadata,
    count_papers_with_fulltext,
    get_papers_with_content,
    make_success_result,
)
from co_scientist.agents.generation.literature_review.outcomes import (
    _emit_empty_search_diagnostics,
    _handle_no_fulltext_available,
    _handle_no_papers_found,
)
from co_scientist.agents.generation.literature_review.search import (
    _phase2_collect_papers_multi_source,
    _phase2_collect_papers_single_source,
    _SearchRunContext,
)
from co_scientist.agents.generation.literature_review.synthesis import (
    _phase4_synthesize,
)
from co_scientist.cache import NodeCache
from co_scientist.constants import (
    LITERATURE_REVIEW_FAILED,
    corpus_slug,
)
from co_scientist.mcp_client import MCPToolClient
from co_scientist.models import Article
from co_scientist.progress import emit_progress
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


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


async def _phase2_collect_papers(
    queries: list[str],
    state: WorkflowState,
    config: SearchConfig,
    mcp_client: MCPToolClient,
    search_errors: list[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Phase 2: collect papers from configured sources.

    Dispatches to the multi-source or single-source collection path based on
    config.is_multi_source. The slug ties this run's searches to the shared
    on-disk corpus so a warm-started corpus from a prior run/tool-based
    generation phase is reused rather than re-downloaded.
    """
    ctx = _SearchRunContext(
        slug=corpus_slug(state["research_goal"]),
        run_id=state["run_id"],
        mcp_client=mcp_client,
        errors=search_errors,
    )

    if config.is_multi_source:
        return await _phase2_collect_papers_multi_source(queries, config, ctx)
    return await _phase2_collect_papers_single_source(queries, config, ctx)


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


def _build_and_cache_result(
    synthesis: str,
    queries: list[str],
    articles: list[Article],
    context_enrichment_sources: list[dict[str, Any]],
    cache_plan: _ReviewCachePlan,
) -> dict[str, Any]:
    """Build the success result dict and populate the node cache with it.

    make_success_result always reports "success" even when synthesis is the
    LITERATURE_REVIEW_FAILED sentinel (that case only reaches here via the
    paper_analyses-empty branch, which still returns a normal-looking result
    dict rather than an early failure return) - downstream nodes rely on
    checking articles_with_reasoning for the sentinel rather than a
    top-level status field.

    Cached under the same force_cache flag used for the lookup, so a
    dev-isolation run that missed the cache still populates it for the next
    call.
    """
    result = make_success_result(synthesis, queries, articles)
    if context_enrichment_sources:
        result["context_enrichment_sources"] = context_enrichment_sources
    cache_plan.node_cache.set(
        "literature_review",
        result,
        force=cache_plan.force_cache,
        **cache_plan.cache_params,
    )
    return result


@dataclass
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
    search_errors: list[str] = []
    all_paper_metadata, paper_source_map = await _phase2_collect_papers(
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


async def _analyze_and_synthesize(
    all_paper_metadata: dict[str, dict[str, Any]],
    state: WorkflowState,
    background_context: str,
) -> str:
    """Phase 3 + 4: analyze papers for gaps/limitations, then synthesize.

    Guards against calling the synthesis LLM with an empty analyses list
    (redundant with _phase4_synthesize's own check, but avoids the
    call/log noise entirely when Phase 3 produced nothing).

    Returns:
        The synthesis text, or the LITERATURE_REVIEW_FAILED sentinel if
        Phase 3 produced no analyses.
    """
    paper_analyses = await _phase3_analyze_papers(all_paper_metadata, state)
    if not paper_analyses:
        return LITERATURE_REVIEW_FAILED
    return await _phase4_synthesize(paper_analyses, state, background_context)


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
