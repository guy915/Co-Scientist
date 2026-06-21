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
_MAX_PER_PAGE = 25


def _reconstruct_abstract(inverted_index: Any) -> str:
    """Rebuild abstract text from OpenAlex's inverted-index representation.

    OpenAlex returns abstracts as ``{word: [positions...]}``; reorder the words
    by position to recover readable text. Returns ``""`` when absent.
    """
    if not isinstance(inverted_index, dict) or not inverted_index:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted_index.items():
        if not isinstance(idxs, list):
            continue
        for idx in idxs:
            if isinstance(idx, int):
                positions.append((idx, str(word)))
    positions.sort(key=lambda item: item[0])
    return " ".join(word for _, word in positions)


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
        raw_id = str(work.get("id") or "")
        work_id = raw_id.rsplit("/", 1)[-1]
        if not work_id:
            continue
        authors = [(a.get("author") or {}).get("display_name", "")
                   for a in (work.get("authorships") or [])
                   if isinstance(a, dict)]
        location = work.get("primary_location") or {}
        url = (location.get("landing_page_url") if isinstance(location, dict)
               else None) or work.get("doi") or raw_id
        out[work_id] = {
            "title":
                work.get("title") or work.get("display_name") or "",
            "authors": [a for a in authors if a],
            "year":
                work.get("publication_year"),
            "abstract":
                _reconstruct_abstract(work.get("abstract_inverted_index")),
            "url":
                url,
            "source":
                "openalex",
        }
    return out


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
    per_page = min(max(max_papers, 1), _MAX_PER_PAGE)
    params: dict[str, str] = {
        "search": query,
        "per-page": str(per_page),
    }
    mailto = os.environ.get("ENTREZ_EMAIL") or os.environ.get("OPENALEX_MAILTO")
    if mailto:
        params["mailto"] = mailto
    if recency_years and recency_years > 0:
        from_year = datetime.now(timezone.utc).year - recency_years
        params["filter"] = f"from_publication_date:{from_year}-01-01"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(_OPENALEX_WORKS_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("OpenAlex search failed for %r: %s", query, exc)
        return {}
    return normalize_works(data, per_page)
