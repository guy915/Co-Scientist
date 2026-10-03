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
    _forced_generation_strategy,
)
from co_scientist.agents.meta_review.meta_review import meta_review_node
from co_scientist.cache import LLMCacheRequest, NullCache, get_cache
from co_scientist.generator.run_setup import _resolve_generation_strategy
from co_scientist.llm import CompletionSpec, LLMCallOptions, call_llm_json
from co_scientist.llm.request.backend import active_backend
from co_scientist.offline.llm import _prompt_text
from co_scientist.prompts import (
    DirectionWritingMaterial,
    DraftPromptRequest,
    ValidationSynthesisRequest,
    format_lab_constraints_section,
    get_draft_prompt_with_tools,
    get_research_overview_direction_prompt,
    get_research_overview_prompt,
    get_validation_synthesis_prompt_with_tools,
)
from co_scientist.prompts.generation_debate import _DEBATE_MAX_DISCUSSION_TURNS
from co_scientist.prompts.loading import load_prompt
from co_scientist.schemas.generation import (
    GENERATION_SCHEMA,
    HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA,
)
from tests._llm_fake import install_fake_backend, install_fake_llm
from tests._state import make_hypothesis, make_review, make_state


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


def test_null_cache_is_noop() -> None:
    cache = NullCache()
    assert cache.get("anything", "m", 0.7, 100) is None
    request = LLMCacheRequest("anything", "m", 0.7, 100)
    cache.set(request, {"x": 1})
    assert cache.get(request) is None


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
        return {
            "hypotheses": [
                {
                    "hypothesis": text,
                    "explanation": "",
                    "experiment": "",
                    "literature_grounding": "",
                }
            ]
        }

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


def test_derivation_is_unchanged_when_no_strategy_is_forced() -> None:
    counts = _determine_generation_counts(
        make_state(),
        total_count=4,
        has_literature=True,
        enable_tool_calling=True,
    )
    assert counts.tools_count > 0
    assert counts.debate_with_lit_count > 0


def test_forced_debate_only_overrides_the_derived_mix() -> None:
    state = make_state(generation_strategy="no_lit")
    counts = _determine_generation_counts(
        state, total_count=4, has_literature=True, enable_tool_calling=True
    )
    assert counts.tools_count == 0
    assert counts.debate_with_lit_count == 0
    assert counts.debate_only_count > 0
    assert counts.is_degraded_mode is True


def test_unknown_forced_label_falls_back_to_derivation() -> None:
    assert (
        _forced_generation_strategy(make_state(generation_strategy="bogus"))
        is None
    )
    counts = _determine_generation_counts(
        make_state(generation_strategy="bogus"),
        total_count=4,
        has_literature=False,
        enable_tool_calling=False,
    )
    assert counts.debate_only_count > 0


def test_resolver_refuses_tools_strategy_without_tool_calling() -> None:
    opts = {"generation_strategy": "lit_and_tools"}
    assert _resolve_generation_strategy(opts, False) == ""
    assert _resolve_generation_strategy(opts, True) == "lit_and_tools"


def test_resolver_allows_debate_strategy_without_tool_calling() -> None:
    opts = {"generation_strategy": "no_lit"}
    assert _resolve_generation_strategy(opts, False) == "no_lit"


def test_resolver_ignores_absent_or_nonstring_strategy() -> None:
    assert _resolve_generation_strategy({}, True) == ""
    assert (
        _resolve_generation_strategy({"generation_strategy": None}, True) == ""
    )


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
        return {
            "hypotheses": [
                {
                    "hypothesis": "the criteria-guided hypothesis",
                    "explanation": "because",
                    "literature_grounding": None,
                    "experiment": "run the assay",
                }
            ]
        }

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

    async def fake_call_llm_json(**kwargs: Any) -> dict[str, Any]:
        return {
            "hypotheses": [
                {
                    "hypothesis": "h",
                    "explanation": "because",
                    "literature_grounding": None,
                    "experiment": "run the assay",
                }
            ]
        }

    monkeypatch.setattr(debate, "call_llm", fake_call_llm)
    monkeypatch.setattr(debate, "call_llm_json", fake_call_llm_json)

    await generate_with_debate(make_state(), count=1)

    envelope = (
        f"typically {_DEBATE_TYPICAL_MIN_TURNS}-{_DEBATE_TYPICAL_MAX_TURNS}"
        f" conversational turns, with a maximum of "
        f"{_DEBATE_MAX_DISCUSSION_TURNS}"
    )
    assert all(envelope in prompt for prompt in prompts)


_NOVELTY_CONTRACT = "novelty claims must be hedged"
_HEDGED_EXAMPLE = "to our knowledge"


def _render_assumptions_prompt(state_overrides: dict[str, Any]) -> str:
    from co_scientist.agents.generation import assumptions as assumptions_mod

    state = make_state(**state_overrides)
    prompt, _ = assumptions_mod._build_assumptions_prompt(state, 2, "", "", "")
    return prompt


def test_assumptions_prompt_without_references_hedges_novelty() -> None:
    prompt = _render_assumptions_prompt({})
    assert _NOVELTY_CONTRACT in prompt.lower()
    assert _HEDGED_EXAMPLE in prompt
    assert "bounded retrieval" in prompt


def test_draft_prompt_hedges_novelty() -> None:
    prompt, _ = get_draft_prompt_with_tools(
        DraftPromptRequest(research_goal="a goal", hypotheses_count=2)
    )
    assert _NOVELTY_CONTRACT in prompt.lower()
    assert "{{MISSING" not in prompt


def test_validation_synthesis_prompts_hedge_novelty() -> None:
    analyses: list[dict[str, Any]] = []
    with_tools, _ = get_validation_synthesis_prompt_with_tools(
        ValidationSynthesisRequest(
            research_goal="a goal", hypotheses_with_analyses=analyses
        )
    )
    assert _NOVELTY_CONTRACT in with_tools.lower()


def test_evolution_prompt_hedges_novelty() -> None:
    prompt = load_prompt("evolution", {})
    assert _NOVELTY_CONTRACT in prompt.lower()


def test_research_overview_prompt_hedges_novelty() -> None:
    prompt, _ = get_research_overview_prompt(
        research_goal="a goal", hypotheses_summary="1. an idea"
    )
    assert _NOVELTY_CONTRACT in prompt.lower()
    assert "report-level text" in prompt


def test_assumptions_prompt_carries_depth_requirements() -> None:
    prompt = _render_assumptions_prompt({})
    assert "## Depth Requirements" in prompt
    assert "Mechanism specificity" in prompt
    assert "Quantitative predictions" in prompt
    assert "Complete experiment detail" in prompt


def test_draft_prompt_requires_full_depth_drafts() -> None:
    prompt, _ = get_draft_prompt_with_tools(
        DraftPromptRequest(research_goal="a goal", hypotheses_count=2)
    )
    assert "a shallow draft becomes a shallow final hypothesis" in prompt


def test_research_overview_prompt_carries_depth_guidance() -> None:
    prompt, _ = get_research_overview_prompt(
        research_goal="a goal", hypotheses_summary="1. an idea"
    )
    assert "research strategy document" in prompt
    assert "multi-paragraph narrative" in prompt


def _direction_prompt() -> str:
    prompt, _ = get_research_overview_direction_prompt(
        research_goal="a goal",
        material=DirectionWritingMaterial(
            title="A direction", rationale="Why it matters.", all_directions="-"
        ),
        hypotheses_summary="1. an idea",
    )
    return prompt


def test_research_direction_prompt_asks_for_sub_topics() -> None:
    """Six developed directions cannot fit one call's clock; draft names them
    first."""
    prompt = _direction_prompt()
    assert "sub_topics" in prompt
    assert "specific_questions" in prompt


def test_research_direction_prompt_asks_for_recent_findings() -> None:
    """Six developed directions cannot fit one call's clock; draft names them
    first."""
    prompt = _direction_prompt()
    assert "recent_findings" in prompt
    assert "already established" in prompt


def test_generation_schema_explanation_field_asks_for_depth() -> None:
    properties = GENERATION_SCHEMA["schema"]["properties"]["hypotheses"][
        "items"
    ]["properties"]
    assert "(4-6 sentences)" not in properties["explanation"]["description"]
    assert "Depth over brevity" in properties["explanation"]["description"]


def test_generation_schema_experiment_field_is_a_numbered_pilot_plan() -> None:
    experiment = GENERATION_SCHEMA["schema"]["properties"]["hypotheses"][
        "items"
    ]["properties"]["experiment"]
    assert experiment["type"] == "object"
    assert set(experiment["required"]) == {
        "steps",
        "go_criterion",
        "no_go_criterion",
    }
    assert "2-5" in experiment["properties"]["steps"]["description"]
    assert "Go/No-Go" in experiment["properties"]["steps"]["description"]


def test_generation_schemas_require_category() -> None:
    generation_item = GENERATION_SCHEMA["schema"]["properties"]["hypotheses"][
        "items"
    ]
    synthesis_item = HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA["schema"][
        "properties"
    ]["hypotheses"]["items"]
    assert "category" in generation_item["required"]
    assert "category" in synthesis_item["required"]


def test_assumptions_prompt_presents_category_contract() -> None:
    prompt = _render_assumptions_prompt({})
    assert "## Category Label" in prompt
    assert "2-4 word" in prompt
    assert "Every hypothesis must carry a category" in prompt


def test_validation_synthesis_prompts_present_category() -> None:
    analyses: list[dict[str, Any]] = []
    with_tools, _ = get_validation_synthesis_prompt_with_tools(
        ValidationSynthesisRequest(
            research_goal="a goal", hypotheses_with_analyses=analyses
        )
    )
    assert "category" in with_tools
    assert "mechanism family" in with_tools


def test_generation_schemas_require_scene_setting() -> None:
    generation_item = GENERATION_SCHEMA["schema"]["properties"]["hypotheses"][
        "items"
    ]
    synthesis_item = HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA["schema"][
        "properties"
    ]["hypotheses"]["items"]
    for node in (generation_item, synthesis_item):
        assert "introduction" in node["required"]
        assert "recent_findings" in node["required"]


def test_assumptions_prompt_presents_scene_setting_contract() -> None:
    prompt = _render_assumptions_prompt({})
    assert "## Scene-Setting" in prompt
    assert "introduction" in prompt
    assert "recent_findings" in prompt


def test_validation_synthesis_prompts_present_scene_setting() -> None:
    analyses: list[dict[str, Any]] = []
    with_tools, _ = get_validation_synthesis_prompt_with_tools(
        ValidationSynthesisRequest(
            research_goal="a goal", hypotheses_with_analyses=analyses
        )
    )
    assert "introduction" in with_tools
    assert "recent_findings" in with_tools


def test_generation_schemas_require_safety_and_toxicity() -> None:
    generation_item = GENERATION_SCHEMA["schema"]["properties"]["hypotheses"][
        "items"
    ]
    synthesis_item = HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA["schema"][
        "properties"
    ]["hypotheses"]["items"]
    for node in (generation_item, synthesis_item):
        assert "safety_and_toxicity" in node["required"]


def test_assumptions_prompt_presents_safety_and_toxicity_contract() -> None:
    prompt = _render_assumptions_prompt({})
    assert "## Safety and Toxicity" in prompt
    assert "safety_and_toxicity" in prompt


def test_validation_synthesis_prompts_present_safety_and_toxicity() -> None:
    analyses: list[dict[str, Any]] = []
    with_tools, _ = get_validation_synthesis_prompt_with_tools(
        ValidationSynthesisRequest(
            research_goal="a goal", hypotheses_with_analyses=analyses
        )
    )
    assert "safety_and_toxicity" in with_tools


def test_lab_constraints_section_empty_when_no_constraints() -> None:
    assert format_lab_constraints_section(None) == ""
    assert format_lab_constraints_section([]) == ""


def test_lab_constraints_section_renders_constraints() -> None:
    section = format_lab_constraints_section(
        ["No mouse work; zebrafish only", "Budget capped at $50k"]
    )
    assert "## Scientist's Lab Constraints" in section
    assert "No mouse work; zebrafish only" in section
    assert "Budget capped at $50k" in section
    assert "Respect them" in section


def test_assumptions_prompt_renders_lab_constraints_from_state() -> None:
    with_constraints = _render_assumptions_prompt(
        {"lab_constraints": ["Zebrafish facility only"]}
    )
    assert "## Scientist's Lab Constraints" in with_constraints
    assert "Zebrafish facility only" in with_constraints

    without = _render_assumptions_prompt({})
    assert "Lab Constraints" not in without


def test_draft_prompt_renders_lab_constraints() -> None:
    prompt, _ = get_draft_prompt_with_tools(
        DraftPromptRequest(
            research_goal="a goal",
            hypotheses_count=2,
            lab_constraints=["Biosafety level 2 only"],
        )
    )
    assert "Biosafety level 2 only" in prompt
    assert "{{MISSING" not in prompt

    bare, _ = get_draft_prompt_with_tools(
        DraftPromptRequest(research_goal="a goal", hypotheses_count=2)
    )
    assert "Lab Constraints" not in bare
    assert "{{MISSING" not in bare


@pytest.mark.parametrize(
    "overrides",
    [{}, {"lab_constraints": ["No primate work"]}],
)
def test_assumptions_prompt_fully_interpolated(
    overrides: dict[str, Any],
) -> None:
    prompt = _render_assumptions_prompt(overrides)
    assert "{{MISSING" not in prompt
