"""Shared-pool metadata gathering, supplementation, and run manifests."""

import json
import logging
import os
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mcp_server.entrez_rate_limit import (
    pilot_trace_context,
    record_pilot_fetch_error,
    record_pilot_metadata_origin,
)
from mcp_server.fulltext_download import _FulltextMixin, _symlink_into_run
from mcp_server.pubmed_client import (
    PUBMED_METADATA_BATCH_ENV,
    _write_metadata_cache_file,
)

if TYPE_CHECKING:
    # asyncio is imported lazily inside the async methods below (see their
    # bodies); this type-checking-only import binds the name for the quoted
    # ``asyncio.Semaphore`` annotations without pulling asyncio in at runtime.
    import asyncio

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _PoolDirs:
    """The two directories a supplementation pass reads and writes.

    Attributes:
        shared_dir: Shared-pool directory holding accumulated papers.
        run_dir: Per-run directory the supplemented papers link into.
        trace: Optional pilot provenance for actual supplement selections.
    """

    shared_dir: Path
    run_dir: Path
    trace: dict[str, Any] | None = None


def _record_pool_supplements(
    trace: dict[str, Any] | None,
    papers_to_supplement: list[tuple[str, dict[str, Any]]],
) -> None:
    if trace is None:
        return
    attempted_ids = {
        paper_id
        for attempt in trace.get("attempts", [])
        for paper_id in attempt.get("first_ids", [])
    }
    records = trace.setdefault("shared_pool_supplements", [])
    for paper_id, _metadata in papers_to_supplement:
        if len(records) >= 9:
            break
        # Supplements are selected from the shared pool's already-cached
        # fulltext files before this run's download phase, so their origin is
        # known without retaining an unbounded snapshot of every cached PMID.
        preexisting = True
        matched_esearch = paper_id in attempted_ids
        records.append(
            {
                "pmid": paper_id,
                "source": "shared_pool",
                "origin": "prior_pool",
                "preexisting": preexisting,
                "matched_esearch_first_ids": matched_esearch,
            }
        )


def _load_shared_pool_candidate(
    metadata_file: Path, shared_dir: Path, paper_id: str
) -> tuple[str, dict[str, Any]] | None:
    """Loads one shared-pool metadata file and checks it has fulltext.

    Args:
        metadata_file: The ``*.metadata.json`` file to load.
        shared_dir: Shared-pool directory holding fulltext files.
        paper_id: The paper id derived from ``metadata_file``'s name.

    Returns:
        A (paper_id, metadata) tuple if the paper has PMC fulltext already
        downloaded to the shared pool. Only papers already downloaded
        qualify here; this supplement path deliberately avoids issuing new
        PMC downloads for a shortfall. Returns None if there is no
        fulltext yet, or if the metadata file is corrupt/partial (logged
        at debug level rather than aborting the whole scan).
    """
    try:
        with open(metadata_file, encoding="utf-8") as f:
            metadata = json.load(f)
        if not metadata.get("pmc_full_text_id"):
            return None
        pmc_id = metadata["pmc_full_text_id"]
        fulltext_file = shared_dir / f"{pmc_id}.fulltext.html"
        if not fulltext_file.exists():
            return None
        return (paper_id, metadata)
    except Exception as e:
        logger.debug("Failed to read shared pool paper %s: %s", paper_id, e)
        return None


def _scan_shared_pool_candidates(
    shared_dir: Path, current_paper_ids_set: set[str]
) -> list[tuple[str, dict[str, Any]]]:
    """Scans the shared pool for downloaded papers not already in this run.

    Args:
        shared_dir: Shared-pool directory to scan for candidate papers.
        current_paper_ids_set: Paper ids already selected for this run.

    Returns:
        (paper_id, metadata) tuples for shared-pool papers that have PMC
        fulltext already downloaded and are not in the current run yet.
    """
    supplement_candidates = []
    for metadata_file in shared_dir.glob("*.metadata.json"):
        paper_id = metadata_file.stem.replace(".metadata", "")
        if paper_id in current_paper_ids_set:
            continue
        candidate = _load_shared_pool_candidate(
            metadata_file, shared_dir, paper_id
        )
        if candidate:
            supplement_candidates.append(candidate)
    return supplement_candidates


def _shared_pool_paper_year(paper_tuple: tuple[str, dict[str, Any]]) -> int:
    """Extracts publication year from a shared-pool paper tuple.

    Args:
        paper_tuple: (paper_id, metadata) tuple.

    Returns:
        Integer year, or 0 if unavailable.
    """
    _, metadata = paper_tuple
    try:
        date_str = metadata.get("date_revised", "")
        return int(date_str.split("/")[0])
    except (ValueError, IndexError, AttributeError):
        return 0


def _link_metadata_to_run(run_dir: Path | None, paper_id: str) -> None:
    """Symlinks a shared-pool metadata file into the run directory.

    Args:
        run_dir: Per-run directory to symlink into, or None to skip.
        paper_id: Paper id whose metadata file should be linked.
    """
    # No-op without a run_id: metadata still lands in the shared pool, it
    # just is not exposed under a per-run directory.
    if not run_dir:
        return
    _symlink_into_run(run_dir, f"{paper_id}.metadata.json")


def _build_run_manifest(
    run_id: str,
    run_dir: Path,
    papers_to_use: list[str],
    all_details: dict[str, Any],
    query: str,
) -> dict[str, Any]:
    """Builds the per-run manifest dict recording the analyzed papers.

    Args:
        run_id: Unique run identifier.
        run_dir: Per-run directory whose mtime dates the manifest.
        papers_to_use: Paper IDs included in this run's result set.
        all_details: Metadata dict keyed by paper_id.
        query: Original PubMed boolean query, recorded for reference.

    Returns:
        The manifest dict ready to serialize as JSON.
    """
    return {
        "run_id": run_id,
        "paper_ids": papers_to_use,
        "pmc_ids": [
            all_details[pid]["pmc_full_text_id"]
            for pid in papers_to_use
            if all_details[pid].get("pmc_full_text_id")
        ],
        "query": query,
        # Directory mtime as a coarse "when was this run's data
        # last touched" timestamp, not a precise search time.
        "timestamp": os.path.getmtime(str(run_dir)),
    }


class _SharedPoolMixin(_FulltextMixin):
    """Adds shared-pool metadata gathering and per-run bookkeeping."""

    async def _fetch_and_cache_metadata(
        self,
        paper_id: str,
        metadata_file: Path,
        run_dir: Path | None,
        semaphore: "asyncio.Semaphore",
    ) -> tuple[str, dict[str, Any] | None]:
        """Fetches metadata from Entrez and caches it to the shared pool.

        Args:
            paper_id: PubMed article ID.
            metadata_file: Shared-pool path to write fetched metadata to.
            run_dir: Per-run directory to symlink the metadata into, or None.
            semaphore: Concurrency limiter shared with the fulltext phase.

        Returns:
            Tuple of (paper_id, metadata_dict) or (paper_id, None) on error.
        """
        # Imported locally so this module can be imported without asyncio.
        import asyncio

        async with semaphore:
            try:
                # Entrez.efetch/elink use blocking urllib and entrez_read
                # sleeps for rate limiting; run off the event loop so the
                # gathered fetches actually proceed concurrently.
                with pilot_trace_context(None, paper_id):
                    paper_details = await asyncio.to_thread(
                        self._fetch_paper_details, paper_id
                    )
                _write_metadata_cache_file(metadata_file, paper_details)
                logger.debug("Saved metadata for %s to shared pool", paper_id)
                _link_metadata_to_run(run_dir, paper_id)
                record_pilot_metadata_origin(paper_id, "entrez_fetch")
                return (paper_id, paper_details)
            except Exception as e:
                record_pilot_fetch_error("metadata_fetch", e, paper_id)
                logger.warning("Failed to read paper %s: %s", paper_id, e)
                logger.debug(traceback.format_exc())
                return (paper_id, None)

    async def _fetch_one_paper_metadata(
        self,
        paper_id: str,
        shared_dir: Path,
        run_dir: Path | None,
        semaphore: "asyncio.Semaphore",
    ) -> tuple[str, dict[str, Any] | None]:
        """Fetches metadata for a single paper, preferring the shared pool.

        Args:
            paper_id: PubMed article ID.
            shared_dir: Shared-pool directory holding cached metadata files.
            run_dir: Per-run directory to symlink cache hits and fresh
                fetches into, or None if no run tracking is requested.
            semaphore: Concurrency limiter shared with the fulltext phase.

        Returns:
            Tuple of (paper_id, metadata_dict) or (paper_id, None) on error.
        """
        # Check shared pool first (smart cache across runs)
        metadata_file = shared_dir / f"{paper_id}.metadata.json"
        if metadata_file.exists():
            record_pilot_metadata_origin(paper_id, "shared_pool_cache")
            logger.debug(
                "Paper %s metadata found in shared pool, reusing", paper_id
            )
            with open(metadata_file, encoding="utf-8") as f:
                metadata = json.load(f)
            _link_metadata_to_run(run_dir, paper_id)
            return (paper_id, metadata)

        return await self._fetch_and_cache_metadata(
            paper_id, metadata_file, run_dir, semaphore
        )

    async def _gather_paper_metadata(
        self,
        paper_ids: list[str],
        shared_dir: Path,
        run_dir: Path | None,
        semaphore: "asyncio.Semaphore",
    ) -> dict[str, Any]:
        """Fetches metadata for many papers concurrently via the shared pool.

        Args:
            paper_ids: PubMed article IDs to fetch metadata for.
            shared_dir: Shared-pool directory holding cached metadata files.
            run_dir: Per-run directory to symlink into, or None.
            semaphore: Concurrency limiter shared with the fulltext phase.

        Returns:
            Dict mapping paper_id to successfully-fetched metadata.
        """
        import asyncio  # Local: importable without asyncio available.

        if os.getenv(PUBMED_METADATA_BATCH_ENV) == "1":
            from mcp_server.pubmed_metadata_batch import gather_metadata

            return await gather_metadata(
                self, paper_ids, shared_dir, run_dir, semaphore
            )

        logger.debug(
            "fetching metadata for %s papers in parallel (max 3 concurrent)",
            len(paper_ids),
        )
        coros = [
            self._fetch_one_paper_metadata(pid, shared_dir, run_dir, semaphore)
            for pid in paper_ids
        ]
        metadata_results = await asyncio.gather(*coros)
        all_details = {
            paper_id: metadata
            for paper_id, metadata in metadata_results
            if metadata is not None
        }
        logger.debug(
            "successfully fetched metadata for %s/%s papers",
            len(all_details),
            len(paper_ids),
        )
        return all_details

    def _select_supplement_papers(
        self,
        shared_dir: Path,
        papers_to_use: list[str],
        fulltext_shortfall: int,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Selects shared-pool papers to top up a short result set.

        Args:
            shared_dir: Shared-pool directory to scan for candidates.
            papers_to_use: Paper IDs already selected for this run.
            fulltext_shortfall: Number of additional papers needed.

        Returns:
            Up to ``fulltext_shortfall`` (paper_id, metadata) tuples, most
            recent first; empty if none are suitable.
        """
        logger.info(
            "attempting to supplement %s papers from shared pool",
            fulltext_shortfall,
        )
        current_paper_ids_set = set(papers_to_use)
        supplement_candidates = _scan_shared_pool_candidates(
            shared_dir, current_paper_ids_set
        )
        supplement_candidates.sort(key=_shared_pool_paper_year, reverse=True)
        return supplement_candidates[:fulltext_shortfall]

    def _apply_shared_pool_supplements(
        self,
        run_dir: Path,
        papers_to_supplement: list[tuple[str, dict[str, Any]]],
        papers_to_use: list[str],
        all_details: dict[str, Any],
    ) -> None:
        """Symlinks supplemented papers into the run and records them.

        Args:
            run_dir: Per-run directory to symlink supplemented papers into.
            papers_to_supplement: (paper_id, metadata) tuples to add.
            papers_to_use: Paper IDs for this run; mutated in place.
            all_details: Metadata dict keyed by paper_id; mutated in place.
        """
        logger.info(
            "Found %s papers in shared pool to supplement",
            len(papers_to_supplement),
        )
        for paper_id, metadata in papers_to_supplement:
            _symlink_into_run(run_dir, f"{paper_id}.metadata.json")
            pmc_id = metadata["pmc_full_text_id"]
            _symlink_into_run(run_dir, f"{pmc_id}.fulltext.html")
            papers_to_use.append(paper_id)
            all_details[paper_id] = metadata

    def _supplement_from_shared_pool(
        self,
        dirs: _PoolDirs,
        papers_to_use: list[str],
        all_details: dict[str, Any],
        fulltext_shortfall: int,
        max_papers: int,
    ) -> None:
        """Tops up a short-of-target result set from the shared pool.

        Scans for already-downloaded papers not in this run's result set
        and, if any are found, symlinks them into the run directory and
        appends them to papers_to_use/all_details in place.

        Args:
            dirs: Shared-pool and per-run directories for this pass.
            papers_to_use: Paper IDs so far; mutated in place.
            all_details: Metadata dict keyed by paper_id; mutated in place.
            fulltext_shortfall: Additional papers needed to reach max_papers.
            max_papers: Target paper count, for the summary log line only.
        """
        shared_dir = dirs.shared_dir
        run_dir = dirs.run_dir
        papers_to_supplement = self._select_supplement_papers(
            shared_dir, papers_to_use, fulltext_shortfall
        )
        if not papers_to_supplement:
            logger.warning(
                "No suitable papers found in shared pool for supplementation"
            )
            return
        self._apply_shared_pool_supplements(
            run_dir, papers_to_supplement, papers_to_use, all_details
        )
        _record_pool_supplements(dirs.trace, papers_to_supplement)
        logger.info(
            "Supplemented %s papers from shared pool (total: %s/%s)",
            len(papers_to_supplement),
            len(papers_to_use),
            max_papers,
        )

    def _save_run_manifest(
        self,
        run_id: str,
        run_dir: Path,
        papers_to_use: list[str],
        all_details: dict[str, Any],
        query: str,
    ) -> None:
        """Writes the per-run manifest recording which papers were analyzed.

        Records exactly which papers (including any shared-pool
        supplements) this run ended up analyzing, independent of the
        per-paper symlinks, so a run's final selection can be audited or
        replayed later.

        Args:
            run_id: Unique run identifier.
            run_dir: Per-run directory to write the manifest into.
            papers_to_use: Paper IDs included in this run's final result
                set.
            all_details: Metadata dict keyed by paper_id.
            query: Original PubMed boolean query, recorded for reference.
        """
        manifest = _build_run_manifest(
            run_id, run_dir, papers_to_use, all_details, query
        )
        manifest_file = run_dir / ".manifest.json"
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        logger.info(
            "Saved manifest for run %s: %s papers", run_id, len(papers_to_use)
        )

    def _prepare_run_directories(
        self, slug: str, run_id: str | None
    ) -> tuple[Path, Path | None]:
        """Creates the shared-pool directory and, if requested, a run dir.

        Args:
            slug: Identifier for organizing results (research goal hash).
            run_id: Unique run identifier for this execution, or None to
                skip per-run tracking.

        Returns:
            A (shared_dir, run_dir) tuple; run_dir is None when run_id is
            not provided.
        """
        base_dir = self.qualified_path / slug
        shared_dir = base_dir / "shared"
        shared_dir.mkdir(parents=True, exist_ok=True)

        run_dir = None
        if run_id:
            run_dir = base_dir / "runs" / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            logger.info(
                "Using shared pool with per-run tracking: run_id=%s", run_id
            )
        else:
            logger.warning(
                "No run_id provided - papers will only go to shared pool "
                "without run tracking"
            )

        return shared_dir, run_dir
