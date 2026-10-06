import asyncio
import json
import logging
from pathlib import Path
from typing import Any, cast

from Bio import Entrez

from mcp_server.entrez import entrez_call
from mcp_server.pubmed_client import _EntrezClient
from mcp_server.pubmed_storage import (
    link_metadata_to_run,
    link_shared_file_to_run,
    write_metadata_cache_file,
)

logger = logging.getLogger(__name__)


def _shared_pool_paper_year(paper: tuple[str, dict[str, Any]]) -> int:
    try:
        return int(paper[1].get("date_revised", "").split("/")[0])
    except (ValueError, IndexError, AttributeError):
        return 0


class PubmedSource(_EntrezClient):
    async def _fetch_one_paper_metadata(
        self,
        paper_id: str,
        shared_dir: Path,
        run_dir: Path | None,
        semaphore: asyncio.Semaphore,
    ) -> tuple[str, dict[str, Any] | None]:
        metadata_file = shared_dir / f"{paper_id}.metadata.json"
        if metadata_file.exists():
            with metadata_file.open(encoding="utf-8") as stream:
                metadata = json.load(stream)
            link_metadata_to_run(run_dir, paper_id)
            return paper_id, metadata

        async with semaphore:
            try:
                # Entrez's blocking HTTP calls and rate limiter must run off
                # the event loop.
                metadata = await asyncio.to_thread(self._fetch_paper_details, paper_id)
                write_metadata_cache_file(metadata_file, metadata)
                link_metadata_to_run(run_dir, paper_id)
                return paper_id, metadata
            except Exception as exc:
                logger.warning("Failed to read paper %s: %s", paper_id, exc)
                logger.debug("Metadata fetch failed", exc_info=True)
                return paper_id, None

    async def _gather_paper_metadata(
        self,
        paper_ids: list[str],
        shared_dir: Path,
        run_dir: Path | None,
        semaphore: asyncio.Semaphore,
    ) -> dict[str, Any]:
        results = await asyncio.gather(
            *(
                self._fetch_one_paper_metadata(paper_id, shared_dir, run_dir, semaphore)
                for paper_id in paper_ids
            )
        )
        # gather preserves search order, independent of completion order.
        return {paper_id: metadata for paper_id, metadata in results if metadata is not None}

    def _download_pmc_fulltext(self, pmc_id: str) -> str:
        """PMC can truncate documents across efetch responses, requiring
        pagination.
        """
        chunks = []
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
            chunks.append(body)
            if "[truncated]" in response or "Result too long" in body:
                cursor += len(body)
            else:
                break
        return "".join(chunks)

    def get_pubmed_fulltext(self, pmc_id: str, slug: str, run_id: str | None = None) -> str | None:
        try:
            shared_dir, run_dir = self._prepare_run_directories(slug, run_id)
            fulltext_file = shared_dir / f"{pmc_id}.fulltext.html"
            if fulltext_file.exists():
                contents = fulltext_file.read_text(encoding="utf-8")
            else:
                contents = self._download_pmc_fulltext(pmc_id)
                fulltext_file.write_text(contents, encoding="utf-8")
            if run_dir is not None:
                link_shared_file_to_run(run_dir, fulltext_file.name)
            return contents
        except Exception as exc:
            logger.error(
                "Failed to download PMC fulltext for %s: %s: %s",
                pmc_id,
                type(exc).__name__,
                exc,
            )
            logger.debug("PMC download failed", exc_info=True)
            return None

    async def _download_fulltexts_for_papers(
        self,
        paper_ids: list[str],
        all_details: dict[str, Any],
        slug: str,
        run_id: str | None,
        semaphore: asyncio.Semaphore,
    ) -> None:
        async def download(paper_id: str) -> None:
            async with semaphore:
                await asyncio.to_thread(
                    self.get_pubmed_fulltext,
                    all_details[paper_id]["pmc_full_text_id"],
                    slug,
                    run_id,
                )

        await asyncio.gather(*(download(paper_id) for paper_id in paper_ids))

    def _supplement_from_shared_pool(
        self,
        shared_dir: Path,
        run_dir: Path,
        papers_to_use: list[str],
        all_details: dict[str, Any],
        shortfall: int,
    ) -> None:
        selected = set(papers_to_use)
        candidates = []
        for metadata_file in shared_dir.glob("*.metadata.json"):
            paper_id = metadata_file.stem.removesuffix(".metadata")
            if paper_id in selected:
                continue
            try:
                with metadata_file.open(encoding="utf-8") as stream:
                    metadata = json.load(stream)
                pmc_id = metadata.get("pmc_full_text_id")
                if pmc_id and (shared_dir / f"{pmc_id}.fulltext.html").exists():
                    candidates.append((paper_id, metadata))
            except Exception as exc:
                logger.debug("Failed to read shared pool paper %s: %s", paper_id, exc)
        candidates.sort(key=_shared_pool_paper_year, reverse=True)
        supplements = candidates[:shortfall]
        for paper_id, metadata in supplements:
            link_metadata_to_run(run_dir, paper_id)
            link_shared_file_to_run(run_dir, f"{metadata['pmc_full_text_id']}.fulltext.html")
            papers_to_use.append(paper_id)
            all_details[paper_id] = metadata
        logger.info("Supplemented %s papers from shared pool", len(supplements))

    def _prepare_run_directories(self, slug: str, run_id: str | None) -> tuple[Path, Path | None]:
        base_dir = self.qualified_path / slug
        shared_dir = base_dir / "shared"
        shared_dir.mkdir(parents=True, exist_ok=True)
        run_dir = base_dir / "runs" / run_id if run_id else None
        if run_dir is not None:
            run_dir.mkdir(parents=True, exist_ok=True)
        return shared_dir, run_dir

    def _assemble_final_results(
        self,
        papers_to_use: list[str],
        all_details: dict[str, Any],
        max_papers: int,
    ) -> dict[str, Any]:
        selected_ids = list(dict.fromkeys(papers_to_use))
        selected_ids.extend(paper_id for paper_id in all_details if paper_id not in selected_ids)
        return {paper_id: all_details[paper_id] for paper_id in selected_ids[:max_papers]}

    async def pubmed_search(
        self,
        query: str,
        slug: str,
        max_papers: int = 10,
        recency_years: int = 0,
        run_id: str | None = None,
        *,
        include_fulltext: bool = True,
    ) -> dict[str, Any]:
        """Search extra candidates to cover missing full text; disabling
        downloads must not change selection.
        """
        shared_dir, run_dir = self._prepare_run_directories(slug, run_id)
        semaphore = asyncio.Semaphore(3)
        paper_ids = self.pubmed_search_ids(
            query,
            retmax=max_papers * 3,
            recency_years=recency_years,
        )
        all_details = await self._gather_paper_metadata(paper_ids, shared_dir, run_dir, semaphore)
        papers_to_use = [
            paper_id
            for paper_id, metadata in all_details.items()
            if metadata.get("pmc_full_text_id") is not None
        ][:max_papers]
        if include_fulltext:
            await self._download_fulltexts_for_papers(
                papers_to_use, all_details, slug, run_id, semaphore
            )
        shortfall = max_papers - len(papers_to_use)
        if shortfall > 0 and run_dir is not None:
            self._supplement_from_shared_pool(
                shared_dir, run_dir, papers_to_use, all_details, shortfall
            )
        if run_id and run_dir:
            manifest = {
                "run_id": run_id,
                "paper_ids": papers_to_use,
                "pmc_ids": [
                    all_details[paper_id]["pmc_full_text_id"]
                    for paper_id in papers_to_use
                    if all_details[paper_id].get("pmc_full_text_id")
                ],
                "query": query,
                "timestamp": run_dir.stat().st_mtime,
            }
            (run_dir / ".manifest.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )
        return self._assemble_final_results(papers_to_use, all_details, max_papers)
