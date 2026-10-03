"""Shared test fixtures for research fakes."""

from __future__ import annotations

import dataclasses
import textwrap
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any, cast

import pytest

from co_scientist.agents.generation.literature_review import node as lr
from co_scientist.agents.generation.literature_review import (
    queries as lr_queries,
)
from co_scientist.agents.generation.literature_review import (
    synthesis as lr_analysis,
)
from co_scientist.agents.generation.literature_review import (
    synthesis as lr_synthesis,
)
from co_scientist.agents.generation.literature_review.research_phase import (
    ResearchOutcome,
)
from co_scientist.config import SearchSourceConfig, WorkflowConfig
from co_scientist.config.registry import ToolRegistry
from co_scientist.config.schema import ToolConfig
from co_scientist.evidence import search
from co_scientist.evidence.search_support import SearchConfig
from co_scientist.mcp_client import MCPToolClient
from co_scientist.research import (
    Document,
    ExtractedFinding,
    Extraction,
    Finding,
    ResearchBudget,
    SourceHit,
)


class FakeRetrieval:
    """A search service that answers from a script.

    Attributes:
        hits_by_source: What each source returns for any query.
        failing_sources: Sources that raise instead of answering.
        unreadable: Locators whose text cannot be fetched.
        queries: Every query issued, in order.
    """

    def __init__(
        self,
        hits_by_source: dict[str, list[SourceHit]] | None = None,
        failing_sources: set[str] | None = None,
        unreadable: set[str] | None = None,
    ) -> None:
        """Configure the scripted answers."""
        self.hits_by_source = hits_by_source or {}
        self.failing_sources = failing_sources or set()
        self.unreadable = unreadable or set()
        self.queries: list[str] = []

    async def search(
        self, *, query: str, source: str, limit: int
    ) -> Sequence[SourceHit]:
        """Return this source's scripted hits, or raise."""
        self.queries.append(query)
        if source in self.failing_sources:
            raise RuntimeError(f"{source} is unreachable")
        return self.hits_by_source.get(source, [])[:limit]

    async def read(self, *, locator: str) -> str | None:
        """Return document text unless the locator is unreadable."""
        if locator in self.unreadable:
            return None
        return f"full text of {locator}"


class FakeModel:
    """A model that answers from a script.

    Attributes:
        stances: What stance planning returns.
        follow_ups_by_question: Follow-ups each question raises.
        barren: Questions that yield no findings.
        exploding: Questions whose extraction raises.
        extracted: Every question extraction ran for, in order.
    """

    def __init__(
        self,
        stances: Sequence[str] = ("mechanism", "prior art"),
        follow_ups_by_question: dict[str, list[str]] | None = None,
        barren: set[str] | None = None,
        exploding: set[str] | None = None,
    ) -> None:
        """Configure the scripted answers."""
        self.stances = tuple(stances)
        self.follow_ups_by_question = follow_ups_by_question or {}
        self.barren = barren or set()
        self.exploding = exploding or set()
        self.extracted: list[str] = []
        self.documents_seen: list[Document] = []

    async def plan_stances(self, *, goal: str, limit: int) -> Sequence[str]:
        """Return the scripted stances, within the limit."""
        return self.stances[:limit]

    async def ask_questions(
        self, *, goal: str, stance: str, limit: int
    ) -> Sequence[str]:
        """Ask one question per stance, named after the stance."""
        return [f"what does {stance} say about {goal}?"][:limit]

    async def to_query(self, *, question: str) -> str:
        """Render the question as a query."""
        return f"query::{question}"

    async def extract(
        self, *, question: str, documents: Sequence[Document]
    ) -> Extraction:
        """Return one finding per document, unless scripted otherwise."""
        self.extracted.append(question)
        self.documents_seen.extend(documents)
        if question in self.exploding:
            raise RuntimeError("extraction failed")
        follow_ups = tuple(self.follow_ups_by_question.get(question, []))
        if question in self.barren:
            return Extraction(findings=(), follow_ups=follow_ups)
        findings = tuple(
            ExtractedFinding(
                text=f"finding from {doc.hit.locator}",
                locator=doc.hit.locator,
                span=f"span from {doc.hit.locator}",
            )
            for doc in documents
        )
        return Extraction(findings=findings, follow_ups=follow_ups)

    async def compress(
        self, *, question: str, findings: Sequence[Finding]
    ) -> str:
        """Summarise a thread by counting what it found."""
        return f"{len(findings)} findings for {question}"


def _hits(*locators: str) -> list[SourceHit]:
    """Build ranked hits for the given locators."""
    return [
        SourceHit(
            locator=locator,
            title=f"title {locator}",
            snippet=f"snippet {locator}",
            rank=index,
        )
        for index, locator in enumerate(locators)
    ]


def _budget(**overrides: object) -> ResearchBudget:
    """A small default budget, overridable per test."""
    defaults: dict[str, object] = {
        "depth": 2,
        "breadth": 2,
        "concurrency": 2,
        "hits_per_question": 2,
        "sources": ("pubmed",),
    }
    defaults.update(overrides)
    return ResearchBudget(**defaults)  # type: ignore[arg-type]


class _NoOpNodeCache:
    """A node cache that never hits and never writes.

    Substituted for the global on-disk ``NodeCache`` so orchestration tests
    neither read stale results nor leave pickles behind.
    """

    def get(self, *_: Any, **__: Any) -> None:
        """Always miss."""
        return None

    def set(self, *_: Any, **__: Any) -> None:
        """No-op store."""
        return None


class _FakeMCPClient:
    """Minimal stand-in for ``MCPToolClient`` used by the node.

    ``call_tool`` returns a fixed payload regardless of tool name/args; the node
    only uses it for searching here (query generation falls back to the stubbed
    LLM, and the no-registry path disables every other tool phase).
    """

    def __init__(self, search_payload: dict[str, dict[str, Any]]) -> None:
        """Store the dict that every ``call_tool`` invocation returns.

        Args:
            search_payload: The ``{paper_id: metadata}`` dict returned for any
                tool call (passed through unchanged by ``normalize_search_
                response`` when there is no tool config).
        """
        self._search_payload = search_payload
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """Record the call and return the canned search payload."""
        self.calls.append((tool_name, kwargs))
        return self._search_payload

    def has_tool(self, _tool_name: str) -> bool:
        """No enrichment tools are exposed by the fake client."""
        return False


def _stub_llms(
    monkeypatch: pytest.MonkeyPatch,
    queries: list[str] | None,
    synthesis: str,
) -> None:
    """Stub the query-generation, per-paper analysis, and synthesis LLMs."""

    async def fake_llm_json(**_: Any) -> dict[str, Any]:
        # Shared by query-generation (reads "queries") and paper analysis
        # (stores the whole dict opaquely for synthesis).
        return {"queries": queries if queries is not None else ["query one"]}

    monkeypatch.setattr(lr_queries, "call_llm_json", fake_llm_json)
    monkeypatch.setattr(lr_analysis, "call_llm_json", fake_llm_json)

    async def fake_llm(**_: Any) -> str:
        return synthesis

    monkeypatch.setattr(lr_synthesis, "call_llm", fake_llm)


def _stub_node(
    monkeypatch: pytest.MonkeyPatch,
    *,
    server_available: bool,
    search_payload: dict[str, dict[str, Any]] | None = None,
    queries: list[str] | None = None,
    synthesis: str = "SYNTHESIZED REVIEW",
) -> _FakeMCPClient:
    """Patch every external seam of ``literature_review_node``.

    ``server_available`` drives ``check_mcp_available`` (the reachable-server
    precondition, not any one source's health); ``search_payload`` is the
    ``{paper_id: metadata}`` the fake MCP client returns from ``call_tool``;
    ``queries`` and ``synthesis`` feed the stubbed query and synthesis LLMs.
    Returns the wired-in ``_FakeMCPClient`` so the test can inspect ``.calls``.
    """
    fake_client = _FakeMCPClient(search_payload or {})

    monkeypatch.setattr(lr, "get_node_cache", lambda: _NoOpNodeCache())

    async def fake_available(**_: Any) -> bool:
        return server_available

    monkeypatch.setattr(lr, "check_mcp_available", fake_available)

    async def fake_get_client(**_: Any) -> _FakeMCPClient:
        return fake_client

    monkeypatch.setattr(lr, "get_mcp_client", fake_get_client)
    _stub_llms(monkeypatch, queries, synthesis)

    return fake_client


def _stub_research(
    monkeypatch: pytest.MonkeyPatch, section: str = "\n\n## Research\nfound"
) -> None:
    """Make phase 6 return one finding, one paper and a ledger."""

    async def fake_phase(*_: Any, **__: Any) -> ResearchOutcome:
        return ResearchOutcome(
            ledger={"threads": [], "calls": [], "findings": []},
            records={
                "PMID7": {
                    "title": "Researched paper",
                    "abstract": "Abstract seven.",
                    "retrieval_call_id": "call-7",
                    "_source_name": "alpha",
                }
            },
            section=section,
        )

    monkeypatch.setattr(lr, "run_research_phase", fake_phase)


def _make_event_recorder() -> tuple[
    list[tuple[str, dict[str, Any]]],
    Callable[[str, dict[str, Any]], Awaitable[None]],
]:
    """Build a progress callback that records (event, payload) tuples.

    Returns:
        A tuple of the (initially empty) recorded-events list and the async
        callback that appends to it; pass the callback as ``progress_callback``
        and inspect the list afterwards.
    """
    events: list[tuple[str, dict[str, Any]]] = []

    async def callback(event: str, payload: dict[str, Any]) -> None:
        events.append((event, payload))

    return events, callback


_TWO_PAPERS: dict[str, dict[str, Any]] = {
    "PMID1": {
        "title": "Tumor microenvironment review",
        "authors": ["Smith J"],
        "year": "2021",
        "fulltext": "Full body one.",
        "abstract": "Abstract one.",
    },
    "PMID2": {
        "title": "Immune checkpoint blockade",
        "authors": ["Doe A"],
        "year": "2022",
        "fulltext": "Full body two.",
        "abstract": "Abstract two.",
    },
}


class _RaisingClient:
    """An MCP client whose every search call raises a transport error."""

    async def call_tool(self, _tool_name: str, **_: Any) -> Any:
        raise ConnectionError("All connection attempts failed")

    def has_tool(self, _tool_name: str) -> bool:
        return False


# A self-contained config that fully replaces the bundled default
# (``settings.merge_strategy: replace``), so the resulting registry contains
# only the tools/servers/workflows defined here. Values are literal (no ${...}
# placeholders) so env-var substitution is a no-op and the tests are
# deterministic regardless of the environment.
REPLACE_CONFIG = textwrap.dedent("""
    version: "2.0"
    servers:
      myserver:
        url: "http://example.test/mcp"
        transport: "streamable_http"
        enabled: true
      offserver:
        url: "http://off.test/mcp"
        enabled: false
    tools:
      search_tools:
        alpha_search:
          server: "myserver"
          mcp_tool_name: "search_alpha"
          display_name: "Alpha Search"
          category: "search"
          enabled: true
        beta_search:
          server: "myserver"
          mcp_tool_name: "search_beta"
          enabled: false
      utility_tools:
        gamma_util:
          server: "myserver"
          mcp_tool_name: "util_gamma"
          enabled: true
    workflows:
      literature_review:
        primary_search: "alpha_search"
        fallback_search: "beta_search"
        availability_check: "gamma_util"
      draft_generation:
        search_tools:
          - "alpha_search"
          - "beta_search"
    enrichments:
      - tool: "gamma_util"
        output_key: "gamma_out"
        enabled: true
        workflow: "generation"
      - tool: "alpha_search"
        output_key: "alpha_out"
        enabled: true
        workflow: "reflection"
      - tool: "beta_search"
        output_key: "beta_out"
        enabled: false
        workflow: "generation"
    prompts:
      domain_context: "test domain context"
      generation_guidance: "test generation guidance"
    settings:
      merge_strategy: "replace"
    """)


def write_config(tmp_path: Path, body: str) -> str:
    """Write ``body`` to a YAML file under ``tmp_path`` and return its path."""
    path = tmp_path / "tools.yaml"
    path.write_text(body, encoding="utf-8")
    return str(path)


RESEARCH_TOOLS_CONFIG = """
version: "2.0"
settings:
  merge_strategy: replace
servers:
  s:
    url: "http://example.test/mcp"
    transport: "streamable_http"
    enabled: true
tools:
  search_tools:
    alpha:
      server: "s"
      mcp_tool_name: "search_alpha"
      category: "search"
      enabled: true
    beta:
      server: "s"
      mcp_tool_name: "search_beta"
      category: "search"
      enabled: true
  utility_tools:
    reader:
      server: "s"
      mcp_tool_name: "read_pdf"
      enabled: true
workflows:
  literature_review:
    search_sources:
      - tool: "alpha"
        papers_per_query: 2
        enabled: true
        content_tool: "reader"
        content_url_field: "pdf_url"
      - tool: "beta"
        enabled: false
"""


class FakeResearchClient:
    """Records tool calls and answers them from a scripted table.

    A scripted value that is an ``Exception`` is raised instead of
    returned, so a source that fails and a source that comes back empty
    can both be driven.
    """

    def __init__(self, responses: dict[str, Any]) -> None:
        """Hold the per-tool answers this client will give."""
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """Answer one tool call, recording what it was asked."""
        self.calls.append((tool_name, kwargs))
        answer = self.responses.get(tool_name)
        if isinstance(answer, Exception):
            raise answer
        return answer


def research_registry(tmp_path: Path) -> ToolRegistry:
    """Build a registry holding only the tools declared above."""
    path = tmp_path / "tools.yaml"
    path.write_text(RESEARCH_TOOLS_CONFIG)
    return ToolRegistry(config_path=str(path), skip_user_config=True)


def research_workflow(registry: ToolRegistry) -> WorkflowConfig:
    """Take the literature-review workflow off a research registry."""
    workflow = registry.get_workflow("literature_review")
    assert workflow is not None
    return workflow


_PAPERS = {
    "doc-a": {
        "title": "Blockade in humans",
        "abstract": "TGF-beta blockade reduced fibrosis in a human cohort.",
        "pdf_url": "u/a",
    },
    "doc-b": {"title": "Merely listed", "abstract": "Unrelated."},
}


class _ScriptedModel:
    """Answers each of the five research prompts by what it was asked."""

    def __init__(self) -> None:
        """Start with nothing asked."""
        self.prompts: list[str] = []

    async def __call__(
        self, prompt: str, spec: Any, *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        """Answer one prompt, recording it."""
        self.prompts.append(prompt)
        if "perspectives to research" in prompt:
            return {"stances": ["mechanism"]}
        if "questions this perspective needs" in prompt:
            return {"questions": ["is the mechanism shown in humans?"]}
        if "search query" in prompt:
            return {"query": "TGF-beta blockade human"}
        if "retrieved documents" in prompt:
            return {
                "findings": [
                    {
                        "document": 0,
                        "claim": "Blockade reduced fibrosis in humans",
                        "quote": (
                            "TGF-beta blockade reduced fibrosis in a"
                            " human cohort."
                        ),
                    }
                ],
                "follow_ups": [],
            }
        return {"summary": "Human evidence exists but is thin."}


def make_tool_config(
    mcp_tool_name: str = "search_x", **overrides: Any
) -> ToolConfig:
    """Build a minimal ToolConfig with the given MCP-facing tool name.

    Args:
        mcp_tool_name: The tool's MCP-facing name, the field nearly every
            call site varies.
        **overrides: Any other ToolConfig fields to set (e.g. ``enabled``,
            ``source_type``, ``response_format``).

    Returns:
        A ToolConfig on the placeholder ``"s"`` server.
    """
    return ToolConfig(server="s", mcp_tool_name=mcp_tool_name, **overrides)


_DEFAULT_SEARCH_CONFIG = SearchConfig(
    tool_registry=None,
    workflow=None,
    is_multi_source=False,
    search_tool_name="search_tool",
    search_tool_config=None,
    source_name="unknown",
    papers_to_read_count=5,
    is_dev_mode=False,
)


def make_search_config(**overrides: Any) -> SearchConfig:
    """Build a SearchConfig with inert defaults, overriding given fields.

    Args:
        **overrides: Any SearchConfig fields to set (e.g. ``workflow``,
            ``tool_registry``, ``is_multi_source``).

    Returns:
        A SearchConfig with every unspecified field left inert.
    """
    return dataclasses.replace(_DEFAULT_SEARCH_CONFIG, **overrides)


def make_search_run_ctx(
    client: Any, errors: list[str], run_id: str = "run1"
) -> search._SearchRunContext:
    """A run context over the shared ``"slug"`` slug for search calls.

    Args:
        client: The duck-typed MCP client the searches call through.
        errors: The list the search path appends swallowed errors to.
        run_id: The run id stamped on progress events.

    Returns:
        A ``_SearchRunContext`` wrapping the given client and error sink.
    """
    return search._SearchRunContext(
        slug="slug",
        run_id=run_id,
        mcp_client=cast(MCPToolClient, client),
        errors=errors,
    )


def make_two_source_workflow(papers_per_query: int) -> WorkflowConfig:
    """A cross-source-deduped workflow with src_a and src_b sources.

    Args:
        papers_per_query: The per-query budget both sources carry.

    Returns:
        A WorkflowConfig over two equally-budgeted search sources.
    """
    return WorkflowConfig(
        search_sources=[
            SearchSourceConfig(tool="src_a", papers_per_query=papers_per_query),
            SearchSourceConfig(tool="src_b", papers_per_query=papers_per_query),
        ],
        deduplicate_across_sources=True,
    )
