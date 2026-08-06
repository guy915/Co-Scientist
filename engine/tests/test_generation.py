"""Tests for debate-based generation and the generate_node wrapper.

``generate_with_debate`` runs multi-turn debates (each non-final turn calls
``call_llm`` and the final turn calls ``call_llm_json``) to produce one
Hypothesis per debate; these tests stub both LLM calls. ``generate_node`` is a
thin wrapper that delegates to the generation coordinator and attaches metrics.
"""

from typing import Any

import pytest

from co_scientist.agents.generation import debate
from co_scientist.agents.generation import generate as generate_mod
from co_scientist.agents.generation.debate import (
    DebateBatchPosition,
    _debate_converged,
    generate_with_debate,
)
from co_scientist.agents.generation.generate import generate_node
from co_scientist.exceptions import GenerationError
from co_scientist.models import GenerationMethod
from co_scientist.prompts.generation_debate import (
    _DEBATE_MAX_DISCUSSION_TURNS,
)
from tests._state import make_hypothesis, make_state


def _stub_debate_llm(monkeypatch: pytest.MonkeyPatch, final_text: str) -> None:
    """Stub debate turns (call_llm) and the final hypothesis (call_llm_json)."""

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
    """Requesting zero debates short-circuits without any LLM call."""
    hyps, transcripts = await generate_with_debate(make_state(), count=0)
    assert hyps == []
    assert transcripts == []


def _stub_debate_llm_counting(
    monkeypatch: pytest.MonkeyPatch, turn_texts: list[str]
) -> tuple[list[str], list[int]]:
    """Stub debate turns with scripted text, counting calls of each kind."""
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
    """A turn writing the HYPOTHESIS sentinel skips to the final turn.

    The prompt's termination condition asks the panel to conclude with
    "HYPOTHESIS" in capitals; honouring it retires the remaining free-form
    turns of the budget, which are serial LLM calls.
    """
    free_form, finals = _stub_debate_llm_counting(
        monkeypatch,
        ["still arguing", "HYPOTHESIS: the panel agrees", "unreached"],
    )

    hyps, _ = await generate_with_debate(make_state(), count=1)

    assert len(hyps) == 1
    assert hyps[0].text == "converged idea"
    # Two free-form turns, then the structured turn - not the full budget.
    assert len(free_form) == 2
    assert len(finals) == 1


async def test_lowercase_hypothesis_prose_does_not_end_the_debate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ordinary talk about "the hypothesis" is not a termination signal."""
    turns = ["the hypothesis is weak"] * _DEBATE_MAX_DISCUSSION_TURNS
    free_form, finals = _stub_debate_llm_counting(monkeypatch, turns)

    await generate_with_debate(make_state(), count=1)

    assert len(free_form) == _DEBATE_MAX_DISCUSSION_TURNS
    assert len(finals) == 1


async def test_a_debate_that_never_converges_stops_at_the_envelope_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A panel that never agrees spends the whole envelope, then stops.

    The paper bounds a debate at 10 conversational turns (SSR note 9.1);
    the loop must enforce that ceiling itself -- no token, no extra turns
    (findings E13/E16).
    """
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
    """Case/wording variants of the consensus marker are all honoured.

    The prompt instructs the panel to write "HYPOTHESIS" in all capitals;
    panels slip on the casing or decorate the marker, so the parse accepts
    the common variants rather than paying the whole envelope for each.
    """
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
    """Discussion content must not be mistaken for the consensus marker.

    Enumerating candidate hypotheses and quoting the instruction are both
    ordinary turn content; only a real conclusion marker stops the debate.
    """
    assert not _debate_converged(turn_text)


async def test_debate_produces_one_hypothesis_per_debate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each debate yields a DEBATE-method hypothesis with a unique debate id."""
    _stub_debate_llm(monkeypatch, "tumor suppressor X gates the pathway")
    hyps, transcripts = await generate_with_debate(make_state(), count=2)
    assert len(hyps) == 2
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
    """Parallel debates are seeded with distinct angles to avoid collapse."""
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

    hyps, _ = await generate_with_debate(make_state(), count=3)

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
    """A per-debate durable task angles like the batch member it is (E14).

    The durable path runs each debate as its own task; passing the task's
    index and the batch total must reproduce the diversity angle the same
    debate would have received inside one in-process batch of that size.
    """
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

    hyps, transcripts = await generate_with_debate(
        make_state(),
        count=1,
        batch_position=DebateBatchPosition(debate_index=2, total_debates=4),
    )

    assert len(hyps) == 1
    assert hyps[0].debate_id == 2
    assert transcripts[0]["debate_id"] == 2
    assert "Parallel debate 3 of 4" in final_prompts[0]
    # The angle is exactly the one a four-debate in-process batch would
    # have assigned to its third member.
    expected = debate._debate_diversity_instruction(2, 4)
    assert expected is not None
    assert expected in final_prompts[0]


async def test_a_lone_debate_still_gets_no_angle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without siblings there is nothing to diverge from, angle-free."""
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
    """State starting hypotheses reach every turn's prompt (finding E2).

    The grounded-debate template declares {{user_hypotheses}} and
    {{instructions}} slots; the node must thread the state's
    starting_hypotheses into the request so no turn renders a
    {{MISSING:...}} sentinel or silently drops the seeds.
    """
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
    # The coordinator passes articles_with_reasoning explicitly; doing so
    # here selects the literature-aware debate template that declares the
    # {{user_hypotheses}} slot.
    await generate_with_debate(
        state,
        count=1,
        articles_with_reasoning=state["articles_with_reasoning"],
    )

    # The full discussion envelope (no scripted convergence) plus the
    # final structured turn; every one of them carries the seeds.
    assert len(prompts) == _DEBATE_MAX_DISCUSSION_TURNS + 1
    for prompt in prompts:
        assert "seed idea: blocking receptor R halts fibrosis" in prompt
        assert "{{MISSING" not in prompt


async def test_empty_final_response_raises_generation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A final turn that returns no hypotheses surfaces a GenerationError."""

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
    """generate_node merges coordinator output with hypothesis-count metric."""

    async def fake_coordinator(_: Any) -> dict[str, Any]:
        # Mirrors the real coordinator's contract, which always includes
        # hypothesis_count alongside the hypotheses.
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
