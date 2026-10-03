from __future__ import annotations

import asyncio
import dataclasses
import logging
import re
from typing import Any

import pytest

from co_scientist.agents.generation import generate as coordinator
from co_scientist.agents.generation import operations as coordinator_enrichment
from co_scientist.agents.generation import prepare_generation
from co_scientist.agents.generation.generate import generate_hypotheses
from co_scientist.agents.generation.operations import (
    _enrich_hypotheses,
    _enrich_one_hypothesis,
    _ResolvedEnrichment,
    _run_one_enrichment,
)
from co_scientist.config.schema import EnrichmentConfig, ToolConfig
from co_scientist.constants import LITERATURE_REVIEW_FAILED
from co_scientist.exceptions import GenerationError
from co_scientist.models import GenerationMethod
from tests._mcp import FakeCallToolClient
from tests._state import (
    _AssumptionsRecorder,
    _DebateRecorder,
    _install,
    _ToolsRecorder,
    make_article,
    make_hypothesis,
    make_state,
)


async def test_condition_a_splits_tools_debate_and_assumptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = _ToolsRecorder([make_hypothesis(text="t1")], llm_calls=3)
    debate = _DebateRecorder(
        [make_hypothesis(text="d1"), make_hypothesis(text="d2")],
        [{"hypothesis_text": "d1"}, {"hypothesis_text": "d2"}],
        llm_calls=9,
    )
    assumptions = _AssumptionsRecorder(
        [make_hypothesis(text="a1")], llm_calls=2
    )
    _install(monkeypatch, tools, debate, assumptions)

    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=4,
        mcp_available=True,
        articles_with_reasoning="some papers and reasoning",
        enable_tool_calling_generation=True,
    )
    result = await generate_hypotheses(state)

    assert assumptions.called and assumptions.count == 1
    assert tools.called and tools.count == 1
    assert debate.called and debate.count == 2
    assert debate.articles_with_reasoning == "some papers and reasoning"
    assert assumptions.articles_with_reasoning == "some papers and reasoning"
    texts = [h.text for h in result["hypotheses"].items]
    assert texts == ["t1", "d1", "d2", "a1"]
    assert result["hypothesis_count"] == 4
    assert len(result["debate_transcripts"]) == 2
    assert result["llm_call_count"] == 3 + 9 + 2


async def test_condition_a_single_count_collapses_to_tools_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = _ToolsRecorder([make_hypothesis(text="t1")])
    debate = _DebateRecorder([], [])
    _install(monkeypatch, tools, debate)

    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=1,
        mcp_available=True,
        articles_with_reasoning="papers",
        enable_tool_calling_generation=True,
    )
    result = await generate_hypotheses(state)

    assert tools.called and tools.count == 1
    assert not debate.called
    assert result["hypothesis_count"] == 1
    assert result["debate_transcripts"] == []


async def test_condition_c_debate_with_lit_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = _ToolsRecorder([make_hypothesis(text="should-not-appear")])
    debate = _DebateRecorder(
        [
            make_hypothesis(text="d1"),
            make_hypothesis(text="d2"),
            make_hypothesis(text="d3"),
        ],
        [{"hypothesis_text": "d1"}],
    )
    _install(monkeypatch, tools, debate)

    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=3,
        mcp_available=True,
        articles_with_reasoning="papers",
        enable_tool_calling_generation=False,
    )
    result = await generate_hypotheses(state)

    assert not tools.called
    assert debate.called and debate.count == 3
    assert debate.articles_with_reasoning == "papers"
    assert [h.text for h in result["hypotheses"].items] == ["d1", "d2", "d3"]
    assert result["hypothesis_count"] == 3
    assert "debate-with-literature" in result["message"]


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


async def test_failed_lit_review_marker_is_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = _ToolsRecorder([])
    debate = _DebateRecorder([make_hypothesis(text="d1")], [])
    _install(monkeypatch, tools, debate)

    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=1,
        mcp_available=True,
        articles_with_reasoning=LITERATURE_REVIEW_FAILED,
        enable_tool_calling_generation=True,
    )
    result = await generate_hypotheses(state)

    assert not tools.called
    assert debate.called and debate.articles_with_reasoning is None
    assert result["hypothesis_count"] == 1


async def test_no_lit_path_invokes_assumptions_technique(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from co_scientist.models import GenerationMethod
    from tests._llm_fake import install_fake_llm

    install_fake_llm(monkeypatch)
    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=8,
        mcp_available=False,
        enable_tool_calling_generation=True,
        model_name="fake-model",
    )

    result = await generate_hypotheses(state)

    methods = {h.generation_method for h in result["hypotheses"].items}
    assert GenerationMethod.ASSUMPTIONS in methods
    assert GenerationMethod.DEBATE in methods


async def test_lit_and_tools_reserves_assumptions_slice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = _ToolsRecorder([make_hypothesis(text="t1")])
    debate = _DebateRecorder([make_hypothesis(text="d1")], [])
    assumptions = _AssumptionsRecorder([make_hypothesis(text="a1")])
    _install(monkeypatch, tools, debate, assumptions)

    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=8,
        mcp_available=True,
        articles_with_reasoning="some papers and reasoning",
        enable_tool_calling_generation=True,
    )
    result = await generate_hypotheses(state)

    assert assumptions.called and assumptions.count is not None
    assert assumptions.count > 0
    assert tools.called and debate.called
    assert (assumptions.count or 0) + (tools.count or 0) + (
        debate.count or 0
    ) == 8
    assert assumptions.articles_with_reasoning == "some papers and reasoning"
    assert assumptions.reference_index is not None
    assert "a1" in [h.text for h in result["hypotheses"].items]


async def test_lit_only_reserves_assumptions_slice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = _ToolsRecorder([])
    debate = _DebateRecorder([make_hypothesis(text="d1")], [])
    assumptions = _AssumptionsRecorder([make_hypothesis(text="a1")])
    _install(monkeypatch, tools, debate, assumptions)

    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=8,
        mcp_available=True,
        articles_with_reasoning="papers",
        enable_tool_calling_generation=False,
    )
    result = await generate_hypotheses(state)

    assert not tools.called
    assert assumptions.called and (assumptions.count or 0) > 0
    assert (assumptions.count or 0) + (debate.count or 0) == 8
    assert assumptions.articles_with_reasoning == "papers"
    assert assumptions.reference_index is not None
    assert "a1" in [h.text for h in result["hypotheses"].items]


async def test_dev_isolation_routes_all_to_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = _ToolsRecorder(
        [
            make_hypothesis(text="t1"),
            make_hypothesis(text="t2"),
            make_hypothesis(text="t3"),
        ]
    )
    debate = _DebateRecorder([], [])
    _install(monkeypatch, tools, debate)

    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=3,
        mcp_available=True,
        articles_with_reasoning="papers",
        enable_tool_calling_generation=True,
        dev_test_lit_tools_isolation=True,
    )
    result = await generate_hypotheses(state)

    assert tools.called and tools.count == 3
    assert not debate.called
    assert result["hypothesis_count"] == 3
    assert "3 tool-based" in result["message"]


async def test_missing_supervisor_guidance_raises() -> None:
    with pytest.raises(GenerationError):
        await generate_hypotheses(make_state())


async def test_result_dict_shape_and_message_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = _ToolsRecorder([make_hypothesis(text="t1")])
    debate = _DebateRecorder(
        [make_hypothesis(text="d1")], [{"hypothesis_text": "d1"}]
    )
    _install(monkeypatch, tools, debate)

    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=2,
        mcp_available=True,
        articles_with_reasoning="papers",
        enable_tool_calling_generation=True,
    )
    result = await generate_hypotheses(state)

    assert set(result.keys()) == {
        "hypotheses",
        "debate_transcripts",
        "hypothesis_count",
        "llm_call_count",
        "message",
    }
    assert result["message"] == (
        "Generated 2 hypotheses (1 tool-based, 1 debate-with-literature)"
    )


async def test_later_generation_is_disclosed_as_research_expansion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = _ToolsRecorder([])
    hypothesis = make_hypothesis(text="underexplored branch")
    hypothesis.generation_method = GenerationMethod.DEBATE
    debate = _DebateRecorder([hypothesis], [])
    _install(monkeypatch, tools, debate)

    state = make_state(
        supervisor_guidance={"focus": "seek an underexplored branch"},
        initial_hypotheses_count=1,
        current_iteration=2,
        mcp_available=False,
        enable_tool_calling_generation=False,
    )
    result = await generate_hypotheses(state)

    expanded = result["hypotheses"].items[0]
    assert expanded.creation_iteration == 2
    assert expanded.generation_method == GenerationMethod.RESEARCH_EXPANSION
    assert expanded.enrichments["base_generation_method"] == "debate"


async def test_progress_callback_emits_start_and_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = _ToolsRecorder([])
    debate = _DebateRecorder(
        [make_hypothesis(text="d1")], [{"hypothesis_text": "d1"}]
    )
    _install(monkeypatch, tools, debate)

    events: list[tuple[str, dict[str, Any]]] = []

    async def callback(event: str, payload: dict[str, Any]) -> None:
        events.append((event, payload))

    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=1,
        mcp_available=True,
        articles_with_reasoning="papers",
        enable_tool_calling_generation=False,
        progress_callback=callback,
    )
    await generate_hypotheses(state)

    emitted = [name for name, _ in events]
    assert emitted == ["generation_start", "generation_complete"]
    assert events[1][1]["hypotheses_count"] == 1


async def test_enrich_one_hypothesis_unwraps_results_path() -> None:
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


async def test_run_one_enrichment_missing_tool_is_noop(
    caplog: pytest.LogCaptureFixture,
) -> None:
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


class _EnrichmentRegistry:
    def __init__(self, configs: list[EnrichmentConfig]) -> None:
        self._configs = configs

    def get_enrichment_configs(self) -> list[EnrichmentConfig]:
        return self._configs


async def test_enrich_hypotheses_no_registry_is_noop() -> None:
    hyps = [make_hypothesis(text="h1")]
    state = make_state(tool_registry=None)

    await _enrich_hypotheses(hyps, state)

    assert hyps[0].enrichments == {}


async def test_enrich_hypotheses_no_configs_is_noop() -> None:
    hyps = [make_hypothesis(text="h1")]
    state = make_state(tool_registry=_EnrichmentRegistry([]))

    await _enrich_hypotheses(hyps, state)

    assert hyps[0].enrichments == {}


async def test_enrich_hypotheses_runs_each_configured_enrichment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


_SUMMARY_RE = re.compile(r"Generated (\d+) total hypotheses \(([^)]*)\)")


def _stub_leaf_strategies(
    monkeypatch: pytest.MonkeyPatch,
    tools: list[str],
    debate: list[str],
    assumptions: list[str],
) -> None:

    async def fake_tools(*_args: Any, **_kwargs: Any) -> Any:
        return [make_hypothesis(text=t) for t in tools], 0

    async def fake_debate(*_args: Any, **_kwargs: Any) -> Any:
        return ([make_hypothesis(text=t) for t in debate], [], 0)

    async def fake_assumptions(*_args: Any, **_kwargs: Any) -> Any:
        return [make_hypothesis(text=t) for t in assumptions], 0

    monkeypatch.setattr(coordinator, "generate_with_tools", fake_tools)
    monkeypatch.setattr(coordinator, "generate_with_debate", fake_debate)
    monkeypatch.setattr(
        coordinator, "generate_with_assumptions", fake_assumptions
    )


def _summary_record(caplog: pytest.LogCaptureFixture) -> str:
    messages = [
        record.getMessage()
        for record in caplog.records
        if _SUMMARY_RE.search(record.getMessage())
    ]
    assert len(messages) == 1, messages
    return messages[0]


def _parse_summary(message: str) -> tuple[int, list[int]]:
    match = _SUMMARY_RE.search(message)
    assert match is not None, message
    total = int(match.group(1))
    parts = [int(n) for n in re.findall(r"\d+", match.group(2))]
    return total, parts


async def test_summary_breakdown_sums_to_total_with_assumptions(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _stub_leaf_strategies(
        monkeypatch,
        tools=["t1", "t2", "t3"],
        debate=["d1", "d2", "d3"],
        assumptions=["a1", "a2"],
    )
    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=8,
        mcp_available=True,
        articles_with_reasoning="some papers and reasoning",
        enable_tool_calling_generation=True,
    )

    with caplog.at_level(logging.INFO):
        result = await generate_hypotheses(state)

    # A nonzero assumptions slice makes missing breakdown attribution
    # observable.
    assert result["hypothesis_count"] == 8
    total, parts = _parse_summary(_summary_record(caplog))
    assert total == 8
    assert sum(parts) == total


async def test_summary_breakdown_sums_to_total_without_assumptions(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _stub_leaf_strategies(
        monkeypatch, tools=["t1"], debate=["d1", "d2"], assumptions=[]
    )
    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=3,
        mcp_available=True,
        articles_with_reasoning="some papers and reasoning",
        enable_tool_calling_generation=True,
    )

    with caplog.at_level(logging.INFO):
        await generate_hypotheses(state)

    total, parts = _parse_summary(_summary_record(caplog))
    assert total == 3
    assert sum(parts) == total


async def test_assumptions_bucket_methods_are_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _stub_leaf_strategies(
        monkeypatch,
        tools=["t1", "t2", "t3"],
        debate=["d1", "d2", "d3"],
        assumptions=["a1", "a2"],
    )
    state = make_state(
        supervisor_guidance={"focus": "x"},
        initial_hypotheses_count=8,
        mcp_available=True,
        articles_with_reasoning="some papers and reasoning",
        enable_tool_calling_generation=True,
    )

    with caplog.at_level(logging.DEBUG):
        await generate_hypotheses(state)

    labels = {
        record.getMessage().split(" generation_methods:")[0]
        for record in caplog.records
        if " generation_methods:" in record.getMessage()
    }
    assert labels == {"tool-based", "debate-with-Lit", "assumptions"}


@pytest.mark.parametrize(
    ("options", "expected_counts", "degraded"),
    [
        ({}, (0, 0, 6, 2), True),
        (
            {"mcp_available": True, "articles_with_reasoning": "papers"},
            (0, 6, 0, 2),
            False,
        ),
        (
            {
                "mcp_available": True,
                "articles_with_reasoning": "papers",
                "enable_tool_calling_generation": True,
            },
            (3, 3, 0, 2),
            False,
        ),
        (
            {
                "mcp_available": True,
                "articles_with_reasoning": LITERATURE_REVIEW_FAILED,
            },
            (0, 0, 6, 2),
            True,
        ),
        (
            {
                "mcp_available": True,
                "articles_with_reasoning": "papers",
                "generation_strategy": "no_lit",
            },
            (0, 0, 6, 2),
            True,
        ),
        ({"dev_test_lit_tools_isolation": True}, (8, 0, 0, 0), False),
        (
            {
                "mcp_available": True,
                "articles_with_reasoning": "papers",
                "enable_tool_calling_generation": True,
                "initial_hypotheses_count": 1,
            },
            (1, 0, 0, 0),
            False,
        ),
    ],
)
async def test_plan_allocations_keep_the_existing_mix(
    options: dict[str, object],
    expected_counts: tuple[int, int, int, int],
    degraded: bool,
) -> None:
    state = make_state(
        **{
            "supervisor_guidance": {"focus": "test"},
            "initial_hypotheses_count": 8,
            **options,
        }
    )
    plan = await prepare_generation(state)

    assert tuple(plan.counts.strategy_counts) == (
        "tools",
        "debate_lit",
        "debate_only",
        "assumptions",
    )
    assert tuple(plan.counts.strategy_counts.values()) == expected_counts
    assert plan.counts.is_degraded_mode is degraded
    assert sum(expected_counts) == state["initial_hypotheses_count"]
    assert set(dataclasses.asdict(plan.counts)) == {
        "tools_count",
        "debate_with_lit_count",
        "debate_only_count",
        "assumptions_count",
        "is_dev_isolation",
        "is_degraded_mode",
    }


async def test_plan_citation_namespace_includes_only_analyzed_sources() -> None:
    state = make_state(
        supervisor_guidance={"focus": "test"},
        mcp_available=True,
        articles_with_reasoning="Read evidence",
        articles=[
            make_article("Analyzed source", used_in_analysis=True),
            make_article("Unread search hit", used_in_analysis=False),
        ],
        context_enrichment_sources=[
            {"type": "knowledge_graph", "display": "A activates B"}
        ],
    )
    plan = await prepare_generation(state)

    assert plan.literature == "Read evidence"
    assert list(plan.reference_index.sources) == ["C1", "C2"]
    assert plan.reference_index.sources["C1"]["title"] == "Analyzed source"
    assert "Unread search hit" not in plan.reference_index.text
    assert "A activates B" in plan.reference_index.text


async def test_plan_requires_supervisor_guidance() -> None:
    with pytest.raises(GenerationError, match="No supervisor_guidance"):
        await prepare_generation(make_state())
