from __future__ import annotations

import functools
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


_KNOWN_CONNECTORS: tuple[tuple[str, str], ...] = (
    ("web_search", "Web search"),
    ("pubmed", "PubMed"),
    ("arxiv", "arXiv"),
    ("biorxiv", "BioRxiv"),
    ("indra", "INDRA"),
)


def connectors_report(
    *,
    literature_available: bool,
    enabled_tools: list[str] | None,
    web_search_available: bool = False,
) -> list[dict[str, str]]:
    """Advertised sources require actual reachability and configuration;
    shared-MCP keyless sources require both.
    """
    tool_blob = " ".join(enabled_tools or []).lower()
    available_by_probe = {
        "pubmed": literature_available,
        "web_search": web_search_available,
        "arxiv": literature_available and "arxiv" in tool_blob,
        "biorxiv": literature_available and "biorxiv" in tool_blob,
    }
    connectors: list[dict[str, str]] = []
    for key, display in _KNOWN_CONNECTORS:
        probed = available_by_probe.get(key)
        listed = probed if probed is not None else key in tool_blob
        if listed:
            connectors.append({"id": key, "display": display})
    if not connectors:
        connectors.append({"id": "pubmed", "display": "PubMed"})
    return connectors


def _is_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def validate_tools_config(value: str | None) -> None:
    """Unreadable configured paths fail at startup rather than silently
    selecting different scientific tools.
    """
    if value is None or _is_url(value):
        return
    if not os.path.isfile(value):
        raise RuntimeError(
            f"tools_config is set to {value!r} but no readable file exists "
            f"there (relative paths resolve from the server working "
            f"directory); fix TOOLS_CONFIG or unset it"
        )


@functools.lru_cache(maxsize=8)
def _enabled_tools(value: str | None) -> list[str] | None:
    """Unset configuration means bundled defaults; process-lifetime caching
    avoids reparsing YAML on every status poll.
    """
    try:
        from co_scientist.config import ToolRegistry
    except Exception:  # pragma: no cover - engine optional at runtime
        return None
    try:
        registry = ToolRegistry(config_path=value, skip_user_config=True)
        return sorted(registry.get_enabled_tools().keys())
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("could not enumerate tools from %s: %s", value, exc)
        return None


def tools_config_report(value: str | None) -> dict[str, Any]:
    if value is None:
        return {
            "tools_config": None,
            "tools_config_valid": True,
            "enabled_tools": _enabled_tools(None),
        }
    if _is_url(value):
        return {
            "tools_config": value,
            "tools_config_valid": True,
            "enabled_tools": None,
        }
    valid = os.path.isfile(value)
    return {
        "tools_config": value,
        "tools_config_valid": valid,
        "enabled_tools": _enabled_tools(value) if valid else None,
    }
