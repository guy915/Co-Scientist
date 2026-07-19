"""Entrez-backed PubMed client: search and per-paper metadata fetching."""

import logging
from pathlib import Path
from time import sleep
from typing import Any

from Bio import Entrez

from mcp_server.entrez import initialize_entrez

logger = logging.getLogger(__name__)

# Configure Entrez credentials at import so the source is ready to query.
initialize_entrez()


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
    names = []
    for author in article["AuthorList"]:
        name = (
            f"{author.get('ForeName', '<invalid>')} "
            f"{author.get('LastName', '<invalid>')}"
        )
        if "<invalid>" not in name:
            names.append(name)
    return names


def _extract_doi(pubmed_article: dict[str, Any]) -> str:
    """Extracts the DOI from a PubmedArticle's ArticleIdList.

    Args:
        pubmed_article: Entrez-parsed ``PubmedArticle`` element.

    Returns:
        The DOI string, or "<not found>" if no ArticleIdList entry is
        tagged with ``IdType="doi"``.
    """
    # ArticleIdList mixes several ID types (pubmed, doi, pmc, ...); filter
    # down to the one tagged IdType="doi". The "<not found>" default covers
    # the empty case where no DOI was assigned.
    return next(
        (
            str(element)
            for element in filter(
                lambda xml_string: (
                    xml_string.attributes.get("IdType", None) == "doi"
                ),
                pubmed_article["PubmedData"]["ArticleIdList"],
            )
        ),
        "<not found>",
    )


class _EntrezClient:
    """PubMed source base: Entrez search and per-paper metadata primitives."""

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
                Entrez.elink(dbfrom="pubmed", db="pmc", id=paper_id)
            )
            return str(related[0]["LinkSetDb"][0]["Link"][0]["Id"])
        except Exception:
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
        date_revised = "{}/{}/{}".format(
            *[
                str(date_revised_raw[field])
                for field in ["Year", "Month", "Day"]
            ]
        )
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
        publication = article["Journal"]["Title"]
        pmc_full_text = self._fetch_pmc_fulltext_id(paper_id, doi)

        return {
            "date_revised": date_revised,
            "title": title,
            "abstract": abstract,
            "doi": doi,
            "authors": authors,
            "publication": publication,
            "pmc_full_text_id": pmc_full_text,
        }

    def pubmed_search_ids(
        self, query: str, retmax: int = 10, recency_years: int = 0
    ) -> list[str]:
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
            "sort": "pub_date",
        }

        # Add recency filter if specified
        if recency_years > 0:
            # Imported locally since it is only needed for this branch.
            from datetime import datetime

            current_year = datetime.now().year
            min_year = current_year - recency_years
            search_params["mindate"] = f"{min_year}/01/01"
            search_params["maxdate"] = f"{current_year}/12/31"
            search_params["datetype"] = "pdat"  # filter by publication date
            logger.debug(
                "applying recency filter: %s-%s (last %s years)",
                min_year,
                current_year,
                recency_years,
            )

        logger.debug("searching pubmed with sort=pub_date (most recent first)")
        results = self.entrez_read(Entrez.esearch(**search_params))
        # esearch's IdList is empty (not absent) when nothing matches, so
        # the truthiness check also covers that case, not just a missing
        # key.
        if id_list := results.get("IdList", None):
            return [str(paper_id) for paper_id in id_list]
        logger.warning("No results found for query: %s", query)
        return []
