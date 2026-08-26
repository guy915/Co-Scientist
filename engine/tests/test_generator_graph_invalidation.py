"""The compiled graph must follow the configuration, not the first call.

``_ensure_graph_built`` compiled the workflow once and then never looked
again, so a generator reused across two calls executed the *first* call's
topology for both. The two directions fail differently and both are silent:
a run that turns the literature-review node off still runs it (and reaches
MCP), while a run that turns it on gets the simplified supervisor -> generate
flow and no literature grounding at all -- with the state saying otherwise
either way.

The MCP-availability probe is cached alongside the graph for the same reason
and has to be invalidated with it: the topology is derived from that answer,
so a graph rebuilt against a stale probe is the same defect one layer down.
"""

from typing import Any

import pytest

from co_scientist.generator import HypothesisGenerator
from tests._mcp import stub_mcp_availability


def _nodes(generator: HypothesisGenerator) -> set[str]:
    """Return the node names of the generator's currently compiled graph."""
    assert generator._graph is not None
    return set(generator._graph.nodes)


async def test_disabling_literature_review_rebuilds_the_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Turning the node off must drop it, not reuse the first topology."""
    stub_mcp_availability(monkeypatch, available=True)
    generator = HypothesisGenerator()

    await generator._prepare_generation("goal one")
    assert "literature_review" in _nodes(generator)

    await generator._prepare_generation(
        "goal two", opts={"enable_literature_review_node": False}
    )
    assert "literature_review" not in _nodes(generator)
    assert "reflection" not in _nodes(generator)


async def test_enabling_literature_review_rebuilds_the_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Turning the node on must add it back to the executed graph."""
    stub_mcp_availability(monkeypatch, available=True)
    generator = HypothesisGenerator()

    await generator._prepare_generation(
        "goal one", opts={"enable_literature_review_node": False}
    )
    assert "literature_review" not in _nodes(generator)

    await generator._prepare_generation("goal two")
    assert "literature_review" in _nodes(generator)


async def test_unchanged_configuration_keeps_the_compiled_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compilation is not free, so an unchanged setting must not recompile."""
    stub_mcp_availability(monkeypatch, available=True)
    generator = HypothesisGenerator()

    await generator._prepare_generation("goal one")
    first = generator._graph
    await generator._prepare_generation("goal two")
    assert generator._graph is first


async def test_availability_is_probed_once_per_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The probe is cached, but a registry change invalidates that cache.

    The cached answer decides the graph shape, so it may not outlive the
    tool configuration it was measured against.
    """
    probes: list[Any] = []

    async def _probe(**kwargs: Any) -> bool:
        probes.append(kwargs.get("tool_registry"))
        return True

    from co_scientist import mcp_client

    monkeypatch.setattr(mcp_client, "check_mcp_available", _probe)
    monkeypatch.setattr(mcp_client, "check_literature_source_available", _probe)

    generator = HypothesisGenerator()
    await generator._prepare_generation("goal one")
    await generator._prepare_generation("goal two")
    assert len(probes) == 2, "one concurrent probe pair, cached afterward"

    generator.reload_tool_registry(tools_config=None, disable_tools=["pubmed"])
    await generator._prepare_generation("goal three")
    assert len(probes) == 4, "a registry change must re-probe"


async def test_reloading_the_registry_invalidates_the_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reloaded registry reaches the state every node reads it from."""
    stub_mcp_availability(monkeypatch, available=True)
    generator = HypothesisGenerator()
    state = await generator._prepare_generation("goal one")
    first_registry = state["tool_registry"]

    generator.reload_tool_registry(tools_config=None, disable_tools=["pubmed"])
    state = await generator._prepare_generation("goal two")

    reloaded = generator._tool_registry
    assert reloaded is not None
    # Read the reloaded registry before the identity checks below: comparing
    # it with `is` against an untyped state value re-widens it to optional
    # under mypy 2.x, and the read then reads as a possible None.
    assert "pubmed" not in reloaded.get_enabled_tools()
    assert state["tool_registry"] is not first_registry
    assert state["tool_registry"] is reloaded
