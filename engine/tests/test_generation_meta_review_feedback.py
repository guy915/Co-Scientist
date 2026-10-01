"""Regression: meta-review synthesis reaches a later generation cycle.

Fidelity audit I2: the paper's Co-Scientist feeds its meta-review synthesis
back into the next generation round, so later ideas are informed by which
areas earlier cycles already covered. In this codebase that feedback
channel is
``state["meta_review"]`` -- populated periodically (not per cycle, so no
extra LLM call is added), and already threaded into every generation
strategy's prompt via ``prompts._common._format_meta_review_context`` (see
``agents/generation/debate.py``, ``assumptions.py``,
``literature_tools/draft_prompt.py``). The terminal, once-only
``research_overview`` synthesis is a different, report-only artifact and
is not the mechanism the paper describes -- the periodic ``meta_review``
node is.

This proves the wiring is real, not merely present in code that never
executes, without coupling to the Orchestrator's own scheduling policy
(owned elsewhere and independently in flux): it sequences the same two
real node calls the durable task runtime chains on a real run --
``generate`` then, later, ``meta_review`` then ``generate`` again (see
``workflow_topology.WORKFLOW_ROUTES``, where meta-review hands over to
evolve, and the Orchestrator alternates back to "generate" -- see
``test_integration_pipeline.py``'s adaptive-orchestration test) -- and
diffs the rendered generation prompts from before and after a real
meta-review synthesis. Both cycles go through the actual coordinator and
the actual debate-generation prompt builder; the meta-review content
being diffed is itself LLM-produced through the fake completion boundary,
not a hand-typed fixture.
"""

from collections.abc import Coroutine
from typing import Any

import pytest

from co_scientist.agents.generation.generate import generate_node
from co_scientist.agents.meta_review.meta_review import meta_review_node
from co_scientist.llm.request.backend import active_backend
from co_scientist.offline.llm import _prompt_text
from tests._llm_fake import install_fake_backend, install_fake_llm
from tests._state import make_hypothesis, make_review, make_state

# Both debate-based and assumptions-based generation's final structured-
# output turn render through GENERATION_SCHEMA (schemas/generation.py),
# whose "name" field is "hypothesis_generation" -- see
# schemas/registry.py's _PROMPT_SCHEMA_MAP ("generation_after_debate",
# "generation_assumptions" both map to it).
_GENERATION_SCHEMA_NAME = "hypothesis_generation"

_RESEARCH_GOAL = "Explain how protein X folds"
_SUPERVISOR_GUIDANCE = {"key_areas": ["protein folding"]}


async def _capture_prompts(
    monkeypatch: pytest.MonkeyPatch, coro: Coroutine[Any, Any, dict[str, Any]]
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """Runs one node coroutine, recording each call's schema name and prompt.

    Wraps the fake backend already installed by ``install_fake_llm`` rather
    than replacing it, so the call still gets a deterministic, schema-true
    fake response; this only observes what was actually sent.

    Returns:
        Tuple of (the node's result dict, ordered (schema_name, prompt)
        pairs for every completion the node made).
    """
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
    """Filter captured calls down to generation-schema prompts, in order."""
    return [prompt for name, prompt in calls if name == _GENERATION_SCHEMA_NAME]


async def test_second_generation_cycle_carries_meta_review_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A generation cycle run after a real meta-review synthesis carries it.

    Cycle 1 runs ``generate_node`` on fresh state (no meta-review yet). A
    real ``meta_review_node`` call then synthesizes ``state["meta_review"]``
    from reviewed hypotheses through the fake LLM boundary. Cycle 2 runs
    ``generate_node`` again with that meta-review merged into state, as it
    would be on a real run's later cycle. The exact leaf value the
    meta-review call produced for ``emerging_themes`` must show up verbatim
    in cycle 2's generation prompt, and in none of cycle 1's.
    """
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
