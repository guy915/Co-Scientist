"""PubMed literature search tool using Bio.Entrez."""
# pylint: disable=inconsistent-quotes

import json
import logging
import os
import traceback
from time import sleep
from typing import Any, cast
from urllib.error import HTTPError, URLError

from Bio import Entrez

from mcp_server.entrez import initialize_entrez
from mcp_server.models import Article

logger = logging.getLogger(__name__)


def check_pubmed_available() -> str:
    """Checks if PubMed is available by making a test query.

    Returns:
        "true" if PubMed can be accessed successfully, "false" otherwise.
    """
    initialize_entrez()

    entrez_email = os.environ.get("ENTREZ_EMAIL")
    if not entrez_email:
        # NCBI requires (or strongly recommends) an identifying email for
        # Entrez API use; treat it as a hard prerequisite here.
        logger.warning(
            "PubMed unavailable: ENTREZ_EMAIL not set (recommended by NCBI)"
        )
        return "false"

    return "true" if _pubmed_canary_query_succeeds() else "false"


def _pubmed_canary_query_succeeds() -> bool:
    """Runs a cheap test query and reports whether PubMed responded.

    Returns:
        True if the test query returned at least one result; False if it
        returned no results or raised an error (details are logged).
    """
    logger.debug("Testing PubMed availability with test query...")

    try:
        # Cheap canary query: "cancer" is guaranteed to have results if
        # PubMed access is working at all.
        test_results = _entrez_read(
            Entrez.esearch(db="pubmed", term="cancer", retmax=1)
        )
    except HTTPError as e:
        _log_pubmed_canary_http_error(e)
        return False
    except URLError as e:
        _log_pubmed_canary_url_error(e)
        return False
    except Exception as e:  # pylint: disable=broad-exception-caught
        _log_pubmed_canary_generic_error(e)
        return False

    id_list = test_results.get("IdList", [])
    if id_list:
        logger.info("PubMed test query successful - PubMed is available")
        return True

    logger.warning(
        "PubMed test query returned no results - might be unavailable"
    )
    logger.debug("PubMed test query results: %s", test_results)
    return False


def _log_pubmed_canary_http_error(e: HTTPError) -> None:
    """Logs full diagnostic detail for a canary-query HTTPError.

    Args:
        e: The HTTPError raised by the canary query.
    """
    logger.error("PubMed test query failed: HTTP %s %s", e.code, e.reason)
    logger.error("Error type: %s", type(e).__name__)
    logger.debug("Request URL: %s", getattr(e, "url", "N/A"))
    logger.debug("Response headers: %s", dict(getattr(e, "headers", {})))

    # Try to read error response body
    try:  # pylint: disable=broad-exception-caught
        if hasattr(e, "read"):
            error_body = e.read()
            error_text = (
                error_body.decode("utf-8", errors="ignore")
                if isinstance(error_body, bytes)
                else error_body
            )
            logger.debug("Error response body: %s", error_text[:500])
    except Exception:  # pylint: disable=broad-exception-caught
        pass

    logger.debug("Full traceback:\n%s", traceback.format_exc())
    logger.warning("PubMed is unavailable - skipping PubMed literature review")


def _log_pubmed_canary_url_error(e: URLError) -> None:
    """Logs diagnostic detail for a canary-query URLError.

    Args:
        e: The URLError raised by the canary query.
    """
    logger.error(
        "PubMed test query failed: URL error - %s",
        e.reason if hasattr(e, "reason") else e,
    )
    logger.error("Error type: %s", type(e).__name__)
    if hasattr(e, "url"):
        logger.debug("Request URL: %s", e.url)
    logger.debug("Full traceback:\n%s", traceback.format_exc())
    logger.warning("PubMed is unavailable - skipping PubMed literature review")


def _log_pubmed_canary_generic_error(e: Exception) -> None:
    """Logs diagnostic detail for an unexpected canary-query error.

    Args:
        e: The exception raised by the canary query.
    """
    logger.error("PubMed test query failed: %s: %s", type(e).__name__, e)
    logger.debug("Full traceback:\n%s", traceback.format_exc())

    # Log Entrez configuration state
    logger.debug("Entrez.email set: %s", bool(Entrez.email))
    logger.debug("Entrez.api_key set: %s", bool(Entrez.api_key))

    logger.warning("PubMed is unavailable - skipping PubMed literature review")


def _entrez_read(handle: Any) -> dict[str, Any]:
    """Reads an Entrez response handle with rate limiting.

    Args:
        handle: Open Entrez response handle.

    Returns:
        Parsed result dict from Entrez.read().

    Raises:
        HTTPError: On HTTP-level errors from the Entrez API.
        URLError: On network-level errors.
    """
    # NCBI's rate limit is 3 requests/second without an API key; sleeping
    # before each read keeps this client comfortably under that.
    sleep(0.25)

    try:
        results = Entrez.read(handle)
        handle.close()
        return cast(dict[str, Any], results)
    except HTTPError as e:
        _log_entrez_read_http_error(e)
        handle.close()
        raise
    except URLError as e:
        _log_entrez_read_url_error(e)
        handle.close()
        raise
    except Exception as e:  # pylint: disable=broad-exception-caught
        _log_entrez_read_generic_error(e, handle)
        handle.close()
        raise


def _log_entrez_http_error_body(e: HTTPError) -> None:
    """Logs the raw response body off an HTTPError, if still readable.

    Args:
        e: The HTTPError whose response body should be logged.
    """
    try:  # pylint: disable=broad-exception-caught
        if hasattr(e, "read"):
            error_body = e.read()
            error_text = (
                error_body.decode("utf-8", errors="ignore")
                if isinstance(error_body, bytes)
                else error_body
            )
            logger.debug("Error response body: %s", error_text[:1000])
    except Exception as read_err:  # pylint: disable=broad-exception-caught
        logger.debug("Could not read error response body: %s", read_err)


def _log_entrez_read_http_error(e: HTTPError) -> None:
    """Logs full diagnostic detail for an HTTPError from an Entrez read.

    Args:
        e: The HTTPError raised while reading the Entrez response.
    """
    logger.error(
        "Entrez HTTP error (%s): %s %s", type(e).__name__, e.code, e.reason
    )
    if hasattr(e, "url"):
        logger.debug("Request URL: %s", e.url)
    if hasattr(e, "headers"):
        logger.debug("Response headers: %s", dict(e.headers))

    # Try to read error response body from the exception
    _log_entrez_http_error_body(e)


def _log_entrez_read_url_error(e: URLError) -> None:
    """Logs diagnostic detail for a URLError from an Entrez read.

    Args:
        e: The URLError raised while reading the Entrez response.
    """
    logger.error(
        "Entrez URL error (%s): %s",
        type(e).__name__,
        e.reason if hasattr(e, "reason") else e,
    )
    if hasattr(e, "url"):
        logger.debug("Request URL: %s", e.url)


def _log_entrez_read_generic_error(e: Exception, handle: Any) -> None:
    """Logs diagnostic detail for an unexpected error from an Entrez read.

    Args:
        e: The exception raised while reading the Entrez response.
        handle: The Entrez response handle being read, used to capture a
            raw-response snippet if it is still readable.
    """
    logger.error("Entrez read error (%s): %s", type(e).__name__, e)

    # Try to read raw response from handle if possible
    try:  # pylint: disable=broad-exception-caught
        if hasattr(handle, "read"):
            raw_response = handle.read()
            if isinstance(raw_response, bytes):
                raw_response = raw_response.decode("utf-8", errors="ignore")
            logger.debug(
                "Raw response from handle (first 1000 chars): %s",
                raw_response[:1000],
            )
    except Exception:  # pylint: disable=broad-exception-caught
        pass

    logger.debug("Full traceback:\n%s", traceback.format_exc())


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
    paper_results = _entrez_read(Entrez.efetch(db="pubmed", id=paper_id))

    pubmed_article = paper_results["PubmedArticle"][0]
    medline = pubmed_article["MedlineCitation"]
    article_data = medline["Article"]

    title = article_data.get("ArticleTitle", "Unknown")
    abstract = _parse_pubmed_abstract(article_data)
    authors = _parse_pubmed_authors(article_data)
    doi = _parse_pubmed_doi(pubmed_article)
    venue, year = _parse_pubmed_venue_year(article_data)

    # Prefer the DOI resolver link when available since it points at the
    # publisher's copy; fall back to the PubMed record page otherwise.
    url = (
        f"https://doi.org/{doi}"
        if doi
        else f"https://pubmed.ncbi.nlm.nih.gov/{paper_id}/"
    )

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
        return (
            " ".join(str(part) for part in abstract_parts)
            if abstract_parts
            else None
        )
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


def search_pubmed(query: str, max_papers: int = 10) -> str:
    """Searches PubMed for papers and returns Article objects with metadata.

    Args:
        query: Search query for PubMed.
        max_papers: Maximum number of papers to retrieve.

    Returns:
        JSON string with list of articles for LLM agent consumption.
    """
    initialize_entrez()

    logger.info(
        "Searching PubMed with query: '%s' (max %s papers)", query, max_papers
    )

    try:  # pylint: disable=broad-exception-caught
        # Step 1: esearch resolves the query to a list of PubMed ids.
        results = _entrez_read(
            Entrez.esearch(db="pubmed", term=query, retmax=max_papers)
        )
        id_list = results.get("IdList", [])

        if not id_list:
            logger.warning("No results found for query: %s", query)
            return json.dumps({"results": [], "count": 0})

        logger.info("Found %s papers, fetching metadata...", len(id_list))

        # Step 2: efetch pulls full metadata per id.
        articles = _fetch_pubmed_articles(id_list)

        logger.info(
            "Successfully retrieved %s papers from PubMed", len(articles)
        )

        articles_json = [article.to_dict() for article in articles]
        return json.dumps({"results": articles_json, "count": len(articles)})

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error searching PubMed: %s", e)
        return json.dumps({"error": str(e), "results": [], "count": 0})


def _fetch_pubmed_articles(id_list: list[str]) -> list[Article]:
    """Fetches metadata for each PubMed id, skipping any that fail.

    Each id is fetched (and any failure handled) independently so one
    malformed record doesn't abort the whole batch.

    Args:
        id_list: PubMed ids to fetch metadata for.

    Returns:
        Article objects for the ids that were fetched successfully.
    """
    articles = []
    for paper_id in id_list:
        try:  # pylint: disable=broad-exception-caught
            article = _fetch_pubmed_article(paper_id)
            articles.append(article)
            logger.debug(
                "fetched metadata for paper %s: %s...",
                paper_id,
                article.title[:50],
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Failed to fetch metadata for paper %s: %s", paper_id, e
            )
            continue
    return articles
