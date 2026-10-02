"""Phase 2 paper-collection group for the literature review orchestrator.

Bundles the collection result shape, private-corpus merging, collection
logging, and the two diagnostics-wrapped entry points
(``_collect_papers_with_diagnostics`` for Phase 2 search,
``_enrich_collected_papers`` for Phases 2.4-2.6 retrieval/enrichment)
that ``orchestration.py``'s ``_collect_and_enrich_papers`` composes into
one call. Split out of ``orchestration.py`` to keep that module under
the file-length ceiling; ``orchestration.py`` re-exports every name
defined here for compatibility.

Search collection calls the shared ``co_scientist.evidence.collection``
boundary. Content/enrichment still imports its orchestration helper locally:
that helper composes agent-specific work and imports this module itself.
The deferred imports also resolve each collaborator at call time, so a test
patches the module that owns it.

"""

import dataclasses
import logging
from typing import Any

from co_scientist.agents.generation.literature_review.outcomes import (
    _emit_empty_search_diagnostics,
)
from co_scientist.evidence.article_support import (
    count_papers_with_fulltext,
)
from co_scientist.evidence.search_support import (
    SearchConfig,
)
from co_scientist.mcp_client import MCPToolClient
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


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
    from co_scientist.evidence.collection import (
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
