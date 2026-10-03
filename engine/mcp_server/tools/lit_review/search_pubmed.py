"""PubMed metadata, availability, record parsing and cached fulltext tools."""

import asyncio
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from Bio import Entrez

from mcp_server.entrez import entrez_call, initialize_entrez, read_entrez
from mcp_server.literature_review import PubmedSource
from mcp_server.pubmed_client import search_with_relaxation
from mcp_server.text_extraction import clean_markup, extract_text_from_pmc_html

logger = logging.getLogger(__name__)


def check_pubmed_available() -> str:
    """Return 'true' when a cheap PubMed canary query returns a result."""
    initialize_entrez()
    try:
        results = read_entrez(
            entrez_call(Entrez.esearch, db="pubmed", term="cancer", retmax=1)
        )
        return "true" if results.get("IdList") else "false"
    except Exception as exc:
        logger.warning("PubMed availability query failed: %s", exc)
        logger.debug("PubMed availability query failed", exc_info=True)
        return "false"


def _esearch_pubmed_ids(query: str, max_papers: int) -> list[str]:
    """Use the same query relaxation policy as fulltext corpus search."""

    def search(term: str, retmax: int, _recency_years: int) -> list[str]:
        results = read_entrez(
            entrez_call(Entrez.esearch, db="pubmed", term=term, retmax=retmax)
        )
        ids: list[str] = results.get("IdList", [])
        return ids

    return search_with_relaxation(query, max_papers, 0, search)


def search_pubmed(query: str, max_papers: int = 10) -> str:
    """Search PubMed and return article metadata as a JSON result envelope.

    Args:
        query: Search query for PubMed.
        max_papers: Maximum number of papers to retrieve.
    """
    initialize_entrez()
    try:
        articles = []
        for paper_id in _esearch_pubmed_ids(query, max_papers):
            try:
                articles.append(_fetch_pubmed_article(paper_id).to_dict())
            except Exception as exc:
                # A malformed paper must not discard successful siblings.
                logger.warning(
                    "Failed to fetch metadata for paper %s: %s", paper_id, exc
                )
        return json.dumps({"results": articles, "count": len(articles)})
    except Exception as exc:
        logger.error("Error searching PubMed: %s", exc)
        return json.dumps({"error": str(exc), "results": [], "count": 0})


@dataclass
class Article:
    """A literature article with extracted content and metadata."""

    title: str
    url: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    # Publication venue, e.g. journal or conference name.
    venue: str | None = None
    # Citation count, when available from the source; 0 if unknown.
    citations: int = 0
    abstract: str | None = None
    # Full extracted text, e.g. markdown from PMC fulltext (see
    # text_extraction.py); None if only metadata/abstract was retrieved.
    content: str | None = None
    # Source-specific identifier (e.g. PubMed ID), independent of url.
    source_id: str | None = None
    # Default reflects this dataclass's shared, multi-source origin; PubMed
    # tools in this server explicitly set "pubmed" via field_mapping.
    source: str = "google_scholar"
    # Direct links to downloadable PDF(s), if the source exposes any.
    pdf_links: list[str] = field(default_factory=list)
    # Set true once an agent has actually consulted this article's content,
    # as opposed to it merely appearing in search results.
    used_in_analysis: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Converts the article to a dictionary for serialization.

        Returns:
            Dict with all article fields.
        """
        return asdict(self)


def _pubmed_article_url(doi: str | None, paper_id: str) -> str:
    """Returns the best canonical URL for a PubMed article.

    Args:
        doi: The article DOI, if known.
        paper_id: The PubMed id, used as a fallback.

    Returns:
        The DOI resolver link when a DOI is available, otherwise the
        PubMed record page.
    """
    # Prefer the DOI resolver link when available since it points at the
    # publisher's copy; fall back to the PubMed record page otherwise.
    return (
        f"https://doi.org/{doi}"
        if doi
        else f"https://pubmed.ncbi.nlm.nih.gov/{paper_id}/"
    )


def _fetch_pubmed_article(paper_id: str) -> Article:
    """Fetches and parses metadata for a single PubMed article.

    Args:
        paper_id: PubMed id to fetch.

    Returns:
        Article populated from the Entrez efetch response.

    Raises:
        Exception: Propagated from the Entrez efetch call or from an
            unexpected response structure; the caller treats any failure
            as a per-paper skip.
    """
    paper_results = read_entrez(
        entrez_call(Entrez.efetch, db="pubmed", id=paper_id)
    )

    pubmed_article = paper_results["PubmedArticle"][0]
    medline = pubmed_article["MedlineCitation"]
    article_data = medline["Article"]

    # PubMed formats inside its metadata -- italics around species names,
    # subscripts inside gene symbols -- and an agent quoting a title reads
    # it as text.
    title = clean_markup(article_data.get("ArticleTitle")) or "Unknown"
    abstract = _parse_pubmed_abstract(article_data)
    authors = _parse_pubmed_authors(article_data)
    doi = _parse_pubmed_doi(pubmed_article)
    venue, year = _parse_pubmed_venue_year(article_data)
    url = _pubmed_article_url(doi, paper_id)

    return Article(
        title=title,
        url=url,
        authors=authors,
        year=year,
        venue=venue,
        abstract=abstract,
        source_id=paper_id,
        source="pubmed",
    )


def _parse_pubmed_abstract(article_data: dict[str, Any]) -> str | None:
    """Joins a possibly multi-part PubMed abstract into one string.

    PubMed abstracts are sometimes split into multiple labeled sections
    (e.g. Background/Methods/Results); join them into one string.

    Args:
        article_data: The Entrez-parsed ``Article`` mapping.

    Returns:
        The joined abstract text, or None if unavailable/malformed.
    """
    try:
        abstract_parts = article_data.get("Abstract", {}).get(
            "AbstractText", []
        )
        if not abstract_parts:
            return None
        # An absent abstract stays None rather than becoming "": ranking
        # reads the empty string as evidence it has already seen.
        return clean_markup(" ".join(str(part) for part in abstract_parts))
    except (KeyError, TypeError):
        return None


def _author_full_name(author: Any) -> str | None:
    """Builds one "Forename Lastname" string from an AuthorList entry.

    Args:
        author: A single entry from the article's AuthorList.

    Returns:
        "Forename Lastname" if the entry is a dict with both name parts,
        else None.
    """
    if not isinstance(author, dict):
        return None
    first_name = author.get("ForeName", "")
    last_name = author.get("LastName", "")
    return f"{first_name} {last_name}" if first_name and last_name else None


def _parse_pubmed_authors(article_data: dict[str, Any]) -> list[str]:
    """Builds "Forename Lastname" strings for each author on an article.

    Args:
        article_data: The Entrez-parsed ``Article`` mapping.

    Returns:
        List of author display names; entries missing either name part
        are skipped. Empty list if the author list is unavailable.
    """
    authors = []
    try:
        author_list = article_data.get("AuthorList", [])
        for author in author_list:
            name = _author_full_name(author)
            if name:
                authors.append(name)
    except (KeyError, TypeError):
        pass
    return authors


def _parse_pubmed_doi(pubmed_article: dict[str, Any]) -> str | None:
    """Extracts the DOI from a PubmedArticle's ArticleIdList.

    Args:
        pubmed_article: The Entrez-parsed ``PubmedArticle`` element.

    Returns:
        The DOI string, or None if not present/malformed.
    """
    doi = None
    try:
        # ArticleIdList mixes several id types (pubmed, doi, pii, ...);
        # each entry carries its type as an XML attribute, so filter for
        # "doi" specifically.
        article_ids = pubmed_article.get("PubmedData", {}).get(
            "ArticleIdList", []
        )
        for article_id in article_ids:
            if (
                hasattr(article_id, "attributes")
                and article_id.attributes.get("IdType") == "doi"
            ):
                doi = str(article_id)
                break
    except (KeyError, TypeError, AttributeError):
        pass
    return doi


def _parse_pubmed_venue_year(
    article_data: dict[str, Any],
) -> tuple[str | None, int | None]:
    """Extracts the journal venue and publication year of an article.

    Args:
        article_data: The Entrez-parsed ``Article`` mapping.

    Returns:
        A (venue, year) tuple; either element is None if unavailable or
        malformed.
    """
    venue = None
    year = None
    try:
        journal_info = article_data.get("Journal", {})
        venue = journal_info.get("Title")

        pub_date = journal_info.get("JournalIssue", {}).get("PubDate", {})
        year_str = pub_date.get("Year")
        if year_str:
            year = int(year_str)
    except (KeyError, TypeError, ValueError):
        pass
    return venue, year


def _read_and_extract_fulltext(html_file: Path) -> str:
    return extract_text_from_pmc_html(html_file.read_text(encoding="utf-8"))


async def _extract_fulltext(
    pmc_id: str, metadata: dict[str, Any], run_dir: Path
) -> bool:
    """Attach fulltext when available, leaving metadata usable on failure."""
    try:
        html_file = run_dir / f"{pmc_id}.fulltext.html"
        if not html_file.exists():
            logger.warning(
                "Fulltext file not found for %s at %s", pmc_id, html_file
            )
            return False
        # Full-article parsing is CPU-heavy; keep it off the event loop.
        metadata["fulltext"] = await asyncio.to_thread(
            _read_and_extract_fulltext, html_file
        )
        return True
    except Exception as exc:
        logger.error("Failed to extract text from %s: %s", pmc_id, exc)
        return False


def _pubmed_cache_dir() -> Path:
    cache_dir = Path(
        os.getenv("COSCIENTIST_LIT_REVIEW_DIR", "./cache/literature_review")
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


async def pubmed_search_with_fulltext(  # noqa: PLR0913
    query: str,
    slug: str,
    max_papers: int = 10,
    recency_years: int = 0,
    run_id: str | None = None,
    *,
    include_fulltext: bool = True,
) -> dict[str, Any]:
    """Search PubMed and attach readable text from cached PMC articles.

    Args:
        query: PubMed boolean query (AND/OR/NOT operators).
        slug: Identifier for organizing results (research goal hash).
        max_papers: Maximum papers to retrieve.
        recency_years: Filter to papers from last N years (0 = no filter).
        run_id: Unique run identifier for per-run tracking.
        include_fulltext: Skip downloads and extraction when false, retaining
            PMC-linked selection and metadata provenance.

    Returns:
        Metadata keyed by PubMed ID, with fulltext where available.
    """
    lit_review_dir = _pubmed_cache_dir()
    source = PubmedSource(lit_review_dir / "pubmed")
    results = await source.pubmed_search(
        query,
        slug,
        max_papers,
        recency_years,
        run_id,
        include_fulltext=include_fulltext,
    )
    if include_fulltext:
        base_dir = lit_review_dir / "pubmed" / slug
        run_dir = base_dir / "runs" / run_id if run_id else base_dir
        extracted = sum(
            await asyncio.gather(
                *(
                    _extract_fulltext(pmc_id, metadata, run_dir)
                    for metadata in results.values()
                    if (pmc_id := metadata.get("pmc_full_text_id"))
                )
            )
        )
        logger.info(
            "Extracted fulltext for %s/%s papers", extracted, len(results)
        )
    return results
