"""Failure handling and diagnostics for the literature review node.

Each helper covers one self-contained diagnostic side effect or early-exit
failure result of ``literature_review_node``: exception description for logs,
empty-search diagnostics, and the no-papers / no-fulltext failure results.
"""

import logging
from typing import Any

from co_scientist.agents.generation.literature_review.helpers import (
    build_articles_from_metadata,
    make_failure_result,
)
from co_scientist.nodes.progress import emit_progress
from co_scientist.state import WorkflowState

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
    return (
        f"{type(current).__name__}: {message}"
        if message
        else type(current).__name__
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
    else:
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
        has_ft = bool(
            meta.get("pmc_full_text_id")
            or meta.get("fulltext")
            or meta.get("pdf_url")
        )
        logger.debug(
            "Paper %s: title='%s...' has_fulltext=%s",
            paper_id,
            meta.get("title", "")[:60],
            has_ft,
        )
