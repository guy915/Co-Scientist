"""MCP/PubMed availability resolution for the hypothesis generator.

Provides the mixin that lazily checks whether the MCP server and PubMed
are reachable, caches the answers per generator instance, and decides
whether the literature review node should be part of a generation call.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class McpAvailabilityMixin:
    """Lazy, per-instance MCP/PubMed availability checks for the generator.

    ``HypothesisGenerator`` mixes this in; the attributes below are
    assigned in its ``__init__``.
    """

    _tool_registry: Any | None
    _mcp_available: bool | None
    _pubmed_available: bool | None

    async def _check_cached_availability(self) -> tuple[bool, bool]:
        """Lazily checks and caches MCP/PubMed availability for this call.

        Each check runs at most once per instance; later calls reuse
        ``self._mcp_available`` / ``self._pubmed_available``.

        Returns:
            Tuple of (mcp_available, pubmed_available).
        """
        from co_scientist.mcp_client import (
            check_mcp_available,
            check_pubmed_available_via_mcp,
        )

        if self._mcp_available is None:
            self._mcp_available = await check_mcp_available(
                tool_registry=self._tool_registry
            )
        if self._pubmed_available is None:
            self._pubmed_available = await check_pubmed_available_via_mcp(
                tool_registry=self._tool_registry
            )

        return self._mcp_available, self._pubmed_available

    async def _resolve_literature_review_settings(
        self,
        opts: dict[str, Any],
    ) -> tuple[bool, bool, bool]:
        """Determines literature-review/MCP availability for this call.

        Checks are cached per instance (on ``self._mcp_available`` and
        ``self._pubmed_available``) and skipped entirely when the caller has
        explicitly disabled the literature review node.

        Args:
            opts: Caller-supplied generation options.

        Returns:
            Tuple of (mcp_available, pubmed_available,
            enable_literature_review_node).
        """
        # Check if explicitly set in opts first to avoid unnecessary MCP
        # checks
        if opts.get("enable_literature_review_node") is False:
            # Literature review explicitly disabled, no need to check MCP
            return False, False, False

        # Check system availability (cached per instance)
        (
            mcp_available,
            pubmed_available,
        ) = await self._check_cached_availability()

        # Determine if literature review node should be included
        # user can override via opts, otherwise auto-detect based on MCP
        # availability
        enable_literature_review_node = opts.get(
            "enable_literature_review_node", mcp_available
        )

        if not mcp_available and enable_literature_review_node:
            logger.warning(
                "Literature review node requested but MCP server"
                " unavailable - disabling"
            )
            enable_literature_review_node = False

        return mcp_available, pubmed_available, enable_literature_review_node
