"""Article construction, retrieval-content parsing and provenance metadata."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from co_scientist.constants import (
    LITERATURE_REVIEW_FAILED,
    PROMPT_PAPER_MAX_CHARS,
    strip_citation_markers,
    truncate_for_prompt,
)
from co_scientist.models import Article, phase_message
from co_scientist.research import Finding, ResearchResult

if TYPE_CHECKING:
    from co_scientist.research_adapter import ResearchRetrieval


def records_from_findings(
    result: ResearchResult, retrieval: ResearchRetrieval
) -> dict[str, dict[str, Any]]:
    """Turn the papers that produced findings into review-shaped records.

    Generation and Reflection share the same article pool and provenance
    shape, so neither agent owns this conversion.

    Only documents something was actually drawn from are carried over: a
    hit the loop searched up but read nothing useful from is already on
    record in the ledger, and adding it to the paper pool would put a
    document into every downstream prompt on the strength of having
    appeared in a result list.

    Each record is stamped with the id of the call that surfaced it,
    which is what lets a caller persisting the article say which query
    found it and which question that query was serving.
    """
    records: dict[str, dict[str, Any]] = {}
    for finding in result.findings:
        if finding.locator in records:
            continue
        record = retrieval.record(finding.locator)
        if record is None:
            continue
        record["retrieval_call_id"] = finding.call_id
        record.setdefault("_source_name", _source_of(result, finding))
        records[finding.locator] = record
    return records


def _source_of(result: ResearchResult, finding: Finding) -> str:
    """Name the source whose call surfaced one finding."""
    for call in result.calls:
        if call.id == finding.call_id:
            return call.source
    return ""


logger = logging.getLogger(__name__)


def _metadata_is_retracted(metadata: dict[str, Any]) -> bool:
    """Return whether source metadata identifies a retracted publication."""
    publication_types = metadata.get("publication_types") or []
    if isinstance(publication_types, str):
        publication_types = [publication_types]
    normalized_types = {str(item).lower() for item in publication_types}
    return bool(
        metadata.get("is_retracted")
        or str(metadata.get("correction_status") or "").lower() == "retracted"
        or "retracted publication" in normalized_types
    )


# =============================================================================
# Article building
# =============================================================================


def _publication_type(metadata: dict[str, Any]) -> str | None:
    """Return the publisher-declared publication type, either spelling.

    PubMed answers with a plural ``publication_types`` list; only the
    singular key was read, so the field was always None and the strongest
    source-type signal there is -- the one that tells a preprint PubMed
    indexes from the journal articles beside it -- never left the search
    response. Consumed downstream by the app's citation-metadata check.
    """
    declared = metadata.get("publication_type")
    if declared:
        return str(declared)
    types = metadata.get("publication_types") or []
    if isinstance(types, str):
        types = [types]
    # Joined rather than first-wins: PubMed mixes the declared types on one
    # record ("Journal Article" beside "Preprint", the way it also carries
    # "Retracted Publication" -- see _metadata_is_retracted), so taking
    # element zero drops whichever the indexer happened to list second.
    return "; ".join(str(item) for item in types) or None


def _correction_status(metadata: dict[str, Any], is_retracted: bool) -> str:
    """Name a paper's correction state, deriving it when unstated."""
    return str(
        metadata.get("correction_status")
        or ("retracted" if is_retracted else "current")
    )


def build_article_from_metadata(
    paper_id: str,
    metadata: dict[str, Any],
    source_name: str = "pubmed",
    used_in_analysis: bool = True,
) -> Article:
    """Build an Article object from MCP response metadata."""
    year = parse_year_from_metadata(metadata)
    url = _build_article_url(paper_id, metadata, source_name)
    is_retracted = _metadata_is_retracted(metadata)

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
        doi=metadata.get("doi"),
        is_retracted=is_retracted,
        correction_status=_correction_status(metadata, is_retracted),
        publication_type=_publication_type(metadata),
        pdf_links=[],
        used_in_analysis=used_in_analysis,
        # Collection time, not the caller's eventual persistence time (see
        # Article.retrieved_at).
        retrieved_at=time.time(),
        retrieval_score=metadata.get("retrieval_score"),
        retrieval_rationale=metadata.get("retrieval_rationale"),
        retriever_version=metadata.get("retriever_version"),
        retrieval_call_id=metadata.get("retrieval_call_id"),
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
                paper_id,
                metadata,
                paper_source,
                used_in_analysis=_has_analyzable_content(metadata),
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

    Fulltext is always preferred when available. Otherwise, a source-provided
    abstract is an explicit, bounded evidence passage and can support
    abstract-level analysis without pretending the full paper was retrieved.
    """
    return bool(metadata.get("fulltext") or metadata.get("abstract"))


def get_papers_with_content(
    all_paper_metadata: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Get papers that have content available for analysis.

    Papers with fulltext are preferred. Abstract-bearing records use their
    abstract as a visibly shallower fallback.
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
    metadata: dict[str, Any], max_chars: int = PROMPT_PAPER_MAX_CHARS
) -> str:
    """Get paper content for analysis, with truncation if needed.

    Strips the source paper's own inline citation markers (this is the
    metadata dict, never the stored ``Article`` -- the marker never
    existed anywhere but this prompt copy). Stripped after truncation,
    not before, so the regex runs over a bounded string; a marker split
    by the cut simply fails to match, which is harmless.
    """
    # Fulltext is preferred; abstract is the fallback when fulltext wasn't
    # fetched (mirrors the policy in get_papers_with_content).
    content = str(metadata.get("fulltext") or metadata.get("abstract") or "")
    if len(content) > max_chars:
        logger.debug("Truncating paper content to %s chars", max_chars)
    return strip_citation_markers(truncate_for_prompt(content, max_chars))


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
    analyzed = [article for article in articles if article.used_in_analysis]
    return {
        "articles_with_reasoning": synthesis,
        "literature_review_queries": queries,
        "articles": articles,
        "messages": phase_message(
            "literature_review",
            f"completed literature review with {len(queries)}"
            f" queries, {len(analyzed)} of {len(articles)} articles analyzed",
            articles_retrieved=len(articles),
            articles_analyzed=len(analyzed),
            fulltext_analyzed=sum(
                bool(article.content) for article in analyzed
            ),
            abstract_only_analyzed=sum(
                bool(not article.content and article.abstract)
                for article in analyzed
            ),
        ),
    }
