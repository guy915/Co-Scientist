"""Engine model, retrieval and tier-budget adapters for the research loop."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from co_scientist.config.registry import ToolRegistry
from co_scientist.config.schema import WorkflowConfig
from co_scientist.constants import (
    DEFAULT_MAX_TOKENS,
    EXTENDED_MAX_TOKENS,
    corpus_slug,
    strip_citation_markers,
    truncate_for_prompt,
)
from co_scientist.evidence.retrieval_support import (
    build_content_config,
    describe_exception,
    parse_content_result,
)
from co_scientist.evidence.search_query import (
    _build_query_tool_params,
    _call_search_tool,
)
from co_scientist.evidence.search_support import (
    SearchConfig,
    normalize_search_response,
)
from co_scientist.llm import CompletionSpec, LLMCallOptions, call_llm_json
from co_scientist.mcp_client import MCPToolClient, campaign_serves_tool
from co_scientist.prompts import load_prompt_with_schema
from co_scientist.research import (
    Document,
    ExtractedFinding,
    Extraction,
    Finding,
    ResearchBudget,
    RetrievalError,
    SourceHit,
)

logger = logging.getLogger(__name__)


# Per-document character budget for the extraction prompt. Far below the
# whole-paper budget the per-paper analysis uses, because that call embeds
# one paper and this one embeds every document a question admitted -- the
# same ceiling would multiply by the level's breadth. A read that needs
# more than this is a read the loop should have narrowed with a better
# question.
_DOCUMENT_MAX_CHARS = 24_000


class LlmResearchModel:
    """Answer the loop's five questions with one configured model.

    The model is chosen at construction, not per call, so the caller
    decides which of a run's models pays for its research -- the same
    separation the rest of the engine keeps between worker and supervisor
    models.
    """

    def __init__(
        self,
        model_name: str,
        *,
        run_id: str | None = None,
        temperature: float = 0.4,
        use_cache: bool = True,
    ) -> None:
        """Bind the model and the run this research belongs to.

        Args:
            model_name: LiteLLM model name to call.
            run_id: Owning run, for per-run cache scoping and logging.
            temperature: Sampling temperature for all five calls. Lower
                than the generation default: every one of these is a
                reading or rendering task, where variety is noise.
            use_cache: Whether a cached response may satisfy a call.
        """
        self._model = model_name
        self._run_id = run_id
        self._temperature = temperature
        self._use_cache = use_cache

    async def plan_stances(self, *, goal: str, limit: int) -> Sequence[str]:
        """Choose the perspectives the first level should cover."""
        data = await self._ask(
            "research_stances",
            {"research_goal": goal, "limit": limit},
            DEFAULT_MAX_TOKENS,
        )
        return _strings(data.get("stances"))[:limit]

    async def ask_questions(
        self, *, goal: str, stance: str, limit: int
    ) -> Sequence[str]:
        """Ask what one stance needs to know."""
        data = await self._ask(
            "research_questions",
            {"research_goal": goal, "stance": stance, "limit": limit},
            DEFAULT_MAX_TOKENS,
        )
        return _strings(data.get("questions"))[:limit]

    async def to_query(self, *, question: str) -> str:
        """Render a question as a source-shaped query."""
        data = await self._ask(
            "research_query", {"question": question}, DEFAULT_MAX_TOKENS
        )
        query = data.get("query")
        # A model that returns nothing usable has not refused the
        # question, so the question's own text is the honest fallback --
        # a worse query than it could have written, not a dropped thread.
        return query.strip() if isinstance(query, str) and query else question

    async def extract(
        self, *, question: str, documents: Sequence[Document]
    ) -> Extraction:
        """Read the admitted documents for one question."""
        if not documents:
            return Extraction()
        data = await self._ask(
            "research_extract",
            {
                "question": question,
                "documents": _numbered(documents),
            },
            EXTENDED_MAX_TOKENS,
        )
        return Extraction(
            findings=_findings(data.get("findings"), documents),
            follow_ups=tuple(_strings(data.get("follow_ups"))),
        )

    async def compress(
        self, *, question: str, findings: Sequence[Finding]
    ) -> str:
        """Reduce one answered question to an account worth carrying."""
        if not findings:
            return ""
        data = await self._ask(
            "research_compress",
            {
                "question": question,
                "findings": "\n".join(
                    f"- {finding.text} ({finding.locator})"
                    for finding in findings
                ),
            },
            DEFAULT_MAX_TOKENS,
        )
        summary = data.get("summary")
        return summary.strip() if isinstance(summary, str) else ""

    async def _ask(
        self,
        prompt_name: str,
        variables: dict[str, object],
        max_tokens: int,
    ) -> dict[str, object]:
        """Render one prompt with its schema and call the model."""
        prompt, schema = load_prompt_with_schema(prompt_name, variables)
        result = await call_llm_json(
            prompt,
            CompletionSpec(
                model_name=self._model,
                max_tokens=max_tokens,
                temperature=self._temperature,
                json_schema=schema,
            ),
            options=LLMCallOptions(
                use_cache=self._use_cache,
                run_id=self._run_id,
                prompt_name=prompt_name,
            ),
        )
        return result


def _numbered(documents: Sequence[Document]) -> str:
    """Render the documents the way the extraction schema indexes them.

    Strips each document's own inline citation markers from this prompt
    copy (``document.text`` itself is untouched) -- left in, the
    extraction model can copy one into a reported finding as if it were
    its own.
    """
    blocks = []
    for index, document in enumerate(documents):
        kind = "full text" if document.full_text else "abstract only"
        text = strip_citation_markers(
            truncate_for_prompt(document.text, _DOCUMENT_MAX_CHARS)
        )
        blocks.append(f"[{index}] {document.hit.title} ({kind})\n{text}")
    return "\n\n".join(blocks)


def _findings(
    raw: object, documents: Sequence[Document]
) -> tuple[ExtractedFinding, ...]:
    """Bind each reported finding back to the document it was drawn from.

    A finding whose index names no document is dropped rather than
    attributed to a neighbour: the whole value of a finding is which
    source it came from, and a plausible wrong locator is worse than one
    fewer finding.
    """
    if not isinstance(raw, list):
        return ()
    bound = (_one_finding(item, documents) for item in raw)
    return tuple(finding for finding in bound if finding is not None)


def _one_finding(
    item: object, documents: Sequence[Document]
) -> ExtractedFinding | None:
    """Validate one reported finding, or refuse it."""
    if not isinstance(item, dict):
        return None
    index, claim, quote = (
        item.get("document"),
        item.get("claim"),
        item.get("quote"),
    )
    if not isinstance(index, int) or not 0 <= index < len(documents):
        return None
    if not isinstance(claim, str) or not isinstance(quote, str):
        return None
    if not claim.strip() or not quote.strip():
        return None
    return ExtractedFinding(
        text=claim.strip(),
        locator=documents[index].hit.locator,
        span=quote.strip(),
    )


def _strings(raw: object) -> list[str]:
    """Take the non-empty strings out of a model's list, in order."""
    if not isinstance(raw, list):
        return []
    return [
        item.strip() for item in raw if isinstance(item, str) and item.strip()
    ]


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

    @classmethod
    async def open_for(cls, config: SearchConfig, run_id: str) -> McpRetrieval:
        """Open retrieval after the caller has checked its research gates.

        Args:
            config: Resolved search configuration with a registry/workflow.
            run_id: The run whose retrieval provenance is recorded.

        Returns:
            Retrieval over the run's enabled MCP sources.

        Raises:
            ValueError: The configuration has no registry or workflow.
        """
        from co_scientist.mcp_client import get_mcp_client

        if config.tool_registry is None or config.workflow is None:
            raise ValueError("Research requires a tool registry and workflow")
        client = await get_mcp_client(tool_registry=config.tool_registry)
        return cls(
            client,
            config.tool_registry,
            config.workflow,
            ResearchRun(run_id=run_id, research_goal=config.research_goal),
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


# Tier -> (depth, breadth, hits per question). Absent means no research.
_TIER_CEILINGS: dict[str, tuple[int, int, int]] = {
    "extended": (2, 4, 4),
    "ultra": (3, 6, 5),
}

# Threads in flight at once. Bounded well below the thread count because
# each thread is a fan of searches plus a read plus two model calls, and
# the sources throttle a burst long before this engine runs out of loop.
_CONCURRENCY = 3


def budget_for_tier(tier: str, sources: Sequence[str]) -> ResearchBudget | None:
    """Resolve one run tier's research ceilings.

    Args:
        tier: Normalized run tier (``express``, ``standard``,
            ``extended``, ``ultra``).
        sources: Search sources the run has enabled, in preference
            order, as the retrieval port names them.

    Returns:
        The budget for this tier, or None when the tier does not buy
        research -- which a caller reads as "skip it", not as an error.
        A tier that would research but has no source enabled also gets
        None, since a budget with no source is not constructible and an
        empty registry is a configuration state, not a failure.
    """
    ceilings = _TIER_CEILINGS.get(tier)
    if ceilings is None or not sources:
        return None
    depth, breadth, hits = ceilings
    return ResearchBudget(
        depth=depth,
        breadth=breadth,
        concurrency=_CONCURRENCY,
        hits_per_question=hits,
        sources=tuple(sources),
    )


def tier_researches(tier: str) -> bool:
    """Whether this tier buys any research at all.

    The one authority on the question, so a caller deciding whether to
    warn about missing tools does not grow a second copy of the tier
    list beside this one.

    Args:
        tier: Normalized run tier.

    Returns:
        True when the tier has ceilings here.
    """
    return tier in _TIER_CEILINGS


# Tier -> (depth, breadth, hits) for ONE reviewed hypothesis. Deliberately
# below the run-level table: this is asked per hypothesis, so a level here
# costs as much as the whole literature-review phase does over the run.
_REVIEW_CEILINGS: dict[str, tuple[int, int, int]] = {
    "extended": (2, 2, 3),
    "ultra": (2, 3, 4),
}

# How many of a run's hypotheses a tier researches during review, best
# ranked first. The other factor in the product: at most this many times
# the budget's own thread ceiling -- 5 x 4 = 20 threads on extended,
# 8 x 5 = 40 on ultra. The breadth floor is why a level never halves to
# one: 2 + 2 and 3 + 2.
#
# **That ceiling is per cycle, not per run**, and the difference was
# measured rather than reasoned: one live extended run bought 9 review
# gatherings and 20 threads against the 12 this table was being quoted
# as bounding. Comprehensive reflection runs once per cycle, and each
# cycle has a fresh top-N -- evolution rewrites hypotheses, and a
# rewritten one needs its full review again. So a run's real ceiling is
# this product times `max_iterations`, and a quote that omits the
# iteration factor understates by exactly that. Two independently
# reasonable caps whose product is larger than either suggests is the
# shape of this repo's 299-call incident; the fix here is an honest
# quote, since the spend itself is bounded and small.
#
# Raised from 3/5 on 2026-08-21, from the same run's numbers. It
# produced 28 hypotheses and funded 9 distinct ones across three cycles
# -- under a third of the pool, and the rest carried the single
# retrieval round their reviews do on their own, which is the gap
# `REFLECT-TYPES-001` recorded. At 5 and 8 that run funds roughly half.
# The measured price of one gathering there was ~2.2 threads, so the
# increase buys about 13 more threads over a three-cycle extended run:
# a few cents against a $1.60 bill. The caveat is not the threads. Every
# funded hypothesis adds papers to the shared evidence the full and
# simulation reviews both read, and `comprehensive_reflection` is
# already 76% of a run's input tokens because its tool loop re-sends its
# transcript each turn -- so this multiplies the phase that most needs
# the resend fixed. Reverting is one edit to these two numbers.
_REVIEW_HYPOTHESES: dict[str, int] = {
    "extended": 5,
    "ultra": 8,
}


def review_budget_for_tier(
    tier: str, sources: Sequence[str]
) -> ResearchBudget | None:
    """Resolve what one reviewed hypothesis may spend on research.

    Args:
        tier: Normalized run tier.
        sources: Search sources the run has enabled, in preference order.

    Returns:
        The per-hypothesis budget, or None when this tier does not
        research reviews or the run has no source to search.
    """
    ceilings = _REVIEW_CEILINGS.get(tier)
    if ceilings is None or not sources:
        return None
    depth, breadth, hits = ceilings
    return ResearchBudget(
        depth=depth,
        breadth=breadth,
        concurrency=_CONCURRENCY,
        hits_per_question=hits,
        sources=tuple(sources),
    )


def reviewed_hypothesis_limit(tier: str) -> int:
    """How many hypotheses this tier researches during review.

    Args:
        tier: Normalized run tier.

    Returns:
        The cap, or 0 when the tier does not research reviews at all --
        which a caller reads as "research nothing here".
    """
    return _REVIEW_HYPOTHESES.get(tier, 0)


__all__ = [
    "LlmResearchModel",
    "McpRetrieval",
    "budget_for_tier",
    "tier_researches",
]
