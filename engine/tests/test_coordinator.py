from __future__ import annotations

import asyncio
import logging

import pytest

from co_scientist.agents.generation import prepare_generation
from co_scientist.agents.generation.generate import generate_hypotheses
from co_scientist.agents.generation.operations import (
    _enrich_one_hypothesis,
    _ResolvedEnrichment,
    _run_one_enrichment,
)
from co_scientist.config.schema import EnrichmentConfig, ToolConfig
from co_scientist.exceptions import GenerationError
from tests._mcp import FakeCallToolClient
from tests._state import (
    _DebateRecorder,
    _install,
    _ToolsRecorder,
    make_hypothesis,
    make_state,
)


async def test_condition_b_degraded_mode_applies_fallback_grounding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = _ToolsRecorder([])
    debate = _DebateRecorder(
        [
            make_hypothesis(text="d1", literature_grounding=None),
            make_hypothesis(text="d2", literature_grounding="stale"),
        ],
        [{"hypothesis_text": "d1"}, {"hypothesis_text": "d2"}],
    )
    _install(monkeypatch, tools, debate)

    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=2,
        mcp_available=False,
        articles_with_reasoning="ignored because mcp unavailable",
        enable_tool_calling_generation=True,
    )
    result = await generate_hypotheses(state)

    assert not tools.called
    assert debate.called and debate.count == 2
    assert debate.articles_with_reasoning is None
    for hyp in result["hypotheses"].items:
        assert hyp.literature_grounding is not None
        assert hyp.literature_grounding.startswith(
            "No literature review available."
        )
    assert "debate-only" in result["message"]
    assert result["hypothesis_count"] == 2


async def test_condition_b_degraded_mode_logs_a_single_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """User-visible diagnostics render each warning; decorative banners
    multiply records."""
    tools = _ToolsRecorder([])
    debate = _DebateRecorder([make_hypothesis(text="d1")], [])
    _install(monkeypatch, tools, debate)

    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=1,
        mcp_available=False,
        articles_with_reasoning=None,
        enable_tool_calling_generation=True,
    )
    with caplog.at_level(logging.WARNING):
        await generate_hypotheses(state)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "latent knowledge" in warnings[0].getMessage()


async def test_enrich_one_hypothesis_records_error_on_failure() -> None:
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


class _ToolLookupRegistry:
    def __init__(self, tool: ToolConfig | None) -> None:
        self._tool = tool

    def get_tool(self, _tool_id: str) -> ToolConfig | None:
        return self._tool


async def test_run_one_enrichment_fans_out_per_hypothesis() -> None:
    tool_config = ToolConfig(server="s", mcp_tool_name="nvd_search")
    mcp_client = FakeCallToolClient({"ok": True})
    hyps = [make_hypothesis(text="h1"), make_hypothesis(text="h2")]
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


async def test_plan_requires_supervisor_guidance() -> None:
    with pytest.raises(GenerationError, match="No supervisor_guidance"):
        await prepare_generation(make_state())
