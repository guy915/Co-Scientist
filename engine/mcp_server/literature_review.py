"""PubMed document source with fulltext download from PMC."""
# pylint: disable=inconsistent-quotes

from Bio import Entrez
from time import sleep
import os
import logging
from pathlib import Path
from typing import Any, cast
import traceback
import json

from mcp_server.entrez import initialize_entrez

logger = logging.getLogger(__name__)

# Configure Entrez credentials at import so the source is ready to query.
initialize_entrez()


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


def _parse_authors(article: dict[str, Any]) -> list[str]:
    """Builds "Forename Lastname" strings for each author on an article.

    Args:
        article: Entrez-parsed ``Article`` mapping (from a
            ``PubmedArticle["MedlineCitation"]["Article"]`` node).

    Returns:
        List of author display names, dropping any entry where either name
        part was missing rather than emitting a name with a literal
        "<invalid>" token in it.
    """
    return list(
        filter(lambda author: '<invalid>' not in author, [
            f"{author.get('ForeName', '<invalid>')} "
            f"{author.get('LastName', '<invalid>')}" for author in
            [dict(author_data) for author_data in article['AuthorList']]
        ]))


def _extract_doi(pubmed_article: dict[str, Any]) -> str:
    """Extracts the DOI from a PubmedArticle's ArticleIdList.

    Args:
        pubmed_article: Entrez-parsed ``PubmedArticle`` element.

    Returns:
        The DOI string, or "<not found>" if no ArticleIdList entry is
        tagged with ``IdType="doi"``.
    """
    try:
        # ArticleIdList mixes several ID types (pubmed, doi, pmc, ...);
        # filter down to the one tagged IdType="doi". IndexError (empty
        # list after filtering) means no DOI was assigned.
        return [
            str(element) for element in filter(
                lambda xml_string: xml_string.attributes.get("IdType", None) ==
                'doi', pubmed_article['PubmedData']['ArticleIdList'])
        ][0]
    except IndexError:
        return "<not found>"


class PubmedSource:
    """PubMed document source with fulltext download from PMC."""

    def __init__(self, qualified_path: Path):
        """Initializes the PubMed source.

        Args:
            qualified_path: Directory where this source stores papers (the
                ``pubmed`` subdirectory of the literature-review root).
        """
        self.qualified_path = qualified_path

    def entrez_read(self, handle: Any) -> Any:
        """Reads an Entrez handle with rate-limit delay.

        Entrez.read parses XML into either a dict-like or list-like structure
        depending on the query, so the return type is intentionally opaque.

        Args:
            handle: Open Entrez response handle.

        Returns:
            Parsed result from Entrez.read() (dict-like or list-like).
        """
        # NCBI's documented courtesy limit is at most ~3 requests/second
        # without an API key; a fixed delay per call is a simple way to
        # stay under that across many sequential/concurrent calls.
        sleep(0.25)  # rate limits - recommended by entrez docs
        results = Entrez.read(handle)
        handle.close()
        return results

    def _fetch_pmc_fulltext_id(self, paper_id: str, doi: str) -> str | None:
        """Looks up the PMC fulltext ID linked to a PubMed article.

        Args:
            paper_id: PubMed article ID.
            doi: DOI of the article, used only for the debug log line when no
                PMC link is found.

        Returns:
            The linked PMC ID, or None if no fulltext link exists.
        """
        try:
            # elink cross-references PubMed IDs to PMC IDs; a paper only has
            # a usable PMC fulltext if this link exists. Any failure here
            # (no link, malformed response) just means fulltext is
            # unavailable, not a fatal error for the caller.
            related = self.entrez_read(
                Entrez.elink(dbfrom="pubmed", db="pmc", id=paper_id))
            return related[0]["LinkSetDb"][0]["Link"][0]["Id"]
        except Exception:  # pylint: disable=broad-exception-caught
            logger.debug("%s -- fulltext not available in pmc", doi)
            return None

    def _fetch_paper_details(self, paper_id: str) -> dict[str, Any]:
        """Fetches and parses one paper's metadata from Entrez (blocking).

        Performs the blocking efetch/elink network calls and XML parsing for a
        single paper. Intended to be dispatched via asyncio.to_thread so
        callers can fetch many papers concurrently without blocking the event
        loop.

        Args:
            paper_id: PubMed article ID.

        Returns:
            Metadata dict for the paper (title, abstract, authors, doi, etc.).
        """
        # efetch returns a PubmedArticleSet; a single-id request still comes
        # back as a one-element list, hence the [0] below.
        results = self.entrez_read(Entrez.efetch(db="pubmed", id=paper_id))
        pubmed_article = results["PubmedArticle"][0]
        citation = pubmed_article["MedlineCitation"]
        article = citation["Article"]

        # Entrez.read parses DateRevised into a dict-like with separate
        # Year/Month/Day string fields; join them into "YYYY/M/D" (no
        # zero-padding) to match the split-and-index expression this field
        # is consumed with elsewhere (e.g. field_mapping "date_revised|
        # split:/|index:0|int" to pull out just the year).
        date_revised_raw = citation["DateRevised"]
        # pylint: disable-next=consider-using-f-string
        date_revised = "{}/{}/{}".format(*[
            str(date_revised_raw[field]) for field in ["Year", "Month", "Day"]
        ])
        try:
            # Some articles split the abstract into multiple labeled
            # sections (Background, Methods, ...); join them into one
            # string. Articles with no abstract omit the key entirely.
            abstract = " ".join(article["Abstract"]["AbstractText"])
        except KeyError:
            abstract = "<not found>"

        title = article["ArticleTitle"]
        authors = _parse_authors(article)
        doi = _extract_doi(pubmed_article)
        publication = article['Journal']['Title']
        pmc_full_text = self._fetch_pmc_fulltext_id(paper_id, doi)

        return {
            "date_revised": date_revised,
            "title": title,
            "abstract": abstract,
            "doi": doi,
            "authors": authors,
            "publication": publication,
            "pmc_full_text_id": pmc_full_text
        }

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

        # Add recency filter if specified
        if recency_years > 0:
            # Imported locally since it is only needed for this branch.
            # pylint: disable-next=import-outside-toplevel
            from datetime import datetime
            current_year = datetime.now().year
            min_year = current_year - recency_years
            search_params["mindate"] = f"{min_year}/01/01"
            search_params["maxdate"] = f"{current_year}/12/31"
            search_params["datetype"] = "pdat"  # filter by publication date
            logger.debug("applying recency filter: %s-%s (last %s years)",
                         min_year, current_year, recency_years)

        logger.debug("searching pubmed with sort=pub_date (most recent first)")
        results = self.entrez_read(Entrez.esearch(**search_params))
        # esearch's IdList is empty (not absent) when nothing matches, so
        # the truthiness check also covers that case, not just a missing
        # key.
        if (id_list := results.get("IdList", None)):
            return [str(paper_id) for paper_id in id_list]
        logger.warning("No results found for query: %s", query)
        return []

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
        return "".join(text)

    def get_pubmed_fulltext(self,
                            pmc_id: str,
                            slug: str,
                            run_id: str | None = None) -> str | None:
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
        try:  # pylint: disable=broad-exception-caught
            # Check shared pool first
            base_dir = self.qualified_path / slug
            shared_dir = base_dir / "shared"
            shared_dir.mkdir(parents=True, exist_ok=True)
            fulltext_file = shared_dir / f"{pmc_id}.fulltext.html"

            # Check if already downloaded to shared pool
            if fulltext_file.exists():
                logger.info("Fulltext %s found in shared pool, reusing", pmc_id)
                with open(fulltext_file, encoding='utf-8') as f:
                    contents = f.read()

                # Create symlink to run directory if needed
                if run_id:
                    run_dir = base_dir / "runs" / run_id
                    run_dir.mkdir(parents=True, exist_ok=True)
                    _symlink_into_run(run_dir, f"{pmc_id}.fulltext.html")

                return contents

            contents = self._download_pmc_fulltext(pmc_id)

            # Save to shared pool
            with open(fulltext_file, 'w', encoding='utf-8') as f:
                f.write(contents)
            logger.info("Downloaded and saved fulltext %s to shared pool",
                        pmc_id)

            # Create symlink to run directory if run_id provided
            if run_id:
                run_dir = base_dir / "runs" / run_id
                run_dir.mkdir(parents=True, exist_ok=True)
                _symlink_into_run(run_dir, f"{pmc_id}.fulltext.html")

            return contents
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Failed to download PMC fulltext for %s: %s: %s",
                         pmc_id,
                         type(e).__name__, e)
            logger.debug(traceback.format_exc())
            return None

    async def _gather_paper_metadata(
            self, paper_ids: list[str], shared_dir: Path, run_dir: Path | None,
            semaphore: "asyncio.Semaphore") -> dict[str, Any]:
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
        import asyncio  # pylint: disable=import-outside-toplevel

        def link_to_run(paper_id: str) -> None:
            """Symlinks a shared-pool metadata file into the run directory."""
            # No-op without a run_id: metadata still lands in the shared
            # pool, it just is not exposed under a per-run directory.
            if not run_dir:
                return
            _symlink_into_run(run_dir, f"{paper_id}.metadata.json")

        async def fetch_paper_metadata(
                paper_id: str) -> tuple[str, dict[str, Any] | None]:
            """Fetches metadata for a single paper with rate limiting.

            Args:
                paper_id: PubMed article ID.

            Returns:
                Tuple of (paper_id, metadata_dict) or (paper_id, None) on error.
            """
            # Check shared pool first (smart cache across runs)
            metadata_file = shared_dir / f"{paper_id}.metadata.json"

            if metadata_file.exists():
                logger.debug("Paper %s metadata found in shared pool, reusing",
                             paper_id)
                with open(metadata_file, encoding='utf-8') as f:
                    metadata = json.load(f)

                link_to_run(paper_id)
                return (paper_id, metadata)

            async with semaphore:
                try:
                    # Entrez.efetch/elink use blocking urllib and entrez_read
                    # sleeps for rate limiting; run off the event loop so the
                    # gathered fetches actually proceed concurrently.
                    paper_details = await asyncio.to_thread(
                        self._fetch_paper_details, paper_id)

                    # Save metadata to shared pool
                    with open(metadata_file, "w", encoding="utf-8") as f:
                        json.dump(paper_details, f)
                    logger.debug("Saved metadata for %s to shared pool",
                                 paper_id)

                    link_to_run(paper_id)
                    return (paper_id, paper_details)

                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.warning("Failed to read paper %s: %s", paper_id, e)
                    logger.debug(traceback.format_exc())
                    return (paper_id, None)

        # Fetch all paper metadata in parallel
        logger.debug(
            "fetching metadata for %s papers in parallel (max 3 concurrent)",
            len(paper_ids))
        metadata_results = await asyncio.gather(
            *[fetch_paper_metadata(pid) for pid in paper_ids])

        # Collect successful results
        all_details = {
            paper_id: metadata
            for paper_id, metadata in metadata_results
            if metadata is not None
        }
        logger.debug("successfully fetched metadata for %s/%s papers",
                     len(all_details), len(paper_ids))
        return all_details

    async def _download_fulltexts_for_papers(
            self, papers_to_use: list[str], all_details: dict[str,
                                                              Any], slug: str,
            run_id: str | None, semaphore: "asyncio.Semaphore") -> None:
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
        # Imported locally, matching the other async helpers in this class.
        import asyncio  # pylint: disable=import-outside-toplevel

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

    def _supplement_from_shared_pool(self, shared_dir: Path, run_dir: Path,
                                     papers_to_use: list[str],
                                     all_details: dict[str, Any],
                                     fulltext_shortfall: int,
                                     max_papers: int) -> None:
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
        logger.info("attempting to supplement %s papers from shared pool",
                    fulltext_shortfall)

        # Scan shared pool for papers not in current run
        current_paper_ids_set = set(papers_to_use)
        supplement_candidates = []

        for metadata_file in shared_dir.glob("*.metadata.json"):
            paper_id = metadata_file.stem.replace(".metadata", "")
            if paper_id not in current_paper_ids_set:
                try:
                    with open(metadata_file, encoding='utf-8') as f:
                        metadata = json.load(f)
                    # Only consider papers with PMC fulltext
                    if metadata.get('pmc_full_text_id'):
                        # Check if fulltext exists in shared pool. Only
                        # papers already downloaded qualify here; this
                        # supplement path deliberately avoids issuing
                        # new PMC downloads for a shortfall.
                        pmc_id = metadata['pmc_full_text_id']
                        fulltext_file = (shared_dir / f"{pmc_id}.fulltext.html")
                        if fulltext_file.exists():
                            supplement_candidates.append((paper_id, metadata))
                # pylint: disable-next=broad-exception-caught
                except Exception as e:
                    # Corrupt/partial metadata file: skip this
                    # candidate rather than aborting the whole scan.
                    logger.debug("Failed to read shared pool paper %s: %s",
                                 paper_id, e)

        # Sort candidates by date (most recent first)
        def get_year(paper_tuple: tuple[str, dict[str, Any]]) -> int:
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

        # Take up to shortfall papers
        papers_to_supplement = supplement_candidates[:fulltext_shortfall]

        if papers_to_supplement:
            logger.info("Found %s papers in shared pool to supplement",
                        len(papers_to_supplement))

            # Create symlinks for supplemented papers
            for paper_id, metadata in papers_to_supplement:
                _symlink_into_run(run_dir, f"{paper_id}.metadata.json")
                pmc_id = metadata['pmc_full_text_id']
                _symlink_into_run(run_dir, f"{pmc_id}.fulltext.html")

                # Add to results
                papers_to_use.append(paper_id)
                all_details[paper_id] = metadata

            logger.info(
                "Supplemented %s papers from shared pool "
                "(total: %s/%s)", len(papers_to_supplement), len(papers_to_use),
                max_papers)
        else:
            logger.warning("No suitable papers found in shared pool for "
                           "supplementation")

    def _save_run_manifest(self, run_id: str, run_dir: Path,
                           papers_to_use: list[str],
                           all_details: dict[str, Any], query: str) -> None:
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
            "timestamp": os.path.getmtime(str(run_dir))
        }
        manifest_file = run_dir / ".manifest.json"
        with open(manifest_file, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2)
        logger.info("Saved manifest for run %s: %s papers", run_id,
                    len(papers_to_use))

    async def pubmed_search(self,
                            query: str,
                            slug: str,
                            max_papers: int = 10,
                            recency_years: int = 0,
                            run_id: str | None = None) -> dict[str, Any]:
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
        import asyncio  # pylint: disable=import-outside-toplevel

        # Request 3x papers to account for ~33% fulltext availability
        # we'll filter down to max_papers with fulltext
        search_buffer = max_papers * 3
        logger.info("Requesting %s papers from PubMed to find %s with fulltext",
                    search_buffer, max_papers)
        paper_ids = self.pubmed_search_ids(query,
                                           retmax=search_buffer,
                                           recency_years=recency_years)

        # Create shared pool and run-specific directories
        base_dir = self.qualified_path / slug
        shared_dir = base_dir / "shared"
        shared_dir.mkdir(parents=True, exist_ok=True)

        # Create run directory if run_id provided (enables per-run tracking)
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

        # Semaphore to limit concurrent entrez API calls (respect rate limits)
        # allow 3 concurrent (conservative, can increase to 10 with API key)
        semaphore = asyncio.Semaphore(3)

        all_details = await self._gather_paper_metadata(paper_ids, shared_dir,
                                                        run_dir, semaphore)

        # Filter to papers with PMC IDs and take first max_papers
        # (most recent, thanks to sort). asyncio.gather preserves input
        # order regardless of completion order, and dicts preserve
        # insertion order, so all_details still iterates in the same
        # most-recent-first order as paper_ids.
        papers_with_pmc = [
            paper_id for paper_id in all_details
            if all_details[paper_id].get('pmc_full_text_id') is not None
        ]
        # Take first max_papers with fulltext
        papers_to_use = papers_with_pmc[:max_papers]

        logger.info("fulltext availability: %s/%s papers have PMC fulltexts",
                    len(papers_with_pmc), len(all_details))
        logger.info("selecting %s/%s papers with fulltext (target: %s)",
                    len(papers_to_use), len(papers_with_pmc), max_papers)

        # Check if we're short of target
        fulltext_shortfall = max_papers - len(papers_to_use)
        if fulltext_shortfall > 0:
            logger.warning(
                "Short of target by %s papers - will attempt shared pool "
                "supplement", fulltext_shortfall)

        if len(papers_to_use) == 0:
            logger.error(
                "No papers have PMC fulltexts - (no documents to analyze)")

        await self._download_fulltexts_for_papers(papers_to_use, all_details,
                                                  slug, run_id, semaphore)

        # If short of target, supplement from shared pool
        # Requires run_dir because supplementing only makes sense when
        # building a per-run view (symlinks below need somewhere to go);
        # without a run_id there is no per-run result set to top up.
        if fulltext_shortfall > 0 and run_dir:
            self._supplement_from_shared_pool(shared_dir, run_dir,
                                              papers_to_use, all_details,
                                              fulltext_shortfall, max_papers)

        # Save manifest for this run if run_id provided
        if run_id and run_dir:
            self._save_run_manifest(run_id, run_dir, papers_to_use, all_details,
                                    query)

        # Return ONLY papers with fulltext (ready for analysis)
        final_details = {
            paper_id: all_details[paper_id] for paper_id in papers_to_use
        }
        logger.info("Returning %s papers with fulltext (target was %s)",
                    len(final_details), max_papers)
        return final_details
