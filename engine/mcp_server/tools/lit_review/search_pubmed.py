"""PubMed literature search tool using Bio.Entrez."""

import json
import logging
import os
import traceback
from urllib.error import HTTPError, URLError

from Bio import Entrez

from mcp_server.entrez import initialize_entrez
from mcp_server.models import Article

# Re-export the relocated helpers so their original import paths
# (``...search_pubmed import _entrez_read``, etc.) keep resolving.
from .pubmed_entrez import (
    _entrez_read as _entrez_read,
)
from .pubmed_entrez import (
    _log_entrez_http_error_body as _log_entrez_http_error_body,
)
from .pubmed_entrez import (
    _log_entrez_read_generic_error as _log_entrez_read_generic_error,
)
from .pubmed_entrez import (
    _log_entrez_read_http_error as _log_entrez_read_http_error,
)
from .pubmed_entrez import (
    _log_entrez_read_url_error as _log_entrez_read_url_error,
)
from .pubmed_parsing import (
    _author_full_name as _author_full_name,
)
from .pubmed_parsing import (
    _fetch_pubmed_article as _fetch_pubmed_article,
)
from .pubmed_parsing import (
    _parse_pubmed_abstract as _parse_pubmed_abstract,
)
from .pubmed_parsing import (
    _parse_pubmed_authors as _parse_pubmed_authors,
)
from .pubmed_parsing import (
    _parse_pubmed_doi as _parse_pubmed_doi,
)
from .pubmed_parsing import (
    _parse_pubmed_venue_year as _parse_pubmed_venue_year,
)
from .pubmed_parsing import (
    _pubmed_article_url as _pubmed_article_url,
)

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
    except Exception as e:
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
    try:
        if hasattr(e, "read"):
            error_body = e.read()
            error_text = (
                error_body.decode("utf-8", errors="ignore")
                if isinstance(error_body, bytes)
                else error_body
            )
            logger.debug("Error response body: %s", error_text[:500])
    except Exception:
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


def _esearch_pubmed_ids(query: str, max_papers: int) -> list[str]:
    """Resolves a PubMed query to a list of article ids.

    Args:
        query: Search query for PubMed.
        max_papers: Maximum number of ids to return.

    Returns:
        The list of PubMed ids matching the query (possibly empty).
    """
    results = _entrez_read(
        Entrez.esearch(db="pubmed", term=query, retmax=max_papers)
    )
    id_list: list[str] = results.get("IdList", [])
    return id_list


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

    try:
        # Step 1: esearch resolves the query to a list of PubMed ids.
        id_list = _esearch_pubmed_ids(query, max_papers)

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

    except Exception as e:
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
        try:
            article = _fetch_pubmed_article(paper_id)
            articles.append(article)
            logger.debug(
                "fetched metadata for paper %s: %s...",
                paper_id,
                article.title[:50],
            )
        except Exception as e:
            logger.warning(
                "Failed to fetch metadata for paper %s: %s", paper_id, e
            )
            continue
    return articles
