"""Shared-pool metadata gathering, supplementation, and run manifests."""

import json
import logging
import os
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mcp_server.fulltext_download import _FulltextMixin, _symlink_into_run

if TYPE_CHECKING:
    # asyncio is imported lazily inside the async methods below (see their
    # bodies); this type-checking-only import binds the name for the quoted
    # ``asyncio.Semaphore`` annotations without pulling asyncio in at runtime.
    import asyncio

logger = logging.getLogger(__name__)


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


class _SharedPoolMixin(_FulltextMixin):
    """Adds shared-pool metadata gathering and per-run bookkeeping."""

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
            run_dir: Per-run directory to symlink cache hits and fresh
                fetches into, or None if no run tracking is requested.
            semaphore: Concurrency limiter, shared with the fulltext
                download phase.

        Returns:
            Dict mapping paper_id to metadata for every paper fetched
            successfully (failures are omitted).
        """
        # Imported locally so importing this module does not require an
        # event loop / asyncio setup unless this async method is actually
        # called.
        import asyncio

        def link_to_run(paper_id: str) -> None:
            """Symlinks a shared-pool metadata file into the run directory."""
            # No-op without a run_id: metadata still lands in the shared
            # pool, it just is not exposed under a per-run directory.
            if not run_dir:
                return
            _symlink_into_run(run_dir, f"{paper_id}.metadata.json")

        async def fetch_paper_metadata(
            paper_id: str,
        ) -> tuple[str, dict[str, Any] | None]:
            """Fetches metadata for a single paper with rate limiting.

            Args:
                paper_id: PubMed article ID.

            Returns:
                Tuple of (paper_id, metadata_dict) or (paper_id, None) on error.
            """
            # Check shared pool first (smart cache across runs)
            metadata_file = shared_dir / f"{paper_id}.metadata.json"

            if metadata_file.exists():
                logger.debug(
                    "Paper %s metadata found in shared pool, reusing", paper_id
                )
                with open(metadata_file, encoding="utf-8") as f:
                    metadata = json.load(f)

                link_to_run(paper_id)
                return (paper_id, metadata)

            async with semaphore:
                try:
                    # Entrez.efetch/elink use blocking urllib and entrez_read
                    # sleeps for rate limiting; run off the event loop so the
                    # gathered fetches actually proceed concurrently.
                    paper_details = await asyncio.to_thread(
                        self._fetch_paper_details, paper_id
                    )

                    # Save metadata to shared pool
                    with open(metadata_file, "w", encoding="utf-8") as f:
                        json.dump(paper_details, f)
                    logger.debug(
                        "Saved metadata for %s to shared pool", paper_id
                    )

                    link_to_run(paper_id)
                    return (paper_id, paper_details)

                except Exception as e:
                    logger.warning("Failed to read paper %s: %s", paper_id, e)
                    logger.debug(traceback.format_exc())
                    return (paper_id, None)

        # Fetch all paper metadata in parallel
        logger.debug(
            "fetching metadata for %s papers in parallel (max 3 concurrent)",
            len(paper_ids),
        )
        metadata_results = await asyncio.gather(
            *[fetch_paper_metadata(pid) for pid in paper_ids]
        )

        # Collect successful results
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

    def _supplement_from_shared_pool(
        self,
        shared_dir: Path,
        run_dir: Path,
        papers_to_use: list[str],
        all_details: dict[str, Any],
        fulltext_shortfall: int,
        max_papers: int,
    ) -> None:
        """Tops up a short-of-target result set from the shared pool.

        Scans the shared pool for already-downloaded papers not already in
        this run's result set and, if any are found, symlinks them into the
        run directory and appends them to papers_to_use/all_details in
        place.

        Args:
            shared_dir: Shared-pool directory to scan for candidate papers.
            run_dir: Per-run directory to symlink supplemented papers into.
            papers_to_use: Paper IDs selected for this run so far; mutated
                in place with any supplemented paper IDs.
            all_details: Metadata dict keyed by paper_id; mutated in place
                with any supplemented papers' metadata.
            fulltext_shortfall: Number of additional papers needed to reach
                max_papers.
            max_papers: Target number of papers WITH fulltext, used only
                for the summary log line.
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

        # Take up to shortfall papers
        papers_to_supplement = supplement_candidates[:fulltext_shortfall]

        if not papers_to_supplement:
            logger.warning(
                "No suitable papers found in shared pool for supplementation"
            )
            return

        logger.info(
            "Found %s papers in shared pool to supplement",
            len(papers_to_supplement),
        )

        # Create symlinks for supplemented papers
        for paper_id, metadata in papers_to_supplement:
            _symlink_into_run(run_dir, f"{paper_id}.metadata.json")
            pmc_id = metadata["pmc_full_text_id"]
            _symlink_into_run(run_dir, f"{pmc_id}.fulltext.html")

            # Add to results
            papers_to_use.append(paper_id)
            all_details[paper_id] = metadata

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
        manifest = {
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
