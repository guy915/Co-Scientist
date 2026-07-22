"""Enhanced PubMed search that downloads fulltexts from PMC.

Wraps PubmedSource.pubmed_search() from literature_review.py to provide
search + fulltext download + text extraction as a single MCP tool.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from mcp_server.literature_review import PubmedSource
from mcp_server.text_extraction import extract_text_from_pmc_html

logger = logging.getLogger(__name__)


def _read_and_extract_fulltext(html_file: Path) -> str:
    """Reads cached fulltext HTML and extracts clean text (blocking).

    Args:
        html_file: Path to the cached PMC fulltext HTML file.

    Returns:
        Extracted plain/markdown text from the HTML.
    """
    with open(html_file, encoding="utf-8") as f:
        html_content = f.read()
    return extract_text_from_pmc_html(html_content)


async def _extract_fulltext(
    pmc_id: str, metadata: dict[str, Any], run_dir: Path
) -> bool:
    """Attaches extracted fulltext to one paper's metadata.

    Args:
        pmc_id: PMC full-text identifier for the paper.
        metadata: Paper metadata dict to attach fulltext to; mutated in
            place on success.
        run_dir: Directory containing the cached fulltext HTML files.

    Returns:
        True if fulltext was found and attached, False otherwise.
    """
    try:
        html_file = run_dir / f"{pmc_id}.fulltext.html"
        if not html_file.exists():
            logger.warning(
                "Fulltext file not found for %s at %s", pmc_id, html_file
            )
            return False
        # bs4/lxml parsing of full articles is CPU-heavy; run it off the
        # event loop so concurrent MCP requests are not stalled.
        text = await asyncio.to_thread(_read_and_extract_fulltext, html_file)
        metadata["fulltext"] = text
        logger.debug("extracted %s chars from %s", len(text), pmc_id)
        return True
    except Exception as e:
        logger.error("Failed to extract text from %s: %s", pmc_id, e)
        return False


async def _extract_fulltexts(
    results: dict[str, dict[str, Any]], run_dir: Path
) -> int:
    """Extracts fulltext for every paper that has a PMC fulltext id.

    Args:
        results: Mapping of paper_id to metadata dicts; entries are
            mutated in place with a "fulltext" key where extraction
            succeeds.
        run_dir: Directory containing the cached fulltext HTML files.

    Returns:
        Count of papers successfully enriched with fulltext.
    """
    # Only papers that actually have a PMC fulltext id get an extraction
    # coroutine; papers without open-access fulltext are left as-is.
    extractions = [
        _extract_fulltext(pmc_id, metadata, run_dir)
        for metadata in results.values()
        if (pmc_id := metadata.get("pmc_full_text_id"))
    ]
    # Extractions run concurrently; each returns True/False so summing
    # gives the count of papers successfully enriched with fulltext.
    return sum(await asyncio.gather(*extractions))


def _pubmed_cache_dir() -> Path:
    """Returns the literature-review cache root, creating it if needed.

    Returns:
        The directory configured by COSCIENTIST_LIT_REVIEW_DIR (default
        ``./cache/literature_review``), guaranteed to exist.
    """
    # Entrez credentials are configured at import time by literature_review.
    lit_review_dir = Path(
        os.getenv("COSCIENTIST_LIT_REVIEW_DIR", "./cache/literature_review")
    )
    lit_review_dir.mkdir(parents=True, exist_ok=True)
    return lit_review_dir


def _fulltext_run_dir(
    lit_review_dir: Path, slug: str, run_id: str | None
) -> Path:
    """Returns the directory holding cached fulltext HTML for a run.

    Args:
        lit_review_dir: Literature-review cache root.
        slug: Snake_case identifier for organizing results.
        run_id: Unique run identifier, or None for the shared pool.

    Returns:
        The per-run symlinked directory when ``run_id`` is given, otherwise
        the shared slug directory.
    """
    # Fulltext HTML lives under the per-run symlinked directory when a
    # run_id is given, otherwise fall back to the shared slug directory.
    base_dir = lit_review_dir / "pubmed" / slug
    return base_dir / "runs" / run_id if run_id else base_dir


async def _run_pubmed_search(
    lit_review_dir: Path,
    query: str,
    slug: str,
    max_papers: int,
    recency_years: int,
    run_id: str | None,
) -> dict[str, dict[str, Any]]:
    """Runs the PubMed search against the on-disk cache.

    Args:
        lit_review_dir: Literature-review cache root.
        query: PubMed boolean query (AND/OR/NOT operators).
        slug: Snake_case identifier for organizing results.
        max_papers: Maximum papers to retrieve.
        recency_years: Filter to papers from last N years (0 = no filter).
        run_id: Unique run identifier, enabling per-run tracking.

    Returns:
        Dict mapping paper_id to metadata for the matched papers.
    """
    # PubmedSource owns the on-disk cache under lit_review_dir/pubmed; see
    # its shared-pool layout described in the module docstring above.
    pubmed_source = PubmedSource(lit_review_dir / "pubmed")
    logger.info(
        "Searching pubmed with query: %s, slug: %s, run_id: %s, "
        "max_papers: %s, recency_years: %s",
        query,
        slug,
        run_id,
        max_papers,
        recency_years,
    )
    results = await pubmed_source.pubmed_search(
        query, slug, max_papers, recency_years, run_id
    )
    logger.info("Pubmed search complete - found %s papers", len(results))
    return results


async def _attach_fulltexts(
    results: dict[str, dict[str, Any]], run_dir: Path
) -> None:
    """Extracts and attaches fulltext to matched papers, logging the count.

    Args:
        results: Mapping of paper_id to metadata; mutated in place with a
            "fulltext" key where extraction succeeds.
        run_dir: Directory containing the cached fulltext HTML files.
    """
    papers_with_fulltext = await _extract_fulltexts(results, run_dir)
    logger.info(
        "Extracted fulltext for %s/%s papers",
        papers_with_fulltext,
        len(results),
    )


async def pubmed_search_with_fulltext(
    query: str,
    slug: str,
    max_papers: int = 10,
    recency_years: int = 0,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Searches PubMed and downloads fulltexts (HTML from PMC).

    Performs search with fulltext download. HTML-only implementation.

    Uses shared pool architecture - papers stored in slug/shared/ and
    symlinked to slug/runs/{run_id}/ for per-run isolation.

    Args:
        query: PubMed boolean query (AND/OR/NOT operators).
        slug: Snake_case identifier for organizing results (research goal hash).
        max_papers: Maximum papers to retrieve.
        recency_years: Filter to papers from last N years (0 = no filter).
        run_id: Unique run identifier for this execution (enables per-run
            tracking).

    Returns:
        Dict mapping paper_id to metadata (title, abstract, authors, doi,
        pmc_full_text_id, etc.).
    """
    lit_review_dir = _pubmed_cache_dir()
    results = await _run_pubmed_search(
        lit_review_dir, query, slug, max_papers, recency_years, run_id
    )

    # Extract fulltext from HTML and add to metadata.
    run_dir = _fulltext_run_dir(lit_review_dir, slug, run_id)
    await _attach_fulltexts(results, run_dir)

    # `results` metadata dicts were mutated in place by extract_fulltext,
    # so the fulltext (where available) is already attached here.
    return results
