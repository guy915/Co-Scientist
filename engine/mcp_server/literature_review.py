# Copyright 2026 The Co-Scientist Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Literature review agent and PubMed document source implementation."""
# pylint: disable=inconsistent-quotes

from Bio import Entrez
from time import sleep
import os
import logging
from pathlib import Path
from typing import cast
import traceback
import json
from abc import ABC

logger = logging.getLogger(__name__)


class DocumentSource(ABC):
    """Abstract base class for literature document sources."""

    # folder name for papers
    data_dir: str
    # set when added to LiteratureReviewAgent or manually
    qualified_path: Path | None

    async def fetch_for_query(
            self,  # pylint: disable=unused-argument
            query: str,
            slug: str = "",
            max_papers: int = 10):
        """Fetches papers for a given query and writes them to qualified_path.

        Returns details relevant for an agent to read, in an unspecified format.
        """
        raise NotImplementedError


class LiteratureReviewAgent:
    """Orchestrates multiple document sources for literature review."""

    source_root: Path
    source_dirs: list[str]
    sources: dict[str, DocumentSource]

    def __init__(self, source_root: Path):
        """Initializes the agent with a root directory for storing papers.

        Args:
            source_root: Root path where all source subdirectories are created.
        """
        self.source_root = source_root
        self.source_dirs = []
        self.sources = {}
        logger.info("Initialized LiteratureReviewAgent with source root: %s",
                    source_root)

    def add_source(self, name: str, source: DocumentSource):
        """Registers a document source under a given name.

        Args:
            name: Key used to refer to this source in fetch_for_query.
            source: DocumentSource instance to register.
        """
        self.source_dirs.append(source.data_dir)
        source.qualified_path = self.source_root / source.data_dir
        self.sources[name] = source

    async def fetch_for_query(self,
                              source_name: str,
                              query: str,
                              slug: str,
                              max_papers: int = 10,
                              recency_years: int = 0,
                              run_id: str = None):
        """Fetches papers from a named source for the given query.

        Args:
            source_name: Key of the registered source to query.
            query: Search query string.
            slug: Identifier for organizing results.
            max_papers: Maximum number of papers to retrieve.
            recency_years: Filter to papers from last N years (0 = no filter).
            run_id: Unique run identifier for per-run tracking.

        Returns:
            Source-specific result mapping.
        """
        return await self.sources[source_name].fetch_for_query(
            query, slug, max_papers, recency_years, run_id)


class PubmedSource(DocumentSource):
    """PubMed document source with fulltext download from PMC."""

    def __init__(self, qualified_path=None):
        """Initializes the PubMed source.

        Args:
            qualified_path: Optional path override; normally set by the agent.
        """
        self.data_dir = "pubmed"
        self.qualified_path = qualified_path

    async def fetch_for_query(self,
                              query: str,
                              slug: str,
                              max_papers: int = 10,
                              recency_years: int = 0,
                              run_id: str = None):
        """Fetches papers from PubMed for the given query.

        Args:
            query: PubMed boolean query string.
            slug: Identifier for organizing results.
            max_papers: Maximum papers to retrieve.
            recency_years: Filter to papers from last N years (0 = no filter).
            run_id: Unique run identifier for per-run tracking.

        Returns:
            Dict mapping paper_id to metadata.
        """
        return await self.pubmed_search(query, slug, max_papers, recency_years,
                                        run_id)

    def _assert_qualified_path(self) -> Path:
        """Returns qualified_path, raising if it is unset.

        Returns:
            The qualified path for this source.

        Raises:
            ValueError: If qualified_path has not been set.
        """
        if self.qualified_path is None:
            raise ValueError(
                "Ensure qualified_path is set via initializer or from "
                "LiteratureReviewAgent.")
        return self.qualified_path

    def entrez_read(self, handle) -> dict:
        """Reads an Entrez handle with rate-limit delay.

        Args:
            handle: Open Entrez response handle.

        Returns:
            Parsed result dict from Entrez.read().
        """
        sleep(0.25)  # rate limits - recommended by entrez docs
        results = Entrez.read(handle)
        handle.close()
        return results  # type: ignore

    def pubmed_search_ids(self,
                          query: str,
                          retmax: int = 10,
                          recency_years: int = 0) -> list[str]:
        """Searches PubMed and returns matching paper IDs.

        Args:
            query: PubMed boolean query.
            retmax: Maximum results to return.
            recency_years: Filter to papers from last N years (0 = no filter).

        Returns:
            List of PubMed IDs sorted by publication date (most recent first).
        """
        search_params = {
            "db": "pubmed",
            "term": query,
            "retmax": retmax,
            "sort": "pub_date"
        }

        # add recency filter if specified
        if recency_years > 0:
            from datetime import datetime  # pylint: disable=import-outside-toplevel
            current_year = datetime.now().year
            min_year = current_year - recency_years
            search_params["mindate"] = f"{min_year}/01/01"
            search_params["maxdate"] = f"{current_year}/12/31"
            search_params["datetype"] = "pdat"  # filter by publication date
            logger.debug("applying recency filter: %s-%s (last %s years)",
                         min_year, current_year, recency_years)

        logger.debug("searching pubmed with sort=pub_date (most recent first)")
        results = self.entrez_read(Entrez.esearch(**search_params))
        if (id_list := results.get("IdList", None)):
            return id_list
        logger.warning("No results found for query: %s", query)
        return []

    def get_pubmed_fulltext(self, pmc_id: str, slug: str, run_id: str = None):
        """Downloads the fulltext of a PMC paper and saves it to shared pool.

        Uses shared pool architecture - saves to slug/shared/ and creates a
        symlink to slug/runs/{run_id}/ if run_id is provided.

        This operation is expected to fail gracefully and logs, rather than
        raising the exception further.

        Args:
            pmc_id: PMC article identifier.
            slug: Identifier for organizing results.
            run_id: Unique run identifier for per-run symlink creation.
        """
        try:  # pylint: disable=broad-exception-caught
            # check shared pool first
            base_dir = self._assert_qualified_path() / slug
            shared_dir = base_dir / "shared"
            shared_dir.mkdir(parents=True, exist_ok=True)
            fulltext_file = shared_dir / f"{pmc_id}.fulltext.html"

            # check if already downloaded to shared pool
            if fulltext_file.exists():
                logger.info("Fulltext %s found in shared pool, reusing", pmc_id)
                with open(fulltext_file, 'r', encoding='utf-8') as f:
                    contents = f.read()

                # create symlink to run directory if needed
                if run_id:
                    run_dir = base_dir / "runs" / run_id
                    run_dir.mkdir(parents=True, exist_ok=True)
                    run_fulltext_symlink = run_dir / f"{pmc_id}.fulltext.html"
                    if not run_fulltext_symlink.exists():
                        run_fulltext_symlink.symlink_to(
                            f"../../shared/{pmc_id}.fulltext.html")
                        logger.debug("Created symlink for %s in run %s", pmc_id,
                                     run_id)

                return contents

            # download fulltext
            text = []
            cursor = 0
            while True:
                response = Entrez.efetch(db="pmc",
                                         id=pmc_id,
                                         retstart=cursor,
                                         rettype="xml")
                sleep(0.25)
                body = cast(bytes, response.read()).decode('utf-8')
                text.append(body)
                if "[truncated]" in response or "Result too long" in body:
                    cursor += len(body)
                else:
                    break
            contents = "".join(text)

            # save to shared pool
            with open(fulltext_file, 'w', encoding='utf-8') as f:
                f.write(contents)
            logger.info("Downloaded and saved fulltext %s to shared pool",
                        pmc_id)

            # create symlink to run directory if run_id provided
            if run_id:
                run_dir = base_dir / "runs" / run_id
                run_dir.mkdir(parents=True, exist_ok=True)
                run_fulltext_symlink = run_dir / f"{pmc_id}.fulltext.html"
                if not run_fulltext_symlink.exists():
                    run_fulltext_symlink.symlink_to(
                        f"../../shared/{pmc_id}.fulltext.html")
                    logger.debug("Created symlink for %s in run %s", pmc_id,
                                 run_id)

            return contents
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Failed to download PMC fulltext for %s: %s: %s",
                         pmc_id,
                         type(e).__name__, e)
            logger.debug(traceback.format_exc())

    async def pubmed_search(self,
                            query: str,
                            slug: str,
                            max_papers: int = 10,
                            recency_years: int = 0,
                            run_id: str = None):
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
        import asyncio  # pylint: disable=import-outside-toplevel

        # request 3x papers to account for ~33% fulltext availability
        # we'll filter down to max_papers with fulltext
        search_buffer = max_papers * 3
        logger.info("Requesting %s papers from PubMed to find %s with fulltext",
                    search_buffer, max_papers)
        paper_ids = self.pubmed_search_ids(query,
                                           retmax=search_buffer,
                                           recency_years=recency_years)

        # create shared pool and run-specific directories
        base_dir = self._assert_qualified_path() / slug
        shared_dir = base_dir / "shared"
        shared_dir.mkdir(parents=True, exist_ok=True)

        # create run directory if run_id provided (enables per-run tracking)
        run_dir = None
        if run_id:
            run_dir = base_dir / "runs" / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Using shared pool with per-run tracking: run_id=%s",
                        run_id)
        else:
            logger.warning(
                "No run_id provided - papers will only go to shared pool "
                "without run tracking")

        # track papers belonging to this run for manifest
        current_run_papers = []

        # semaphore to limit concurrent entrez API calls (respect rate limits)
        # allow 3 concurrent (conservative, can increase to 10 with API key)
        semaphore = asyncio.Semaphore(3)

        async def fetch_paper_metadata(
                paper_id: str) -> tuple[str, dict | None]:
            """Fetches metadata for a single paper with rate limiting.

            Args:
                paper_id: PubMed article ID.

            Returns:
                Tuple of (paper_id, metadata_dict) or (paper_id, None) on error.
            """
            # check shared pool first (smart cache across runs)
            metadata_file = shared_dir / f"{paper_id}.metadata.json"

            if metadata_file.exists():
                logger.debug("Paper %s metadata found in shared pool, reusing",
                             paper_id)
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)

                # create symlink to run directory if run_id provided
                if run_dir:
                    run_metadata_symlink = (run_dir /
                                            f"{paper_id}.metadata.json")
                    if not run_metadata_symlink.exists():
                        run_metadata_symlink.symlink_to(
                            f"../../shared/{paper_id}.metadata.json")
                    current_run_papers.append(paper_id)

                return (paper_id, metadata)

            async with semaphore:
                try:
                    results = self.entrez_read(
                        Entrez.efetch(db="pubmed", id=paper_id))
                    date_revised_raw = results["PubmedArticle"][0][
                        "MedlineCitation"]["DateRevised"]
                    date_revised = "{}/{}/{}".format(  # pylint: disable=consider-using-f-string
                        *[
                            str(date_revised_raw[field])
                            for field in ["Year", "Month", "Day"]
                        ])
                    try:
                        abstract = " ".join(
                            results["PubmedArticle"][0]["MedlineCitation"]
                            ["Article"]["Abstract"]["AbstractText"])
                    except KeyError:
                        abstract = "<not found>"

                    title = results["PubmedArticle"][0]["MedlineCitation"][
                        "Article"]["ArticleTitle"]

                    authors = list(
                        filter(
                            lambda author: '<invalid>' not in author,
                            [
                                f"{author.get('ForeName', '<invalid>')} "  # pylint: disable=line-too-long
                                f"{author.get('LastName', '<invalid>')}"
                                for author in [
                                    dict(author_data) for author_data in
                                    results["PubmedArticle"][0]
                                    ['MedlineCitation']['Article']['AuthorList']
                                ]
                            ]))

                    try:
                        doi = [
                            str(element) for element in filter(
                                lambda xml_string: xml_string.attributes.get(
                                    "IdType", None) == 'doi',
                                results["PubmedArticle"][0]['PubmedData']
                                ['ArticleIdList'])
                        ][0]
                    except IndexError:
                        doi = "<not found>"

                    publication = results["PubmedArticle"][0][
                        'MedlineCitation']['Article']['Journal']['Title']

                    try:
                        related = self.entrez_read(
                            Entrez.elink(dbfrom="pubmed", db="pmc",
                                         id=paper_id))
                        pmc_full_text = related[0]["LinkSetDb"][0]["Link"][0][
                            "Id"]
                    except Exception:  # pylint: disable=broad-exception-caught
                        pmc_full_text = None
                        logger.debug("%s -- fulltext not available in pmc", doi)

                    paper_details = {
                        "date_revised": date_revised,
                        "title": title,
                        "abstract": abstract,
                        "doi": doi,
                        "authors": authors,
                        "publication": publication,
                        "pmc_full_text_id": pmc_full_text
                    }

                    # save metadata to shared pool
                    with open(metadata_file, "w", encoding="utf-8") as f:
                        json.dump(paper_details, f)
                    logger.debug("Saved metadata for %s to shared pool",
                                 paper_id)

                    # create symlink to run directory if run_id provided
                    if run_dir:
                        run_metadata_symlink = (run_dir /
                                                f"{paper_id}.metadata.json")
                        if not run_metadata_symlink.exists():
                            run_metadata_symlink.symlink_to(
                                f"../../shared/{paper_id}.metadata.json")
                        current_run_papers.append(paper_id)

                    return (paper_id, paper_details)

                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.warning("Failed to read paper %s: %s", paper_id, e)
                    logger.debug(traceback.format_exc())
                    return (paper_id, None)

        # fetch all paper metadata in parallel
        logger.debug(
            "fetching metadata for %s papers in parallel (max 3 concurrent)",
            len(paper_ids))
        metadata_results = await asyncio.gather(
            *[fetch_paper_metadata(pid) for pid in paper_ids])

        # collect successful results
        all_details = {
            paper_id: metadata
            for paper_id, metadata in metadata_results
            if metadata is not None
        }
        logger.debug("successfully fetched metadata for %s/%s papers",
                     len(all_details), len(paper_ids))

        # filter to papers with PMC IDs and take first max_papers
        # (most recent, thanks to sort)
        papers_with_pmc = [
            paper_id for paper_id in all_details
            if all_details[paper_id].get('pmc_full_text_id') is not None
        ]
        # take first max_papers with fulltext
        papers_to_use = papers_with_pmc[:max_papers]

        logger.info("fulltext availability: %s/%s papers have PMC fulltexts",
                    len(papers_with_pmc), len(all_details))
        logger.info("selecting %s/%s papers with fulltext (target: %s)",
                    len(papers_to_use), len(papers_with_pmc), max_papers)

        # check if we're short of target
        fulltext_shortfall = max_papers - len(papers_to_use)
        if fulltext_shortfall > 0:
            logger.warning(
                "Short of target by %s papers - will attempt shared pool "
                "supplement", fulltext_shortfall)

        if len(papers_to_use) == 0:
            logger.error(
                "No papers have PMC fulltexts - (no documents to analyze)")

        # download fulltexts in parallel (synchronous calls wrapped in executor)
        async def download_fulltext(paper_id: str) -> None:
            """Downloads fulltext for a single paper to shared pool.

            Args:
                paper_id: PubMed article ID to download fulltext for.
            """
            async with semaphore:
                pmc_id = all_details[paper_id]['pmc_full_text_id']
                # get_pubmed_fulltext is synchronous, run in executor
                await asyncio.get_event_loop().run_in_executor(
                    None, self.get_pubmed_fulltext, pmc_id, slug, run_id)

        if papers_to_use:
            logger.info(
                "Downloading %s fulltexts in parallel (max 3 concurrent)",
                len(papers_to_use))
            await asyncio.gather(
                *[download_fulltext(pid) for pid in papers_to_use])

        # if short of target, supplement from shared pool
        if fulltext_shortfall > 0 and run_dir:
            logger.info("attempting to supplement %s papers from shared pool",
                        fulltext_shortfall)

            # scan shared pool for papers not in current run
            current_paper_ids_set = set(papers_to_use)
            supplement_candidates = []

            for metadata_file in shared_dir.glob("*.metadata.json"):
                paper_id = metadata_file.stem.replace(".metadata", "")
                if paper_id not in current_paper_ids_set:
                    try:
                        with open(metadata_file, 'r', encoding='utf-8') as f:
                            metadata = json.load(f)
                        # only consider papers with PMC fulltext
                        if metadata.get('pmc_full_text_id'):
                            # check if fulltext exists in shared pool
                            pmc_id = metadata['pmc_full_text_id']
                            fulltext_file = (shared_dir /
                                             f"{pmc_id}.fulltext.html")
                            if fulltext_file.exists():
                                supplement_candidates.append(
                                    (paper_id, metadata))
                    except Exception as e:  # pylint: disable=broad-exception-caught
                        logger.debug("Failed to read shared pool paper %s: %s",
                                     paper_id, e)

            # sort candidates by date (most recent first)
            def get_year(paper_tuple):
                """Extracts publication year from paper metadata tuple.

                Args:
                    paper_tuple: (paper_id, metadata) tuple.

                Returns:
                    Integer year, or 0 if unavailable.
                """
                _, metadata = paper_tuple
                try:
                    date_str = metadata.get('date_revised', '')
                    year = int(date_str.split('/')[0])
                    return year
                except (ValueError, IndexError, AttributeError):
                    return 0

            supplement_candidates.sort(key=get_year, reverse=True)

            # take up to shortfall papers
            papers_to_supplement = supplement_candidates[:fulltext_shortfall]

            if papers_to_supplement:
                logger.info("Found %s papers in shared pool to supplement",
                            len(papers_to_supplement))

                # create symlinks for supplemented papers
                for paper_id, metadata in papers_to_supplement:
                    # symlink metadata
                    run_metadata_symlink = (run_dir /
                                            f"{paper_id}.metadata.json")
                    if not run_metadata_symlink.exists():
                        run_metadata_symlink.symlink_to(
                            f"../../shared/{paper_id}.metadata.json")

                    # symlink fulltext
                    pmc_id = metadata['pmc_full_text_id']
                    run_fulltext_symlink = run_dir / f"{pmc_id}.fulltext.html"
                    if not run_fulltext_symlink.exists():
                        run_fulltext_symlink.symlink_to(
                            f"../../shared/{pmc_id}.fulltext.html")

                    # add to results
                    papers_to_use.append(paper_id)
                    all_details[paper_id] = metadata
                    current_run_papers.append(paper_id)

                logger.info(
                    "Supplemented %s papers from shared pool "
                    "(total: %s/%s)", len(papers_to_supplement),
                    len(papers_to_use), max_papers)
            else:
                logger.warning(
                    "No suitable papers found in shared pool for supplement")

        # save manifest for this run if run_id provided
        if run_id and run_dir:
            manifest = {
                "run_id": run_id,
                "paper_ids": papers_to_use,
                "pmc_ids": [
                    all_details[pid]["pmc_full_text_id"]
                    for pid in papers_to_use
                    if all_details[pid].get("pmc_full_text_id")
                ],
                "query": query,
                "timestamp": os.path.getmtime(str(run_dir))
            }
            manifest_file = run_dir / ".manifest.json"
            with open(manifest_file, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=2)
            logger.info("Saved manifest for run %s: %s papers", run_id,
                        len(papers_to_use))

        # return ONLY papers with fulltext (ready for analysis)
        final_details = {
            paper_id: all_details[paper_id] for paper_id in papers_to_use
        }
        logger.info("Returning %s papers with fulltext (target was %s)",
                    len(final_details), max_papers)
        return final_details
