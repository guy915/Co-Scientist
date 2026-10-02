"""PubMed corpus search with cached PMC fulltext extraction."""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from mcp_server.literature_review import PubmedSource
from mcp_server.text_extraction import extract_text_from_pmc_html

logger = logging.getLogger(__name__)


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
