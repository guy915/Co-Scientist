"""PMC fulltext download and shared-pool storage for PubMed papers."""

import contextvars
import logging
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from Bio import Entrez

from mcp_server.entrez_rate_limit import (
    entrez_call,
    pilot_trace_context,
    record_pilot_fetch_error,
)
from mcp_server.pubmed_client import _EntrezClient

if TYPE_CHECKING:
    # asyncio is imported lazily inside the async methods below (see their
    # bodies); this type-checking-only import binds the name for the quoted
    # ``asyncio.Semaphore`` annotations without pulling asyncio in at runtime.
    import asyncio

logger = logging.getLogger(__name__)


def _symlink_into_run(run_dir: Path, filename: str) -> None:
    """Links a shared-pool file into a per-run directory (idempotent).

    Args:
        run_dir: Per-run directory that should hold the symlink.
        filename: Basename of the file under ``<slug>/shared/`` to link to.
    """
    symlink = run_dir / filename
    if not symlink.exists():
        # Relative symlink: run_dir is <slug>/runs/<run_id>/, so two levels
        # up reaches <slug>/, from which "shared/<filename>" resolves. Kept
        # relative so the whole <slug> tree stays portable if moved/copied.
        symlink.symlink_to(f"../../shared/{filename}")


class _FulltextMixin(_EntrezClient):
    """Adds PMC fulltext download and shared-pool storage to the client."""

    def _download_pmc_fulltext(self, pmc_id: str) -> str:
        """Downloads a PMC article's fulltext XML, paging through truncation.

        NCBI caps the size of a single efetch response and signals this
        either on the response handle itself or in the body text; when that
        happens, page through the rest of the document by re-issuing efetch
        with retstart advanced past what has already been read, accumulating
        chunks until a response comes back with no truncation marker.

        Args:
            pmc_id: PMC article identifier.

        Returns:
            The concatenated fulltext XML contents of the paper.
        """
        text = []
        cursor = 0
        while True:
            response = entrez_call(
                Entrez.efetch,
                db="pmc",
                id=pmc_id,
                retstart=cursor,
                rettype="xml",
            )
            body = cast(bytes, response.read()).decode("utf-8")
            text.append(body)
            if "[truncated]" in response or "Result too long" in body:
                cursor += len(body)
            else:
                break
        return "".join(text)

    def _read_or_fetch_fulltext(self, fulltext_file: Path, pmc_id: str) -> str:
        """Returns a paper's fulltext, reusing the shared-pool copy if present.

        Args:
            fulltext_file: Shared-pool path where the fulltext is cached.
            pmc_id: PMC article identifier to download when not cached.

        Returns:
            The fulltext contents, read from disk when already cached or
            freshly downloaded and written to the shared pool otherwise.
        """
        if fulltext_file.exists():
            logger.info("Fulltext %s found in shared pool, reusing", pmc_id)
            with open(fulltext_file, encoding="utf-8") as f:
                return f.read()
        contents = self._download_pmc_fulltext(pmc_id)
        with open(fulltext_file, "w", encoding="utf-8") as f:
            f.write(contents)
        logger.info("Downloaded and saved fulltext %s to shared pool", pmc_id)
        return contents

    def _store_fulltext(
        self, pmc_id: str, slug: str, run_id: str | None
    ) -> str:
        """Fetches a PMC fulltext into the shared pool and links it per-run.

        Args:
            pmc_id: PMC article identifier.
            slug: Identifier for organizing results.
            run_id: Unique run identifier for per-run symlink creation, or
                None to skip the symlink.

        Returns:
            The fulltext contents of the paper.
        """
        # Check shared pool first
        base_dir = self.qualified_path / slug
        shared_dir = base_dir / "shared"
        shared_dir.mkdir(parents=True, exist_ok=True)
        fulltext_file = shared_dir / f"{pmc_id}.fulltext.html"

        contents = self._read_or_fetch_fulltext(fulltext_file, pmc_id)

        # Create symlink into the per-run directory if one was requested.
        if run_id:
            run_dir = base_dir / "runs" / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            _symlink_into_run(run_dir, f"{pmc_id}.fulltext.html")
        return contents

    def get_pubmed_fulltext(
        self, pmc_id: str, slug: str, run_id: str | None = None
    ) -> str | None:
        """Downloads the fulltext of a PMC paper and saves it to shared pool.

        Uses shared pool architecture - saves to slug/shared/ and creates a
        symlink to slug/runs/{run_id}/ if run_id is provided.

        This operation is expected to fail gracefully and logs, rather than
        raising the exception further.

        Args:
            pmc_id: PMC article identifier.
            slug: Identifier for organizing results.
            run_id: Unique run identifier for per-run symlink creation.

        Returns:
            The fulltext HTML contents of the paper, or None if the download
            fails.
        """
        try:
            return self._store_fulltext(pmc_id, slug, run_id)
        except Exception as e:
            record_pilot_fetch_error("fulltext", e)
            logger.error(
                "Failed to download PMC fulltext for %s: %s: %s",
                pmc_id,
                type(e).__name__,
                e,
            )
            logger.debug(traceback.format_exc())
            return None

    async def _download_one_fulltext(
        self,
        paper_id: str,
        all_details: dict[str, Any],
        slug: str,
        run_id: str | None,
        semaphore: "asyncio.Semaphore",
    ) -> None:
        """Downloads fulltext for a single paper to the shared pool.

        Args:
            paper_id: PubMed article ID to download fulltext for.
            all_details: Metadata dict keyed by paper_id, used to look up the
                paper's PMC fulltext ID.
            slug: Identifier for organizing results.
            run_id: Unique run identifier for per-run symlink creation.
            semaphore: Concurrency limiter, shared with the metadata fetch
                phase.
        """
        # Imported locally, matching the other async helpers in this class.
        import asyncio

        async with semaphore:
            pmc_id = all_details[paper_id]["pmc_full_text_id"]
            # Preserve the pilot's run/paper identity across this executor
            # boundary; unlike asyncio.to_thread, run_in_executor does not
            # copy ContextVars itself.
            with pilot_trace_context(None, paper_id):
                context = contextvars.copy_context()
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    context.run,
                    self.get_pubmed_fulltext,
                    pmc_id,
                    slug,
                    run_id,
                )

    async def _download_fulltexts_for_papers(
        self,
        papers_to_use: list[str],
        all_details: dict[str, Any],
        slug: str,
        run_id: str | None,
        semaphore: "asyncio.Semaphore",
    ) -> None:
        """Downloads PMC fulltexts for the selected papers, in parallel.

        Args:
            papers_to_use: PubMed IDs of the papers to download fulltext for.
            all_details: Metadata dict keyed by paper_id, used to look up
                each paper's PMC fulltext ID.
            slug: Identifier for organizing results.
            run_id: Unique run identifier for per-run symlink creation.
            semaphore: Concurrency limiter, shared with the metadata fetch
                phase.
        """
        if not papers_to_use:
            return
        # Imported locally, matching the other async helpers in this class.
        import asyncio

        logger.info(
            "Downloading %s fulltexts in parallel (max 3 concurrent)",
            len(papers_to_use),
        )
        await asyncio.gather(
            *[
                self._download_one_fulltext(
                    pid, all_details, slug, run_id, semaphore
                )
                for pid in papers_to_use
            ]
        )
