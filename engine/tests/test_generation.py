from __future__ import annotations

from typing import Any

import pytest

from co_scientist.domains.research_state.models import GenerationMethod
from co_scientist.science.generation import assumptions as assumptions_mod
from co_scientist.science.generation.assumptions import (
    generate_with_assumptions,
)
from co_scientist.science.generation.generate import (
    generate_hypotheses,
)
from tests._state import (
    _DebateRecorder,
    _install,
    _ToolsRecorder,
    make_generation_response,
    make_hypothesis,
    make_state,
)


def _tree_response(count: int = 2, load_bearing_from: int = 0) -> dict[str, Any]:
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
        "parents": [{"parent_index": index, "sub_assumptions": subs} for index, subs in entries]
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
    final = calls[-1]["prompt"]
    assert "assumption 0" in final and "assumption 1" in final
    assert "(load-bearing)" in final and "sub A" in final


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
        assert hyp.literature_grounding.startswith("No literature review available.")
    assert "debate-only" in result["message"]
    assert result["hypothesis_count"] == 2
