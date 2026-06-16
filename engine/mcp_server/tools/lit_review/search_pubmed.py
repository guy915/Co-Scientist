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
"""PubMed literature search tool using Bio.Entrez."""
# pylint: disable=inconsistent-quotes

import json
import logging
import os
import ssl
import traceback
from time import sleep
from typing import Any, cast
from urllib.error import HTTPError, URLError

from Bio import Entrez

from mcp_server.models import Article

logger = logging.getLogger(__name__)

_entrez_initialized = False


def _initialize_entrez() -> None:
    """Initializes Entrez with email and API key from environment.

    Only logs warnings once on first call.
    """
    global _entrez_initialized  # pylint: disable=global-statement

    if _entrez_initialized:
        return

    _entrez_initialized = True
    ssl_verify = os.environ.get("DISABLE_SSL_VERIFY",
                                "").lower() in ("true", "1", "yes")
    logger.debug("SSL verification: %s", ssl_verify)

    if not Entrez.email:
        entrez_email = os.environ.get("ENTREZ_EMAIL")
        if entrez_email:
            Entrez.email = entrez_email
            logger.info("Initialized Entrez with email: %s", entrez_email)
        else:
            logger.warning(
                "ENTREZ_EMAIL not set - PubMed may have stricter rate limits")

    if not Entrez.api_key:
        entrez_key = os.environ.get("ENTREZ_API_KEY")
        if entrez_key:
            Entrez.api_key = entrez_key
            logger.info("Initialized Entrez with API key")
        else:
            logger.info("ENTREZ_API_KEY not set - using default rate limits")

    if not ssl_verify:
        # Deliberate runtime monkeypatch to disable cert verification; the two
        # SSL context factory signatures are interchangeable at call sites here.
        ssl._create_default_https_context = ssl._create_unverified_context  # type: ignore[assignment]  # pylint: disable=protected-access


def check_pubmed_available() -> str:
    """Checks if PubMed is available by making a test query.

    Returns:
        "true" if PubMed can be accessed successfully, "false" otherwise.
    """
    _initialize_entrez()

    entrez_email = os.environ.get("ENTREZ_EMAIL")
    if not entrez_email:
        logger.warning(
            "PubMed unavailable: ENTREZ_EMAIL not set (recommended by NCBI)")
        return "false"

    try:
        logger.debug("Testing PubMed availability with test query...")

        test_results = _entrez_read(
            Entrez.esearch(db="pubmed", term="cancer", retmax=1))

        id_list = test_results.get("IdList", [])
        if id_list:
            logger.info("PubMed test query successful - PubMed is available")
            return "true"
        else:
            logger.warning(
                "PubMed test query returned no results - might be unavailable")
            logger.debug("PubMed test query results: %s", test_results)
            return "false"

    except HTTPError as e:
        logger.error("PubMed test query failed: HTTP %s %s", e.code, e.reason)
        logger.error("Error type: %s", type(e).__name__)
        logger.debug("Request URL: %s", getattr(e, 'url', 'N/A'))
        logger.debug("Response headers: %s", dict(getattr(e, 'headers', {})))

        # Try to read error response body
        try:  # pylint: disable=broad-exception-caught
            if hasattr(e, 'read'):
                error_body = e.read()
                error_text = (error_body.decode('utf-8', errors='ignore')
                              if isinstance(error_body, bytes) else error_body)
                logger.debug("Error response body: %s", error_text[:500])
        except Exception:  # pylint: disable=broad-exception-caught
            pass

        logger.debug("Full traceback:\n%s", traceback.format_exc())
        logger.warning(
            "PubMed is unavailable - skipping PubMed literature review")
        return "false"

    except URLError as e:
        logger.error("PubMed test query failed: URL error - %s",
                     e.reason if hasattr(e, 'reason') else e)
        logger.error("Error type: %s", type(e).__name__)
        if hasattr(e, 'url'):
            logger.debug("Request URL: %s", e.url)
        logger.debug("Full traceback:\n%s", traceback.format_exc())
        logger.warning(
            "PubMed is unavailable - skipping PubMed literature review")
        return "false"

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("PubMed test query failed: %s: %s", type(e).__name__, e)
        logger.debug("Full traceback:\n%s", traceback.format_exc())

        # Log Entrez configuration state
        logger.debug("Entrez.email set: %s", bool(Entrez.email))
        logger.debug("Entrez.api_key set: %s", bool(Entrez.api_key))

        logger.warning(
            "PubMed is unavailable - skipping PubMed literature review")
        return "false"


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
    sleep(0.25)

    try:
        results = Entrez.read(handle)
        handle.close()
        return cast(dict[str, Any], results)
    except HTTPError as e:
        # Log HTTP error details
        logger.error("Entrez HTTP error (%s): %s %s",
                     type(e).__name__, e.code, e.reason)
        if hasattr(e, 'url'):
            logger.debug("Request URL: %s", e.url)
        if hasattr(e, 'headers'):
            logger.debug("Response headers: %s", dict(e.headers))

        # Try to read error response body from the exception
        try:  # pylint: disable=broad-exception-caught
            if hasattr(e, 'read'):
                error_body = e.read()
                error_text = (error_body.decode('utf-8', errors='ignore')
                              if isinstance(error_body, bytes) else error_body)
                logger.debug("Error response body: %s", error_text[:1000])
        except Exception as read_err:  # pylint: disable=broad-exception-caught
            logger.debug("Could not read error response body: %s", read_err)

        handle.close()
        raise
    except URLError as e:
        logger.error("Entrez URL error (%s): %s",
                     type(e).__name__, e.reason if hasattr(e, 'reason') else e)
        if hasattr(e, 'url'):
            logger.debug("Request URL: %s", e.url)
        handle.close()
        raise
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Entrez read error (%s): %s", type(e).__name__, e)

        # Try to read raw response from handle if possible
        try:  # pylint: disable=broad-exception-caught
            if hasattr(handle, 'read'):
                raw_response = handle.read()
                if isinstance(raw_response, bytes):
                    raw_response = raw_response.decode('utf-8', errors='ignore')
                logger.debug("Raw response from handle (first 1000 chars): %s",
                             raw_response[:1000])
        except Exception:  # pylint: disable=broad-exception-caught
            pass

        logger.debug("Full traceback:\n%s", traceback.format_exc())
        handle.close()
        raise


def search_pubmed(query: str, max_papers: int = 10) -> str:
    """Searches PubMed for papers and returns Article objects with metadata.

    Args:
        query: Search query for PubMed.
        max_papers: Maximum number of papers to retrieve.

    Returns:
        JSON string with list of articles for LLM agent consumption.
    """
    _initialize_entrez()

    logger.info("Searching PubMed with query: '%s' (max %s papers)", query,
                max_papers)

    try:  # pylint: disable=broad-exception-caught
        results = _entrez_read(
            Entrez.esearch(db="pubmed", term=query, retmax=max_papers))
        id_list = results.get("IdList", [])

        if not id_list:
            logger.warning("No results found for query: %s", query)
            return json.dumps({"results": [], "count": 0})

        logger.info("Found %s papers, fetching metadata...", len(id_list))

        articles = []
        for paper_id in id_list:
            try:  # pylint: disable=broad-exception-caught
                paper_results = _entrez_read(
                    Entrez.efetch(db="pubmed", id=paper_id))

                pubmed_article = paper_results["PubmedArticle"][0]
                medline = pubmed_article["MedlineCitation"]
                article_data = medline["Article"]

                title = article_data.get("ArticleTitle", "Unknown")

                try:
                    abstract_parts = article_data.get("Abstract", {}).get(
                        "AbstractText", [])
                    abstract = (" ".join(str(part) for part in abstract_parts)
                                if abstract_parts else None)
                except (KeyError, TypeError):
                    abstract = None

                authors = []
                try:
                    author_list = article_data.get("AuthorList", [])
                    for author in author_list:
                        if isinstance(author, dict):
                            first_name = author.get("ForeName", "")
                            last_name = author.get("LastName", "")
                            if first_name and last_name:
                                authors.append(f"{first_name} {last_name}")
                except (KeyError, TypeError):
                    pass

                doi = None
                try:
                    article_ids = pubmed_article.get("PubmedData", {}).get(
                        "ArticleIdList", [])
                    for article_id in article_ids:
                        if (hasattr(article_id, "attributes") and
                                article_id.attributes.get("IdType") == "doi"):
                            doi = str(article_id)
                            break
                except (KeyError, TypeError, AttributeError):
                    pass

                venue = None
                year = None
                try:
                    journal_info = article_data.get("Journal", {})
                    venue = journal_info.get("Title")

                    pub_date = journal_info.get("JournalIssue",
                                                {}).get("PubDate", {})
                    year_str = pub_date.get("Year")
                    if year_str:
                        year = int(year_str)
                except (KeyError, TypeError, ValueError):
                    pass

                url = f"https://pubmed.ncbi.nlm.nih.gov/{paper_id}/"
                if doi:
                    url = f"https://doi.org/{doi}"

                article = Article(title=title,
                                  url=url,
                                  authors=authors,
                                  year=year,
                                  venue=venue,
                                  abstract=abstract,
                                  source_id=paper_id,
                                  source="pubmed")

                articles.append(article)
                logger.debug("fetched metadata for paper %s: %s...", paper_id,
                             title[:50])

            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("Failed to fetch metadata for paper %s: %s",
                               paper_id, e)
                continue

        logger.info("Successfully retrieved %s papers from PubMed",
                    len(articles))

        articles_json = [article.to_dict() for article in articles]
        return json.dumps({"results": articles_json, "count": len(articles)})

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error searching PubMed: %s", e)
        return json.dumps({"error": str(e), "results": [], "count": 0})


def search_pubmed_raw(query: str, max_papers: int = 10) -> list[Article]:
    """Searches PubMed and returns Article objects for direct API usage.

    Args:
        query: Search query for PubMed.
        max_papers: Maximum number of papers to retrieve.

    Returns:
        List of Article objects with title, abstract, authors, DOI, etc.

    Raises:
        Exception: Propagates exceptions from the Entrez API.
    """
    _initialize_entrez()

    logger.info("Searching PubMed with query: '%s' (max %s papers)", query,
                max_papers)

    try:  # pylint: disable=broad-exception-caught
        results = _entrez_read(
            Entrez.esearch(db="pubmed", term=query, retmax=max_papers))
        id_list = results.get("IdList", [])

        if not id_list:
            logger.warning("No results found for query: %s", query)
            return []

        logger.info("Found %s papers, fetching metadata...", len(id_list))

        articles = []
        for paper_id in id_list:
            try:  # pylint: disable=broad-exception-caught
                paper_results = _entrez_read(
                    Entrez.efetch(db="pubmed", id=paper_id))

                pubmed_article = paper_results["PubmedArticle"][0]
                medline = pubmed_article["MedlineCitation"]
                article_data = medline["Article"]

                title = article_data.get("ArticleTitle", "Unknown")

                try:
                    abstract_parts = article_data.get("Abstract", {}).get(
                        "AbstractText", [])
                    abstract = (" ".join(str(part) for part in abstract_parts)
                                if abstract_parts else None)
                except (KeyError, TypeError):
                    abstract = None

                authors = []
                try:
                    author_list = article_data.get("AuthorList", [])
                    for author in author_list:
                        if isinstance(author, dict):
                            first_name = author.get("ForeName", "")
                            last_name = author.get("LastName", "")
                            if first_name and last_name:
                                authors.append(f"{first_name} {last_name}")
                except (KeyError, TypeError):
                    pass

                doi = None
                try:
                    article_ids = pubmed_article.get("PubmedData", {}).get(
                        "ArticleIdList", [])
                    for article_id in article_ids:
                        if (hasattr(article_id, "attributes") and
                                article_id.attributes.get("IdType") == "doi"):
                            doi = str(article_id)
                            break
                except (KeyError, TypeError, AttributeError):
                    pass

                venue = None
                year = None
                try:
                    journal_info = article_data.get("Journal", {})
                    venue = journal_info.get("Title")

                    pub_date = journal_info.get("JournalIssue",
                                                {}).get("PubDate", {})
                    year_str = pub_date.get("Year")
                    if year_str:
                        year = int(year_str)
                except (KeyError, TypeError, ValueError):
                    pass

                url = f"https://pubmed.ncbi.nlm.nih.gov/{paper_id}/"
                if doi:
                    url = f"https://doi.org/{doi}"

                article = Article(title=title,
                                  url=url,
                                  authors=authors,
                                  year=year,
                                  venue=venue,
                                  abstract=abstract,
                                  source_id=paper_id,
                                  source="pubmed")

                articles.append(article)
                logger.debug("fetched metadata for paper %s: %s...", paper_id,
                             title[:50])

            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("Failed to fetch metadata for paper %s: %s",
                               paper_id, e)
                continue

        logger.info("Successfully retrieved %s papers from PubMed",
                    len(articles))
        return articles

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error searching PubMed: %s", e)
        raise
