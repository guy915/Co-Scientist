"""Article assembly and result-building helpers for the literature review.

Builds ``Article`` objects from collected paper metadata (including year and
URL derivation), classifies which papers have usable fulltext/content for
analysis, and constructs the node's success/failure result dicts.
"""

import logging
from collections.abc import Callable
from typing import Any, cast

from co_scientist.constants import LITERATURE_REVIEW_FAILED
from co_scientist.models import Article, phase_message

logger = logging.getLogger(__name__)

# =============================================================================
# Article building
# =============================================================================


def build_article_from_metadata(
    paper_id: str,
    metadata: dict[str, Any],
    source_name: str = "pubmed",
    used_in_analysis: bool = True,
) -> Article:
    """Build an Article object from MCP response metadata."""
    year = parse_year_from_metadata(metadata)
    url = _build_article_url(paper_id, metadata, source_name)

    # content/pdf_links are unused in PubMed-only mode (fulltext is read
    # directly from files by an external tool); they're still populated
    # here for sources/modes that do rely on them.
    return Article(
        title=metadata.get("title", "unknown"),
        url=url,
        authors=metadata.get("authors", []),
        year=year,
        venue=metadata.get("publication") or metadata.get("venue"),
        citations=0,
        abstract=metadata.get("abstract"),
        content=metadata.get("fulltext"),
        source_id=paper_id,
        source=source_name,
        pdf_links=[],
        used_in_analysis=used_in_analysis,
    )


def _year_from_year_field(metadata: dict[str, Any]) -> int | None:
    """Parse the direct numeric/string "year" field, if present."""
    if not (metadata.get("year")):
        return None
    try:
        return int(metadata["year"])
    except (ValueError, TypeError):
        return None


def _year_from_date_revised(metadata: dict[str, Any]) -> int | None:
    """Parse the leading year from a "date_revised" like "YYYY/MM/DD".

    Fallback for sources (e.g. PubMed) that only expose a revision date
    rather than a direct year field.
    """
    if "date_revised" not in metadata:
        return None
    try:
        return int(metadata["date_revised"].split("/")[0])
    except (ValueError, KeyError, IndexError, AttributeError):
        return None


# Tried in order; the first parser to return a year wins. A tuple of
# callables replaces a try/except-per-format ladder so adding a format
# means adding a parser, not another branch.
_YEAR_PARSERS: tuple[Callable[[dict[str, Any]], int | None], ...] = (
    _year_from_year_field,
    _year_from_date_revised,
)


def parse_year_from_metadata(metadata: dict[str, Any]) -> int | None:
    """Parse year from metadata, handling multiple formats."""
    for parser in _YEAR_PARSERS:
        year = parser(metadata)
        if year is not None:
            return year
    return None


def _build_article_url(
    paper_id: str, metadata: dict[str, Any], source_name: str
) -> str:
    """Build URL for article, using metadata URL or constructing default."""
    # Prefer a URL the tool already supplied.
    url = metadata.get("url")
    if url:
        return cast(str, url)

    # PubMed ids map directly to a canonical article URL.
    if source_name == "pubmed":
        return f"https://pubmed.ncbi.nlm.nih.gov/{paper_id}/"

    # Bare DOIs (e.g. "10.1234/...") resolve via doi.org.
    if paper_id.startswith("10."):
        return f"https://doi.org/{paper_id}"

    # Last resort: use the raw id as-is (may not be a valid URL).
    return paper_id


def build_articles_from_metadata(
    all_paper_metadata: dict[str, dict[str, Any]],
    default_source_name: str,
) -> list[Article]:
    """Build Article objects from collected paper metadata."""
    articles = []
    for paper_id, metadata in all_paper_metadata.items():
        if isinstance(metadata, dict):
            # "_source_name" is stamped onto each paper's metadata during
            # multi-source collection (see literature_review.py's
            # _search_single_source) so per-paper provenance survives the
            # merge into a single dict; single-source mode has no such tag
            # and every paper shares default_source_name.
            paper_source = metadata.get("_source_name", default_source_name)
        else:
            paper_source = default_source_name

        articles.append(
            build_article_from_metadata(
                paper_id, metadata, paper_source, used_in_analysis=True
            )
        )
    return articles


# =============================================================================
# Fulltext availability
# =============================================================================


def _has_fulltext(meta: dict[str, Any]) -> bool:
    """Check whether any fulltext-availability indicator field is set.

    A paper counts as having fulltext if ANY of these indicator fields is
    set - different sources/tools populate different fields, so this is a
    union check rather than one canonical field.
    """
    return bool(
        meta.get("pmc_full_text_id")
        or meta.get("fulltext")
        or meta.get("has_fulltext")
        or meta.get("pdf_url")
    )


def count_papers_with_fulltext(
    all_paper_metadata: dict[str, dict[str, Any]],
) -> tuple[int, int]:
    """Count papers with and without fulltext indicators.

    Returns:
        Tuple of (papers_with_fulltext, papers_without_fulltext)
    """
    with_fulltext = 0
    for meta in all_paper_metadata.values():
        if isinstance(meta, dict) and _has_fulltext(meta):
            with_fulltext += 1

    without_fulltext = len(all_paper_metadata) - with_fulltext
    return with_fulltext, without_fulltext


def _has_analyzable_content(metadata: dict[str, Any]) -> bool:
    """Check whether a paper has content available for analysis.

    Fulltext is always preferred when available. Otherwise, a paper with a
    discovered pdf_url but no downloaded fulltext can still be analyzed
    using its abstract as a fallback rather than being dropped from
    analysis entirely.
    """
    if metadata.get("fulltext"):
        return True
    return bool(metadata.get("pdf_url") and metadata.get("abstract"))


def get_papers_with_content(
    all_paper_metadata: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Get papers that have content available for analysis.

    Papers with fulltext are preferred. Papers with pdf_url and abstract
    can use abstract as fallback.
    """
    papers_with_content = {}
    for pid, metadata in all_paper_metadata.items():
        if not isinstance(metadata, dict) or not _has_analyzable_content(
            metadata
        ):
            continue
        papers_with_content[pid] = metadata
        if not metadata.get("fulltext"):
            logger.debug(
                "Paper %s: using abstract for analysis"
                " (fulltext not downloaded)",
                pid,
            )
    return papers_with_content


# =============================================================================
# Paper analysis helpers
# =============================================================================


def get_paper_content_for_analysis(
    metadata: dict[str, Any], max_chars: int = 200_000
) -> str:
    """Get paper content for analysis, with truncation if needed."""
    # Fulltext is preferred; abstract is the fallback when fulltext wasn't
    # fetched (mirrors the policy in get_papers_with_content).
    content = str(metadata.get("fulltext") or metadata.get("abstract") or "")
    # Bound the input size to the paper-analysis LLM call regardless of how
    # long the source fulltext is.
    if len(content) > max_chars:
        logger.debug("Truncating paper content to %s chars", max_chars)
        content = content[:max_chars] + "\n\n[... truncated for length ...]"
    return content


# =============================================================================
# Result builders
# =============================================================================


def make_failure_result(
    reason: str,
    queries: list[str] | None = None,
    articles: list[Article] | None = None,
) -> dict[str, Any]:
    """Create a failure result dict for early returns."""
    # The LITERATURE_REVIEW_FAILED sentinel is what downstream generation
    # nodes check in articles_with_reasoning to decide whether literature
    # review usably succeeded (as opposed to inspecting queries/articles).
    return {
        "articles_with_reasoning": LITERATURE_REVIEW_FAILED,
        "literature_review_queries": queries or [],
        "articles": articles or [],
        "messages": phase_message(
            "literature_review",
            f"literature review failed - {reason}",
            error=True,
        ),
    }


def make_success_result(
    synthesis: str,
    queries: list[str],
    articles: list[Article],
) -> dict[str, Any]:
    """Create a success result dict."""
    return {
        "articles_with_reasoning": synthesis,
        "literature_review_queries": queries,
        "articles": articles,
        "messages": phase_message(
            "literature_review",
            f"completed literature review with {len(queries)}"
            f" queries, {len(articles)} articles analyzed",
        ),
    }
