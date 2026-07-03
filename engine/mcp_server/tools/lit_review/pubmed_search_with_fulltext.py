"""Enhanced PubMed search that downloads fulltexts from PMC.

Wraps PubmedSource.pubmed_search() from literature_review.py to provide
search + fulltext download + text extraction as a single MCP tool.
"""
# pylint: disable=inconsistent-quotes

import asyncio
import os
import logging
from pathlib import Path
from typing import Any
from Bio import Entrez

from mcp_server.literature_review import PubmedSource, LiteratureReviewAgent
from mcp_server.text_extraction import extract_text_from_pmc_html

logger = logging.getLogger(__name__)


async def pubmed_search_with_fulltext(
        query: str,
        slug: str,
        max_papers: int = 10,
        recency_years: int = 0,
        run_id: str | None = None) -> dict[str, Any]:
    # pylint: disable=line-too-long
    """Searches PubMed and downloads fulltexts (HTML from PMC).

    Initializes Entrez credentials from environment and performs search
    with fulltext download. HTML-only implementation.

    Uses shared pool architecture - papers stored in slug/shared/ and
    symlinked to slug/runs/{run_id}/ for per-run isolation.

    Args:
        query: PubMed boolean query (AND/OR/NOT operators).
        slug: Snake_case identifier for organizing results (research goal hash).
        max_papers: Maximum papers to retrieve.
        recency_years: Filter to papers from last N years (0 = no filter).
        run_id: Unique run identifier for this execution (enables per-run tracking).

    Returns:
        Dict mapping paper_id to metadata (title, abstract, authors, doi, pmc_full_text_id, etc.).
    """
    # pylint: enable=line-too-long
    # initialize entrez credentials
    if (entrez_email := os.environ.get("ENTREZ_EMAIL", None)):
        Entrez.email = entrez_email
    else:
        logger.warning("ENTREZ_EMAIL not set - pubmed may rate limit or fail")

    if (entrez_key := os.environ.get("ENTREZ_API_KEY", None)):
        Entrez.api_key = entrez_key

    # Initialize literature review agent
    lit_review_dir = Path(
        os.getenv("COSCIENTIST_LIT_REVIEW_DIR", "./cache/literature_review"))
    lit_review_dir.mkdir(parents=True, exist_ok=True)

    agent = LiteratureReviewAgent(lit_review_dir)
    pubmed_source = PubmedSource()
    agent.add_source("pubmed", pubmed_source)

    # Fetch papers with fulltexts (pass run_id for per-run tracking)
    logger.info(
        "Searching pubmed with query: %s, slug: %s, run_id: %s, "
        "max_papers: %s, recency_years: %s", query, slug, run_id, max_papers,
        recency_years)
    results = await agent.fetch_for_query("pubmed", query, slug, max_papers,
                                          recency_years, run_id)

    logger.info("Pubmed search complete - found %s papers", len(results))

    # Extract fulltext from HTML and add to metadata
    base_dir = lit_review_dir / "pubmed" / slug
    run_dir = base_dir / "runs" / run_id if run_id else base_dir

    def read_and_extract(html_file: Path) -> str:
        """Reads cached fulltext HTML and extracts clean text (blocking)."""
        with open(html_file, encoding='utf-8') as f:
            html_content = f.read()
        return extract_text_from_pmc_html(html_content)

    async def extract_fulltext(pmc_id: str, metadata: dict[str, Any]) -> bool:
        """Attaches extracted fulltext to one paper's metadata."""
        try:
            html_file = run_dir / f"{pmc_id}.fulltext.html"
            if not html_file.exists():
                logger.warning("Fulltext file not found for %s at %s", pmc_id,
                               html_file)
                return False
            # bs4/lxml parsing of full articles is CPU-heavy; run it off the
            # event loop so concurrent MCP requests are not stalled.
            text = await asyncio.to_thread(read_and_extract, html_file)
            metadata['fulltext'] = text
            logger.debug("extracted %s chars from %s", len(text), pmc_id)
            return True
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Failed to extract text from %s: %s", pmc_id, e)
            return False

    extractions = [
        extract_fulltext(pmc_id, metadata)
        for metadata in results.values()
        if (pmc_id := metadata.get('pmc_full_text_id'))
    ]
    papers_with_fulltext = sum(await asyncio.gather(*extractions))

    logger.info("Extracted fulltext for %s/%s papers", papers_with_fulltext,
                len(results))

    return results
