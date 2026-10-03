"""PubMed search, shared metadata cache, and PMC fulltext retrieval."""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, cast

from Bio import Entrez

from mcp_server.entrez import (
    entrez_call,
    pilot_trace_context,
    record_pilot_fetch_error,
    record_pilot_metadata_origin,
)
from mcp_server.pubmed_client import PUBMED_METADATA_BATCH_ENV, _EntrezClient
from mcp_server.pubmed_pilot_trace import (
    new_pilot_trace,
    record_fetched_papers,
    record_pool_snapshot,
    reserve_trace_run,
    write_trace_atomically,
)
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
    """Store papers in slug/shared and link them into slug/runs/run_id."""

    async def _fetch_one_paper_metadata(
        self,
        paper_id: str,
        shared_dir: Path,
        run_dir: Path | None,
        semaphore: asyncio.Semaphore,
    ) -> tuple[str, dict[str, Any] | None]:
        metadata_file = shared_dir / f"{paper_id}.metadata.json"
        if metadata_file.exists():
            record_pilot_metadata_origin(paper_id, "shared_pool_cache")
            with metadata_file.open(encoding="utf-8") as stream:
                metadata = json.load(stream)
            link_metadata_to_run(run_dir, paper_id)
            return paper_id, metadata

        async with semaphore:
            try:
                # Entrez's blocking HTTP calls and rate limiter must run off
                # the event loop. to_thread preserves the run's trace context.
                with pilot_trace_context(None, paper_id):
                    metadata = await asyncio.to_thread(
                        self._fetch_paper_details, paper_id
                    )
                write_metadata_cache_file(metadata_file, metadata)
                link_metadata_to_run(run_dir, paper_id)
                record_pilot_metadata_origin(paper_id, "entrez_fetch")
                return paper_id, metadata
            except Exception as exc:
                record_pilot_fetch_error("metadata_fetch", exc, paper_id)
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
        if os.getenv(PUBMED_METADATA_BATCH_ENV) == "1":
            from mcp_server.pubmed_metadata_batch import gather_metadata

            return await gather_metadata(
                self, paper_ids, shared_dir, run_dir, semaphore
            )
        results = await asyncio.gather(
            *(
                self._fetch_one_paper_metadata(
                    paper_id, shared_dir, run_dir, semaphore
                )
                for paper_id in paper_ids
            )
        )
        # gather preserves search order, independent of completion order.
        return {
            paper_id: metadata
            for paper_id, metadata in results
            if metadata is not None
        }

    def _download_pmc_fulltext(self, pmc_id: str) -> str:
        """Page through PMC efetch responses when NCBI truncates a document."""
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

    def get_pubmed_fulltext(
        self, pmc_id: str, slug: str, run_id: str | None = None
    ) -> str | None:
        """Cache and link fulltext; record download failures in provenance."""
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
            record_pilot_fetch_error("fulltext", exc)
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
                with pilot_trace_context(None, paper_id):
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
        trace: dict[str, Any] | None,
    ) -> None:
        """Fill a per-run shortfall from already downloaded, recent papers."""
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
                logger.debug(
                    "Failed to read shared pool paper %s: %s", paper_id, exc
                )
        candidates.sort(key=_shared_pool_paper_year, reverse=True)
        supplements = candidates[:shortfall]
        for paper_id, metadata in supplements:
            link_metadata_to_run(run_dir, paper_id)
            link_shared_file_to_run(
                run_dir, f"{metadata['pmc_full_text_id']}.fulltext.html"
            )
            papers_to_use.append(paper_id)
            all_details[paper_id] = metadata
        logger.info("Supplemented %s papers from shared pool", len(supplements))
        if trace is not None:
            attempted_ids = {
                paper_id
                for attempt in trace.get("attempts", [])
                for paper_id in attempt.get("first_ids", [])
            }
            records = trace.setdefault("shared_pool_supplements", [])
            for paper_id, _metadata in supplements:
                if len(records) >= 9:
                    break
                records.append(
                    {
                        "pmid": paper_id,
                        "source": "shared_pool",
                        "origin": "prior_pool",
                        "preexisting": True,
                        "matched_esearch_first_ids": paper_id in attempted_ids,
                    }
                )

    def _prepare_run_directories(
        self, slug: str, run_id: str | None
    ) -> tuple[Path, Path | None]:
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
        """Prefer PMC-linked papers, then fill the corpus with abstracts."""
        selected_ids = list(dict.fromkeys(papers_to_use))
        selected_ids.extend(
            paper_id for paper_id in all_details if paper_id not in selected_ids
        )
        return {
            paper_id: all_details[paper_id]
            for paper_id in selected_ids[:max_papers]
        }

    async def pubmed_search(  # noqa: C901
        self,
        query: str,
        slug: str,
        max_papers: int = 10,
        recency_years: int = 0,
        run_id: str | None = None,
        *,
        include_fulltext: bool = True,
    ) -> dict[str, Any]:
        """Collect a PMC-first corpus and preserve its cache and run provenance.

        Search 3x the requested corpus size to cover missing fulltexts. Keep
        PMC-linked papers in search order, supplement from the existing pool
        for tracked runs, then fill remaining slots with abstract-only records.
        include_fulltext=False skips only downloads, preserving selection.
        """
        trace = new_pilot_trace(run_id)
        shared_dir, run_dir = self._prepare_run_directories(slug, run_id)
        if trace is not None and run_dir is not None and run_id is not None:
            reserve_trace_run(run_dir, run_id, trace["server_build_id"])
        record_pool_snapshot(trace, shared_dir)
        semaphore = asyncio.Semaphore(3)
        with pilot_trace_context(trace):
            try:
                paper_ids = self.pubmed_search_ids(
                    query,
                    retmax=max_papers * 3,
                    recency_years=recency_years,
                    trace=trace,
                )
                all_details = await self._gather_paper_metadata(
                    paper_ids, shared_dir, run_dir, semaphore
                )
                if trace is not None:
                    record_fetched_papers(trace, all_details)
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
                        shared_dir,
                        run_dir,
                        papers_to_use,
                        all_details,
                        shortfall,
                        trace,
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
                if trace is not None:
                    record_fetched_papers(trace, all_details)
                results = self._assemble_final_results(
                    papers_to_use, all_details, max_papers
                )
            except Exception as exc:
                if trace is not None:
                    if trace.get("error") is None:
                        trace["error"] = {
                            "stage": "retrieval_pipeline",
                            "type": type(exc).__name__,
                        }
                    trace["outcome"] = "error"
                    try:
                        self._write_pilot_trace(run_dir, trace, {})
                    except Exception:
                        logger.exception("Failed to write PubMed error trace")
                raise
        if trace is not None:
            trace["outcome"] = "nonempty" if results else "empty"
        self._write_pilot_trace(run_dir, trace, results)
        return results

    def _write_pilot_trace(
        self,
        run_dir: Path | None,
        trace: dict[str, Any] | None,
        results: dict[str, Any],
    ) -> None:
        if trace is not None and run_dir is not None:
            trace["final_ids"] = list(results)[:3]
            write_trace_atomically(run_dir / ".search-trace.json", trace)
