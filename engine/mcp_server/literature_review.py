"""PubMed document source with fulltext download from PMC."""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mcp_server.entrez import initialize_entrez as initialize_entrez
from mcp_server.fulltext_download import _symlink_into_run as _symlink_into_run
from mcp_server.pubmed_client import _extract_doi as _extract_doi
from mcp_server.pubmed_client import _parse_authors as _parse_authors
from mcp_server.shared_pool import (
    _load_shared_pool_candidate as _load_shared_pool_candidate,
)
from mcp_server.shared_pool import (
    _scan_shared_pool_candidates as _scan_shared_pool_candidates,
)
from mcp_server.shared_pool import (
    _shared_pool_paper_year as _shared_pool_paper_year,
)
from mcp_server.shared_pool import _SharedPoolMixin

if TYPE_CHECKING:
    # asyncio is imported lazily inside the async methods below (see their
    # bodies); this type-checking-only import binds the name for the quoted
    # ``asyncio.Semaphore`` annotations without pulling asyncio in at runtime.
    import asyncio

logger = logging.getLogger(__name__)


class PubmedSource(_SharedPoolMixin):
    """PubMed document source with fulltext download from PMC."""

    async def _search_and_collect_metadata(
        self,
        query: str,
        max_papers: int,
        recency_years: int,
        shared_dir: Path,
        run_dir: Path | None,
        semaphore: "asyncio.Semaphore",
    ) -> dict[str, Any]:
        """Searches PubMed and fetches metadata for a buffer of candidates.

        Requests 3x the target paper count to account for ~33% fulltext
        availability - the buffer is filtered down to max_papers with
        fulltext by the caller.

        Args:
            query: PubMed boolean query.
            max_papers: Target number of papers WITH fulltext to collect.
            recency_years: Filter to papers from last N years (0 = no filter).
            shared_dir: Shared-pool directory holding cached metadata files.
            run_dir: Per-run directory to symlink cache hits and fresh
                fetches into, or None if no run tracking is requested.
            semaphore: Concurrency limiter, shared with the fulltext
                download phase.

        Returns:
            Dict mapping paper_id to metadata for every paper fetched
            successfully, most-recent-first.
        """
        search_buffer = max_papers * 3
        logger.info(
            "Requesting %s papers from PubMed to find %s with fulltext",
            search_buffer,
            max_papers,
        )
        paper_ids = self.pubmed_search_ids(
            query, retmax=search_buffer, recency_years=recency_years
        )
        return await self._gather_paper_metadata(
            paper_ids, shared_dir, run_dir, semaphore
        )

    def _select_fulltext_papers(
        self, all_details: dict[str, Any], max_papers: int
    ) -> tuple[list[str], int]:
        """Filters fetched papers down to the target count with fulltext.

        Args:
            all_details: Metadata dict keyed by paper_id, most-recent-first
                (preserved from the search results).
            max_papers: Target number of papers WITH fulltext to select.

        Returns:
            A (papers_to_use, fulltext_shortfall) tuple: the selected paper
            IDs (most recent first, up to max_papers), and how many more
            papers are needed to reach max_papers (<=0 if already met).
        """
        # Filter to papers with PMC IDs and take first max_papers (most
        # recent, thanks to sort). asyncio.gather preserves input order
        # regardless of completion order, and dicts preserve insertion
        # order, so all_details still iterates in the same
        # most-recent-first order as paper_ids.
        papers_with_pmc = [
            paper_id
            for paper_id in all_details
            if all_details[paper_id].get("pmc_full_text_id") is not None
        ]
        papers_to_use = papers_with_pmc[:max_papers]

        logger.info(
            "fulltext availability: %s/%s papers have PMC fulltexts",
            len(papers_with_pmc),
            len(all_details),
        )
        logger.info(
            "selecting %s/%s papers with fulltext (target: %s)",
            len(papers_to_use),
            len(papers_with_pmc),
            max_papers,
        )

        fulltext_shortfall = max_papers - len(papers_to_use)
        if fulltext_shortfall > 0:
            logger.warning(
                "Short of target by %s papers - will attempt shared pool "
                "supplement",
                fulltext_shortfall,
            )
        if len(papers_to_use) == 0:
            logger.error(
                "No papers have PMC fulltexts - (no documents to analyze)"
            )

        return papers_to_use, fulltext_shortfall

    def _assemble_final_results(
        self,
        papers_to_use: list[str],
        all_details: dict[str, Any],
        max_papers: int,
    ) -> dict[str, Any]:
        """Builds the final paper_id-to-metadata mapping to return.

        Args:
            papers_to_use: Paper IDs selected for this run's final result
                set.
            all_details: Metadata dict keyed by paper_id.
            max_papers: Target number of papers WITH fulltext, used only for
                the summary log line.

        Returns:
            Dict mapping paper_id to metadata for papers with fulltext.
        """
        final_details = {
            paper_id: all_details[paper_id] for paper_id in papers_to_use
        }
        logger.info(
            "Returning %s papers with fulltext (target was %s)",
            len(final_details),
            max_papers,
        )
        return final_details

    async def _download_and_record(
        self,
        papers_to_use: list[str],
        all_details: dict[str, Any],
        slug: str,
        run_id: str | None,
        run_dir: Path | None,
        shared_dir: Path,
        fulltext_shortfall: int,
        max_papers: int,
        query: str,
        semaphore: "asyncio.Semaphore",
    ) -> None:
        """Downloads fulltexts, tops up shortfalls, and records the run.

        Args:
            papers_to_use: Paper IDs selected for this run so far; mutated
                in place with any shared-pool supplements.
            all_details: Metadata dict keyed by paper_id; mutated in place
                with any shared-pool supplements' metadata.
            slug: Identifier for organizing results.
            run_id: Unique run identifier for this execution, or None to
                skip per-run tracking.
            run_dir: Per-run directory to symlink into, or None if run_id
                was not provided.
            shared_dir: Shared-pool directory to scan when supplementing.
            fulltext_shortfall: Number of additional papers needed to reach
                max_papers.
            max_papers: Target number of papers WITH fulltext.
            query: Original PubMed boolean query, recorded in the manifest.
            semaphore: Concurrency limiter, shared with the metadata fetch
                phase.
        """
        await self._download_fulltexts_for_papers(
            papers_to_use, all_details, slug, run_id, semaphore
        )

        # If short of target, supplement from shared pool. Requires run_dir
        # because supplementing only makes sense when building a per-run
        # view (symlinks below need somewhere to go); without a run_id
        # there is no per-run result set to top up.
        if fulltext_shortfall > 0 and run_dir:
            self._supplement_from_shared_pool(
                shared_dir,
                run_dir,
                papers_to_use,
                all_details,
                fulltext_shortfall,
                max_papers,
            )

        if run_id and run_dir:
            self._save_run_manifest(
                run_id, run_dir, papers_to_use, all_details, query
            )

    async def pubmed_search(
        self,
        query: str,
        slug: str,
        max_papers: int = 10,
        recency_years: int = 0,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Searches PubMed and downloads fulltext HTML from PMC.

        HTML-only implementation - no PDF fallback.

        Uses shared pool architecture:
        - Papers stored in slug/shared/ (accumulated across runs)
        - Per-run view in slug/runs/{run_id}/ (symlinks to shared)

        Target fulltext strategy:
        - Requests 3x the target number of papers to account for missing
          fulltexts
        - Processes in order (most recent first) until reaching max_papers
          WITH fulltext
        - If PubMed is exhausted, supplements from shared pool
        - Returns ONLY papers with fulltext

        Args:
            query: PubMed boolean query.
            slug: Identifier for organizing results (research goal hash).
            max_papers: Target number of papers WITH fulltext to collect.
            recency_years: Filter to papers from last N years (0 = no filter).
            run_id: Unique run identifier for this execution (enables per-run
                tracking).

        Returns:
            Dict mapping paper_id to metadata for papers with fulltext.
        """
        # Imported locally so importing this module does not require an
        # event loop / asyncio setup unless this async method is actually
        # called.
        import asyncio

        shared_dir, run_dir = self._prepare_run_directories(slug, run_id)

        # Semaphore to limit concurrent entrez API calls (respect rate limits)
        # allow 3 concurrent (conservative, can increase to 10 with API key)
        semaphore = asyncio.Semaphore(3)

        all_details = await self._search_and_collect_metadata(
            query, max_papers, recency_years, shared_dir, run_dir, semaphore
        )
        papers_to_use, fulltext_shortfall = self._select_fulltext_papers(
            all_details, max_papers
        )

        await self._download_and_record(
            papers_to_use,
            all_details,
            slug,
            run_id,
            run_dir,
            shared_dir,
            fulltext_shortfall,
            max_papers,
            query,
            semaphore,
        )

        return self._assemble_final_results(
            papers_to_use, all_details, max_papers
        )
