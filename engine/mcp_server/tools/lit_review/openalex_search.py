"""OpenAlex literature search tool.

OpenAlex (https://openalex.org) is a free, all-field index of scholarly works
that needs no API key. It complements the PubMed (biomedical) and INDRA
(mechanistic) grounding sources with broad, cross-disciplinary literature so
the co-scientist can ground hypotheses outside biomedicine too.

The tool returns a ``{work_id: metadata}`` dict shaped for the engine's
literature-review field mapping (title / authors / year / abstract / url).
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_OPENALEX_WORKS_URL = "https://api.openalex.org/works"
_MAX_PER_PAGE = 100  # Current documented OpenAlex page-size ceiling.


def _inverted_index_positions(
    inverted_index: dict[str, Any],
) -> list[tuple[int, str]]:
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


def _author_display_name(authorship: Any) -> str:
    """Extracts one authorship entry's display name, defaulting to "".

    Args:
        authorship: A single entry from a work's ``authorships`` list.

    Returns:
        The author's display name, or "" if the entry is not a dict or
        has no display name.
    """
    if not isinstance(authorship, dict):
        return ""
    name = (authorship.get("author") or {}).get("display_name", "")
    return name if isinstance(name, str) else ""


def _work_authors(work: dict[str, Any]) -> list[str]:
    """Extracts non-empty author display names from a work record.

    Args:
        work: A single work record from the OpenAlex /works response.

    Returns:
        List of author display names, dropping any empty entries.
    """
    names = (_author_display_name(a) for a in work.get("authorships") or [])
    return [name for name in names if name]


def _first_truthy(*values: str | None) -> str:
    """Returns the first truthy value among ``values``, or "" if none.

    Args:
        values: Candidate values in priority order.

    Returns:
        The first truthy value, or "" if all are falsy/None.
    """
    for value in values:
        if value:
            return value
    return ""


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
    landing_page = (
        location.get("landing_page_url") if isinstance(location, dict) else None
    )
    raw_id = str(work.get("id") or "")
    return _first_truthy(landing_page, work.get("doi"), raw_id)


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
        "cited_by_count": work.get("cited_by_count", 0),
        "publication_date": work.get("publication_date"),
        "updated_date": work.get("updated_date"),
        "work_type": work.get("type"),
        "is_retracted": bool(work.get("is_retracted", False)),
    }


def _works_results(data: dict[str, Any]) -> list[Any]:
    """Extracts the raw ``results`` list from an OpenAlex /works response.

    Args:
        data: Parsed JSON from the OpenAlex works endpoint.

    Returns:
        The response's ``results`` list, or [] if absent/malformed.
    """
    results = data.get("results") if isinstance(data, dict) else None
    return results if isinstance(results, list) else []


def _add_normalized_work(out: dict[str, Any], work: Any) -> None:
    """Normalizes one work record into ``out``, keyed by its short id.

    Args:
        out: Output dict, mutated in place with the normalized entry.
        work: A single, not-yet-validated entry from a /works response's
            ``results`` list.
    """
    if not isinstance(work, dict):
        return
    work_id = _work_short_id(work)
    if not work_id:
        return
    out[work_id] = _build_work_metadata(work)


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
    for work in _works_results(data)[: max(max_papers, 0)]:
        _add_normalized_work(out, work)
    return out


def _build_search_params(
    query: str, max_papers: int, recency_years: int
) -> tuple[dict[str, str], int]:
    """Builds OpenAlex /works query params for a search request.

    Pure function (no I/O) so it can be unit-tested directly.

    Args:
        query: Free-text search query.
        max_papers: Maximum number of works to return across cursor pages.
        recency_years: If > 0, restrict to works published within this many
            years.

    Returns:
        A tuple of (query params dict, effective per-page count).
    """
    # Clamp to at least 1 and at most the API's per-page ceiling.
    per_page = min(max(max_papers, 1), _MAX_PER_PAGE)
    params: dict[str, str] = {
        "search": query,
        "per_page": str(per_page),
        "cursor": "*",
    }
    # Reuse the Entrez contact email if set; OpenAlex's "polite pool"
    # (faster, more reliable responses) is granted to requests that
    # identify a contact via mailto.
    mailto = os.environ.get("ENTREZ_EMAIL") or os.environ.get("OPENALEX_MAILTO")
    if mailto:
        params["mailto"] = mailto
    api_key = os.environ.get("OPENALEX_API_KEY")
    if api_key:
        params["api_key"] = api_key
    filters = ["is_retracted:false"]
    if recency_years and recency_years > 0:
        # OpenAlex filter syntax: restrict to works published on/after
        # January 1 of (current year - recency_years).
        from_year = datetime.now(timezone.utc).year - recency_years
        filters.append(f"from_publication_date:{from_year}-01-01")
    params["filter"] = ",".join(filters)
    return params, per_page


def _next_cursor(data: Any) -> str | None:
    """Return a usable OpenAlex cursor from one response page."""
    if not isinstance(data, dict):
        return None
    meta = data.get("meta")
    if not isinstance(meta, dict):
        return None
    cursor = meta.get("next_cursor")
    return str(cursor) if cursor else None


async def _collect_openalex_works(
    params: dict[str, str], per_page: int, max_papers: int
) -> dict[str, Any]:
    """Pages through OpenAlex works up to ``max_papers``.

    Args:
        params: Query parameters for the works endpoint; mutated with the
            page size and cursor as pagination proceeds.
        per_page: Base page size requested from OpenAlex.
        max_papers: Maximum number of works to collect.

    Returns:
        A dict of normalized works, at most ``max_papers`` entries.
    """
    collected: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=30) as client:
        while len(collected) < max(max_papers, 0):
            params["per_page"] = str(min(per_page, max_papers - len(collected)))
            resp = await client.get(_OPENALEX_WORKS_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            page = normalize_works(data, max_papers - len(collected))
            collected.update(page)
            cursor = _next_cursor(data)
            if not page or not cursor:
                break
            params["cursor"] = cursor
    return collected


async def search_openalex(
    query: str,
    max_papers: int = 10,
    recency_years: int = 0,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Search OpenAlex works and return ``{work_id: metadata}``.

    Args:
        query: Free-text search query.
        max_papers: Maximum number of works to return across cursor pages.
        recency_years: If > 0, restrict to works published within this many
            years.
        run_id: Unused; accepted for interface parity with other search tools.

    Returns:
        A dict of normalized works, or an empty dict on any error so the
        literature-review node degrades gracefully.
    """
    params, per_page = _build_search_params(query, max_papers, recency_years)
    try:
        return await _collect_openalex_works(params, per_page, max_papers)
    except (httpx.HTTPError, ValueError) as exc:
        # Network/parsing failures degrade to no results rather than
        # propagating, so a single failed source doesn't fail the whole
        # literature-review step.
        logger.warning("OpenAlex search failed for %r: %s", query, exc)
        return {}
