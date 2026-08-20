"""One retrieval port over several kinds of source.

The research loop searches a list of source names and does not care where
any of them lives. That is the point of the port -- but until now there was
only ever one implementation behind it, so "which sources exist" and "how a
source is reached" were the same question. They are not: the group's papers
sit on local disk and every other source is an MCP call, and a run has to be
able to lose all of the second kind and keep the first.

This routes by source name on the way out and by locator on the way back,
because a locator is opaque: only the port that returned it knows what it
identifies. Nothing here retries, ranks or merges -- the loop already
searches one source at a time and keeps each source's own ordering, so a
composite that reordered anything would be inventing a policy the loop
deliberately does not have.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from co_scientist.research import RetrievalError, SourceHit
from co_scientist.research_adapter.local_corpus import (
    GROUP_CORPUS_SOURCE,
    LocalCorpusRetrieval,
)
from co_scientist.research_adapter.retrieval import McpRetrieval

# The two concrete ports this routes between. Named rather than left as
# the structural protocol because `record` is not part of it: only the
# MCP half keeps the source's own metadata, and the difference has to be
# visible to the type checker rather than resolved at runtime.
_Port = McpRetrieval | LocalCorpusRetrieval


class ResearchRetrieval:
    """Route search and read across the network and local sources.

    Either half may be absent, and the interesting case is that they are
    absent for different reasons: no MCP client means the search server
    is unreachable, while no corpus means this run's audience was never
    offered one. A composite with neither has no sources at all, which
    the budget refuses before any work starts.

    Attributes:
        sources: Every source this run may search, network ones first in
            workflow order. This is what a caller hands to a budget.
    """

    def __init__(
        self,
        remote: McpRetrieval | None = None,
        local: LocalCorpusRetrieval | None = None,
    ) -> None:
        """Bind whichever halves this run actually has.

        Args:
            remote: Search over the run's MCP tools, when reachable.
            local: Search over the group's papers on disk, when this
                run's audience may read them.
        """
        self._remote = remote
        self._local = local
        self._owner: dict[str, _Port] = {}
        self.sources: tuple[str, ...] = (
            *(remote.sources if remote is not None else ()),
            *(local.sources if local is not None else ()),
        )

    async def search(
        self, *, query: str, source: str, limit: int
    ) -> Sequence[SourceHit]:
        """Search one source through whichever port serves it.

        Args:
            query: The query to issue.
            source: Which source to search.
            limit: Most results wanted.

        Returns:
            Hits in that source's own ordering.

        Raises:
            RetrievalError: No port here serves that source, or the port
                that does failed. The loop records either as a failed
                call and carries on with the remaining sources.
        """
        port = self._port_for(source)
        hits = await port.search(query=query, source=source, limit=limit)
        for hit in hits:
            self._owner[hit.locator] = port
        return hits

    async def read(self, *, locator: str) -> str | None:
        """Read a document through the port that returned it.

        Args:
            locator: Identifier from a hit this composite returned.

        Returns:
            The text, or None when it cannot be had -- including for a
            locator no port here produced.
        """
        port = self._owner.get(locator)
        return None if port is None else await port.read(locator=locator)

    def record(self, locator: str) -> dict[str, Any] | None:
        """Return the search record behind a locator, if this saw it.

        The MCP port keeps the source's own metadata; the local corpus
        has no such record to keep, so an equivalent one is built from
        the hit itself. Callers turning findings into papers need the
        same shape from both, or a corpus paper reaches the pool with no
        title.

        Args:
            locator: Identifier from a hit this composite returned.

        Returns:
            The record, or None for a locator this composite never saw.
        """
        port = self._owner.get(locator)
        if port is None:
            return None
        if isinstance(port, McpRetrieval):
            return port.record(locator)
        return self._corpus_record(locator)

    def _corpus_record(self, locator: str) -> dict[str, Any] | None:
        """Build a paper-shaped record for one corpus hit."""
        if self._local is None:
            return None
        for paper in self._local.catalog():
            if str(paper.get("paper_id")) == locator:
                return {
                    "title": str(paper.get("title") or locator),
                    "abstract": str(paper.get("abstract") or ""),
                    "source_id": locator,
                    "source": GROUP_CORPUS_SOURCE,
                }
        return None

    def _port_for(self, source: str) -> _Port:
        """Pick the port serving one source name.

        Raises:
            RetrievalError: Nothing here serves it.
        """
        if source == GROUP_CORPUS_SOURCE:
            if self._local is None:
                raise RetrievalError(source, "no corpus available to this run")
            return self._local
        if self._remote is None:
            raise RetrievalError(source, "no search server available")
        return self._remote
