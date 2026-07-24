"""Tests for the assumptions-identification generation technique (SSR §4).

Covers the ``generation_assumptions`` prompt/schema shape and the live
``generate_with_assumptions`` grounding path (E07): with a reference index
supplied, the built prompt carries the ``[C*]`` citation list and the
resulting hypothesis resolves its citation keys against the sources.
"""

from typing import Any

import pytest

from co_scientist.prompts.loading import load_prompt_with_schema
from tests._state import make_state


def _one_hypothesis_payload() -> dict[str, Any]:
    """The stubbed LLM response: one grounded hypothesis citing ``[C1]``."""
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
    """A reference index whose sole source is keyed ``C1``."""
    from co_scientist.agents.generation.citations import ReferenceIndex

    return ReferenceIndex(
        text="[C1] Author et al. (2020). A relevant paper.",
        sources={"C1": {"title": "A relevant paper", "type": "paper"}},
    )


def test_assumptions_technique_produces_hypotheses() -> None:
    """The assumptions technique emits hypotheses directly."""
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
    """Assumptions ingests literature context and resolves its citations (E07).

    When a reference index is supplied (literature-available run), the built
    prompt must carry the ``[C*]`` Citation Reference List so the technique can
    ground claims in real sources, and the resulting hypothesis's citation keys
    must resolve against those sources (previously the technique hardcoded an
    empty ``domain_context`` and an empty source map, so it could never ground).
    """
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
    result = await assumptions_mod.generate_with_assumptions(
        state,
        1,
        articles_with_reasoning="literature synthesis text",
        reference_index=reference_index,
    )

    # The [C*] citation list reaches the assumptions prompt.
    assert "[C1]" in captured["prompt"]
    # The generated hypothesis's citation key resolves against the sources.
    assert result[0].citation_map
    assert "C1" in result[0].citation_map


async def test_assumptions_generation_is_never_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Independent generation tasks must not be served one shared answer.

    Generation fans out one durable task per hypothesis, so several tasks
    issue this call with an identical prompt and rely on sampling to
    explore different ideas. A cache hit would hand them all the same
    hypothesis, which the state reducer then dedupes on append -- the run
    commits one hypothesis where the tier asked for several, and nothing
    fails to reveal it.
    """
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
