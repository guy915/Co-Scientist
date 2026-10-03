"""Collect papers, merge private evidence, and report retrieval outcomes."""

import dataclasses
import logging
from typing import Any

from co_scientist.evidence.article_support import (
    _has_fulltext,
    build_articles_from_metadata,
    count_papers_with_fulltext,
    make_failure_result,
)
from co_scientist.evidence.search_support import (
    SearchConfig,
)
from co_scientist.mcp_client import MCPToolClient
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
    # Imported here, not at module load time -- see the module docstring
    # for why a top-level import would cycle with orchestration.py.
    from co_scientist.agents.generation.literature_review.orchestration import (
        _fetch_content_and_enrichment,
    )

    (
        background_context,
        context_enrichment_sources,
    ) = await _fetch_content_and_enrichment(
        all_paper_metadata, paper_source_map, config, mcp_client, state
    )
    return _merge_private_sources(
        state, background_context, context_enrichment_sources
    )
