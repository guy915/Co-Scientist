from __future__ import annotations

import re
from typing import Any

import pytest

from co_scientist.agents.generation import assumptions as assumptions_mod
from co_scientist.agents.generation import debate
from co_scientist.agents.generation.assumptions import (
    ASSUMPTION_TREE_MAX_LOAD_BEARING,
    ASSUMPTION_TREE_MAX_SUB_PER_PARENT,
    ASSUMPTION_TREE_MAX_TOP,
    MAX_FALSIFIED_ASSUMPTION_LINES,
    generate_with_assumptions,
)
from co_scientist.agents.generation.debate import (
    DebateBatchPosition,
    generate_with_debate,
)
from co_scientist.agents.generation.generate import generate_node
from co_scientist.exceptions import GenerationError
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


async def test_debate_produces_one_hypothesis_per_debate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_debate_llm(monkeypatch, "tumor suppressor X gates the pathway")
    hyps, transcripts, llm_calls = await generate_with_debate(
        make_state(), count=2
    )
    assert len(hyps) == 2
    assert llm_calls == 2 * (_DEBATE_MAX_DISCUSSION_TURNS + 1)
    assert all(h.text == "tumor suppressor X gates the pathway" for h in hyps)
    assert all(h.generation_method == GenerationMethod.DEBATE for h in hyps)
    assert all(h.experiment == "run the assay" for h in hyps)
    assert {h.debate_id for h in hyps} == {0, 1}
    assert len(transcripts) == 2
    assert transcripts[0]["hypothesis_text"] == (
        "tumor suppressor X gates the pathway"
    )


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


async def test_single_debate_of_a_larger_batch_gets_its_own_angle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Durable per-debate tasks need the same diversity angle as their batch
    position."""
    final_prompts: list[str] = []

    async def fake_call_llm(**_: Any) -> str:
        return "a debate turn argument"

    async def fake_call_llm_json(**kwargs: Any) -> dict[str, Any]:
        final_prompts.append(str(kwargs["prompt"]))
        return make_generation_response(
            "the angled hypothesis", explanation="because"
        )

    monkeypatch.setattr(debate, "call_llm", fake_call_llm)
    monkeypatch.setattr(debate, "call_llm_json", fake_call_llm_json)

    hyps, transcripts, _ = await generate_with_debate(
        make_state(),
        count=1,
        batch_position=DebateBatchPosition(debate_index=2, total_debates=4),
    )

    assert len(hyps) == 1
    assert hyps[0].debate_id == 2
    assert transcripts[0]["debate_id"] == 2
    assert "Parallel debate 3 of 4" in final_prompts[0]
    expected = debate._debate_diversity_instruction(2, 4)
    assert expected is not None
    assert expected in final_prompts[0]

    final_prompts.clear()
    await generate_with_debate(
        make_state(),
        count=1,
        batch_position=DebateBatchPosition(debate_index=0, total_debates=1),
    )
    assert "Parallel debate" not in final_prompts[0]


async def test_debate_prompts_carry_starting_hypotheses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []

    async def fake_call_llm(**kwargs: Any) -> str:
        prompts.append(str(kwargs["prompt"]))
        return "a debate turn argument"

    async def fake_call_llm_json(**kwargs: Any) -> dict[str, Any]:
        prompts.append(str(kwargs["prompt"]))
        return make_generation_response("refined seed hypothesis")

    monkeypatch.setattr(debate, "call_llm", fake_call_llm)
    monkeypatch.setattr(debate, "call_llm_json", fake_call_llm_json)

    state = make_state(
        starting_hypotheses=["seed idea: blocking receptor R halts fibrosis"],
        articles_with_reasoning="Literature synthesis on receptor R.",
    )
    # Explicit literature context selects the template with starting-hypothesis
    # slots.
    await generate_with_debate(
        state,
        count=1,
        articles_with_reasoning=state["articles_with_reasoning"],
    )

    assert len(prompts) == _DEBATE_MAX_DISCUSSION_TURNS + 1
    for prompt in prompts:
        assert "seed idea: blocking receptor R halts fibrosis" in prompt
        assert "{{MISSING" not in prompt


async def test_empty_final_response_raises_generation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    async def fake_call_llm(**_: Any) -> str:
        return "turn"

    async def fake_call_llm_json(**_: Any) -> dict[str, Any]:
        return {"hypotheses": []}

    monkeypatch.setattr(debate, "call_llm", fake_call_llm)
    monkeypatch.setattr(debate, "call_llm_json", fake_call_llm_json)
    with pytest.raises(GenerationError):
        await generate_with_debate(make_state(), count=1)


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


async def test_tree_bounds_are_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_sequence(
        monkeypatch,
        [
            _tree_response(ASSUMPTION_TREE_MAX_TOP + 4),
            _sub_response(
                *[
                    (i, [f"sub {i}-{j}" for j in range(6)])
                    for i in range(ASSUMPTION_TREE_MAX_TOP + 4)
                ]
            ),
            _final_response(),
        ],
    )
    await generate_with_assumptions(make_state(), 1)

    final_prompt = calls[-1]["prompt"]
    assert f"assumption {ASSUMPTION_TREE_MAX_TOP - 1}" in final_prompt
    assert f"assumption {ASSUMPTION_TREE_MAX_TOP} " not in final_prompt
    sub_prompt = calls[1]["prompt"]
    assert "parent_index" in sub_prompt
    listed_parents = re.findall(r"(?m)^\d+\. assumption \d+", sub_prompt)
    assert len(listed_parents) == ASSUMPTION_TREE_MAX_LOAD_BEARING
    for parent_index in range(ASSUMPTION_TREE_MAX_LOAD_BEARING):
        kept = re.findall(rf"(?m)^\s+{parent_index}\.\d+ sub ", final_prompt)
        assert len(kept) == ASSUMPTION_TREE_MAX_SUB_PER_PARENT


async def test_out_of_range_parent_index_wraps_deterministically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The offline integer filler emits a constant index, which must remain a
    satisfiable parent."""
    calls = _install_sequence(
        monkeypatch,
        [
            _tree_response(1),
            _sub_response((4, ["wrapped sub"])),
            _final_response(),
        ],
    )
    await generate_with_assumptions(make_state(), 1)

    assert "wrapped sub" in calls[-1]["prompt"]


async def test_literature_context_grounds_every_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from co_scientist.agents.generation.citations import ReferenceIndex

    calls = _install_sequence(
        monkeypatch,
        [
            _tree_response(1),
            _sub_response((0, ["sub"])),
            make_generation_response(
                "grounded", literature_grounding="Prior work [C1]."
            ),
        ],
    )
    reference_index = ReferenceIndex(
        text="[C1] Author et al. (2020). A relevant paper.",
        sources={"C1": {"title": "A relevant paper", "type": "paper"}},
    )
    result, _ = await generate_with_assumptions(
        make_state(),
        1,
        articles_with_reasoning="synthesis text",
        reference_index=reference_index,
    )
    for call in calls:
        assert "[C1]" in call["prompt"]
    assert result[0].generation_method is GenerationMethod.ASSUMPTIONS
    assert result[0].citation_map["C1"]["title"] == "A relevant paper"


async def test_expansion_and_wrong_assumption_context_reach_the_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_sequence(
        monkeypatch,
        [
            _tree_response(1),
            _sub_response((0, ["sub"])),
            _final_response(),
        ],
    )
    weakened = make_hypothesis(
        text="a prior hypothesis",
        deep_verification_probes=[
            {
                "question": "Does efflux carry the drug?",
                "answer": "No evidence of efflux.",
                "reasoning": "r",
                "assumption_is_fundamental": False,
                "search_query": "efflux drug",
            }
        ],
        deep_verification_verdict="weakened",
    )
    state = make_state(current_iteration=1, hypotheses=[weakened])
    await generate_with_assumptions(state, 1)

    tree_prompt = calls[0]["prompt"]
    final_prompt = calls[-1]["prompt"]
    for prompt in (tree_prompt, final_prompt):
        assert "Research Expansion Cycle" in prompt
        assert "Verified Incorrect" in prompt
        assert "Does efflux carry the drug?" in prompt
        assert "a prior hypothesis" in prompt


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


@pytest.mark.parametrize(
    ("verdict", "flag", "fundamental", "included"),
    [
        ("weakened", None, False, True),
        ("holds", None, False, False),
        ("undermined", None, False, False),
        ("holds", False, False, True),
        ("weakened", True, False, False),
        ("weakened", None, True, False),
    ],
)
async def test_generation_reworks_only_falsified_nonfundamental_assumptions(
    monkeypatch: pytest.MonkeyPatch,
    verdict: str,
    flag: bool | None,
    fundamental: bool,
    included: bool,
) -> None:
    _stub_debate_llm(monkeypatch, "debated")
    calls = _install_sequence(
        monkeypatch, [{"assumptions": []}, _final_response()]
    )
    probe = _probe(question="Does efflux matter?", fundamental=fundamental)
    if flag is not None:
        probe["assumption_holds"] = flag
    hyp = make_hypothesis(
        deep_verification_probes=[probe], deep_verification_verdict=verdict
    )
    await generate_node(
        make_state(
            hypotheses=[hyp],
            initial_hypotheses_count=4,
            supervisor_guidance={"key_areas": ["mechanism"]},
        )
    )
    final = calls[-1]["prompt"]
    assert ("Verified Incorrect" in final) == included
    assert ("Does efflux matter?" in final) == included
    if included:
        assert "Evidence shows X does not hold." in final
        assert "avoid" in final.lower()
        assert "rework" in final.lower()


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


@pytest.mark.parametrize(
    ("tree", "level_calls"),
    [
        (_tree_response(2, load_bearing_from=99), 2),
        ({"assumptions": []}, 2),
    ],
    ids=["no_load_bearing", "empty_tree"],
)
async def test_tree_without_load_bearing_parents_skips_the_sub_level(
    monkeypatch: pytest.MonkeyPatch, tree: dict[str, Any], level_calls: int
) -> None:
    calls = _install_sequence(monkeypatch, [tree, _final_response()])
    result, llm_calls = await generate_with_assumptions(make_state(), 1)
    assert [c["options"].prompt_name for c in calls] == [
        "generation_assumption_tree",
        "generation_assumptions",
    ]
    assert len(result) == 1
    assert llm_calls == level_calls
    assert ("Assumption Tree" in calls[-1]["prompt"]) is bool(
        tree["assumptions"]
    )
