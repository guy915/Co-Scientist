"""Tests for the generation coordinator's post-generation enrichment step.

``_enrich_hypotheses`` fans out configured MCP tool calls per hypothesis via
``_run_one_enrichment``/``_enrich_one_hypothesis``. Enrichment is
supplementary -- failures land on the hypothesis rather than raising -- so
these tests cover the success, missing-tool, and tool-failure branches
directly, plus the coordinator-level wiring (registry/config resolution,
mcp client construction, per-config fan-out).
"""

import asyncio
from typing import Any

import pytest

from co_scientist.agents.generation import coordinator_enrichment
from co_scientist.agents.generation.coordinator_enrichment import (
    _enrich_hypotheses,
    _enrich_one_hypothesis,
    _ResolvedEnrichment,
    _run_one_enrichment,
)
from co_scientist.config.schema import EnrichmentConfig, ToolConfig
from tests._mcp import FakeCallToolClient
from tests._state import make_hypothesis, make_state

# -----------------------------------------------------------------------------
# _enrich_one_hypothesis
# -----------------------------------------------------------------------------


async def test_enrich_one_hypothesis_unwraps_results_path() -> None:
    """A configured results_path unwraps a nested list from a dict result."""
    hyp = make_hypothesis(text="h1", explanation="the explanation")
    enrichment = EnrichmentConfig(
        tool="cve_lookup",
        input_field="explanation",
        max_results=5,
        results_path="results",
    )
    tool_config = ToolConfig(server="s", mcp_tool_name="nvd_search")
    mcp_client = FakeCallToolClient({"results": [{"id": "CVE-1"}], "total": 1})

    await _enrich_one_hypothesis(
        hyp,
        _ResolvedEnrichment(enrichment, tool_config, "cves"),
        mcp_client,
        asyncio.Semaphore(2),
    )

    assert hyp.enrichments["cves"] == [{"id": "CVE-1"}]
    assert mcp_client.calls == [
        ("nvd_search", {"topic": "the explanation", "max_results": 5})
    ]


async def test_enrich_one_hypothesis_without_results_path_uses_raw_parsed() -> (
    None
):
    """No results_path stores the parsed response as-is."""
    hyp = make_hypothesis(text="h1")
    enrichment = EnrichmentConfig(tool="cve_lookup", max_results=3)
    tool_config = ToolConfig(server="s", mcp_tool_name="nvd_search")
    mcp_client = FakeCallToolClient({"raw": "payload"})

    await _enrich_one_hypothesis(
        hyp,
        _ResolvedEnrichment(enrichment, tool_config, "cves"),
        mcp_client,
        asyncio.Semaphore(2),
    )

    assert hyp.enrichments["cves"] == {"raw": "payload"}


async def test_enrich_one_hypothesis_defaults_input_to_text() -> None:
    """input_field falling back to 'text' queries with hyp.text."""
    hyp = make_hypothesis(text="fallback text")
    enrichment = EnrichmentConfig(tool="cve_lookup")
    tool_config = ToolConfig(server="s", mcp_tool_name="nvd_search")
    mcp_client = FakeCallToolClient({})

    await _enrich_one_hypothesis(
        hyp,
        _ResolvedEnrichment(enrichment, tool_config, "cves"),
        mcp_client,
        asyncio.Semaphore(1),
    )

    _, kwargs = mcp_client.calls[0]
    assert kwargs["topic"] == "fallback text"


async def test_enrich_one_hypothesis_records_error_on_failure() -> None:
    """A failing tool call stores an error payload instead of raising."""
    hyp = make_hypothesis(text="h1")
    enrichment = EnrichmentConfig(tool="cve_lookup")
    tool_config = ToolConfig(server="s", mcp_tool_name="nvd_search")
    mcp_client = FakeCallToolClient(error=RuntimeError("mcp down"))

    await _enrich_one_hypothesis(
        hyp,
        _ResolvedEnrichment(enrichment, tool_config, "cves"),
        mcp_client,
        asyncio.Semaphore(1),
    )

    assert hyp.enrichments["cves"] == {"error": "mcp down"}


# -----------------------------------------------------------------------------
# _run_one_enrichment
# -----------------------------------------------------------------------------


class _ToolLookupRegistry:
    """Minimal registry stand-in exposing only get_tool."""

    def __init__(self, tool: ToolConfig | None) -> None:
        self._tool = tool

    def get_tool(self, _tool_id: str) -> ToolConfig | None:
        """Return the configured tool, or None to model a missing one."""
        return self._tool


async def test_run_one_enrichment_missing_tool_is_noop(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An enrichment whose tool is unresolvable in the registry is skipped."""
    caplog.set_level("WARNING")
    hyps = [make_hypothesis(text="h1")]

    await _run_one_enrichment(
        EnrichmentConfig(tool="missing_tool"),
        _ToolLookupRegistry(None),
        hyps,
        mcp_client=None,
        semaphore=asyncio.Semaphore(1),
    )

    assert hyps[0].enrichments == {}
    assert "not found in registry" in caplog.text


async def test_run_one_enrichment_fans_out_per_hypothesis() -> None:
    """A resolved tool runs once per hypothesis, keyed by output_key."""
    tool_config = ToolConfig(server="s", mcp_tool_name="nvd_search")
    mcp_client = FakeCallToolClient({"ok": True})
    hyps = [make_hypothesis(text="h1"), make_hypothesis(text="h2")]
    # output_key left blank -> falls back to the tool id.
    enrichment = EnrichmentConfig(tool="cve_lookup")

    await _run_one_enrichment(
        enrichment,
        _ToolLookupRegistry(tool_config),
        hyps,
        mcp_client,
        asyncio.Semaphore(2),
    )

    assert {kwargs["topic"] for _, kwargs in mcp_client.calls} == {
        "h1",
        "h2",
    }
    assert hyps[0].enrichments["cve_lookup"] == {"ok": True}
    assert hyps[1].enrichments["cve_lookup"] == {"ok": True}


# -----------------------------------------------------------------------------
# _enrich_hypotheses
# -----------------------------------------------------------------------------


class _EnrichmentRegistry:
    """Minimal registry stand-in exposing only get_enrichment_configs."""

    def __init__(self, configs: list[EnrichmentConfig]) -> None:
        self._configs = configs

    def get_enrichment_configs(self) -> list[EnrichmentConfig]:
        """Return the configured enrichment configs."""
        return self._configs


async def test_enrich_hypotheses_no_registry_is_noop() -> None:
    """No tool_registry on state short-circuits before touching MCP."""
    hyps = [make_hypothesis(text="h1")]
    state = make_state(tool_registry=None)

    await _enrich_hypotheses(hyps, state)

    assert hyps[0].enrichments == {}


async def test_enrich_hypotheses_no_configs_is_noop() -> None:
    """A registry with no enrichment configs short-circuits before MCP."""
    hyps = [make_hypothesis(text="h1")]
    state = make_state(tool_registry=_EnrichmentRegistry([]))

    await _enrich_hypotheses(hyps, state)

    assert hyps[0].enrichments == {}


async def test_enrich_hypotheses_runs_each_configured_enrichment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each enabled enrichment config drives one _run_one_enrichment call."""
    recorded: list[tuple[str, Any]] = []

    async def fake_run_one_enrichment(
        enrichment: EnrichmentConfig,
        _tool_registry: Any,
        _hypotheses: list[Any],
        mcp_client: Any,
        _semaphore: asyncio.Semaphore,
    ) -> None:
        recorded.append((enrichment.tool, mcp_client))

    async def fake_get_mcp_client(**_: Any) -> str:
        return "fake-mcp-client"

    monkeypatch.setattr(
        coordinator_enrichment, "_run_one_enrichment", fake_run_one_enrichment
    )
    monkeypatch.setattr(
        coordinator_enrichment, "get_mcp_client", fake_get_mcp_client
    )

    configs = [
        EnrichmentConfig(tool="cve_lookup"),
        EnrichmentConfig(tool="trial_lookup"),
    ]
    registry = _EnrichmentRegistry(configs)
    hyps = [make_hypothesis(text="h1")]
    state = make_state(tool_registry=registry)

    await _enrich_hypotheses(hyps, state)

    assert recorded == [
        ("cve_lookup", "fake-mcp-client"),
        ("trial_lookup", "fake-mcp-client"),
    ]
