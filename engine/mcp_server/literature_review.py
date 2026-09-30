"""PubMed document source with fulltext download from PMC."""

import dataclasses
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mcp_server.entrez import initialize_entrez as initialize_entrez
from mcp_server.entrez_rate_limit import pilot_trace_context
from mcp_server.fulltext_download import _symlink_into_run as _symlink_into_run
from mcp_server.pubmed_client import _extract_doi as _extract_doi
from mcp_server.pubmed_client import _parse_authors as _parse_authors
from mcp_server.pubmed_pilot_trace import new_pilot_trace as _new_pilot_trace
from mcp_server.pubmed_pilot_trace import (
    record_fetched_papers as _record_fetched_papers,
)
from mcp_server.pubmed_pilot_trace import (
    record_pool_snapshot as _record_pool_snapshot,
)
from mcp_server.pubmed_pilot_trace import (
    reserve_trace_run as _reserve_trace_run,
)
from mcp_server.pubmed_pilot_trace import (
    write_trace_atomically as _write_trace_atomically,
)
from mcp_server.shared_pool import (
    _load_shared_pool_candidate as _load_shared_pool_candidate,
)
from mcp_server.shared_pool import _PoolDirs, _SharedPoolMixin
from mcp_server.shared_pool import (
    _scan_shared_pool_candidates as _scan_shared_pool_candidates,
)
from mcp_server.shared_pool import (
    _shared_pool_paper_year as _shared_pool_paper_year,
)

if TYPE_CHECKING:
    # asyncio is imported lazily inside the async methods below (see their
    # bodies); this type-checking-only import binds the name for the quoted
    # ``asyncio.Semaphore`` annotations without pulling asyncio in at runtime.
    import asyncio

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class _PubmedRun:
    """Static filesystem and concurrency context for one search run.

    Attributes:
        query: PubMed boolean query for this run.
        slug: Identifier for organizing results (research goal hash).
        max_papers: Target number of papers WITH fulltext to collect.
        run_id: Unique run identifier, or None to skip per-run tracking.
        run_dir: Per-run directory to symlink into, or None.
        shared_dir: Shared-pool directory holding accumulated papers.
        semaphore: Concurrency limiter bounding entrez API calls.
        trace: Bounded pilot provenance, when explicitly enabled.
    """

    query: str
    slug: str
    max_papers: int
    run_id: str | None
    run_dir: Path | None
    shared_dir: Path
    semaphore: "asyncio.Semaphore"
    trace: dict[str, Any] | None


class PubmedSource(_SharedPoolMixin):
    """PubMed document source with fulltext download from PMC."""

    async def _search_and_collect_metadata(
        self,
        query: str,
        max_papers: int,
        recency_years: int,
        run: "_PubmedRun",
    ) -> dict[str, Any]:
        """Searches PubMed and fetches metadata for a buffer of candidates.

        Requests 3x the target paper count to cover ~33% fulltext
        availability; the buffer is filtered to max_papers by the caller.

        Args:
            query: PubMed boolean query.
            max_papers: Target number of papers WITH fulltext to collect.
            recency_years: Filter to papers from last N years (0 = no filter).
            run: Filesystem and concurrency context for this search run.

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
        with pilot_trace_context(run.trace):
            paper_ids = self.pubmed_search_ids(
                query,
                retmax=search_buffer,
                recency_years=recency_years,
                trace=run.trace,
            )
            all_details = await self._gather_paper_metadata(
                paper_ids, run.shared_dir, run.run_dir, run.semaphore
            )
        if run.trace is not None:
            _record_fetched_papers(run.trace, all_details)
        return all_details

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
        fulltext_shortfall = max_papers - len(papers_to_use)
        self._log_fulltext_selection(
            papers_with_pmc,
            papers_to_use,
            all_details,
            max_papers,
            fulltext_shortfall,
        )
        return papers_to_use, fulltext_shortfall

    def _log_fulltext_selection(
        self,
        papers_with_pmc: list[str],
        papers_to_use: list[str],
        all_details: dict[str, Any],
        max_papers: int,
        fulltext_shortfall: int,
    ) -> None:
        """Logs fulltext availability and any shortfall against target.

        Args:
            papers_with_pmc: Paper IDs that have a PMC fulltext.
            papers_to_use: Paper IDs selected, capped at max_papers.
            all_details: Metadata keyed by paper_id.
            max_papers: Target number of papers WITH fulltext.
            fulltext_shortfall: Papers still needed to reach max_papers.
        """
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

    def _assemble_final_results(
        self,
        papers_to_use: list[str],
        all_details: dict[str, Any],
        max_papers: int,
    ) -> dict[str, Any]:
        """Builds the final paper_id-to-metadata mapping to return.

        Args:
            papers_to_use: Paper IDs with downloaded PMC full text.
            all_details: Metadata dict keyed by paper_id.
            max_papers: Target number of papers in the evidence corpus.

        Returns:
            Dict mapping paper_id to metadata, preferring full text and
            filling any shortfall with ranked abstract-only records.
        """
        selected_ids = list(dict.fromkeys(papers_to_use))
        selected_ids.extend(
            paper_id for paper_id in all_details if paper_id not in selected_ids
        )
        selected_ids = selected_ids[:max_papers]
        final_details = {
            paper_id: all_details[paper_id] for paper_id in selected_ids
        }
        fulltext_count = sum(
            bool(metadata.get("fulltext"))
            for metadata in final_details.values()
        )
        logger.info(
            "Returning %s papers (%s with fulltext; target was %s)",
            len(final_details),
            fulltext_count,
            max_papers,
        )
        return final_details

    async def _download_and_record(
        self,
        run: _PubmedRun,
        papers_to_use: list[str],
        all_details: dict[str, Any],
        fulltext_shortfall: int,
    ) -> None:
        """Downloads fulltexts, tops up shortfalls, and records the run.

        Args:
            run: Filesystem and concurrency context for this search run.
            papers_to_use: Selected paper IDs; mutated with supplements.
            all_details: Metadata keyed by paper_id; mutated with supplements.
            fulltext_shortfall: Additional papers needed to reach max_papers.
        """
        await self._download_fulltexts_for_papers(
            papers_to_use, all_details, run.slug, run.run_id, run.semaphore
        )
        self._maybe_supplement_from_pool(
            run, papers_to_use, all_details, fulltext_shortfall
        )
        if run.run_id and run.run_dir:
            self._save_run_manifest(
                run.run_id, run.run_dir, papers_to_use, all_details, run.query
            )

    def _maybe_supplement_from_pool(
        self,
        run: _PubmedRun,
        papers_to_use: list[str],
        all_details: dict[str, Any],
        fulltext_shortfall: int,
    ) -> None:
        """Tops up the result set from the shared pool when short of target.

        Supplementing only makes sense when building a per-run view, so it
        is skipped without a run_dir: the symlinks it creates need a per-run
        destination, and without a run_id there is no result set to top up.

        Args:
            run: Filesystem and concurrency context for this search run.
            papers_to_use: Selected paper IDs; mutated in place.
            all_details: Metadata keyed by paper_id; mutated in place.
            fulltext_shortfall: Additional papers needed to reach max_papers.
        """
        if fulltext_shortfall > 0 and run.run_dir:
            self._supplement_from_shared_pool(
                _PoolDirs(
                    shared_dir=run.shared_dir,
                    run_dir=run.run_dir,
                    trace=run.trace,
                ),
                papers_to_use,
                all_details,
                fulltext_shortfall,
                run.max_papers,
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
        - Returns fulltext papers first, then ranked abstract-only papers to
          fill the requested corpus size

        Args:
            query: PubMed boolean query.
            slug: Identifier for organizing results (research goal hash).
            max_papers: Target number of papers WITH fulltext to collect.
            recency_years: Filter to papers from last N years (0 = no filter).
            run_id: Unique run identifier for this execution (enables per-run
                tracking).

        Returns:
            Dict mapping paper_id to metadata, with fulltext where available.
        """
        return await self._pubmed_search_impl(
            query, slug, max_papers, recency_years, run_id
        )

    async def _pubmed_search_impl(
        self,
        query: str,
        slug: str,
        max_papers: int,
        recency_years: int,
        run_id: str | None,
    ) -> dict[str, Any]:
        """Runs the full PubMed search, download, and assembly pipeline.

        Args:
            query: PubMed boolean query.
            slug: Identifier for organizing results (research goal hash).
            max_papers: Target number of papers WITH fulltext to collect.
            recency_years: Filter to papers from last N years (0 = no filter).
            run_id: Unique run identifier, or None to skip per-run tracking.

        Returns:
            Dict mapping paper_id to metadata, with fulltext where available.
        """
        run = self._build_run(query, slug, max_papers, run_id)
        with pilot_trace_context(run.trace):
            try:
                all_details = await self._search_and_collect_metadata(
                    query, max_papers, recency_years, run
                )
                papers_to_use, fulltext_shortfall = (
                    self._select_fulltext_papers(all_details, max_papers)
                )
                await self._download_and_record(
                    run, papers_to_use, all_details, fulltext_shortfall
                )
                if run.trace is not None:
                    _record_fetched_papers(run.trace, all_details)
                final_results = self._assemble_final_results(
                    papers_to_use, all_details, max_papers
                )
            except Exception as exc:
                self._write_pilot_error_trace(run, exc)
                raise
        if run.trace is not None:
            run.trace["outcome"] = "nonempty" if final_results else "empty"
        self._write_pilot_trace(run, final_results)
        return final_results

    def _write_pilot_error_trace(self, run: _PubmedRun, exc: Exception) -> None:
        if run.trace is None:
            return
        if run.trace.get("error") is None:
            run.trace["error"] = {
                "stage": "retrieval_pipeline",
                "type": type(exc).__name__,
            }
        run.trace["outcome"] = "error"
        try:
            self._write_pilot_trace(run, {})
        except Exception:
            logger.exception("Failed to write PubMed pilot error trace")

    def _write_pilot_trace(
        self, run: _PubmedRun, final_results: dict[str, Any]
    ) -> None:
        if run.trace is None or run.run_dir is None:
            return
        run.trace["final_ids"] = list(final_results)[:3]
        _write_trace_atomically(run.run_dir / ".search-trace.json", run.trace)

    def _build_run(
        self, query: str, slug: str, max_papers: int, run_id: str | None
    ) -> _PubmedRun:
        """Prepares run directories and assembles the run context.

        The entrez semaphore allows 3 concurrent calls (conservative; can
        rise to 10 with an API key).

        Args:
            query: PubMed boolean query.
            slug: Identifier for organizing results (research goal hash).
            max_papers: Target number of papers WITH fulltext to collect.
            run_id: Unique run identifier, or None to skip per-run tracking.

        Returns:
            A _PubmedRun bundling the filesystem context and semaphore.
        """
        # Imported locally so importing this module does not require an
        # event loop / asyncio setup unless this async path is actually run.
        import asyncio

        trace = _new_pilot_trace(run_id)
        shared_dir, run_dir = self._prepare_run_directories(slug, run_id)
        if trace is not None and run_dir is not None and run_id is not None:
            _reserve_trace_run(run_dir, run_id, trace["server_build_id"])
        _record_pool_snapshot(trace, shared_dir)
        return _PubmedRun(
            query,
            slug,
            max_papers,
            run_id,
            run_dir,
            shared_dir,
            asyncio.Semaphore(3),
            trace,
        )
