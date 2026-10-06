from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

import pytest

from co_scientist.agents.generation import assumptions as assumptions_mod
from co_scientist.agents.generation import debate, prepare_generation
from co_scientist.agents.generation.assumptions import (
    MAX_FALSIFIED_ASSUMPTION_LINES,
    generate_with_assumptions,
)
from co_scientist.agents.generation.debate import generate_with_debate
from co_scientist.agents.generation.generate import (
    generate_hypotheses,
    generate_node,
)
from co_scientist.agents.generation.operations import (
    _enrich_one_hypothesis,
    _ResolvedEnrichment,
    _run_one_enrichment,
)
from co_scientist.agents.meta_review.meta_review import meta_review_node
from co_scientist.config.schema import EnrichmentConfig, ToolConfig
from co_scientist.exceptions import GenerationError
from co_scientist.generator.run_setup import _resolve_generation_strategy
from co_scientist.llm.request.backend import active_backend
from co_scientist.models import GenerationMethod
from co_scientist.offline.llm import _prompt_text
from co_scientist.prompts.generation_debate import _DEBATE_MAX_DISCUSSION_TURNS
from tests._llm_fake import (
    install_fake_backend,
    install_fake_llm,
    stub_call_llm_json,
)
from tests._mcp import FakeCallToolClient
from tests._state import (
    _DebateRecorder,
    _install,
    _ToolsRecorder,
    make_generation_response,
    make_hypothesis,
    make_review,
    make_state,
)


def _stub_debate_llm(monkeypatch: pytest.MonkeyPatch, final_text: str) -> None:

    async def fake_call_llm(**_: Any) -> str:
        return "a debate turn argument"

    async def fake_call_llm_json(**_: Any) -> dict[str, Any]:
        return make_generation_response(final_text)

    monkeypatch.setattr(debate, "call_llm", fake_call_llm)
    monkeypatch.setattr(debate, "call_llm_json", fake_call_llm_json)


@pytest.mark.parametrize(
    ("turn_text", "converges"),
    [
        ("HYPOTHESIS: the panel agrees", True),
        ("we conclude: HYPOTHESIS — inhibition of E", True),
        ("**HYPOTHESIS**: the panel agrees", True),
        ("HYPOTHESIS\nthe panel agrees", True),
        ("the hypothesis is weak", False),
        ("Hypothesis 1: a direct causal mechanism", False),
        ("Hypotheses: three candidates remain", False),
        ('we will write "HYPOTHESIS" once we agree', False),
        ("the panel still disagrees", False),
    ],
)
async def test_generation_retires_converged_debates_and_caps_discussion(
    monkeypatch: pytest.MonkeyPatch,
    turn_text: str,
    converges: bool,
) -> None:
    turns: list[str] = []

    async def discuss(**_: Any) -> str:
        text = "still arguing" if not turns else turn_text
        turns.append(text)
        return text

    monkeypatch.setattr(debate, "call_llm", discuss)
    stub_call_llm_json(
        monkeypatch, debate, make_generation_response("converged idea")
    )
    result = await generate_node(
        make_state(
            initial_hypotheses_count=1,
            supervisor_guidance={"key_areas": ["mechanism"]},
        )
    )
    expected_turns = 2 if converges else _DEBATE_MAX_DISCUSSION_TURNS
    assert (
        result["debate_transcripts"][0]["transcript"].count("Turn ")
        == expected_turns
    )
    assert result["metrics"].llm_calls == expected_turns + 1
    assert result["hypotheses"].items[0].text == "converged idea"


async def test_parallel_debates_receive_distinct_focus_prompts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final_prompts: list[str] = []

    async def fake_call_llm(**_: Any) -> str:
        return "a debate turn argument"

    async def fake_call_llm_json(**kwargs: Any) -> dict[str, Any]:
        prompt = str(kwargs["prompt"])
        final_prompts.append(prompt)
        debate_number = len(final_prompts)
        return make_generation_response(
            f"hypothesis from debate {debate_number}"
        )

    monkeypatch.setattr(debate, "call_llm", fake_call_llm)
    monkeypatch.setattr(debate, "call_llm_json", fake_call_llm_json)

    hyps, _, _ = await generate_with_debate(make_state(), count=3)

    assert [h.text for h in hyps] == [
        "hypothesis from debate 1",
        "hypothesis from debate 2",
        "hypothesis from debate 3",
    ]
    assert len(final_prompts) == 3
    assert "Parallel debate 1 of 3" in final_prompts[0]
    assert "Parallel debate 2 of 3" in final_prompts[1]
    assert "Parallel debate 3 of 3" in final_prompts[2]
    assert len(set(final_prompts)) == 3


def _tree_response(
    count: int = 2, load_bearing_from: int = 0
) -> dict[str, Any]:
    return {
        "assumptions": [
            {
                "assumption": f"assumption {i}",
                "load_bearing": i >= load_bearing_from,
            }
            for i in range(count)
        ]
    }


def _sub_response(*entries: tuple[int, list[str]]) -> dict[str, Any]:
    return {
        "parents": [
            {"parent_index": index, "sub_assumptions": subs}
            for index, subs in entries
        ]
    }


def _final_response(text: str = "a challenging hypothesis") -> dict[str, Any]:
    return make_generation_response(
        text,
        explanation="why",
        literature_grounding="grounding",
        experiment="how",
    )


def _install_sequence(
    monkeypatch: pytest.MonkeyPatch, responses: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    remaining = list(responses)

    async def _fake(prompt: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append({"prompt": prompt, **kwargs})
        return remaining.pop(0) if remaining else _final_response()

    monkeypatch.setattr(assumptions_mod, "call_llm_json", _fake)
    return calls


async def test_tree_makes_three_bounded_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_sequence(
        monkeypatch,
        [
            _tree_response(2),
            _sub_response((0, ["sub A", "sub B"])),
            _final_response(),
        ],
    )
    state = make_state(research_goal="explain protein folding")

    result, llm_calls = await generate_with_assumptions(state, 1)

    assert [c["options"].prompt_name for c in calls] == [
        "generation_assumption_tree",
        "generation_assumption_sub",
        "generation_assumptions",
    ]
    assert len(result) == 1
    assert result[0].generation_method is GenerationMethod.ASSUMPTIONS
    assert llm_calls == 3
    assert all(call["options"].use_cache is False for call in calls)
    final = calls[-1]["prompt"]
    assert "assumption 0" in final and "assumption 1" in final
    assert "(load-bearing)" in final and "sub A" in final


def _probe(
    question: str = "Does X hold?",
    answer: str = "Evidence shows X does not hold.",
    fundamental: bool = False,
    **extra: object,
) -> dict[str, object]:
    probe: dict[str, object] = {
        "question": question,
        "answer": answer,
        "reasoning": "reasoning text",
        "assumption_is_fundamental": fundamental,
        "search_query": "X holds",
    }
    probe.update(extra)
    return probe


async def test_generation_caps_falsified_assumption_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_debate_llm(monkeypatch, "debated")
    calls = _install_sequence(
        monkeypatch, [{"assumptions": []}, _final_response()]
    )
    hyp = make_hypothesis(
        deep_verification_probes=[_probe(question=f"Q{i}?") for i in range(10)],
        deep_verification_verdict="weakened",
    )
    await generate_node(
        make_state(
            hypotheses=[hyp],
            initial_hypotheses_count=4,
            supervisor_guidance={"key_areas": ["mechanism"]},
        )
    )
    final = calls[-1]["prompt"]
    assert all(f"Q{i}?" in final for i in range(MAX_FALSIFIED_ASSUMPTION_LINES))
    assert f"Q{MAX_FALSIFIED_ASSUMPTION_LINES}?" not in final


async def _fake_debate_call_llm(
    *_a: Any, options: Any = None, **_k: Any
) -> str:
    assert options is not None and options.use_cache is False
    return "turn"


def _make_fake_debate_call_llm_json(counter: dict[str, int]) -> Any:

    async def fake_call_llm_json(
        *_a: Any, options: Any = None, **_k: Any
    ) -> dict[str, Any]:
        use_cache = options.use_cache if options is not None else True
        if use_cache:
            text = "CACHED-IDENTICAL"
        else:
            counter["n"] += 1
            text = f"FRESH-{counter['n']}"
        return make_generation_response(
            text, explanation="", experiment="", literature_grounding=""
        )

    return fake_call_llm_json


def test_parallel_debates_stay_distinct_with_warm_cache(
    monkeypatch: Any,
) -> None:
    """Identical prompts rely on fresh sampling; cached replay collapses
    generated ideas."""
    monkeypatch.setattr(
        debate,
        "get_debate_generation_prompt",
        lambda *_a, **_k: ("prompt", {"name": "x"}),
    )
    monkeypatch.setattr(debate, "call_llm", _fake_debate_call_llm)
    monkeypatch.setattr(
        debate, "call_llm_json", _make_fake_debate_call_llm_json({"n": 0})
    )

    state = make_state(research_goal="g", model_name="m")
    hyps, _, _ = asyncio.run(generate_with_debate(state, count=4))

    assert len(hyps) == 4
    texts = {h.text for h in hyps}
    assert len(texts) == 4, f"expected 4 distinct hypotheses, got {texts}"


_GENERATION_SCHEMA_NAME = "hypothesis_generation"


_RESEARCH_GOAL = "Explain how protein X folds"


_SUPERVISOR_GUIDANCE = {"key_areas": ["protein folding"]}


async def _capture_prompts(
    monkeypatch: pytest.MonkeyPatch, coro: Coroutine[Any, Any, dict[str, Any]]
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    original = active_backend()
    calls: list[tuple[str, str]] = []

    async def spy(**kwargs: Any) -> Any:
        response_format = kwargs.get("response_format")
        schema_name = ""
        if response_format and response_format.get("type") == "json_schema":
            schema_name = response_format["json_schema"].get("name", "")
        calls.append((schema_name, _prompt_text(kwargs)))
        return await original.complete(**kwargs)

    install_fake_backend(
        monkeypatch, spy, supports_json_schema=original.supports_json_schema
    )
    result = await coro
    return result, calls


def _generation_prompts(calls: list[tuple[str, str]]) -> list[str]:
    return [prompt for name, prompt in calls if name == _GENERATION_SCHEMA_NAME]


async def test_second_generation_cycle_carries_meta_review_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_llm(monkeypatch)

    cycle1_state = make_state(
        research_goal=_RESEARCH_GOAL,
        supervisor_guidance=_SUPERVISOR_GUIDANCE,
        initial_hypotheses_count=1,
    )
    _, cycle1_calls = await _capture_prompts(
        monkeypatch, generate_node(cycle1_state)
    )
    cycle1_prompts = _generation_prompts(cycle1_calls)
    assert cycle1_prompts, "cycle 1 never rendered a generation prompt"

    reviewed_state = make_state(
        hypotheses=[
            make_hypothesis(
                text="a reviewed hypothesis", reviews=[make_review()]
            )
        ]
    )
    meta_review_result, meta_review_calls = await _capture_prompts(
        monkeypatch, meta_review_node(reviewed_state)
    )
    assert meta_review_calls, "meta_review never made an LLM call"
    meta_review = meta_review_result["meta_review"]
    assert meta_review["emerging_themes"], (
        "offline meta_review produced no themes to trace"
    )
    theme_marker = meta_review["emerging_themes"][0]

    cycle2_state = make_state(
        research_goal=_RESEARCH_GOAL,
        supervisor_guidance=_SUPERVISOR_GUIDANCE,
        initial_hypotheses_count=1,
        current_iteration=1,
        meta_review=meta_review,
    )
    _, cycle2_calls = await _capture_prompts(
        monkeypatch, generate_node(cycle2_state)
    )
    cycle2_prompts = _generation_prompts(cycle2_calls)
    assert cycle2_prompts, "cycle 2 never rendered a generation prompt"

    assert not any(theme_marker in prompt for prompt in cycle1_prompts)
    assert any(theme_marker in prompt for prompt in cycle2_prompts)
    assert any(
        "Research Areas Already Covered" in prompt for prompt in cycle2_prompts
    )
    assert not any(
        "Research Areas Already Covered" in prompt for prompt in cycle1_prompts
    )


@pytest.mark.parametrize(
    ("opts", "tool_calling", "expected"),
    [
        ({"generation_strategy": "lit_and_tools"}, False, ""),
        ({"generation_strategy": "lit_and_tools"}, True, "lit_and_tools"),
        ({"generation_strategy": "no_lit"}, False, "no_lit"),
        ({}, True, ""),
        ({"generation_strategy": None}, True, ""),
    ],
)
def test_the_resolver_refuses_tool_strategies_without_tool_calling(
    opts: dict[str, Any], tool_calling: bool, expected: str
) -> None:
    assert _resolve_generation_strategy(opts, tool_calling) == expected


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
