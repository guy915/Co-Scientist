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
"""Enhanced PubMed search that downloads fulltexts from PMC.

Wraps PubmedSource.pubmed_search() from literature_review.py to provide
search + fulltext download + text extraction as a single MCP tool.
"""
# pylint: disable=inconsistent-quotes

import os
import logging
from pathlib import Path
from typing import Any, Dict
from Bio import Entrez

from mcp_server.literature_review import PubmedSource, LiteratureReviewAgent
from mcp_server.text_extraction import extract_text_from_pmc_html

logger = logging.getLogger(__name__)


async def pubmed_search_with_fulltext(query: str,
                                      slug: str,
                                      max_papers: int = 10,
                                      recency_years: int = 0,
                                      run_id: str = None) -> Dict[str, Any]:
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

    # initialize literature review agent
    lit_review_dir = Path(
        os.getenv("COSCIENTIST_LIT_REVIEW_DIR", "./cache/literature_review"))
    lit_review_dir.mkdir(parents=True, exist_ok=True)

    agent = LiteratureReviewAgent(lit_review_dir)
    pubmed_source = PubmedSource()
    agent.add_source("pubmed", pubmed_source)

    # fetch papers with fulltexts (pass run_id for per-run tracking)
    logger.info(
        "Searching pubmed with query: %s, slug: %s, run_id: %s, "
        "max_papers: %s, recency_years: %s", query, slug, run_id, max_papers,
        recency_years)
    results = await agent.fetch_for_query("pubmed", query, slug, max_papers,
                                          recency_years, run_id)

    logger.info("Pubmed search complete - found %s papers", len(results))

    # extract fulltext from HTML and add to metadata
    base_dir = lit_review_dir / "pubmed" / slug
    run_dir = base_dir / "runs" / run_id if run_id else base_dir

    papers_with_fulltext = 0
    for _, metadata in results.items():
        pmc_id = metadata.get('pmc_full_text_id')
        if pmc_id:
            try:  # pylint: disable=broad-exception-caught
                # read HTML from cache
                html_file = run_dir / f"{pmc_id}.fulltext.html"
                if html_file.exists():
                    with open(html_file, 'r', encoding='utf-8') as f:
                        html_content = f.read()

                    # extract clean text/markdown
                    text = extract_text_from_pmc_html(html_content)
                    metadata['fulltext'] = text
                    papers_with_fulltext += 1
                    logger.debug("extracted %s chars from %s", len(text),
                                 pmc_id)
                else:
                    logger.warning("Fulltext file not found for %s at %s",
                                   pmc_id, html_file)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("Failed to extract text from %s: %s", pmc_id, e)

    logger.info("Extracted fulltext for %s/%s papers", papers_with_fulltext,
                len(results))

    return results
