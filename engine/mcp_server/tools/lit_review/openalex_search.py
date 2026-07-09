"""OpenAlex literature search tool.

OpenAlex (https://openalex.org) is a free, all-field index of scholarly works
that needs no API key. It complements the PubMed (biomedical) and INDRA
(mechanistic) grounding sources with broad, cross-disciplinary literature so
the co-scientist can ground hypotheses outside biomedicine too.

The tool returns a ``{work_id: metadata}`` dict shaped for the engine's
literature-review field mapping (title / authors / year / abstract / url).
"""
# pylint: disable=inconsistent-quotes

import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_OPENALEX_WORKS_URL = "https://api.openalex.org/works"
_MAX_PER_PAGE = 25  # OpenAlex /works page-size ceiling used by this tool.


def _inverted_index_positions(
        inverted_index: dict[str, Any]) -> list[tuple[int, str]]:
    """Flattens an OpenAlex inverted index into (position, word) pairs.

    Args:
        inverted_index: Mapping of word to the list of positions it
            appears at.

    Returns:
        Unsorted list of (position, word) pairs, skipping any
        malformed/non-integer position entries.
    """
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted_index.items():
        if not isinstance(idxs, list):
            continue
        for idx in idxs:
            if isinstance(idx, int):
                positions.append((idx, str(word)))
    return positions


def _reconstruct_abstract(inverted_index: Any) -> str:
    """Rebuild abstract text from OpenAlex's inverted-index representation.

    OpenAlex returns abstracts as ``{word: [positions...]}``; reorder the words
    by position to recover readable text. Returns ``""`` when absent.
    """
    if not isinstance(inverted_index, dict) or not inverted_index:
        return ""
    positions = _inverted_index_positions(inverted_index)
    # Sort by original word position to restore reading order.
    positions.sort(key=lambda item: item[0])
    return " ".join(word for _, word in positions)


def _work_short_id(work: dict[str, Any]) -> str:
    """Extracts the short OpenAlex work id (e.g. "W123") from a work record.

    OpenAlex ids are full URLs like "https://openalex.org/W123"; keep only
    the short form to use as the output dict key.

    Args:
        work: A single work record from the OpenAlex /works response.

    Returns:
        The short work id, or "" if the record has no id.
    """
    raw_id = str(work.get("id") or "")
    return raw_id.rsplit("/", 1)[-1]


def _work_authors(work: dict[str, Any]) -> list[str]:
    """Extracts non-empty author display names from a work record.

    Args:
        work: A single work record from the OpenAlex /works response.

    Returns:
        List of author display names, dropping any empty entries.
    """
    authors = [(a.get("author") or {}).get("display_name", "")
               for a in (work.get("authorships") or [])
               if isinstance(a, dict)]
    return [a for a in authors if a]


def _work_url(work: dict[str, Any]) -> str:
    """Picks the best available URL for a work record.

    Prefers a human-readable landing page, then falls back to the DOI,
    then to the raw OpenAlex id URL so a url is always present.

    Args:
        work: A single work record from the OpenAlex /works response.

    Returns:
        Best-available URL string for the work.
    """
    location = work.get("primary_location") or {}
    landing_page = (location.get("landing_page_url") if isinstance(
        location, dict) else None)
    raw_id = str(work.get("id") or "")
    return landing_page or work.get("doi") or raw_id


def _build_work_metadata(work: dict[str, Any]) -> dict[str, Any]:
    """Builds the normalized metadata dict for one OpenAlex work.

    Args:
        work: A single work record from the OpenAlex /works response.

    Returns:
        Metadata dict carrying title, authors, year, abstract, url, and
        source, shaped for the engine's literature-review field mapping.
    """
    return {
        "title": work.get("title") or work.get("display_name") or "",
        "authors": _work_authors(work),
        "year": work.get("publication_year"),
        "abstract": _reconstruct_abstract(work.get("abstract_inverted_index")),
        "url": _work_url(work),
        "source": "openalex",
    }


def normalize_works(data: dict[str, Any], max_papers: int) -> dict[str, Any]:
    """Normalize an OpenAlex /works response into ``{work_id: metadata}``.

    Pure function (no I/O) so it can be unit-tested directly.

    Args:
        data: Parsed JSON from the OpenAlex works endpoint.
        max_papers: Maximum number of works to keep.

    Returns:
        A dict keyed by short OpenAlex work id, each value carrying title,
        authors, year, abstract, url, and source.
    """
    out: dict[str, Any] = {}
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return out
    for work in results[:max(max_papers, 0)]:
        if not isinstance(work, dict):
            continue
        work_id = _work_short_id(work)
        if not work_id:
            continue
        out[work_id] = _build_work_metadata(work)
    return out


def _build_search_params(query: str, max_papers: int,
                         recency_years: int) -> tuple[dict[str, str], int]:
    """Builds OpenAlex /works query params for a search request.

    Pure function (no I/O) so it can be unit-tested directly.

    Args:
        query: Free-text search query.
        max_papers: Maximum number of works to return (capped at 25).
        recency_years: If > 0, restrict to works published within this many
            years.

    Returns:
        A tuple of (query params dict, effective per-page count).
    """
    # Clamp to at least 1 and at most the API's per-page ceiling.
    per_page = min(max(max_papers, 1), _MAX_PER_PAGE)
    params: dict[str, str] = {
        "search": query,
        "per-page": str(per_page),
    }
    # Reuse the Entrez contact email if set; OpenAlex's "polite pool"
    # (faster, more reliable responses) is granted to requests that
    # identify a contact via mailto.
    mailto = os.environ.get("ENTREZ_EMAIL") or os.environ.get("OPENALEX_MAILTO")
    if mailto:
        params["mailto"] = mailto
    if recency_years and recency_years > 0:
        # OpenAlex filter syntax: restrict to works published on/after
        # January 1 of (current year - recency_years).
        from_year = datetime.now(timezone.utc).year - recency_years
        params["filter"] = f"from_publication_date:{from_year}-01-01"
    return params, per_page


async def search_openalex(
        query: str,
        max_papers: int = 10,
        recency_years: int = 0,
        run_id: str | None = None,  # pylint: disable=unused-argument
) -> dict[str, Any]:
    """Search OpenAlex works and return ``{work_id: metadata}``.

    Args:
        query: Free-text search query.
        max_papers: Maximum number of works to return (capped at 25).
        recency_years: If > 0, restrict to works published within this many
            years.
        run_id: Unused; accepted for interface parity with other search tools.

    Returns:
        A dict of normalized works, or an empty dict on any error so the
        literature-review node degrades gracefully.
    """
    params, per_page = _build_search_params(query, max_papers, recency_years)

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(_OPENALEX_WORKS_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        # Network/parsing failures degrade to no results rather than
        # propagating, so a single failed source doesn't fail the whole
        # literature-review step.
        logger.warning("OpenAlex search failed for %r: %s", query, exc)
        return {}
    return normalize_works(data, per_page)
