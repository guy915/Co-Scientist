from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

import pytest

from co_scientist.agents.generation import debate
from co_scientist.agents.generation.debate import generate_with_debate
from co_scientist.agents.generation.generate import generate_node
from co_scientist.agents.meta_review.meta_review import meta_review_node
from co_scientist.generator.run_setup import _resolve_generation_strategy
from co_scientist.llm.request.backend import active_backend
from co_scientist.offline.llm import _prompt_text
from tests._llm_fake import (
    install_fake_backend,
    install_fake_llm,
)
from tests._state import (
    make_generation_response,
    make_hypothesis,
    make_review,
    make_state,
)


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
