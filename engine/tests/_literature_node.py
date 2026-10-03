"""Shared harness for the literature review node's orchestration tests.

External seams stubbed (each bound on the submodule that consumes it):

* ``node.get_node_cache`` -> a no-op cache (always miss / no-op set), so the
  global on-disk node cache never interferes and tests stay deterministic.
* ``node.check_mcp_available`` -> bool, the server-reachability gate the node
  consults before doing any work; ``False`` drives the unavailable fallback,
  ``True`` the happy path (without it the node would dial ``localhost:8888``).
* ``node.get_mcp_client`` -> a fake whose ``call_tool`` returns canned search
  papers, standing in for the real MCP search/tool path.
* ``call_llm_json`` -> shared by query-generation (``queries``, returns
  ``queries``) and per-paper analysis (``analysis``, the dict is stored opaquely
  and fed to synthesis), so it is stubbed on both submodules.
* ``synthesis.call_llm`` -> phase-4 synthesis text (prompt saving lives inside
  the real LLM wrappers now, so stubbing them also keeps prompt files off disk).
* ``node.run_research_phase`` -> one canned Phase 6 finding, paper and ledger.

With ``tool_registry=None`` the multi-source/PDF-discovery/content-fetch/
context-enrichment phases (2.4/2.5/2.6) all early-return, so the node runs in
its real single-source, LLM-only orchestration.
"""

from collections.abc import Awaitable, Callable
from typing import Any

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
