"""One retrieval port in front of the research loop.

The research loop searches a list of source names and does not care where
any of them lives -- that is the point of the port. This wraps the run's
MCP retrieval so a caller building the loop's dependencies goes through
one seam rather than depending on :class:`McpRetrieval` directly, which is
what lets a future second source join without every call site changing.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from co_scientist.research import RetrievalError, SourceHit
from co_scientist.research_adapter.retrieval import McpRetrieval


class ResearchRetrieval:
    """Route search and read to the run's MCP retrieval.

    Attributes:
        sources: Every source this run may search, in workflow order.
            This is what a caller hands to a budget.
    """

    def __init__(self, remote: McpRetrieval | None = None) -> None:
        """Bind the run's MCP retrieval, when it has one.

        Args:
            remote: Search over the run's MCP tools, when reachable.
        """
        self._remote = remote
        self.sources: tuple[str, ...] = (
            remote.sources if remote is not None else ()
        )

    async def search(
        self, *, query: str, source: str, limit: int
    ) -> Sequence[SourceHit]:
        """Search one source through the MCP port.

        Args:
            query: The query to issue.
            source: Which source to search.
            limit: Most results wanted.

        Returns:
            Hits in that source's own ordering.

        Raises:
            RetrievalError: No MCP retrieval is available, or the call
                failed. The loop records either as a failed call and
                carries on with the remaining sources.
        """
        if self._remote is None:
            raise RetrievalError(source, "no search server available")
        return await self._remote.search(
            query=query, source=source, limit=limit
        )

    async def read(self, *, locator: str) -> str | None:
        """Read a document through the MCP port.

        Args:
            locator: Identifier from a hit this composite returned.

        Returns:
            The text, or None when it cannot be had.
        """
        if self._remote is None:
            return None
        return await self._remote.read(locator=locator)

    def record(self, locator: str) -> dict[str, Any] | None:
        """Return the search record behind a locator, if this saw it.

        Args:
            locator: Identifier from a hit this composite returned.

        Returns:
            The record, or None for a locator this composite never saw.
        """
        if self._remote is None:
            return None
        return self._remote.record(locator)
