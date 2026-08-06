"""Regression tests: meta-review critique reaches the remaining surfaces.

Extends ``test_meta_review_prompt_threading`` to the four surfaces audit
E7 found the critique absent from: Proximity, Literature Review (query
formulation and source synthesis), the Safety screen, and the
observation-review node path. Each renders the critique when a
meta-review exists and an explicit empty state -- never a
``{{MISSING:...}}`` sentinel -- when one does not yet exist
(iteration 1).
"""

from typing import Any

import pytest

from co_scientist.agents.proximity import proximity, proximity_node
from co_scientist.agents.reflection import reflection
from co_scientist.agents.reflection.reflection import reflection_node
from co_scientist.agents.safety.safety_screen import safety_screen_node
from co_scientist.prompts import (
    get_literature_review_query_generation_prompt,
    get_literature_review_query_generation_pubmed_prompt,
    get_literature_review_synthesis_prompt,
)
from tests._llm_fake import stub_call_llm_json
from tests._state import make_hypothesis, make_state

# Distinctive markers unlikely to appear in a template by accident.
_STRENGTH = "UNIQUEMARKER-strength-mechanistic-clarity"
_WEAKNESS = "UNIQUEMARKER-weakness-unvalidated-target"
_RECOMMENDATION = "UNIQUEMARKER-recommendation-search-missing-evidence"

_META_REVIEW = {
    "common_strengths": [_STRENGTH],
    "common_weaknesses": [_WEAKNESS],
    "strategic_recommendations": [_RECOMMENDATION],
}

_ARTICLES = "Article 1: observation A supports pathway X."


def _assert_critique_present(prompt: str) -> None:
    """Assert the meta-review context section and its critique render."""
    assert "Meta-Review Context" in prompt
    assert _STRENGTH in prompt
    assert _WEAKNESS in prompt
    assert _RECOMMENDATION in prompt


def _assert_empty_state(prompt: str) -> None:
    """Assert no critique section and no unresolved placeholder."""
    assert "Meta-Review Context" not in prompt
    assert "{{MISSING" not in prompt


# --- Proximity ---------------------------------------------------------


def _stub_proximity_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, Any]]:
    """Patch proximity's call_llm_json, capturing each call's kwargs."""
    calls: list[dict[str, Any]] = []

    async def fake(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        # Empty clusters: the node skips deduplication for this pass,
        # which is fine -- only the rendered prompt matters here.
        return {"similarity_clusters": []}

    monkeypatch.setattr(proximity, "call_llm_json", fake)
    return calls


@pytest.mark.asyncio()
async def test_proximity_prompt_includes_meta_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The similarity judgment sees the meta-review's direction."""
    calls = _stub_proximity_llm(monkeypatch)
    state = make_state(
        hypotheses=[
            make_hypothesis(text="Inhibiting X reduces Y."),
            make_hypothesis(text="Blocking Z helps."),
        ],
        meta_review=_META_REVIEW,
    )

    await proximity_node(state)

    assert calls, "the proximity LLM call never ran"
    _assert_critique_present(calls[0]["prompt"])


@pytest.mark.asyncio()
async def test_proximity_prompt_empty_state_without_meta_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Iteration-1 proximity prompts carry no critique section."""
    calls = _stub_proximity_llm(monkeypatch)
    state = make_state(
        hypotheses=[
            make_hypothesis(text="Inhibiting X reduces Y."),
            make_hypothesis(text="Blocking Z helps."),
        ]
    )

    await proximity_node(state)

    assert calls, "the proximity LLM call never ran"
    _assert_empty_state(calls[0]["prompt"])


# --- Literature review: query formulation ------------------------------


def test_query_generation_prompt_includes_meta_review() -> None:
    """Query formulation searches what the critique says is missing."""
    prompt = get_literature_review_query_generation_prompt(
        "Reverse liver fibrosis", meta_review=_META_REVIEW
    )
    _assert_critique_present(prompt)


def test_query_generation_prompt_empty_state() -> None:
    """Iteration-1 query prompts carry no critique section."""
    prompt = get_literature_review_query_generation_prompt(
        "Reverse liver fibrosis"
    )
    _assert_empty_state(prompt)


def test_pubmed_query_generation_prompt_includes_meta_review() -> None:
    """The PubMed query variant carries the critique too."""
    prompt = get_literature_review_query_generation_pubmed_prompt(
        "Reverse liver fibrosis", meta_review=_META_REVIEW
    )
    _assert_critique_present(prompt)


# --- Literature review: synthesis --------------------------------------


def test_synthesis_prompt_includes_meta_review() -> None:
    """Source analysis weighs the critique's gaps and weaknesses."""
    prompt = get_literature_review_synthesis_prompt(
        "Reverse liver fibrosis", [], meta_review=_META_REVIEW
    )
    _assert_critique_present(prompt)


def test_synthesis_prompt_empty_state() -> None:
    """Iteration-1 synthesis prompts carry no critique section."""
    prompt = get_literature_review_synthesis_prompt(
        "Reverse liver fibrosis", []
    )
    _assert_empty_state(prompt)


# --- Safety screen ------------------------------------------------------


@pytest.mark.asyncio()
async def test_safety_decisions_carry_meta_review_context() -> None:
    """Blocked/held decisions record the critique as adjudication context."""
    unsafe = make_hypothesis(
        "Weaponize engineered pathogens for maximum spread", id="bad-1"
    )
    state = make_state(hypotheses=[unsafe], meta_review=_META_REVIEW)
    result = await safety_screen_node(state)

    decision = result["safety_decisions"][0]
    assert decision["outcome"] == "prohibited"
    _assert_critique_present(decision["meta_review_context"])


@pytest.mark.asyncio()
async def test_safety_decisions_empty_state_without_meta_review() -> None:
    """Iteration-1 decisions record no critique context at all."""
    unsafe = make_hypothesis(
        "Weaponize engineered pathogens for maximum spread", id="bad-1"
    )
    state = make_state(hypotheses=[unsafe])
    result = await safety_screen_node(state)

    decision = result["safety_decisions"][0]
    assert decision["outcome"] == "prohibited"
    assert "meta_review_context" not in decision


def _policy_pool() -> list[Any]:
    """A fresh safe/unsafe hypothesis pair for one screening pass.

    Fresh objects per pass: a hypothesis screened once carries its
    safety_status, and the screen skips hypotheses it already stamped.
    """
    return [
        make_hypothesis(
            "CRISPR-Cas9 targeting of BRCA1 mutations in breast cancer",
            id="safe-1",
        ),
        make_hypothesis(
            "Weaponize engineered pathogens for maximum spread", id="bad-1"
        ),
    ]


@pytest.mark.asyncio()
async def test_meta_review_context_never_overrides_safety_policy() -> None:
    """Context informs; it never loosens. Outcomes are identical with it.

    A critique that praises the research direction must not clear a
    prohibited hypothesis, and the held/removed pool split must match a
    screen run without any meta-review.
    """
    praising = {
        "common_strengths": ["the pathogen work is promising"],
        "strategic_recommendations": ["keep the pathogen direction"],
    }
    with_context = await safety_screen_node(
        make_state(hypotheses=_policy_pool(), meta_review=praising)
    )
    without_context = await safety_screen_node(
        make_state(hypotheses=_policy_pool())
    )

    assert with_context["hypotheses"] == without_context["hypotheses"]
    assert [d["outcome"] for d in with_context["safety_decisions"]] == [
        d["outcome"] for d in without_context["safety_decisions"]
    ]
    assert [d["hypothesis_id"] for d in with_context["safety_decisions"]] == [
        "bad-1"
    ]


# --- Observation review --------------------------------------------------


@pytest.mark.asyncio()
async def test_observation_review_node_threads_meta_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The observation node renders the state's meta-review into its prompt."""
    calls = stub_call_llm_json(
        monkeypatch,
        reflection,
        {"classification": "neutral", "reasoning": "no signal"},
    )
    state = make_state(
        hypotheses=[make_hypothesis(text="Inhibiting X reduces Y.")],
        articles_with_reasoning=_ARTICLES,
        meta_review=_META_REVIEW,
    )

    await reflection_node(state)

    assert calls, "the observation LLM call never ran"
    _assert_critique_present(calls[0]["prompt"])


@pytest.mark.asyncio()
async def test_observation_review_node_empty_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Iteration-1 observation prompts carry no critique section."""
    calls = stub_call_llm_json(
        monkeypatch,
        reflection,
        {"classification": "neutral", "reasoning": "no signal"},
    )
    state = make_state(
        hypotheses=[make_hypothesis(text="Inhibiting X reduces Y.")],
        articles_with_reasoning=_ARTICLES,
    )

    await reflection_node(state)

    assert calls, "the observation LLM call never ran"
    _assert_empty_state(calls[0]["prompt"])
