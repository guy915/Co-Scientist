"""General-web search tool.

Complements the academic sources (PubMed, OpenAlex, ChEMBL, UniProt) with the
open web: news, grey literature, consortium and regulatory material, and
recent developments that have not become papers. Provider selection and
response normalization live in ``providers``; this module is the MCP-facing
surface.
"""

import logging
from typing import Any

from mcp_server.tools.web.providers import (
    resolve_provider,
    web_search_credential_error,
)

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


async def check_web_search_available() -> bool:
    """Reports whether a web search issued now would reach a provider.

    The connector's status used to be inferred from whether the server
    advertises ``search_web`` at all, which only tells you that some key
    was set at boot. A key that the provider has since refused -- revoked,
    unpaid, or out of quota -- leaves the tool registered and answering
    every search with an empty result set, so the connector reads as
    healthy while returning nothing. This answers the question that was
    actually being asked.

    Returns:
        True when a provider is configured and its key has not been
        refused since the last search that worked.
    """
    if resolve_provider() is None:
        return False
    return web_search_credential_error() is None
