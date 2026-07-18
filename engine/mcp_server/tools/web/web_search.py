"""General-web search tool.

Complements the academic sources (PubMed, OpenAlex, ChEMBL, UniProt) with the
open web: news, grey literature, consortium and regulatory material, and
recent developments that have not become papers. Provider selection and
response normalization live in ``providers``; this module is the MCP-facing
surface.
"""

import logging
from typing import Any

from mcp_server.tools.web.providers import resolve_provider

logger = logging.getLogger(__name__)

_MAX_RESULTS_CEILING = 20


async def search_web(
    query: str,
    max_results: int = 10,
    recency_days: int = 0,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Search the web and return ``{result_id: metadata}``.

    Args:
        query: Natural-language search query. Boolean operators are not
            interpreted by web engines the way they are by PubMed.
        max_results: Maximum number of results to return.
        recency_days: If > 0, restrict to results published within this many
            days.
        run_id: Unused; accepted for interface parity with other search
            tools.

    Returns:
        A dict keyed by result id, each value carrying title, url, abstract
        (the result snippet or extracted page text), source, and
        published_date. Empty on any error so a failed search degrades
        gracefully.
    """
    provider = resolve_provider()
    if provider is None:
        logger.warning("Web search requested but no provider key is configured")
        return {}

    name, search_fn = provider
    capped = min(max(max_results, 1), _MAX_RESULTS_CEILING)
    results = await search_fn(query, capped, max(recency_days, 0))
    logger.debug(
        "web search via %s returned %s results for %r",
        name,
        len(results),
        query,
    )
    return results
