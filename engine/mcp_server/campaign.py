"""Campaign cost policy for the independently packaged reference server."""

import os


def campaign_free_mode() -> bool:
    """Read the same strict mode contract as the engine without importing it."""
    configured = (
        os.getenv("COSCIENTIST_REQUIRE_FREE_MODELS", "0").strip().lower()
    )
    if configured not in {"0", "false", "", "1", "true"}:
        raise RuntimeError("zero-cost campaign mode setting is invalid")
    return configured in {"1", "true"}


def require_metered_search_allowed() -> None:
    """Refuse account-backed search before any request or fallback."""
    if campaign_free_mode():
        raise RuntimeError("metered web search is unavailable in campaign mode")
