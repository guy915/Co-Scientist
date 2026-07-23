"""General-web search providers behind one normalized interface.

The engine consumes search results as ``{result_id: metadata}`` dicts, the
same shape the OpenAlex and PubMed tools return, so every provider here
normalizes into that shape and the rest of the pipeline stays provider
agnostic. Swapping providers is an environment-variable change.

Two providers are implemented: Brave (an independent index, the default) and
Tavily (agent-oriented, returns extracted page content alongside results).
"""

import hashlib
import html
import logging
import os
import re
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Search snippets arrive with markup: Brave wraps query-term matches in
# <strong>, and providers pass through entities from the source page. The
# agent should never see tags, so snippets are cleaned to plain text on the
# way in, the same guarantee read_url gives for page bodies.
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def clean_snippet(raw: Any) -> str:
    """Strips markup and normalizes whitespace in a result snippet.

    Args:
        raw: Snippet text from a provider, possibly containing HTML tags
            and character entities.

    Returns:
        Plain text with tags removed, entities decoded, and runs of
        whitespace collapsed. Empty string for missing or non-string input.
    """
    if not isinstance(raw, str) or not raw:
        return ""
    # Unescape after stripping tags so an encoded "&lt;b&gt;" in the source
    # text cannot reintroduce a tag that the strip already removed.
    text = html.unescape(_TAG_RE.sub("", raw))
    return _WHITESPACE_RE.sub(" ", text).strip()


_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
_TAVILY_URL = "https://api.tavily.com/search"

_REQUEST_TIMEOUT = 30

# Brave expresses recency as a coarse bucket rather than a day count.
_BRAVE_FRESHNESS_BUCKETS = ((1, "pd"), (7, "pw"), (31, "pm"), (365, "py"))


def _result_id(prefix: str, index: int, url: str) -> str:
    """Builds a stable per-result key for the returned dict.

    Args:
        prefix: Provider short name.
        index: Rank of the result within the response.
        url: Result URL, used to keep keys distinct when ranks collide
            across merged calls.

    Returns:
        A key of the form ``"<prefix>-<index>-<url digest>"``. A blake2b
        digest of the URL, not the built-in ``hash``, so the id is stable
        across processes -- it becomes the Article's source_id, which
        lineage and deduplication key on.
    """
    digest = hashlib.blake2b(url.encode(), digest_size=4).hexdigest()
    return f"{prefix}-{index}-{digest}"


def _brave_freshness(recency_days: int) -> str | None:
    """Maps a day count onto Brave's freshness buckets.

    Args:
        recency_days: Restrict to results this recent; 0 means no limit.

    Returns:
        A Brave freshness code, or None when no restriction applies.
    """
    if recency_days <= 0:
        return None
    for threshold, code in _BRAVE_FRESHNESS_BUCKETS:
        if recency_days <= threshold:
            return code
    return None


def _result_metadata(
    item: dict[str, Any],
    url: str,
    provider_fields: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Builds the metadata for one normalized result.

    Args:
        item: One raw result item from the provider.
        url: The item's already-extracted result URL.
        provider_fields: Maps the item to provider-specific fields.

    Returns:
        The common metadata merged with the provider-specific fields.
    """
    return {
        "title": clean_snippet(item.get("title")),
        "url": url,
        "source": "web",
        **provider_fields(item),
    }


def _normalize_results(
    results: Any,
    max_results: int,
    prefix: str,
    provider_fields: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Builds the shared ``{result_id: metadata}`` envelope.

    Owns everything the providers have in common -- the list guard, the
    result cap, the per-item dict and url checks, the id scheme, and the
    common fields -- so a provider defines only its own field mapping and
    the two cannot drift apart.

    Args:
        results: The provider's raw result list (any type; non-lists yield
            an empty dict).
        max_results: Maximum number of results to keep.
        prefix: Provider short name for ``_result_id``.
        provider_fields: Maps one raw result item to the provider-specific
            metadata fields.

    Returns:
        A dict of normalized results, empty if the payload is malformed.
    """
    if not isinstance(results, list):
        return {}

    out: dict[str, Any] = {}
    for index, item in enumerate(results[: max(max_results, 0)]):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        if not url:
            continue
        key = _result_id(prefix, index, url)
        out[key] = _result_metadata(item, url, provider_fields)
    return out


def normalize_brave(data: Any, max_results: int) -> dict[str, Any]:
    """Normalizes a Brave web-search response.

    Pure function (no I/O) so it can be unit-tested directly.

    Args:
        data: Parsed JSON from the Brave search endpoint.
        max_results: Maximum number of results to keep.

    Returns:
        A dict of normalized results, empty if the payload is malformed.
    """

    def fields(item: dict[str, Any]) -> dict[str, Any]:
        # Brave's "description" is the result snippet, with query terms
        # wrapped in <strong>. It maps onto abstract because that is the
        # field the engine's article pipeline already reads for summary
        # text.
        return {
            "abstract": clean_snippet(item.get("description")),
            "published_date": item.get("page_age") or item.get("age") or "",
            "site": (item.get("profile") or {}).get("name")
            if isinstance(item.get("profile"), dict)
            else "",
        }

    web = data.get("web") if isinstance(data, dict) else None
    results = web.get("results") if isinstance(web, dict) else None
    return _normalize_results(results, max_results, "brave", fields)


def normalize_tavily(data: Any, max_results: int) -> dict[str, Any]:
    """Normalizes a Tavily search response.

    Pure function (no I/O) so it can be unit-tested directly.

    Args:
        data: Parsed JSON from the Tavily search endpoint.
        max_results: Maximum number of results to keep.

    Returns:
        A dict of normalized results, empty if the payload is malformed.
    """

    def fields(item: dict[str, Any]) -> dict[str, Any]:
        # Tavily returns extracted page text, not just a snippet, so a
        # hit is often usable without a follow-up read_url call.
        return {
            "abstract": clean_snippet(item.get("content")),
            "published_date": item.get("published_date") or "",
            "score": item.get("score"),
        }

    results = data.get("results") if isinstance(data, dict) else None
    return _normalize_results(results, max_results, "tavily", fields)


async def search_brave(
    query: str, max_results: int, recency_days: int
) -> dict[str, Any]:
    """Runs one Brave web search.

    Args:
        query: Natural-language search query.
        max_results: Maximum number of results to return. ``search_web``,
            the only caller, has already clamped this to a sane range.
        recency_days: Restrict to results this recent; 0 means no limit.

    Returns:
        Normalized results, or an empty dict on any network or parse error
        so a failed search degrades to "no results" rather than raising.
    """
    params: dict[str, str] = {
        "q": query,
        "count": str(max_results),
    }
    freshness = _brave_freshness(recency_days)
    if freshness:
        params["freshness"] = freshness
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": os.environ.get("BRAVE_API_KEY", ""),
    }
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(_BRAVE_URL, params=params, headers=headers)
            resp.raise_for_status()
            return normalize_brave(resp.json(), max_results)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Brave web search failed for %r: %s", query, exc)
        return {}


async def search_tavily(
    query: str, max_results: int, recency_days: int
) -> dict[str, Any]:
    """Runs one Tavily search.

    Args:
        query: Natural-language search query.
        max_results: Maximum number of results to return. ``search_web``,
            the only caller, has already clamped this to a sane range.
        recency_days: Restrict to results this recent; 0 means no limit.

    Returns:
        Normalized results, or an empty dict on any network or parse error.
    """
    payload: dict[str, Any] = {
        "query": query,
        "max_results": max_results,
        "search_depth": "basic",
    }
    if recency_days > 0:
        payload["days"] = recency_days
    headers = {
        "Authorization": f"Bearer {os.environ.get('TAVILY_API_KEY', '')}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.post(_TAVILY_URL, json=payload, headers=headers)
            resp.raise_for_status()
            return normalize_tavily(resp.json(), max_results)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Tavily search failed for %r: %s", query, exc)
        return {}


SearchFn = Callable[[str, int, int], Awaitable[dict[str, Any]]]

# Provider name -> (search function, name of the env var holding its key).
_PROVIDERS: dict[str, tuple[SearchFn, str]] = {
    "brave": (search_brave, "BRAVE_API_KEY"),
    "tavily": (search_tavily, "TAVILY_API_KEY"),
}

# Order used when WEB_SEARCH_PROVIDER is unset: first provider with a key
# configured wins. Brave leads on latency and runs an index independent of
# Google and Bing.
_AUTODETECT_ORDER = ("brave", "tavily")


def _resolve_requested_provider(requested: str) -> tuple[str, SearchFn] | None:
    """Resolves an explicit ``WEB_SEARCH_PROVIDER`` request.

    Args:
        requested: The lowercased, stripped value of the env var.

    Returns:
        A (provider name, search function) pair when the requested
        provider is known and its key is configured, otherwise None (with
        a warning logged explaining why).
    """
    entry = _PROVIDERS.get(requested)
    if entry is None:
        logger.warning(
            "Unknown WEB_SEARCH_PROVIDER %r, falling back to autodetect",
            requested,
        )
        return None
    if os.environ.get(entry[1]):
        return requested, entry[0]
    logger.warning(
        "WEB_SEARCH_PROVIDER=%s but %s is not set", requested, entry[1]
    )
    return None


def _autodetect_provider() -> tuple[str, SearchFn] | None:
    """Picks the first autodetect-order provider with a key configured.

    Returns:
        A (provider name, search function) pair, or None if no provider
        in ``_AUTODETECT_ORDER`` has its key set.
    """
    for name in _AUTODETECT_ORDER:
        search_fn, key_var = _PROVIDERS[name]
        if os.environ.get(key_var):
            return name, search_fn
    return None


def resolve_provider() -> tuple[str, SearchFn] | None:
    """Selects the configured web-search provider.

    An explicit ``WEB_SEARCH_PROVIDER`` wins when its key is present.
    Otherwise the first provider in autodetect order with a key configured
    is used.

    Returns:
        A (provider name, search function) pair, or None when no provider
        has an API key configured. None is what suppresses tool
        registration, so a key-less deployment never advertises a web
        search tool it cannot serve.
    """
    requested = os.environ.get("WEB_SEARCH_PROVIDER", "").strip().lower()
    if requested:
        result = _resolve_requested_provider(requested)
        if result is not None:
            return result

    return _autodetect_provider()
