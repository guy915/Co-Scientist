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


def normalize_brave(data: Any, max_results: int) -> dict[str, Any]:
    """Normalizes a Brave web-search response.

    Pure function (no I/O) so it can be unit-tested directly.

    Args:
        data: Parsed JSON from the Brave search endpoint.
        max_results: Maximum number of results to keep.

    Returns:
        A dict of normalized results, empty if the payload is malformed.
    """
    web = data.get("web") if isinstance(data, dict) else None
    results = web.get("results") if isinstance(web, dict) else None
    if not isinstance(results, list):
        return {}

    out: dict[str, Any] = {}
    for index, item in enumerate(results[: max(max_results, 0)]):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        if not url:
            continue
        out[_result_id("brave", index, url)] = {
            "title": clean_snippet(item.get("title")),
            "url": url,
            # Brave's "description" is the result snippet, with query terms
            # wrapped in <strong>. It maps onto abstract because that is the
            # field the engine's article pipeline already reads for summary
            # text.
            "abstract": clean_snippet(item.get("description")),
            "source": "web",
            "published_date": item.get("page_age") or item.get("age") or "",
            "site": (item.get("profile") or {}).get("name")
            if isinstance(item.get("profile"), dict)
            else "",
        }
    return out


def normalize_tavily(data: Any, max_results: int) -> dict[str, Any]:
    """Normalizes a Tavily search response.

    Pure function (no I/O) so it can be unit-tested directly.

    Args:
        data: Parsed JSON from the Tavily search endpoint.
        max_results: Maximum number of results to keep.

    Returns:
        A dict of normalized results, empty if the payload is malformed.
    """
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return {}

    out: dict[str, Any] = {}
    for index, item in enumerate(results[: max(max_results, 0)]):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        if not url:
            continue
        out[_result_id("tavily", index, url)] = {
            "title": clean_snippet(item.get("title")),
            "url": url,
            # Tavily returns extracted page text, not just a snippet, so a
            # hit is often usable without a follow-up read_url call.
            "abstract": clean_snippet(item.get("content")),
            "source": "web",
            "published_date": item.get("published_date") or "",
            "score": item.get("score"),
        }
    return out


async def search_brave(
    query: str, max_results: int, recency_days: int
) -> dict[str, Any]:
    """Runs one Brave web search.

    Args:
        query: Natural-language search query.
        max_results: Maximum number of results to return.
        recency_days: Restrict to results this recent; 0 means no limit.

    Returns:
        Normalized results, or an empty dict on any network or parse error
        so a failed search degrades to "no results" rather than raising.
    """
    params: dict[str, str] = {
        "q": query,
        "count": str(min(max(max_results, 1), 20)),
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
        max_results: Maximum number of results to return.
        recency_days: Restrict to results this recent; 0 means no limit.

    Returns:
        Normalized results, or an empty dict on any network or parse error.
    """
    payload: dict[str, Any] = {
        "query": query,
        "max_results": min(max(max_results, 1), 20),
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
        entry = _PROVIDERS.get(requested)
        if entry is None:
            logger.warning(
                "Unknown WEB_SEARCH_PROVIDER %r, falling back to autodetect",
                requested,
            )
        elif os.environ.get(entry[1]):
            return requested, entry[0]
        else:
            logger.warning(
                "WEB_SEARCH_PROVIDER=%s but %s is not set", requested, entry[1]
            )

    for name in _AUTODETECT_ORDER:
        search_fn, key_var = _PROVIDERS[name]
        if os.environ.get(key_var):
            return name, search_fn
    return None
