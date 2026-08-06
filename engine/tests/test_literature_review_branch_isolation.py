"""Concurrent literature-review phases must fail independently.

Phases 2.4/2.5 (paper retrieval) and Phase 2.6 (context enrichment) run
under one ``asyncio.gather`` because they share no data. Without
isolation, the first of the two to raise cancels the other mid-call, so a
knowledge-graph outage discards every paper the retrieval branch had
already fetched -- and vice versa -- and fails the whole literature-review
node task.
"""

from typing import Any

import pytest

from co_scientist.agents.generation.literature_review import (
    orchestration as lr_orchestration,
)
from tests._mcp import make_tool_results_client
from tests._search_fixtures import make_search_config
from tests._state import make_state


async def _boom(*_: Any, **__: Any) -> Any:
    """Stand in for a phase whose external dependency went down."""
    raise RuntimeError("external dependency refused the call")


async def _enrichment_ok(*_: Any, **__: Any) -> tuple[str, list[Any]]:
    """Stand in for a context-enrichment phase that succeeded."""
    return "KRAS activates MAPK", [{"id": "kg:1"}]


async def _fetch_content_and_enrichment() -> tuple[str, list[Any]]:
    """Drive the phase pair with the module's own fixtures."""
    return await lr_orchestration._fetch_content_and_enrichment(
        {},
        {},
        make_search_config(),
        make_tool_results_client(),
        make_state(research_goal="Study of KRAS in cancer"),
    )


async def test_failed_retrieval_keeps_the_enrichment_it_ran_beside(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retrieval fault does not discard the enrichment branch's result."""
    monkeypatch.setattr(lr_orchestration, "_discover_then_fetch_content", _boom)
    monkeypatch.setattr(
        lr_orchestration, "_phase2_6_fetch_context_enrichment", _enrichment_ok
    )

    context, sources = await _fetch_content_and_enrichment()

    assert context == "KRAS activates MAPK"
    assert sources == [{"id": "kg:1"}]


async def test_failed_enrichment_degrades_to_empty_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An enrichment fault leaves the node with the empty context it handles."""
    retrieved: list[str] = []

    async def _retrieval_ok(*_: Any, **__: Any) -> None:
        retrieved.append("papers")

    monkeypatch.setattr(
        lr_orchestration, "_discover_then_fetch_content", _retrieval_ok
    )
    monkeypatch.setattr(
        lr_orchestration, "_phase2_6_fetch_context_enrichment", _boom
    )

    context, sources = await _fetch_content_and_enrichment()

    assert retrieved == ["papers"]
    assert (context, sources) == ("", [])
