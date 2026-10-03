"""Retrieval for the research loop, over this engine's MCP tools.

``co_scientist.research`` states its needs as two protocols and imports
nothing from the rest of the engine. This module is one half of the other
side of that boundary: it satisfies :class:`RetrievalPort` using the same
MCP search path the literature review already uses, so a research thread
searches exactly the sources a run has configured and no others.

Deliberately reused rather than reimplemented: ``_call_search_tool``
(which owns the transient-failure retry every source needs),
``_build_query_tool_params`` and ``normalize_search_response`` (which own
the per-tool argument and response shapes), and ``build_content_config``
(which owns the per-source full-text tool). A second copy of any of them
would drift from the one the literature review is tested against.

What this module adds is the part the loop needs and the review path does
not: one search is one source and one query, hits keep the source's own
ranking, and a failure is raised as :class:`RetrievalError` so the loop
records it as a failed call rather than losing it.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from co_scientist.config.registry import ToolRegistry
from co_scientist.config.workflow_schema import WorkflowConfig
from co_scientist.constants import corpus_slug
from co_scientist.evidence.retrieval_support import (
    build_content_config,
    describe_exception,
    parse_content_result,
)
from co_scientist.evidence.search_query import (
    _build_query_tool_params,
)
from co_scientist.evidence.search_retry import (
    _call_search_tool,
)
from co_scientist.evidence.search_support import (
    normalize_search_response,
)
from co_scientist.mcp_client import MCPToolClient
from co_scientist.mcp_client.campaign import campaign_serves_tool
from co_scientist.research import RetrievalError, SourceHit


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


logger = logging.getLogger(__name__)

# Metadata fields worth carrying onto a hit. The raw record is kept
# separately for the full-text fetch; what travels with the hit is only
# what a later reader or a stored provenance row can use, since
# SourceHit.metadata is part of the call's content id and a field that
# varies per fetch (a timestamp, a score recomputed on retry) would make
# the same search hash differently every time.
_CARRIED_FIELDS = ("doi", "pmid", "year", "url", "publication", "venue")


@dataclass(frozen=True)
class ResearchRun:
    """Which run is researching, and what for.

    Bundled rather than passed loose because both fields travel together
    into every tool call: sources that scope by run want the id, sources
    that scope by corpus want the slug derived from the goal, and
    per-tool content params may substitute the goal itself.

    Attributes:
        run_id: Owning run, passed to tools that scope by it.
        research_goal: The goal this research serves.
    """

    run_id: str
    research_goal: str = ""

    @property
    def slug(self) -> str:
        """Corpus slug for this goal, derived the way every caller does.

        The warm corpus is keyed by this slug, so deriving it any other
        way is a silent cache miss and a re-download.
        """
        return corpus_slug(self.research_goal) if self.research_goal else ""


class McpRetrieval:
    """Search and read through the run's configured MCP tools.

    One instance serves one research request. It remembers each hit's raw
    metadata as it goes, because the full-text tool is addressed by a URL
    field of the search record and a locator on its own does not carry
    one.

    Attributes:
        sources: Enabled search source tool ids, in workflow order. This
            is what a caller passes to ``ResearchBudget.sources``; the
            loop searches each of them per question.
    """

    def __init__(
        self,
        mcp_client: MCPToolClient,
        registry: ToolRegistry,
        workflow: WorkflowConfig,
        run: ResearchRun,
    ) -> None:
        """Bind the client and the run's tool configuration.

        Args:
            mcp_client: Initialized client for this run's MCP servers.
            registry: Resolves a source's tool id to its tool config.
            workflow: The literature workflow whose enabled sources and
                content tools this retrieval uses.
            run: Which run is researching, and what for.
        """
        self._client = mcp_client
        self._registry = registry
        self._workflow = workflow
        self._run = run
        self._records: dict[str, tuple[str, dict[str, Any]]] = {}
        # A source the campaign MCP policy refuses would fail every call it
        # is given, so it is not offered to the loop at all.
        self.sources: tuple[str, ...] = tuple(
            source.tool
            for source in workflow.get_enabled_search_sources()
            if _campaign_admits(registry, source.tool)
        )

    async def search(
        self, *, query: str, source: str, limit: int
    ) -> Sequence[SourceHit]:
        """Run one query against one source.

        Args:
            query: The query to issue.
            source: Tool id of the source to search.
            limit: Most results wanted.

        Returns:
            Hits in the source's own ordering.

        Raises:
            RetrievalError: The source is not configured, or the call
                failed after its retries. The loop records either as a
                failed call and carries on with the other sources.
        """
        tool_config = self._registry.get_tool(source)
        if tool_config is None:
            raise RetrievalError(source, "no such tool in the registry")
        params = _build_query_tool_params(
            query, self._run.slug, self._run.run_id, limit, tool_config
        )
        try:
            raw = await _call_search_tool(
                self._client, tool_config.mcp_tool_name, params
            )
        except Exception as exc:
            raise RetrievalError(source, describe_exception(exc)) from exc
        return self._to_hits(
            normalize_search_response(raw, tool_config), source, limit
        )

    def record(self, locator: str) -> dict[str, Any] | None:
        """Return the search record behind a locator, if this saw it.

        The loop hands its caller findings bound to locators, and a
        locator is opaque -- it carries no title, no URL and no year. A
        caller turning findings into its own records needs what the
        source actually returned, which only this instance still holds.

        Args:
            locator: Identifier from a hit this instance returned.

        Returns:
            A copy of the source's own metadata, or None for a locator
            this instance never saw.
        """
        known = self._records.get(locator)
        return dict(known[1]) if known is not None else None

    async def read(self, *, locator: str) -> str | None:
        """Fetch a hit's full text, when a content tool can reach it.

        Returns None whenever the text cannot be had -- an unconfigured
        content tool, a record with no URL, or a failed fetch are all the
        same answer to the loop, which falls back to the snippet rather
        than dropping the document.

        Args:
            locator: Identifier from a hit this instance returned.

        Returns:
            The document's text, or None.
        """
        known = self._records.get(locator)
        if known is None:
            return None
        source, record = known
        config = build_content_config(
            self._workflow, self._registry, self._workflow.is_multi_source()
        ).get(source)
        if config is None:
            return None
        url = record.get(config.url_field)
        if not url:
            return None
        return await self._fetch(locator, str(url), config)

    async def _fetch(self, locator: str, url: str, config: Any) -> str | None:
        """Call one content tool for one document, swallowing failures."""
        from co_scientist.config.schema import resolve_content_params

        params = resolve_content_params(
            config.content_params,
            {"research_goal": self._run.research_goal, "focus_areas": []},
        )
        try:
            result = await self._client.call_tool(
                config.mcp_tool_name, url=url, **params
            )
        except Exception as exc:
            logger.warning(
                "Could not read %s via %s: %s",
                locator,
                config.mcp_tool_name,
                describe_exception(exc),
            )
            return None
        return parse_content_result(result)

    def _to_hits(
        self,
        normalized: dict[str, dict[str, Any]],
        source: str,
        limit: int,
    ) -> list[SourceHit]:
        """Convert normalized search records to hits, keeping their order."""
        hits = []
        for rank, (locator, record) in enumerate(normalized.items()):
            if rank >= limit:
                break
            self._records[locator] = (source, record)
            hits.append(
                SourceHit(
                    locator=locator,
                    title=str(record.get("title") or locator),
                    snippet=str(record.get("abstract") or ""),
                    rank=rank,
                    score=_as_score(record.get("retrieval_score")),
                    metadata=_carried(record, source),
                )
            )
        return hits


def _campaign_admits(registry: ToolRegistry, source: str) -> bool:
    """Whether the campaign MCP policy lets this run search ``source``."""
    tool = registry.get_tool(source)
    return tool is None or campaign_serves_tool(tool.mcp_tool_name)


def _as_score(value: Any) -> float | None:
    """Read a source's own score, when it gave one that is a number."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _carried(record: dict[str, Any], source: str) -> dict[str, str]:
    """Take the stable identifying fields off a search record."""
    carried = {"source": source}
    for field in _CARRIED_FIELDS:
        value = record.get(field)
        if value not in (None, "", []):
            carried[field] = str(value)
    return carried
