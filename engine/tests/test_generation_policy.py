from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from typing import Any

import pytest

import co_scientist.cache as cache_mod
import co_scientist.llm.call as llm_call
from co_scientist.agents.generation import debate
from co_scientist.agents.generation.debate import generate_with_debate
from co_scientist.agents.generation.generate import generate_node
from co_scientist.agents.generation.operations import (
    _determine_generation_counts,
)
from co_scientist.agents.meta_review.meta_review import meta_review_node
from co_scientist.cache import LLMCacheRequest, get_cache
from co_scientist.generator.run_setup import _resolve_generation_strategy
from co_scientist.llm import CompletionSpec, LLMCallOptions, call_llm_json
from co_scientist.llm.request.backend import active_backend
from co_scientist.offline.llm import _prompt_text
from co_scientist.prompts import (
    DraftPromptRequest,
    ValidationSynthesisRequest,
    get_draft_prompt_with_tools,
    get_research_overview_prompt,
    get_validation_synthesis_prompt_with_tools,
)
from co_scientist.prompts.generation_debate import _DEBATE_MAX_DISCUSSION_TURNS
from co_scientist.prompts.loading import load_prompt
from tests._llm_fake import (
    install_fake_backend,
    install_fake_llm,
    stub_call_llm_json,
)
from tests._state import (
    make_generation_response,
    make_hypothesis,
    make_review,
    make_state,
)


async def _fresh_call_llm(*_a: Any, **_k: Any) -> str:
    """Patch the single-attempt primitive, not a public wrapper that runs its
    own retry loop."""
    return json.dumps({"hypotheses": [{"hypothesis": "FRESH"}]})


def _run_json_call(schema: Any, *, use_cache: bool) -> dict[str, Any]:
    return asyncio.run(
        call_llm_json(
            "P",
            CompletionSpec(
                model_name="m",
                max_tokens=100,
                temperature=0.7,
                json_schema=schema,
            ),
            options=LLMCallOptions(use_cache=use_cache),
        )
    )


def test_call_llm_json_bypasses_warm_cache_when_disabled(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    monkeypatch.setenv("COSCIENTIST_CACHE_ENABLED", "true")
    monkeypatch.setenv("COSCIENTIST_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(cache_mod, "_global_cache", None)

    schema = {"name": "x"}
    get_cache().set(
        LLMCacheRequest("P", "m", 0.7, 100, json_schema=schema),
        {"hypotheses": [{"hypothesis": "CACHED"}]},
    )
    monkeypatch.setattr(llm_call, "_call_llm_single_attempt", _fresh_call_llm)

    cached = _run_json_call(schema, use_cache=True)
    assert cached["hypotheses"][0]["hypothesis"] == "CACHED"

    fresh = _run_json_call(schema, use_cache=False)
    assert fresh["hypotheses"][0]["hypothesis"] == "FRESH"

    monkeypatch.setattr(cache_mod, "_global_cache", None)


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


def test_forced_debate_only_overrides_the_derived_mix() -> None:
    state = make_state(generation_strategy="no_lit")
    counts = _determine_generation_counts(
        state, total_count=4, has_literature=True, enable_tool_calling=True
    )
    assert counts.tools_count == 0
    assert counts.debate_with_lit_count == 0
    assert counts.debate_only_count > 0
    assert counts.is_degraded_mode is True


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


async def test_debate_prompts_carry_scientist_criteria(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []

    async def fake_call_llm(**kwargs: Any) -> str:
        prompts.append(str(kwargs["prompt"]))
        return "HYPOTHESIS: agreed"

    async def fake_call_llm_json(**kwargs: Any) -> dict[str, Any]:
        prompts.append(str(kwargs["prompt"]))
        return make_generation_response(
            "the criteria-guided hypothesis", explanation="because"
        )

    monkeypatch.setattr(debate, "call_llm", fake_call_llm)
    monkeypatch.setattr(debate, "call_llm_json", fake_call_llm_json)

    state = make_state(
        criteria=["Translational feasibility within five years"],
    )
    await generate_with_debate(state, count=1)

    assert any(
        "Scientist Evaluation Criteria" in prompt
        and "Translational feasibility within five years" in prompt
        for prompt in prompts
    )

    prompts.clear()
    await generate_with_debate(make_state(), count=1)
    assert all(
        "Scientist Evaluation Criteria" not in prompt for prompt in prompts
    )
    assert all("{{MISSING" not in prompt for prompt in prompts)


async def test_debate_prompt_states_the_envelope_from_the_loop_constants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale prose envelope is a real instruction even when code enforces
    different bounds."""
    from co_scientist.prompts.generation_debate import (
        _DEBATE_TYPICAL_MAX_TURNS,
        _DEBATE_TYPICAL_MIN_TURNS,
    )

    prompts: list[str] = []

    async def fake_call_llm(**kwargs: Any) -> str:
        prompts.append(str(kwargs["prompt"]))
        return "HYPOTHESIS: agreed"

    monkeypatch.setattr(debate, "call_llm", fake_call_llm)
    stub_call_llm_json(
        monkeypatch,
        debate,
        make_generation_response("h", explanation="because"),
    )

    await generate_with_debate(make_state(), count=1)

    envelope = (
        f"typically {_DEBATE_TYPICAL_MIN_TURNS}-{_DEBATE_TYPICAL_MAX_TURNS}"
        f" conversational turns, with a maximum of "
        f"{_DEBATE_MAX_DISCUSSION_TURNS}"
    )
    assert all(envelope in prompt for prompt in prompts)


@pytest.mark.parametrize(
    "constraints",
    [None, ["No mouse work; zebrafish only", "Budget capped at $50k"]],
)
async def test_generation_sends_the_scientific_contract_to_assumptions(
    monkeypatch: pytest.MonkeyPatch,
    constraints: list[str] | None,
) -> None:
    from co_scientist.agents.generation import assumptions

    calls: list[dict[str, Any]] = []

    async def complete(prompt: str, **kwargs: Any) -> dict[str, Any]:
        calls.append({"prompt": prompt, **kwargs})
        return make_generation_response("assumptions hypothesis")

    async def discuss(**_: Any) -> str:
        return "HYPOTHESIS: agreed"

    monkeypatch.setattr(assumptions, "call_llm_json", complete)
    monkeypatch.setattr(debate, "call_llm", discuss)
    stub_call_llm_json(monkeypatch, debate, make_generation_response("debated"))
    await generate_node(
        make_state(
            initial_hypotheses_count=4,
            lab_constraints=constraints,
            supervisor_guidance={"key_areas": ["mechanism"]},
        )
    )
    prompt = calls[-1]["prompt"]
    for text in (
        "novelty claims must be hedged",
        "to our knowledge",
        "bounded retrieval",
        "depth requirements",
        "mechanism specificity",
        "quantitative predictions",
        "complete experiment detail",
        "category label",
        "2-4 word",
        "every hypothesis must carry a category",
        "scene-setting",
        "introduction",
        "recent_findings",
        "safety and toxicity",
        "safety_and_toxicity",
    ):
        assert text in prompt.lower()
    assert "{{MISSING" not in prompt
    assert ("Lab Constraints" in prompt) == bool(constraints)
    if constraints:
        assert all(constraint in prompt for constraint in constraints)
        assert "Respect them" in prompt
    item = calls[-1]["spec"].json_schema["schema"]["properties"]["hypotheses"][
        "items"
    ]
    assert {
        "category",
        "introduction",
        "recent_findings",
        "safety_and_toxicity",
    } <= set(item["required"])
    properties = item["properties"]
    assert "Depth over brevity" in properties["explanation"]["description"]
    assert "(4-6 sentences)" not in properties["explanation"]["description"]
    experiment = properties["experiment"]
    assert experiment["type"] == "object"
    assert set(experiment["required"]) == {
        "steps",
        "go_criterion",
        "no_go_criterion",
    }
    assert "2-5" in experiment["properties"]["steps"]["description"]
    assert "Go/No-Go" in experiment["properties"]["steps"]["description"]


@pytest.mark.parametrize(
    ("strategy", "expected_tools_count_positive", "expected_debate_only"),
    [(None, True, False), ("bogus", True, False), ("no_lit", False, True)],
)
def test_forced_strategy_overrides_only_a_recognised_label(
    strategy: str | None,
    expected_tools_count_positive: bool,
    expected_debate_only: bool,
) -> None:
    state = make_state(generation_strategy=strategy)
    counts = _determine_generation_counts(
        state, total_count=4, has_literature=True, enable_tool_calling=True
    )
    assert (counts.tools_count > 0) is expected_tools_count_positive
    assert (counts.debate_only_count > 0) is expected_debate_only
    assert counts.is_degraded_mode is expected_debate_only


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


@pytest.mark.parametrize(
    "build",
    [
        lambda: get_draft_prompt_with_tools(
            DraftPromptRequest(research_goal="a goal", hypotheses_count=2)
        )[0],
        lambda: get_validation_synthesis_prompt_with_tools(
            ValidationSynthesisRequest(
                research_goal="a goal", hypotheses_with_analyses=[]
            )
        )[0],
        lambda: load_prompt("evolution", {}),
        lambda: get_research_overview_prompt(
            research_goal="a goal", hypotheses_summary="1. an idea"
        )[0],
    ],
    ids=["draft", "synthesis", "evolution", "overview"],
)
def test_every_writing_prompt_requires_hedged_novelty_claims(
    build: Any,
) -> None:
    assert "novelty claims must be hedged" in build().lower()
