"""Tools-config resolution, validation, and reporting for real runs.

The engine's ``HypothesisGenerator`` accepts a ``tools_config`` (path or URL to
a YAML tools config), but the app adapter historically never forwarded
``settings.tools_config``, so a production ``TOOLS_CONFIG=...indra_cancer.yaml``
was silently ignored and real runs ran the default PubMed-only tools. This
module resolves and validates that setting so a misconfiguration fails loudly
at startup, and reports the effective config (and its enabled tools) on
``/status``.
"""

from __future__ import annotations

import functools
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


# User-facing data-source connectors, matched (case-insensitively) against the
# enabled tool ids so a configured tools YAML surfaces its sources in the
# composer's connectors menu. Add an entry here when a new connector's tools are
# wired up so it appears in the menu automatically.
_KNOWN_CONNECTORS: tuple[tuple[str, str], ...] = (
    ("pubmed", "PubMed"),
    ("indra", "INDRA"),
)


def connectors_report(
    *, literature_available: bool, enabled_tools: list[str] | None
) -> list[dict[str, str]]:
    """Derive the user-facing data-source connectors for the composer menu.

    PubMed is the literature base and is listed whenever the literature stack
    is available; any other known connector is listed when the configured tools
    YAML enables a matching tool. Falls back to PubMed so the menu is never
    empty.

    Args:
        literature_available: Whether the MCP + PubMed literature stack is up.
        enabled_tools: Enabled tool ids from a readable tools config, or None.

    Returns:
        Ordered connectors, each ``{"id": ..., "display": ...}``.
    """
    tool_blob = " ".join(enabled_tools or []).lower()
    connectors: list[dict[str, str]] = []
    for key, display in _KNOWN_CONNECTORS:
        matched = key in tool_blob or (key == "pubmed" and literature_available)
        if matched:
            connectors.append({"id": key, "display": display})
    if not connectors:
        connectors.append({"id": "pubmed", "display": "PubMed"})
    return connectors


def _is_url(value: str) -> bool:
    """True when a tools_config value is an HTTP(S) URL, not a local path.

    A URL is passed through to the engine unchecked; only local paths get a
    readability check, since a URL cannot be resolved against the filesystem.
    """
    return value.startswith("http://") or value.startswith("https://")


def validate_tools_config(value: str | None) -> None:
    """Fail loudly if a configured local tools_config path is not readable.

    A configured-but-unreadable path is an operator error worth surfacing at
    startup rather than silently falling back to default tools (the bug this
    guards against). ``None`` (unset) and URLs are accepted without a
    filesystem check.

    Args:
        value: The configured ``settings.tools_config`` (path, URL, or None).

    Raises:
        RuntimeError: When ``value`` is a local path that does not resolve to
            a readable file.
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
def _enabled_tools(value: str) -> list[str] | None:
    """Return the sorted enabled tool ids for a readable config, best-effort.

    Builds a throwaway ``ToolRegistry`` from the config to enumerate the tools
    a real run would actually enable. Returns None when the engine is not
    importable or the registry cannot be built, so /status degrades to
    reporting the path alone rather than erroring. Cached by path because the
    config is fixed for the process's lifetime (a change needs a restart, which
    also re-runs startup validation), so a polled /status does not re-parse the
    YAML on every call.

    Args:
        value: A readable local tools_config path.

    Returns:
        Sorted enabled tool ids, or None if they cannot be enumerated.
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
    """Describe the effective tools config for the /status route.

    Args:
        value: The configured ``settings.tools_config`` (path, URL, or None).

    Returns:
        A dict with ``tools_config`` (the configured value),
        ``tools_config_valid`` (False only for a configured-but-unreadable
        local path), and ``enabled_tools`` (the sorted enabled tool ids for a
        readable local config, else None — unset/URL/unenumerable configs
        report None).
    """
    if value is None:
        return {
            "tools_config": None,
            "tools_config_valid": True,
            "enabled_tools": None,
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
