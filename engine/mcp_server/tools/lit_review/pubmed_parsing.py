"""Parsing of Entrez PubMed records into ``Article`` objects.

Converts the nested Entrez efetch response for a single PubMed id into a flat
``Article``, with focused helpers for the abstract, authors, DOI, and
journal venue/year sub-structures.
"""

from typing import Any

from Bio import Entrez

from mcp_server.entrez import read_entrez
from mcp_server.entrez_rate_limit import entrez_call
from mcp_server.models import Article
from mcp_server.tools.text import clean_markup


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
