from __future__ import annotations

from typing import Any

import pytest

from co_scientist.agents.generation import assumptions as assumptions_mod
from co_scientist.agents.generation import debate
from co_scientist.agents.generation.assumptions import (
    MAX_FALSIFIED_ASSUMPTION_LINES,
    generate_with_assumptions,
)
from co_scientist.agents.generation.debate import (
    generate_with_debate,
)
from co_scientist.agents.generation.generate import generate_node
from co_scientist.models import GenerationMethod
from co_scientist.prompts.generation_debate import _DEBATE_MAX_DISCUSSION_TURNS
from tests._llm_fake import stub_call_llm_json
from tests._state import make_generation_response, make_hypothesis, make_state


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
