"""Cross-disciplinary literature search via OpenAlex.

Return normalized works for successful searches. Raise when OpenAlex cannot
be reached, refuses quota, or returns invalid JSON so upstream retries and
source-degradation reporting distinguish a failed source from no matches.
"""

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from mcp_server.campaign import campaign_free_mode

logger = logging.getLogger(__name__)

_OPENALEX_WORKS_URL = "https://api.openalex.org/works"
_MAX_PER_PAGE = 100  # Current documented OpenAlex page-size ceiling.

# OpenAlex's default `search` param is stemmed and documents wildcards as
# unsupported there (a live 400: "Wildcards (* or ?) require exact (no-stem)
# search... Use the search.exact= parameter instead"). Quoted phrases and
# boolean AND/NOT/OR pass through unmodified -- only * and ? are rejected.
_WILDCARD_CHARS_RE = re.compile(r"[*?]")
_WHITESPACE_RE = re.compile(r"\s+")


def _sanitize_query(query: str) -> str:
    """Strips OpenAlex's disallowed wildcard characters from a query.

    A model-written query carrying ``*``/``?`` (glob-style truncation
    conventions common to other search sources) makes the whole request
    fail with HTTP 400 rather than degrading to a literal match, so the
    characters are dropped and any resulting run of whitespace collapsed.

    Args:
        query: Free-text search query, as generated upstream.

    Returns:
        The query with wildcard characters removed and whitespace
        collapsed/trimmed.
    """
    stripped = _WILDCARD_CHARS_RE.sub("", query)
    cleaned = _WHITESPACE_RE.sub(" ", stripped).strip()
    if cleaned != query:
        logger.info("Rewrote OpenAlex query %r to %r", query, cleaned)
    return cleaned


class OpenAlexUnavailableError(RuntimeError):
    """OpenAlex could not be searched, as distinct from having no match."""


def _refusal_detail(response: httpx.Response) -> str:
    """Lift OpenAlex's own explanation out of an error body, if it gave one."""
    try:
        body = response.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    return str(body.get("message") or body.get("error") or "")


def _unavailable_reason(exc: Exception) -> str:
    """Describe why OpenAlex refused, in terms worth reading in a log.

    A rate limit is the failure this source actually has, and its body
    carries the only useful part -- how long the caller is locked out and
    why -- so it is lifted out rather than left as a bare status code.

    Args:
        exc: The failure raised while searching.

    Returns:
        A single-line reason.
    """
    if not isinstance(exc, httpx.HTTPStatusError):
        return f"{type(exc).__name__}: {exc}"
    parts = [f"HTTP {exc.response.status_code}"]
    detail = _refusal_detail(exc.response)
    if detail:
        parts.append(detail)
    retry_after = exc.response.headers.get("retry-after")
    if retry_after:
        parts.append(f"retry after {retry_after}s")
    return "; ".join(parts)


def _reconstruct_abstract(inverted_index: Any) -> str:
    """Restore abstract word order from OpenAlex's position lists."""
    if not isinstance(inverted_index, dict):
        return ""
    positions = [
        (position, str(word))
        for word, offsets in inverted_index.items()
        if isinstance(offsets, list)
        for position in offsets
        if isinstance(position, int)
    ]
    positions.sort(key=lambda item: item[0])
    return " ".join(word for _, word in positions)


def normalize_works(  # noqa: C901
    data: dict[str, Any], max_papers: int
) -> dict[str, Any]:
    """Normalize OpenAlex results to metadata keyed by short work ID."""
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return {}
    normalized: dict[str, Any] = {}
    for work in results[: max(max_papers, 0)]:
        if not isinstance(work, dict):
            continue
        raw_id = str(work.get("id") or "")
        work_id = raw_id.rsplit("/", 1)[-1]
        if not work_id:
            continue
        authors = []
        for authorship in work.get("authorships") or []:
            if isinstance(authorship, dict):
                name = (authorship.get("author") or {}).get("display_name", "")
                if isinstance(name, str) and name:
                    authors.append(name)
        location = work.get("primary_location") or {}
        landing_page = (
            location.get("landing_page_url")
            if isinstance(location, dict)
            else None
        )
        normalized[work_id] = {
            "title": work.get("title") or work.get("display_name") or "",
            "authors": authors,
            "year": work.get("publication_year"),
            "abstract": _reconstruct_abstract(
                work.get("abstract_inverted_index")
            ),
            "url": landing_page or work.get("doi") or raw_id,
            "source": "openalex",
            "cited_by_count": work.get("cited_by_count", 0),
            "publication_date": work.get("publication_date"),
            "updated_date": work.get("updated_date"),
            "work_type": work.get("type"),
            "is_retracted": bool(work.get("is_retracted", False)),
        }
    return normalized


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
        "search": _sanitize_query(query),
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
    # Anonymous quota cannot draw down the host account's prepaid balance.
    if api_key and not campaign_free_mode():
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
    async with httpx.AsyncClient(
        timeout=30, trust_env=not campaign_free_mode()
    ) as client:
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
        A dict of normalized works, empty when OpenAlex answered and had
        no match.

    Raises:
        OpenAlexUnavailableError: OpenAlex could not be asked -- refused,
            unreachable, or answering with something unparseable. Raised
            rather than returned as no results so the caller can tell a
            missing source from an empty one.
    """
    params, per_page = _build_search_params(query, max_papers, recency_years)
    try:
        return await _collect_openalex_works(params, per_page, max_papers)
    except (httpx.HTTPError, ValueError) as exc:
        reason = _unavailable_reason(exc)
        logger.warning("OpenAlex search failed for %r: %s", query, reason)
        raise OpenAlexUnavailableError(
            f"OpenAlex could not be searched: {reason}"
        ) from exc
