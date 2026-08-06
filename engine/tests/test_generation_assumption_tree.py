"""Tests for the iterative assumption/sub-assumption tree (audit E12).

The technique makes up to three bounded structured calls -- level-0
assumptions, level-1 sub-assumptions for the load-bearing parents, then
hypothesis generation from the tree -- instead of one combined call.
These tests pin the tree shape and bounds, the positional (non-echoing)
sub-assumption mapping, the graceful no-tree fallback, the prompt
threading of literature/expansion/K9 context, and offline determinism.
"""

import re
from typing import Any

import pytest

from co_scientist.agents.generation import assumptions as assumptions_mod
from co_scientist.agents.generation.assumptions import (
    ASSUMPTION_TREE_MAX_LOAD_BEARING,
    ASSUMPTION_TREE_MAX_SUB_PER_PARENT,
    ASSUMPTION_TREE_MAX_TOP,
    generate_with_assumptions,
)
from co_scientist.models import GenerationMethod
from tests._state import make_hypothesis, make_state


def _tree_response(
    count: int = 2, load_bearing_from: int = 0
) -> dict[str, Any]:
    """A level-0 payload of ``count`` assumptions, some load-bearing."""
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
    """A level-1 payload mapping parents (by index) to sub-assumptions."""
    return {
        "parents": [
            {"parent_index": index, "sub_assumptions": subs}
            for index, subs in entries
        ]
    }


def _final_response(text: str = "a challenging hypothesis") -> dict[str, Any]:
    """A final GENERATION_SCHEMA payload with one hypothesis."""
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
    """Patch call_llm_json to serve ``responses`` in order, recording calls.

    Returns:
        The list each call appends its kwargs to (the prompt arrives as
        the first positional argument, recorded under "prompt").
    """
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
    """Level 0, level 1, and the final generation call all run in order."""
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
    """The final call is prompted with the tree the earlier levels built."""
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
    # Level-0 assumptions stay positional in the rendered tree too.
    assert "assumption 1" in final_prompt


async def test_sub_call_lists_parents_positionally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sub-level prompt numbers parents; only load-bearing ones expand."""
    calls = _install_sequence(
        monkeypatch,
        [
            # Only the second assumption is load-bearing.
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
    """Oversized model output is capped at every level of the tree."""
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
    # Level 0 capped: assumption MAX_TOP-1 exists, MAX_TOP never entered.
    assert f"assumption {ASSUMPTION_TREE_MAX_TOP - 1}" in final_prompt
    assert f"assumption {ASSUMPTION_TREE_MAX_TOP} " not in final_prompt
    # Level 1 capped: only MAX_LOAD_BEARING parents were expanded.
    sub_prompt = calls[1]["prompt"]
    listed_parents = re.findall(r"(?m)^\d+\. assumption \d+", sub_prompt)
    assert len(listed_parents) == ASSUMPTION_TREE_MAX_LOAD_BEARING
    # Each expanded parent keeps at most MAX_SUB_PER_PARENT sub-assumptions
    # (six were offered); subs render as "   <parent>.<n> <text>".
    for parent_index in range(ASSUMPTION_TREE_MAX_LOAD_BEARING):
        kept = re.findall(rf"(?m)^\s+{parent_index}\.\d+ sub ", final_prompt)
        assert len(kept) == ASSUMPTION_TREE_MAX_SUB_PER_PARENT


async def test_out_of_range_parent_index_wraps_deterministically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fixed out-of-range index still yields a satisfiable tree.

    The deterministic offline filler fills integers with a constant
    (4), so the parser must map a stray index back into the parent list
    (modulo) rather than discarding the whole level.
    """
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
    """Without load-bearing parents there is no sub call, only the final."""
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
    """An empty level-0 answer degrades to the plain final call, no failure."""
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
    """Every level opts out of the cache, like the rest of generation."""
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
    """A real reference index reaches the tree, sub, and final prompts."""
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
    """E11b/K9 sections render into the tree level and the final call."""
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


async def test_assumptions_slice_runs_the_tree_in_the_real_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A count>=4 run routes its assumptions slice through the real graph.

    Mirrors the durable path's entry: the coordinator allocates one
    hypothesis to the assumptions strategy, which must build the tree
    (two extra schema calls on the fake) and still deliver its count.
    """
    from co_scientist.generator import GeneratorOptions, HypothesisGenerator
    from tests._llm_fake import install_fake_llm

    install_fake_llm(monkeypatch)
    gen = HypothesisGenerator(
        model_name="fake/model",
        max_iterations=0,
        initial_hypotheses_count=4,
        evolution_max_count=2,
        options=GeneratorOptions(tournament_pairs=2, enable_cache=False),
    )
    initial_state = await gen._prepare_generation(
        "Explain how protein X folds",
        opts={"enable_literature_review_node": False},
    )
    assert gen._graph is not None
    final_state = await gen._graph.ainvoke(
        initial_state, config={"recursion_limit": 100}
    )

    parents = [h for h in final_state["hypotheses"] if h.generation == 0]
    assert len(parents) == 4
    methods = {h.generation_method for h in parents}
    assert GenerationMethod.ASSUMPTIONS in methods


async def test_offline_tree_is_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The offline backend produces the same tree run after run.

    Exercises the real offline router (schema-filling included), so the
    new ASSUMPTION_TREE/ASSUMPTION_SUB schemas must stay satisfiable by
    the canned filler -- one assumption, one parent, wrapped indices.
    """
    from co_scientist import offline_llm
    from tests._offline_helpers import isolate_offline_router

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
