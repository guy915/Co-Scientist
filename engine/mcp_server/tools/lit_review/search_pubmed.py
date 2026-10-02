"""PubMed metadata search and availability probe."""

import json
import logging

from Bio import Entrez

from mcp_server.entrez import initialize_entrez, read_entrez
from mcp_server.entrez_rate_limit import entrez_call
from mcp_server.pubmed_query import search_with_relaxation

from .pubmed_parsing import _fetch_pubmed_article

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
