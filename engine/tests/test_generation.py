from __future__ import annotations

import re
from typing import Any

import pytest

from co_scientist.agents.generation import assumptions as assumptions_mod
from co_scientist.agents.generation import debate
from co_scientist.agents.generation import generate as generate_mod
from co_scientist.agents.generation.assumptions import (
    ASSUMPTION_TREE_MAX_LOAD_BEARING,
    ASSUMPTION_TREE_MAX_SUB_PER_PARENT,
    ASSUMPTION_TREE_MAX_TOP,
    MAX_FALSIFIED_ASSUMPTION_LINES,
    build_falsified_assumptions_section,
    falsified_nonfundamental_assumptions,
    generate_with_assumptions,
)
from co_scientist.agents.generation.debate import (
    DebateBatchPosition,
    _debate_converged,
    generate_with_debate,
)
from co_scientist.agents.generation.generate import generate_node
from co_scientist.exceptions import GenerationError
from co_scientist.models import GenerationMethod
from co_scientist.prompts.generation_debate import _DEBATE_MAX_DISCUSSION_TURNS
from co_scientist.prompts.loading import load_prompt_with_schema
from tests._state import make_hypothesis, make_state


def _stub_debate_llm(monkeypatch: pytest.MonkeyPatch, final_text: str) -> None:

    async def fake_call_llm(**_: Any) -> str:
        return "a debate turn argument"

    async def fake_call_llm_json(**_: Any) -> dict[str, Any]:
        return {
            "hypotheses": [
                {
                    "hypothesis": final_text,
                    "explanation": "because the mechanism fits",
                    "literature_grounding": None,
                    "experiment": "run the assay",
                }
            ]
        }

    monkeypatch.setattr(debate, "call_llm", fake_call_llm)
    monkeypatch.setattr(debate, "call_llm_json", fake_call_llm_json)


async def test_count_zero_returns_empty() -> None:
    hyps, transcripts, llm_calls = await generate_with_debate(
        make_state(), count=0
    )
    assert hyps == []
    assert transcripts == []
    assert llm_calls == 0


def _stub_debate_llm_counting(
    monkeypatch: pytest.MonkeyPatch, turn_texts: list[str]
) -> tuple[list[str], list[int]]:
    free_form: list[str] = []
    finals: list[int] = []

    async def fake_call_llm(**_: Any) -> str:
        text = turn_texts[len(free_form)]
        free_form.append(text)
        return text

    async def fake_call_llm_json(**_: Any) -> dict[str, Any]:
        finals.append(1)
        return {
            "hypotheses": [
                {
                    "hypothesis": "converged idea",
                    "explanation": "because the mechanism fits",
                    "literature_grounding": None,
                    "experiment": "run the assay",
                }
            ]
        }

    monkeypatch.setattr(debate, "call_llm", fake_call_llm)
    monkeypatch.setattr(debate, "call_llm_json", fake_call_llm_json)
    return free_form, finals


async def test_declared_convergence_ends_the_debate_early(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Free-form turns are serial provider calls; an explicit conclusion
    retires unused turns."""
    free_form, finals = _stub_debate_llm_counting(
        monkeypatch,
        ["still arguing", "HYPOTHESIS: the panel agrees", "unreached"],
    )

    hyps, _, llm_calls = await generate_with_debate(make_state(), count=1)

    assert len(hyps) == 1
    assert hyps[0].text == "converged idea"
    assert len(free_form) == 2
    assert len(finals) == 1
    assert llm_calls == 3


async def test_lowercase_hypothesis_prose_does_not_end_the_debate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    turns = ["the hypothesis is weak"] * _DEBATE_MAX_DISCUSSION_TURNS
    free_form, finals = _stub_debate_llm_counting(monkeypatch, turns)

    await generate_with_debate(make_state(), count=1)

    assert len(free_form) == _DEBATE_MAX_DISCUSSION_TURNS
    assert len(finals) == 1


async def test_a_debate_that_never_converges_stops_at_the_envelope_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    turns = ["the panel still disagrees"] * _DEBATE_MAX_DISCUSSION_TURNS
    free_form, finals = _stub_debate_llm_counting(monkeypatch, turns)

    await generate_with_debate(make_state(), count=1)

    assert len(free_form) == _DEBATE_MAX_DISCUSSION_TURNS == 10
    assert len(finals) == 1


@pytest.mark.parametrize(
    "turn_text",
    [
        "HYPOTHESIS: the panel agrees on this mechanism",
        "HYPOTHESIS. The panel agrees on this mechanism",
        "we conclude: HYPOTHESIS — partial inhibition of E",
        "Hypothesis: the panel agrees on this mechanism",
        "hypothesis:\nthe panel agrees on this mechanism",
        "**HYPOTHESIS**: the panel agrees on this mechanism",
        "- HYPOTHESIS: the panel agrees on this mechanism",
        "HYPOTHESIS\nthe panel agrees on this mechanism",
    ],
)
def test_convergence_token_variants_end_the_debate(turn_text: str) -> None:
    """Panels vary marker casing or decoration; strict spelling buys
    unnecessary debate turns."""
    assert _debate_converged(turn_text)


@pytest.mark.parametrize(
    "turn_text",
    [
        "the hypothesis is weak",
        "Hypothesis 1: a direct causal mechanism",
        "Hypothesis 2: an upstream regulator",
        "Hypotheses: three candidates remain",
        'we will write "HYPOTHESIS" once we agree',
        "The hypothesis states that E inhibits R",
    ],
)
def test_ordinary_hypothesis_prose_does_not_end_the_debate(
    turn_text: str,
) -> None:
    """Enumeration and quoted instructions are discussion, not conclusion
    markers."""
    assert not _debate_converged(turn_text)


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
        return {
            "hypotheses": [
                {
                    "hypothesis": f"hypothesis from debate {debate_number}",
                    "explanation": "because the mechanism fits",
                    "literature_grounding": None,
                    "experiment": "run the assay",
                }
            ]
        }

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
        return {
            "hypotheses": [
                {
                    "hypothesis": "the angled hypothesis",
                    "explanation": "because",
                    "literature_grounding": None,
                    "experiment": "run the assay",
                }
            ]
        }

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


async def test_a_lone_debate_still_gets_no_angle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final_prompts: list[str] = []

    async def fake_call_llm(**_: Any) -> str:
        return "a debate turn argument"

    async def fake_call_llm_json(**kwargs: Any) -> dict[str, Any]:
        final_prompts.append(str(kwargs["prompt"]))
        return {
            "hypotheses": [
                {
                    "hypothesis": "the lone hypothesis",
                    "explanation": "because",
                    "literature_grounding": None,
                    "experiment": "run the assay",
                }
            ]
        }

    monkeypatch.setattr(debate, "call_llm", fake_call_llm)
    monkeypatch.setattr(debate, "call_llm_json", fake_call_llm_json)

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
        return {
            "hypotheses": [
                {
                    "hypothesis": "refined seed hypothesis",
                    "explanation": "because the mechanism fits",
                    "literature_grounding": None,
                    "experiment": "run the assay",
                }
            ]
        }

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


async def test_generate_node_attaches_metrics_and_passes_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    async def fake_coordinator(_: Any) -> dict[str, Any]:
        return {
            "hypotheses": [
                make_hypothesis(text="h1"),
                make_hypothesis(text="h2"),
            ],
            "hypothesis_count": 2,
            "message": "generated 2 hypotheses",
        }

    monkeypatch.setattr(generate_mod, "generate_hypotheses", fake_coordinator)
    result = await generate_node(make_state())
    assert len(result["hypotheses"]) == 2
    assert result["metrics"].hypothesis_count == 2


def _one_hypothesis_payload() -> dict[str, Any]:
    return {
        "hypotheses": [
            {
                "hypothesis": "A testable claim",
                "explanation": "why",
                "literature_grounding": "This builds on prior work [C1].",
                "experiment": "how",
            }
        ]
    }


def _c1_reference_index() -> Any:
    from co_scientist.agents.generation.citations import ReferenceIndex

    return ReferenceIndex(
        text="[C1] Author et al. (2020). A relevant paper.",
        sources={"C1": {"title": "A relevant paper", "type": "paper"}},
    )


def test_assumptions_technique_produces_hypotheses() -> None:
    _, schema = load_prompt_with_schema(
        "generation_assumptions",
        {
            "research_goal": "A goal",
            "domain_context": "",
            "meta_review_context": "",
            "num_hypotheses": 2,
        },
    )
    assert schema is not None
    assert "hypotheses" in schema["schema"]["properties"]


async def test_assumptions_grounds_in_supplied_literature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from co_scientist.agents.generation import assumptions as assumptions_mod

    captured: dict[str, str] = {}

    async def _fake_call_llm_json(prompt: str, *_a: Any, **_k: Any) -> Any:
        captured["prompt"] = prompt
        return _one_hypothesis_payload()

    monkeypatch.setattr(assumptions_mod, "call_llm_json", _fake_call_llm_json)

    reference_index = _c1_reference_index()
    state = make_state(
        research_goal="A goal",
        model_name="fake-model",
    )
    result, _ = await assumptions_mod.generate_with_assumptions(
        state,
        1,
        articles_with_reasoning="literature synthesis text",
        reference_index=reference_index,
    )

    assert "[C1]" in captured["prompt"]
    assert result[0].citation_map
    assert "C1" in result[0].citation_map


async def test_assumptions_live_prompt_hedges_and_threads_constraints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from co_scientist.agents.generation import assumptions as assumptions_mod

    captured: dict[str, str] = {}

    async def _fake_call_llm_json(prompt: str, *_a: Any, **_k: Any) -> Any:
        captured["prompt"] = prompt
        return _one_hypothesis_payload()

    monkeypatch.setattr(assumptions_mod, "call_llm_json", _fake_call_llm_json)

    await assumptions_mod.generate_with_assumptions(
        make_state(
            research_goal="A goal",
            model_name="fake-model",
            lab_constraints=["Zebrafish facility only"],
        ),
        1,
    )

    assert "Novelty claims must be hedged" in captured["prompt"]
    assert "## Scientist's Lab Constraints" in captured["prompt"]
    assert "Zebrafish facility only" in captured["prompt"]


async def test_assumptions_generation_is_never_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Identical generation prompts rely on sampling; cache replay collapses
    the pool through dedup."""
    from co_scientist.agents.generation import assumptions as assumptions_mod

    captured: dict[str, Any] = {}

    async def _fake_call_llm_json(_prompt: str, *_a: Any, **kwargs: Any) -> Any:
        captured["options"] = kwargs["options"]
        return _one_hypothesis_payload()

    monkeypatch.setattr(assumptions_mod, "call_llm_json", _fake_call_llm_json)

    await assumptions_mod.generate_with_assumptions(
        make_state(research_goal="A goal", model_name="fake-model"), 1
    )

    assert captured["options"].use_cache is False


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
    return {
        "hypotheses": [
            {
                "hypothesis": text,
                "explanation": "why",
                "literature_grounding": "grounding",
                "experiment": "how",
            }
        ]
    }


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


async def test_tree_section_reaches_the_final_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_sequence(
        monkeypatch,
        [
            _tree_response(2),
            _sub_response((0, ["sub A"])),
            _final_response(),
        ],
    )
    await generate_with_assumptions(make_state(), 1)

    final_prompt = calls[-1]["prompt"]
    assert "assumption 0" in final_prompt
    assert "(load-bearing)" in final_prompt
    assert "sub A" in final_prompt
    assert "assumption 1" in final_prompt


async def test_sub_call_lists_parents_positionally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_sequence(
        monkeypatch,
        [
            _tree_response(2, load_bearing_from=1),
            _sub_response((0, ["sub of the load-bearing parent"])),
            _final_response(),
        ],
    )
    await generate_with_assumptions(make_state(), 1)

    sub_prompt = calls[1]["prompt"]
    assert "0. assumption 1" in sub_prompt
    assert "assumption 0" not in sub_prompt
    assert "parent_index" in sub_prompt


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


async def test_no_load_bearing_assumptions_skips_level_1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_sequence(
        monkeypatch,
        [
            _tree_response(2, load_bearing_from=99),
            _final_response(),
        ],
    )
    result, llm_calls = await generate_with_assumptions(make_state(), 1)
    assert [c["options"].prompt_name for c in calls] == [
        "generation_assumption_tree",
        "generation_assumptions",
    ]
    assert len(result) == 1
    assert llm_calls == 2


async def test_empty_tree_degrades_to_single_final_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_sequence(
        monkeypatch,
        [{"assumptions": []}, _final_response()],
    )
    result, llm_calls = await generate_with_assumptions(make_state(), 1)
    assert len(result) == 1
    assert llm_calls == 2
    final_prompt = calls[-1]["prompt"]
    assert "Assumption Tree" not in final_prompt


async def test_tree_levels_are_never_cached(
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
    await generate_with_assumptions(make_state(), 1)
    assert all(call["options"].use_cache is False for call in calls)


async def test_literature_context_grounds_every_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from co_scientist.agents.generation.citations import ReferenceIndex

    calls = _install_sequence(
        monkeypatch,
        [
            _tree_response(1),
            _sub_response((0, ["sub"])),
            _final_response(),
        ],
    )
    reference_index = ReferenceIndex(
        text="[C1] Author et al. (2020). A relevant paper.",
        sources={"C1": {"title": "A relevant paper", "type": "paper"}},
    )
    await generate_with_assumptions(
        make_state(),
        1,
        articles_with_reasoning="synthesis text",
        reference_index=reference_index,
    )
    for call in calls:
        assert "[C1]" in call["prompt"]


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


async def test_offline_tree_is_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from co_scientist.offline import llm as offline_llm
    from tests._mcp import isolate_offline_router

    isolate_offline_router(monkeypatch)
    offline_llm.install_offline_router()

    state = make_state(
        research_goal="explain how protein X folds",
        model_name=offline_llm.DEFAULT_OFFLINE_MODEL,
    )
    first, _ = await generate_with_assumptions(state, 2)
    second, _ = await generate_with_assumptions(state, 2)

    assert first, "the offline tree must still produce hypotheses"
    assert [h.text for h in first] == [h.text for h in second]
    assert all(
        h.generation_method is GenerationMethod.ASSUMPTIONS for h in first
    )


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


def test_weakened_hypothesis_contributes_nonfundamental_probes() -> None:
    hyp = make_hypothesis(
        deep_verification_probes=[
            _probe(question="Is acrB essential here?"),
            _probe(question="Is the core mechanism sound?", fundamental=True),
        ],
        deep_verification_verdict="weakened",
    )
    lines = falsified_nonfundamental_assumptions([hyp])
    assert len(lines) == 1
    assert "Is acrB essential here?" in lines[0]
    assert "Evidence shows X does not hold." in lines[0]


def test_holds_verdict_contributes_nothing() -> None:
    hyp = make_hypothesis(
        deep_verification_probes=[_probe()],
        deep_verification_verdict="holds",
    )
    assert falsified_nonfundamental_assumptions([hyp]) == []


def test_undermined_verdict_contributes_nothing() -> None:
    hyp = make_hypothesis(
        deep_verification_probes=[_probe()],
        deep_verification_verdict="undermined",
    )
    assert falsified_nonfundamental_assumptions([hyp]) == []


def test_explicit_assumption_holds_false_is_admitted_alone() -> None:
    hyp = make_hypothesis(
        deep_verification_probes=[_probe(assumption_holds=False)],
        deep_verification_verdict="holds",
    )
    lines = falsified_nonfundamental_assumptions([hyp])
    assert len(lines) == 1


def test_explicit_assumption_holds_true_overrides_weakened() -> None:
    hyp = make_hypothesis(
        deep_verification_probes=[_probe(assumption_holds=True)],
        deep_verification_verdict="weakened",
    )
    assert falsified_nonfundamental_assumptions([hyp]) == []


def test_guidance_is_capped() -> None:
    probes = [_probe(question=f"Q{i}?") for i in range(10)]
    hyp = make_hypothesis(
        deep_verification_probes=probes,
        deep_verification_verdict="weakened",
    )
    lines = falsified_nonfundamental_assumptions([hyp])
    assert len(lines) == MAX_FALSIFIED_ASSUMPTION_LINES


def test_section_empty_until_something_is_falsified() -> None:
    assert build_falsified_assumptions_section(None) == ""
    assert build_falsified_assumptions_section([]) == ""
    clean = make_hypothesis(
        deep_verification_probes=[_probe()],
        deep_verification_verdict="holds",
    )
    assert build_falsified_assumptions_section([clean]) == ""


def test_section_carries_the_avoid_or_rework_instruction() -> None:
    hyp = make_hypothesis(
        deep_verification_probes=[_probe(question="Does efflux matter?")],
        deep_verification_verdict="weakened",
    )
    section = build_falsified_assumptions_section([hyp])
    assert "Verified Incorrect" in section
    assert "avoid" in section.lower()
    assert "rework" in section.lower()
    assert "Does efflux matter?" in section
